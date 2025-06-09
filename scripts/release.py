#!/usr/bin/env uv run --script
# This shebang line allows the script to be executed directly using `uv run --script`.
# It's a common practice for runnable scripts in Unix-like environments.

# /// script
# This special comment block is used by `uv` (a fast Python package installer and resolver)
# to define the execution environment and dependencies for this Python script.
# It acts as a self-contained specification for running the script without needing
# a separate `pyproject.toml` or `requirements.txt` file for its own dependencies.
# requires-python = ">=3.12"
# Specifies the minimum Python version required to run this script.
# This ensures compatibility with features and syntax introduced in Python 3.12.
# dependencies = [
#     "click>=8.1.8",
#     "tomlkit>=0.13.2"
# ]
# Lists the external Python packages and their minimum versions that this script relies on.
# - `click`: A powerful library for creating beautiful and composable command-line interfaces (CLIs).
#            It simplifies argument parsing, option handling, and subcommands.
# - `tomlkit`: A library for parsing and manipulating TOML (Tom's Obvious, Minimal Language) files.
#              This is crucial for reading and updating `pyproject.toml` files for PyPI packages.
# ///
import sys          # Provides access to system-specific parameters and functions, used here for `sys.exit()`.
import re           # Regular expression operations, used for validating Git hash format.
import click        # The command-line interface toolkit.
from pathlib import Path  # Object-oriented filesystem paths, making path manipulation easier and safer.
import json         # JSON encoder and decoder, used for reading and writing `package.json` files.
import tomlkit      # TOML parsing and manipulation library.
import datetime     # Classes for manipulating dates and times, used for generating version numbers.
import subprocess   # Allows spawning new processes, used for running Git commands.
from dataclasses import dataclass  # Decorator to automatically generate methods like __init__, __repr__, etc.
from typing import Any, Iterator, NewType, Protocol  # Type hinting utilities for better code clarity and maintainability.


# Custom type aliases for clarity and type safety.
Version = NewType("Version", str)  # Represents a version string, e.g., "2023.10.26".
GitHash = NewType("GitHash", str)  # Represents a Git commit hash string.


class GitHashParamType(click.ParamType):
    """
    A custom Click parameter type designed to validate Git commit hashes
    provided as command-line arguments.

    This class extends `click.ParamType` to provide specific validation rules:
    1. Checks the length of the hash.
    2. Ensures the hash contains only hexadecimal characters.
    3. Verifies that the hash actually exists in the local Git repository.
    """
    name = "git_hash"  # The name of this parameter type, used in help messages.

    def convert(
        self, value: Any, param: click.Parameter | None, ctx: click.Context | None
    ) -> GitHash | None:
        """
        Converts and validates the input value to a GitHash.

        Args:
            value: The raw string value passed as a command-line argument.
            param: The `click.Parameter` object this type is associated with (can be None).
            ctx: The `click.Context` object for the current command (can be None).

        Returns:
            A `GitHash` object if the value is a valid Git hash,
            or `None` if the input `value` itself was `None`.

        Raises:
            `click.BadParameter`: If the input value does not meet the validation criteria.
        """
        if value is None:
            # If no value is provided (e.g., optional parameter not given), return None.
            return None

        # Validate the length of the Git hash. Standard hashes are 40 chars,
        # but short hashes are common (minimum 8 for reasonable uniqueness).
        if not (8 <= len(value) <= 40):
            self.fail(f"Git hash must be between 8 and 40 characters, got {len(value)}")

        # Validate that the Git hash consists only of hexadecimal digits (0-9, a-f, A-F).
        if not re.match(r"^[0-9a-fA-F]+$", value):
            self.fail("Git hash must contain only hex digits (0-9, a-f)")

        try:
            # Use `subprocess.run` to execute a Git command to verify the hash.
            # `git rev-parse --verify <hash>` returns 0 if the hash is valid and exists.
            subprocess.run(
                ["git", "rev-parse", "--verify", value],
                check=True,          # If check is True, will raise CalledProcessError on non-zero exit code.
                capture_output=True  # Capture stdout and stderr, preventing them from printing to console.
            )
        except subprocess.CalledProcessError:
            # If `git rev-parse` fails, it means the hash is not found in the repository.
            self.fail(f"Git hash {value} not found in repository")

        # If all validations pass, convert the hash to lowercase for consistency
        # and return it as a GitHash NewType.
        return GitHash(value.lower())


