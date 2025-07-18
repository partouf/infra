import logging
import sys
from pathlib import Path

import click

from lib.library_props import (
    add_version_to_library,
    extract_library_id_from_github_url,
    extract_repo_from_github_url,
    find_existing_library_by_github_url,
    generate_all_libraries_properties,
    generate_single_library_properties,
    generate_standalone_library_properties,
    merge_properties,
    output_properties,
    process_all_libraries_properties,
    process_library_specific_properties,
    validate_library_version_args,
)
from lib.library_yaml import LibraryYaml

from ..ce_install import cli


@cli.group()
def cpp_library():
    """C++ library management commands."""


@cpp_library.command(name="add")
@click.argument("github_url")
@click.argument("version")
@click.option(
    "--type",
    type=click.Choice(["header-only", "packaged-headers", "static", "shared", "cshared"]),
    default="header-only",
    help="Library type (default: header-only)",
)
@click.option(
    "--target-prefix",
    default="",
    help="Prefix for version tags (e.g., 'v' for tags like v3.11.3)",
)
@click.option(
    "--use-compiler",
    default="g105",
    help="Specific compiler to use for building (default: g105 for cshared libraries)",
)
@click.option(
    "--static-lib-link",
    default="",
    help="Comma-separated list of static library targets to link (without lib prefix or .a suffix)",
)
@click.option(
    "--shared-lib-link",
    default="",
    help="Comma-separated list of shared library targets to link (without lib prefix or .so suffix)",
)
@click.option(
    "--package-install",
    is_flag=True,
    help="Library requires CMake package installation for headers",
)
def add_cpp_library(
    github_url: str,
    version: str,
    type: str,
    target_prefix: str,
    use_compiler: str,
    static_lib_link: str,
    shared_lib_link: str,
    package_install: bool,
):
    """Add or update a C++ library entry in libraries.yaml."""
    if static_lib_link and type not in ["static", "cshared"]:
        click.echo("Error: --static-lib-link can only be used with --type static or cshared", err=True)
        sys.exit(1)

    if shared_lib_link and type not in ["shared", "cshared"]:
        click.echo("Error: --shared-lib-link can only be used with --type shared or cshared", err=True)
        sys.exit(1)

    library_yaml, cpp_libraries = LibraryYaml.load_library_yaml_section("c++")

    existing_lib_id = find_existing_library_by_github_url(cpp_libraries, github_url)

    if existing_lib_id:
        lib_id = existing_lib_id
        repo_field = cpp_libraries[lib_id].get("repo", "")
    else:
        try:
            lib_id = extract_library_id_from_github_url(github_url)
            repo_field = extract_repo_from_github_url(github_url)
        except ValueError as e:
            click.echo(f"Error: {e}", err=True)
            sys.exit(1)

    if lib_id in cpp_libraries:
        if existing_lib_id:
            click.echo(f"Found existing library '{lib_id}' for {github_url}")

        if static_lib_link or shared_lib_link or package_install:
            warnings = []
            if static_lib_link or shared_lib_link:
                warnings.append("--static-lib-link and --shared-lib-link")
            if package_install:
                warnings.append("--package-install")
            warning_text = " and ".join(warnings) + " are ignored when adding to existing libraries"
            click.echo(f"Warning: {warning_text}", err=True)

        message = add_version_to_library(cpp_libraries, lib_id, version, target_prefix)
        click.echo(message)
    else:
        library_entry = {
            "type": "github",
            "repo": repo_field,
            "check_file": "README.md",
            "targets": [version],
        }

        if target_prefix:
            library_entry["target_prefix"] = target_prefix

        if static_lib_link:
            library_entry["staticliblink"] = [lib.strip() for lib in static_lib_link.split(",") if lib.strip()]

        if shared_lib_link:
            library_entry["sharedliblink"] = [lib.strip() for lib in shared_lib_link.split(",") if lib.strip()]

        if type == "packaged-headers":
            library_entry["build_type"] = "cmake"
            library_entry["lib_type"] = "headeronly"
            library_entry["package_install"] = True
        elif type == "header-only":
            pass
        elif type == "static":
            library_entry["build_type"] = "cmake"
            library_entry["lib_type"] = "static"
        elif type == "shared":
            library_entry["build_type"] = "cmake"
            library_entry["lib_type"] = "shared"
        elif type == "cshared":
            library_entry["build_type"] = "cmake"
            library_entry["lib_type"] = "cshared"
            library_entry["use_compiler"] = use_compiler

        if package_install:
            library_entry["package_install"] = True

        cpp_libraries[lib_id] = library_entry
        click.echo(f"Added new library {lib_id} with version {version}")

    library_yaml.save()
    click.echo(f"Successfully updated {library_yaml.yaml_path}")
    click.echo(f"\nLibrary '{lib_id}' is now available for property generation.")
    click.echo("To update the properties file, run:")
    click.echo(f"  ce_install cpp-library generate-linux-props --library {lib_id} --version {version} \\")
    click.echo("    --input-file <ce-repo>/etc/config/c++.amazon.properties \\")
    click.echo("    --output-file <ce-repo>/etc/config/c++.amazon.properties")


