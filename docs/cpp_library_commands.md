# C++ Library Management Commands

This document describes the C++ library management commands for adding and managing C++ libraries in Compiler Explorer.

## Overview

The C++ library commands allow you to:
- Add new C++ libraries from GitHub URLs
- Generate Linux properties files for C++ libraries
- Generate Windows properties files for C++ libraries
- Update existing properties files with new or modified libraries

## Commands

### `cpp-library add`

Add a new C++ library or update an existing library version.

```bash
ce_install cpp-library add <github_url> <version> [--type <library_type>] [--target-prefix <prefix>]
```

**Parameters:**
- `github_url`: GitHub URL of the library (e.g., `https://github.com/fmtlib/fmt`)
- `version`: Version to add (e.g., `10.2.1`)
- `--type`: Library type (optional, default: `header-only`)
- `--target-prefix`: Prefix for version tags (optional, e.g., 'v' for tags like v3.11.3)

**Library Types:**
- `header-only`: Header-only library (default)
- `packaged-headers`: Headers provided by package manager
- `static`: Static library requiring compilation
- `shared`: Shared library requiring compilation

**Examples:**
```bash
# Add a static library
ce_install cpp-library add https://github.com/fmtlib/fmt 10.2.1 --type static

# Add a header-only library
ce_install cpp-library add https://github.com/nlohmann/json 3.11.3

# Add a library with 'v' prefixed version tags
ce_install cpp-library add https://github.com/nlohmann/json 3.11.3 --target-prefix v
```

### `cpp-library generate-linux-props`

Generate Linux properties file for C++ libraries.

```bash
ce_install cpp-library generate-linux-props [options]
```

**Options:**
- `--input-file <file>`: Existing properties file to update
- `--output-file <file>`: Output file (defaults to stdout)
- `--library <name>`: Only process this specific library
- `--version <version>`: Only process this specific version (requires --library)

**Examples:**
```bash
# Generate all C++ library properties to stdout
ce_install cpp-library generate-linux-props

# Generate properties to a file
ce_install cpp-library generate-linux-props --output-file cpp_libraries.properties

# Update existing properties file
ce_install cpp-library generate-linux-props --input-file existing.properties --output-file updated.properties

# Generate properties for a specific library
ce_install cpp-library generate-linux-props --library fmt

# Generate properties for a specific library version
ce_install cpp-library generate-linux-props --library fmt --version 10.2.1 --input-file existing.properties
```

### `cpp-library generate-windows-props`

Generate Windows properties file for C++ libraries.

```bash
ce_install cpp-library generate-windows-props [options]
```

**Options:**
- `--input-file <file>`: Existing properties file to update
- `--output-file <file>`: Output file (defaults to stdout)

**Example:**
```bash
# Generate all C++ Windows library properties
ce_install cpp-library generate-windows-props --output-file cpp_libraries_windows.properties
```

## Usage Workflow

### Adding a New Library

1. **Add the library:**
   ```bash
   ce_install cpp-library add https://github.com/fmtlib/fmt 10.2.1 --type static
   ```

2. **Generate updated properties:**
   ```bash
   ce_install cpp-library generate-linux-props \
     --input-file /opt/compiler-explorer/etc/config/c++.linux.properties \
     --output-file /opt/compiler-explorer/etc/config/c++.linux.properties
   ```

### Adding a Version to Existing Library

```bash
# Add new version
ce_install cpp-library add https://github.com/fmtlib/fmt 11.0.0 --type static

# Update properties for just this library
ce_install cpp-library generate-linux-props --library fmt \
  --input-file existing.properties --output-file updated.properties
```

### Generating Properties from Scratch

```bash
# Generate complete properties file
ce_install cpp-library generate-linux-props --output-file cpp_libraries.properties
```

## Notes

- The `add` command automatically detects if a library already exists and adds the version appropriately
- Properties generation can be done for all libraries or filtered to specific libraries/versions
- Windows and Linux properties may include different libraries based on build compatibility
- Library paths and linking information are automatically configured based on library type