# Instantiate the custom `GitHashParamType` to be used with `click.argument` or `click.option`.
GIT_HASH = GitHashParamType()


class Package(Protocol):
    """
    A `Protocol` defining the interface that all package types (e.g., NPM, PyPI)
    must adhere to. This ensures that different package implementations can be
    treated uniformly by functions like `find_changed_packages`.

    Protocols are a feature of Python's `typing` module for structural subtyping.
    """
    path: Path  # The `pathlib.Path` object pointing to the package's root directory.

    def package_name(self) -> str:
        """
        Abstract method: Must return the name of the package.
        Implementations (e.g., `NpmPackage`, `PyPiPackage`) will define how to extract this.
        """
        ...  # Ellipsis indicates an abstract method in a Protocol.

    def update_version(self, version: Version) -> None:
        """
        Abstract method: Must update the package's version to the given `Version`.
        Implementations will define how to write the new version to the package's manifest file.
        """
        ...


@dataclass
class NpmPackage:
    """
    Represents an NPM (Node Package Manager) package.
    It encapsulates the logic for interacting with `package.json` files.
    """
    path: Path  # The `pathlib.Path` object for the directory containing `package.json`.

    def package_name(self) -> str:
        """
        Reads the `name` field from the `package.json` file to get the package's identifier.

        Returns:
            The name of the NPM package as a string.
        """
        with open(self.path / "package.json", "r") as f:
            # Load the JSON content from package.json and extract the "name" field.
            return json.load(f)["name"]

    def update_version(self, version: Version):
        """
        Updates the `version` field within the `package.json` file.

        Args:
            version: The new `Version` (string) to set for the package.
        """
        with open(self.path / "package.json", "r+") as f:
            # Open in "r+" mode to allow both reading and writing to the same file.
            data = json.load(f)  # Load the existing JSON data.
            data["version"] = version  # Update the "version" key with the new version.
            f.seek(0)  # Move the file pointer to the beginning of the file.
            json.dump(data, f, indent=2)  # Write the modified data back, formatted with 2-space indentation.
            f.truncate()  # Truncate the file in case the new content is shorter than the old.


@dataclass
class PyPiPackage:
    """
    Represents a PyPI (Python Package Index) package.
    It encapsulates the logic for interacting with `pyproject.toml` files.
    """
    path: Path  # The `pathlib.Path` object for the directory containing `pyproject.toml`.

    def package_name(self) -> str:
        """
        Reads the `project.name` field from the `pyproject.toml` file to get the package's identifier.

        Returns:
            The name of the PyPI package as a string.

        Raises:
            Exception: If the `project.name` field is not found in `pyproject.toml`.
        """
        with open(self.path / "pyproject.toml") as f:
            toml_data = tomlkit.parse(f.read())  # Parse the TOML content.
            # Access the "name" key within the "project" table. `get` is used for safe access.
            name = toml_data.get("project", {}).get("name")
            if not name:
                # If the name is missing, raise an error as it's a required field for a package.
                raise Exception("No name in pyproject.toml project section")
            return str(name)  # Ensure the name is returned as a string.

    def update_version(self, version: Version):
        """
        Updates the `project.version` field within the `pyproject.toml` file.

        Args:
            version: The new `Version` (string) to set for the package.
        """
        # Update version in pyproject.toml
        with open(self.path / "pyproject.toml") as f:
            data = tomlkit.parse(f.read())  # Load the existing TOML data.
            data["project"]["version"] = version  # Update the "version" key in the "project" table.

        with open(self.path / "pyproject.toml", "w") as f:
            # Write the modified TOML data back to the file.
            f.write(tomlkit.dumps(data))


