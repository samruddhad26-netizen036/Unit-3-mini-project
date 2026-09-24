"""DevDoctor CLI entry point."""

import argparse
import sys

from devdoctor import __version__


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser for the CLI."""
    parser = argparse.ArgumentParser(
        prog="devdoctor",
        description="DevDoctor - A local-first developer assistant for Python environment diagnostics.",
    )
    parser.add_argument(
        "-v", "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    diagnose_parser = subparsers.add_parser(
        "diagnose",
        help="Inspect a Python project and the local environment (read-only)",
    )
    diagnose_parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Path to the target project directory (default: current directory)",
    )
    diagnose_parser.add_argument(
        "--json",
        action="store_true",
        help="Output the inspection result as JSON",
    )

    subparsers.add_parser("repair", help="Repair Python environment issues (not yet implemented)")

    return parser


def run_diagnose(path: str, as_json: bool) -> int:
    """Run environment + project inspection and print the report."""
    from devdoctor.diagnostics import inspect
    from devdoctor.reporting import format_human, format_json

    result = inspect(path)
    if as_json:
        print(format_json(result))
    else:
        print(format_human(result))
    if result.project.error:
        return 2
    return 0


def main(args: list[str] | None = None) -> int:
    """Main CLI entry point."""
    parser = create_parser()
    parsed_args = parser.parse_args(args)

    if parsed_args.command is None:
        parser.print_help()
        return 0

    if parsed_args.command == "diagnose":
        return run_diagnose(parsed_args.path, parsed_args.json)

    if parsed_args.command == "repair":
        print("Command 'repair' is not yet implemented.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
