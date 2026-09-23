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

    # Add a placeholder for future commands
    subparsers.add_parser("diagnose", help="Diagnose Python environment issues (not yet implemented)")
    subparsers.add_parser("repair", help="Repair Python environment issues (not yet implemented)")

    return parser


def main(args: list[str] | None = None) -> int:
    """Main CLI entry point."""
    parser = create_parser()
    parsed_args = parser.parse_args(args)

    if parsed_args.command is None:
        parser.print_help()
        return 0

    # Placeholder for future commands
    if parsed_args.command in ("diagnose", "repair"):
        print(f"Command '{parsed_args.command}' is not yet implemented.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())