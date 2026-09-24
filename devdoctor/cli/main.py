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
    diagnose_parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="Skip test execution (faster, no subprocess)",
    )
    diagnose_parser.add_argument(
        "--ai",
        action="store_true",
        help="Enable AI-powered diagnosis using local Ollama model (requires Ollama running)",
    )

    repair_parser = subparsers.add_parser(
        "repair",
        help="Diagnose and automatically repair a Python project (requires Ollama)",
    )
    repair_parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Path to the target project directory (default: current directory)",
    )
    repair_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show proposed repairs without making changes",
    )
    repair_parser.add_argument(
        "--yes",
        action="store_true",
        help="Auto-approve repairs without prompting (use with caution)",
    )
    repair_parser.add_argument(
        "--max-cycles",
        type=int,
        default=3,
        help="Maximum repair cycles (default: 3)",
    )

    return parser


def run_diagnose(path: str, as_json: bool, skip_tests: bool = False, use_ai: bool = False) -> int:
    """Run environment + project inspection and print the report."""
    if use_ai:
        return _run_ai_diagnose(path, as_json, skip_tests)

    from devdoctor.diagnostics import inspect
    from devdoctor.reporting import format_human, format_json

    result = inspect(path, run_tests=not skip_tests)
    if as_json:
        print(format_json(result))
    else:
        print(format_human(result))
    if result.project.error:
        return 2
    return 0


def _run_ai_diagnose(path: str, as_json: bool, skip_tests: bool) -> int:
    """Run AI-powered diagnosis."""
    import json
    import os

    from devdoctor.agent import AgentConfig, diagnose_with_ai

    model = os.environ.get("DEVDOCTOR_MODEL")
    ollama_url = os.environ.get("DEVDOCTOR_OLLAMA_URL")
    config = AgentConfig(
        model=model,
        ollama_url=ollama_url,
    )
    result = diagnose_with_ai(path, config)
    if as_json:
        print(json.dumps(result, indent=2))
    else:
        _print_ai_diagnosis(result)
    # Return non-zero if diagnosis indicates error
    diag = result.get("diagnosis", {})
    if diag.get("status") == "error":
        return 1
    return 0


def _print_ai_diagnosis(result: dict) -> None:
    """Print AI diagnosis in human-readable format."""
    diag = result.get("diagnosis", {})
    print("AI DIAGNOSIS")
    print()
    print(f"Status: {diag.get('status', 'unknown').upper()}")
    print(f"Summary: {diag.get('summary', 'No summary provided')}")
    print()
    problems = diag.get("problems", [])
    if problems:
        print("Problems Found:")
        print()
        for i, problem in enumerate(problems, 1):
            print(f"  {i}. {problem.get('title', 'Unknown problem')}")
            print(f"     Likely Cause: {problem.get('likely_cause', 'Unknown')}")
            print(f"     Recommended Action: {problem.get('recommended_action', 'None')}")
            print(f"     Confidence: {problem.get('confidence', 'unknown')}")
            evidence = problem.get("evidence", [])
            if evidence:
                print("     Evidence:")
                for ev in evidence:
                    print(f"       - {ev}")
            print()
    else:
        print("No problems detected.")
        print()


def run_repair(path: str, dry_run: bool = False, auto_approve: bool = False, max_cycles: int = 3) -> int:
    """Run AI-powered repair on a project."""
    import os

    from devdoctor.agent import RepairAgent, RepairConfig

    model = os.environ.get("DEVDOCTOR_MODEL")
    ollama_url = os.environ.get("DEVDOCTOR_OLLAMA_URL")
    config = RepairConfig(
        model=model,
        ollama_url=ollama_url,
        dry_run=dry_run,
        auto_approve=auto_approve,
        max_repair_cycles=max_cycles,
    )

    agent = RepairAgent(path, config)
    report = agent.run()

    if report.dry_run:
        print("DRY RUN - No changes were made.")
    print()
    print("REPAIR REPORT")
    print()
    print(f"Status: {report.status.upper()}")
    print(f"Cycles: {report.cycles}")

    if report.status == "failed" and isinstance(report.initial_diagnosis, dict):
        error = report.initial_diagnosis.get("error")
        if error:
            print()
            print(f"Error: {error}")

    if report.actions_attempted:
        print()
        print("Actions:")
        for i, action_result in enumerate(report.actions_attempted, 1):
            action = action_result.action
            status = "OK" if action_result.success else "FAILED"
            print(f"  {i}. [{status}] {action.action} {action.package}" + (f"=={action.version}" if action.version else ""))
            print(f"     Reason: {action.reason}")
            if action_result.error:
                print(f"     Error: {action_result.error}")
            if action_result.modified_files:
                for f in action_result.modified_files:
                    print(f"     Modified: {f}")

    if report.verification:
        print()
        print(f"Verification: {'SUCCESS' if report.verification.success else 'FAILED'}")
        print(f"  {report.verification.message}")

    if report.rollback_performed:
        print()
        print(f"Rollback: {'SUCCESS' if report.rollback_success else 'FAILED'}")

    return 0 if report.status == "success" else 1


def main(args: list[str] | None = None) -> int:
    """Main CLI entry point."""
    parser = create_parser()
    parsed_args = parser.parse_args(args)

    if parsed_args.command is None:
        parser.print_help()
        return 0

    if parsed_args.command == "diagnose":
        return run_diagnose(parsed_args.path, parsed_args.json, parsed_args.skip_tests, parsed_args.ai)

    if parsed_args.command == "repair":
        return run_repair(parsed_args.path, parsed_args.dry_run, parsed_args.yes, parsed_args.max_cycles)

    return 0


if __name__ == "__main__":
    sys.exit(main())