def has_changes(path: Path, git_hash: GitHash) -> bool:
    """
    Checks if any files within a specified directory (`path`) have changed
    between the current Git HEAD and a given `git_hash`.
    It specifically looks for changes in Python (`.py`) and TypeScript (`.ts`) files.

    Args:
        path: The `pathlib.Path` object representing the directory to check for changes.
        git_hash: The `GitHash` (string) representing the commit to compare against.

    Returns:
        `True` if one or more relevant files (`.py`, `.ts`) have changed;
        `False` otherwise (no changes or an error occurred during git diff).
    """
    try:
        # Execute `git diff --name-only <git_hash> -- .`
        # - `git diff`: Shows changes between commits, commit and working tree, etc.
        # - `--name-only`: Shows only the names of changed files.
        # - `<git_hash>`: The specific commit to compare against.
        # - `--`: Separates options from paths.
        # - `.`: Specifies the current directory as the scope for the diff.
        output = subprocess.run(
            ["git", "diff", "--name-only", git_hash, "--", "."],
            cwd=path,             # Execute the command in the specified directory.
            check=True,           # Raise `subprocess.CalledProcessError` if the command exits with non-zero status.
            capture_output=True,  # Capture standard output and standard error.
            text=True,            # Decode stdout/stderr as text (default encoding).
        )

        # Split the captured standard output (which lists changed files line by line)
        # into a list of `Path` objects.
        changed_files = [Path(f) for f in output.stdout.splitlines()]
        # Filter the list to include only files with `.py` or `.ts` extensions.
        relevant_files = [f for f in changed_files if f.suffix in [".py", ".ts"]]
        # Return True if there is at least one relevant file that has changed.
        return len(relevant_files) >= 1
    except subprocess.CalledProcessError:
        # If the `git diff` command fails (e.g., due to a detached HEAD, or other git issues),
        # it's safer to assume no changes for the purpose of this script, or log the error.
        # Here, it simply returns False.
        return False


def gen_version() -> Version:
    """
    Generates a version string based on the current local date.
    The format is `YYYY.MM.DD`.

    Returns:
        A `Version` object (which is a `str` NewType) representing the current date.
    """
    now = datetime.datetime.now()  # Get the current date and time.
    # Format the date into a string: Year.Month.Day
    return Version(f"{now.year}.{now.month}.{now.day}")


def find_changed_packages(directory: Path, git_hash: GitHash) -> Iterator[Package]:
    """
    Scans the given `directory` for potential package directories (NPM or PyPI)
    and yields `Package` objects for those that have relevant changes
    since the specified `git_hash`.

    Args:
        directory: The root `pathlib.Path` to start searching for packages.
        git_hash: The `GitHash` (string) to compare file changes against.

    Yields:
        An `Iterator` of `Package` objects (`NpmPackage` or `PyPiPackage`)
        that have detected changes.
    """
    # Look for NPM packages by searching for `package.json` files in direct subdirectories.
    for path in directory.glob("*/package.json"):
        # `path.parent` gives the directory containing `package.json`, which is the package root.
        if has_changes(path.parent, git_hash):
            yield NpmPackage(path.parent)  # Yield an NpmPackage instance if changes are found.

    # Look for PyPI packages by searching for `pyproject.toml` files in direct subdirectories.
    for path in directory.glob("*/pyproject.toml"):
        # `path.parent` gives the directory containing `pyproject.toml`, which is the package root.
        if has_changes(path.parent, git_hash):
            yield PyPiPackage(path.parent)  # Yield a PyPiPackage instance if changes are found.


@click.group()
def cli():
    """
    The main command group for this CLI application.
    All subcommands (`update-packages`, `generate-notes`, etc.) are attached to this group.
    """
    pass  # This function serves as the root command group and doesn't perform any actions itself.


@cli.command("update-packages")
@click.option(
    "--directory",
    type=click.Path(exists=True, path_type=Path),  # Ensures the path exists and converts to a Path object.
    default=Path.cwd(),                            # Defaults to the current working directory.
    help="The root directory to search for packages and apply version updates. "
         "Defaults to the current working directory."
)
@click.argument(
    "git_hash",
    type=GIT_HASH,  # Uses our custom GitHashParamType for validation.
    help="The Git commit hash to compare against for detecting changed packages. "
         "Only packages with changes since this hash will be updated."
)
def update_packages(directory: Path, git_hash: GitHash) -> int:
    """
    Updates the version of identified changed packages.

    This command performs the following actions:
    1. Resolves the absolute path of the target directory.
    2. Generates a new version string based on the current date (YYYY.MM.DD).
    3. Iterates through all detected changed packages (NPM or PyPI).
    4. For each changed package, it calls its `update_version` method to write
       the new version to its respective manifest file (`package.json` or `pyproject.toml`).
    5. Prints the name and new version of each updated package to standard output.
    """
    path = directory.resolve(strict=True)  # Get the absolute, resolved path; raises error if path doesn't exist.
    version = gen_version()  # Generate the new version number.

    # Iterate over packages that have changed since the given git_hash.
    for package in find_changed_packages(path, git_hash):
        name = package.package_name()  # Get the package's name.
        package.update_version(version)  # Call the package's method to update its version.

        click.echo(f"{name}@{version}")  # Print confirmation of the update.

    return 0  # Indicate successful execution.


