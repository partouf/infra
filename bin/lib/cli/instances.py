import datetime
import logging
import shlex
import subprocess
import sys
import time
from typing import Dict, Sequence

import click

from lib.amazon import as_client, get_autoscaling_group, target_group_arn_for
from lib.blue_green_deploy import BlueGreenDeployment
from lib.ce_utils import (
    are_you_sure,
    describe_current_release,
    is_running_on_admin_node,
    set_update_message,
    wait_for_autoscale_state,
)
from lib.cli import cli
from lib.env import Config, Environment
from lib.instance import Instance, print_instances
from lib.ssh import exec_remote, exec_remote_all, run_remote_shell

LOGGER = logging.getLogger(__name__)


@cli.group()
def instances():
    """Instance management commands."""


@instances.command(name="exec_all")
@click.pass_obj
@click.argument("remote_cmd", required=True, nargs=-1)
def instances_exec_all(cfg: Config, remote_cmd: Sequence[str]):
    """Execute REMOTE_CMD on all the instances."""
    escaped = shlex.join(remote_cmd)
    if not are_you_sure(f"exec command {escaped} in all instances", cfg):
        return

    print("Running '{}' on all instances".format(escaped))
    exec_remote_all(pick_instances(cfg), remote_cmd)


@instances.command(name="login")
@click.pass_obj
def instances_login(cfg: Config):
    """Log in to one of the instances."""
    instance = pick_instance(cfg)
    run_remote_shell(instance)


@instances.command(name="restart_one")
@click.pass_obj
def instances_restart_one(cfg: Config):
    """Restart one of the instances."""
    instance = pick_instance(cfg)
    as_instance_status = instance.describe_autoscale()
    if not as_instance_status:
        LOGGER.error("Failed restarting %s - was not in ASG", instance)
        return
    as_group_name = as_instance_status["AutoScalingGroupName"]
    modified_groups: Dict[str, int] = {}
    try:
        restart_one_instance(as_group_name, instance, modified_groups)
    except RuntimeError as e:
        LOGGER.error("Failed restarting %s - skipping: %s", instance, e)


@instances.command(name="start")
@click.pass_obj
def instances_start(cfg: Config):
    """Start up the instances."""
    print("Starting version %s", describe_current_release(cfg))
    exec_remote_all(pick_instances(cfg), ["sudo", "systemctl", "start", "compiler-explorer"])


@instances.command(name="stop")
@click.pass_obj
def instances_stop(cfg: Config):
    """Stop the instances."""
    if cfg.env == Environment.PROD:
        print("Operation aborted. This would bring down the site")
        print("If you know what you are doing, edit the code in bin/lib/ce.py, function instances_stop_cmd")
    elif are_you_sure("stop all instances", cfg):
        exec_remote_all(pick_instances(cfg), ["sudo", "systemctl", "stop", "compiler-explorer"])


@instances.command(name="restart")
@click.option(
    "--motd",
    type=str,
    default="Site is being updated",
    help="Set the message of the day used during update",
    show_default=True,
)
@click.pass_obj
def instances_restart(cfg: Config, motd: str):
    """Restart the instances, picking up new code."""
    if not are_you_sure("restart all instances with version {}".format(describe_current_release(cfg)), cfg):
        return
    begin_time = datetime.datetime.now()
    # Store old motd
    set_update_message(cfg, motd)
    modified_groups: Dict[str, int] = {}
    failed = False
    to_restart = pick_instances(cfg)

    for index, instance in enumerate(to_restart):
        LOGGER.info("Restarting %s (%d of %d)...", instance, index + 1, len(to_restart))
        as_instance_status = instance.describe_autoscale()
        if not as_instance_status:
            LOGGER.warning("Skipping %s as it is no longer in the ASG", instance)
            continue
        as_group_name = as_instance_status["AutoScalingGroupName"]
        if as_instance_status["LifecycleState"] != "InService":
            LOGGER.warning("Skipping %s as it is not InService (%s)", instance, as_instance_status)
            continue

        try:
            restart_one_instance(as_group_name, instance, modified_groups)
        except RuntimeError as e:
            LOGGER.error("Failed restarting %s - skipping: %s", instance, e)
            failed = True
            # TODO, what here?

    for group, desired in iter(modified_groups.items()):
        LOGGER.info("Putting desired instances for %s back to %d", group, desired)
        as_client.update_auto_scaling_group(AutoScalingGroupName=group, DesiredCapacity=desired)
    set_update_message(cfg, "")
    end_time = datetime.datetime.now()
    delta_time = end_time - begin_time
    print(f"Instances restarted in {delta_time.total_seconds()} seconds")
    sys.exit(1 if failed else 0)