@cpp_library.command(name="generate-windows-props")
@click.option("--input-file", type=click.Path(exists=True), help="Existing properties file to update")
@click.option("--output-file", type=click.Path(), help="Output file (defaults to stdout)")
@click.option("--library", help="Only update this specific library")
@click.option("--version", help="Only update this specific version (requires --library)")
def generate_cpp_windows_props(input_file, output_file, library, version):
    """Generate C++ Windows properties file from libraries.yaml."""
    if version and not library:
        click.echo("Error: --version requires --library to be specified", err=True)
        sys.exit(1)

    yaml_dir = Path(__file__).parent.parent.parent / "yaml"
    library_yaml = LibraryYaml(str(yaml_dir))

    if "c++" not in library_yaml.yaml_doc["libraries"]:
        click.echo("No C++ libraries found in libraries.yaml")
        return

    if library:
        click.echo("Filtering by library for Windows properties is not yet implemented", err=True)
        sys.exit(1)
    else:
        logger = logging.getLogger()
        new_properties_text = library_yaml.get_ce_properties_for_cpp_windows_libraries(logger)

    if input_file:
        with open(input_file, "r", encoding="utf-8") as f:
            existing_content = f.read()

        merged_content = merge_properties(existing_content, new_properties_text)
        result = merged_content
    else:
        result = new_properties_text

    if output_file:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(result)
        click.echo(f"Properties written to {output_file}")
    else:
        click.echo(result)


@cpp_library.command(name="generate-linux-props")
@click.option("--input-file", type=click.Path(exists=True), help="Existing properties file to update")
@click.option("--output-file", type=click.Path(), help="Output file (defaults to stdout)")
@click.option("--library", help="Only update this specific library")
@click.option("--version", help="Only update this specific version (requires --library)")
def generate_cpp_linux_props(input_file, output_file, library, version):
    """Generate C++ Linux properties file from libraries.yaml."""
    error = validate_library_version_args(library, version)
    if error:
        click.echo(error, err=True)
        sys.exit(1)

    yaml_dir = Path(__file__).parent.parent.parent / "yaml"
    library_yaml = LibraryYaml(str(yaml_dir))

    if "c++" not in library_yaml.yaml_doc["libraries"]:
        click.echo("No C++ libraries found in libraries.yaml")
        return

    cpp_libraries = library_yaml.yaml_doc["libraries"]["c++"]

    if library:
        if library not in cpp_libraries:
            click.echo(f"Error: Library '{library}' not found in libraries.yaml", err=True)
            sys.exit(1)

        lib_info = cpp_libraries[library]

        if lib_info.get("build_type") in ["manual", "none", "never"]:
            click.echo(
                f"Warning: Library '{library}' has build_type '{lib_info.get('build_type')}' and would normally be skipped",
                err=True,
            )

        try:
            lib_props = generate_single_library_properties(library, lib_info, specific_version=version)
        except ValueError as e:
            click.echo(f"Error: {e}", err=True)
            sys.exit(1)

        if version:
            if "name" not in lib_props:
                lib_props["name"] = library
            if "url" not in lib_props and lib_info.get("type") == "github" and "repo" in lib_info:
                lib_props["url"] = f"https://github.com/{lib_info['repo']}"

        result = process_library_specific_properties(
            input_file, library, lib_props, version, generate_standalone_library_properties
        )
    else:
        new_properties_text = generate_all_libraries_properties(cpp_libraries)
        result = process_all_libraries_properties(input_file, new_properties_text)

    message = output_properties(result, output_file)
    if message:
        click.echo(message)