@cli.command("generate-notes")
@click.option(
    "--directory",
    type=click.Path(exists=True, path_type=Path),
    default=Path.cwd(),
    help="The root directory to search for packages when generating release notes. "
         "Defaults to the current working directory."
)
@click.argument(
    "git_hash",
    type=GIT_HASH,
    help="The Git commit hash to compare against for detecting changed packages. "
         "Only packages with changes since this hash will be listed in the notes."
)
def generate_notes(directory: Path, git_hash: GitHash) -> int:
    """
    Generates a simple set of release notes for changed packages.

    This command outputs Markdown-formatted release notes to standard output, including:
    1. A main release header with the generated version.
    2. A sub-header for "Updated packages".
    3. A bulleted list of all packages that have changed since the specified
       `git_hash`, along with their new version.
    """
    path = directory.resolve(strict=True)
    version = gen_version()  # Generate the release version.

    click.echo(f"# Release : v{version}")  # Print the main release heading.
    click.echo("")                          # Print a blank line for readability.
    click.echo("## Updated packages")        # Print the sub-heading for updated packages.
    # Iterate through changed packages and list them in the notes.
    for package in find_changed_packages(path, git_hash):
        name = package.package_name()
        click.echo(f"- {name}@{version}")  # Print each updated package in a bulleted list.

    return 0


@cli.command("generate-version")
def generate_version() -> int:
    """
    Generates and prints the current date-based version number to standard output.

    This command is useful for scripts or CI/CD pipelines that need to obtain
    the version number without performing any package updates or other actions.
    """
    # Detect package type - This comment seems misplaced as this command only generates a version.
    # It might be a remnant from an earlier design or a general comment template.
    click.echo(gen_version())  # Print the generated version.
    return 0


@cli.command("generate-matrix")
@click.option(
    "--directory",
    type=click.Path(exists=True, path_type=Path),
    default=Path.cwd(),
    help="The root directory to search for packages when generating the matrix. "
         "Defaults to the current working directory."
)
@click.option(
    "--npm",
    is_flag=True,   # This makes it a boolean flag (e.g., `--npm` will be True if present).
    default=False,  # Default value is False if the flag is not provided.
    help="Include NPM packages in the generated matrix JSON output."
)
@click.option(
    "--pypi",
    is_flag=True,
    default=False,
    help="Include PyPI packages in the generated matrix JSON output."
)
@click.argument(
    "git_hash",
    type=GIT_HASH,
    help="The Git commit hash to compare against for detecting changed packages. "
         "Only packages with changes since this hash will be included in the matrix."
)
def generate_matrix(directory: Path, git_hash: GitHash, pypi: bool, npm: bool) -> int:
    """
    Generates a JSON array of relative paths for changed packages.

    This command is particularly useful in CI/CD (Continuous Integration/Continuous Delivery)
    pipelines to create a dynamic "matrix" of jobs. For example, a CI job might run
    only for the directories of packages that have actually changed.

    The output is a JSON string representing a list of relative paths.
    Users can filter the output by package type using the `--npm` and `--pypi` flags.
    """
    path = directory.resolve(strict=True)
    version = gen_version()  # The generated version is not directly used in the output JSON,
                             # but might be used by a downstream CI step that consumes this matrix.

    changes = []  # List to store relative paths of changed packages.
    # Iterate through all packages that have changed since the given git_hash.
    for package in find_changed_packages(path, git_hash):
        # Calculate the path of the package relative to the base `directory`.
        pkg = package.path.relative_to(path)
        # Check if the `--npm` flag is set and the current package is an NpmPackage.
        if npm and isinstance(package, NpmPackage):
            changes.append(str(pkg))  # Add its relative path as a string.
        # Check if the `--pypi` flag is set and the current package is a PyPiPackage.
        if pypi and isinstance(package, PyPiPackage):
            changes.append(str(pkg))  # Add its relative path as a string.

    # Print the list of changed package relative paths as a JSON array.
    click.echo(json.dumps(changes))
    return 0


if __name__ == "__main__":
    # This block ensures that the `cli()` function is called when the script is executed directly.
    # `sys.exit()` is used to ensure the script exits with the status code returned by `cli()`.
    # A status code of 0 typically indicates success, while non-zero indicates an error.
    sys.exit(cli())