@instances.command(name="status")
@click.pass_obj
def instances_status(cfg: Config):
    """Get the status of the instances."""
    if cfg.env.supports_blue_green:
        try:
            deployment = BlueGreenDeployment(cfg)

            # Try to get blue and green target groups
            blue_tg_arn = deployment.get_target_group_arn("blue")
            green_tg_arn = deployment.get_target_group_arn("green")
            active_color = deployment.get_active_color()

            print(f"Blue-Green Environment: {cfg.env.value}")
            print(f"Active Color: {active_color}")
            print()

            # Show blue instances
            blue_instances = Instance.elb_instances(blue_tg_arn)
            if blue_instances:
                marker = " (ACTIVE)" if active_color == "blue" else ""
                print(f"Blue Instances{marker}:")
                print_instances(blue_instances, number=False)
            else:
                marker = " (ACTIVE)" if active_color == "blue" else ""
                print(f"Blue Instances{marker}: No instances")

            print()

            # Show green instances
            green_instances = Instance.elb_instances(green_tg_arn)
            if green_instances:
                marker = " (ACTIVE)" if active_color == "green" else ""
                print(f"Green Instances{marker}:")
                print_instances(green_instances, number=False)
            else:
                marker = " (ACTIVE)" if active_color == "green" else ""
                print(f"Green Instances{marker}: No instances")

            # Add note about Service/Version information if not on admin node
            if (blue_instances or green_instances) and not is_running_on_admin_node():
                print()
                print("Note: Service and Version information requires SSH access from admin node.")

        except Exception as e:
            print(f"Error: Failed to get blue-green status for {cfg.env.value}: {e}")
    else:
        # Legacy single target group environment
        print(f"Environment: {cfg.env.value}")
        print_instances(Instance.elb_instances(target_group_arn_for(cfg)), number=False)


def pick_instance(cfg: Config):
    elb_instances = get_instances_for_environment(cfg)
    if len(elb_instances) == 1:
        return elb_instances[0]
    while True:
        print_instances(elb_instances, number=True)
        inst = input("Which instance? ")
        try:
            return elb_instances[int(inst)]
        except (ValueError, IndexError):
            pass


def pick_instances(cfg: Config):
    return get_instances_for_environment(cfg)


def get_instances_for_environment(cfg: Config):
    """Get instances for the environment, handling both blue-green and legacy deployments."""
    if cfg.env.supports_blue_green:
        try:
            deployment = BlueGreenDeployment(cfg)
            active_color = deployment.get_active_color()
            active_tg_arn = deployment.get_target_group_arn(active_color)

            return Instance.elb_instances(active_tg_arn)
        except Exception as e:
            raise RuntimeError(f"Failed to get instances for blue-green environment {cfg.env.value}: {e}") from e

    return Instance.elb_instances(target_group_arn_for(cfg))


def restart_one_instance(as_group_name: str, instance: Instance, modified_groups: Dict[str, int]):
    instance_id = instance.instance.instance_id
    LOGGER.info("Enabling instance protection for %s", instance)
    as_client.set_instance_protection(
        AutoScalingGroupName=as_group_name, InstanceIds=[instance_id], ProtectedFromScaleIn=True
    )
    as_group = get_autoscaling_group(as_group_name)
    adjustment_required = as_group["DesiredCapacity"] == as_group["MinSize"]
    if adjustment_required:
        LOGGER.info("Group '%s' needs to be adjusted to keep enough nodes", as_group_name)
        modified_groups[as_group["AutoScalingGroupName"]] = as_group["DesiredCapacity"]
    LOGGER.info("Putting %s into standby", instance)
    as_client.enter_standby(
        InstanceIds=[instance_id],
        AutoScalingGroupName=as_group_name,
        ShouldDecrementDesiredCapacity=not adjustment_required,
    )
    wait_for_autoscale_state(instance, "Standby")
    LOGGER.info("Restarting service on %s", instance)
    restart_response = exec_remote(instance, ["sudo", "systemctl", "restart", "compiler-explorer"])
    if restart_response:
        LOGGER.warning("Restart gave some output: %s", restart_response)
    wait_for_healthok(instance)
    LOGGER.info("Moving %s out of standby", instance)
    as_client.exit_standby(InstanceIds=[instance_id], AutoScalingGroupName=as_group_name)
    wait_for_autoscale_state(instance, "InService")
    wait_for_elb_state(instance, "healthy")
    LOGGER.info("Disabling instance protection for %s", instance)
    as_client.set_instance_protection(
        AutoScalingGroupName=as_group_name, InstanceIds=[instance_id], ProtectedFromScaleIn=False
    )
    LOGGER.info("Instance restarted ok")


def wait_for_elb_state(instance, state):
    LOGGER.info("Waiting for %s to reach ELB state '%s'...", instance, state)
    while True:
        instance.update()
        instance_state = instance.instance.state["Name"]
        if instance_state != "running":
            raise RuntimeError("Instance no longer running (state {})".format(instance_state))
        LOGGER.debug("State is %s", instance.elb_health)
        if instance.elb_health == state:
            LOGGER.info("...done")
            return
        time.sleep(5)


def is_everything_awesome(instance):
    try:
        response = exec_remote(instance, ["curl", "-s", "--max-time", "2", "http://127.0.0.1/healthcheck"])
        return response.strip() == "Everything is awesome"
    except subprocess.CalledProcessError:
        return False


def wait_for_healthok(instance):
    LOGGER.info("Waiting for instance to be Online %s", instance)
    sys.stdout.write("Waiting")
    while not is_everything_awesome(instance):
        sys.stdout.write(".")
        # Flush stdout so tmux updates
        sys.stdout.flush()
        time.sleep(10)
    print("Ok, Everything is awesome!")
