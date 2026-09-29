"""srxsync command-line entry point."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from srxsync.categories import CategoryModel
from srxsync.inventory import InventoryError, load_inventory
from srxsync.orchestrator import Orchestrator, RunConfig
from srxsync.results import DriftSummary, PushSummary
from srxsync.transport import KNOWN_TRANSPORTS, make_transport


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="srxsync")
    sub = parser.add_subparsers(dest="command", required=True)

    push = sub.add_parser("push", help="sync config from source to targets")
    push.add_argument("--inventory", required=True, type=Path)
    mode = push.add_mutually_exclusive_group(required=True)
    mode.add_argument("--replace", dest="mode", action="store_const", const="replace")
    mode.add_argument("--merge", dest="mode", action="store_const", const="merge")
    push.add_argument(
        "--commit-confirmed",
        type=int,
        default=5,
        help="minutes for commit-confirmed rollback timer (default: 5)",
    )
    push.add_argument("--max-parallel", type=int, default=5)
    push.add_argument("--on-error", choices=["continue", "abort"], default="continue")
    push.add_argument("--dry-run", action="store_true")
    push.add_argument(
        "--transport",
        choices=list(KNOWN_TRANSPORTS),
        default="pyez",
        help="backend transport (default: pyez)",
    )

    check = sub.add_parser("check", help="detect drift between source and targets")
    check.add_argument("--inventory", required=True, type=Path)
    check.add_argument("--verbose", action="store_true")
    check.add_argument("--max-parallel", type=int, default=5)
    check.add_argument(
        "--transport",
        choices=list(KNOWN_TRANSPORTS),
        default="pyez",
        help="backend transport (default: pyez)",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        categories = CategoryModel.default()
        inventory = load_inventory(args.inventory, known_categories=categories.known_names())
    except InventoryError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    try:
        transport_cls = make_transport(args.transport)
    except ImportError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    orch = Orchestrator(inventory=inventory, categories=categories, transport_factory=transport_cls)

    if args.command == "push":
        cfg = RunConfig(
            mode=args.mode,
            commit_confirmed_minutes=args.commit_confirmed,
            max_parallel=args.max_parallel,
            on_error=args.on_error,
            dry_run=args.dry_run,
        )
        push_summary = asyncio.run(orch.push(cfg))
        _print_push_summary(push_summary)
        return 0 if push_summary.all_ok else 1

    if args.command == "check":
        drift_summary = asyncio.run(orch.check(args.max_parallel))
        _print_drift_summary(drift_summary, verbose=args.verbose)
        return 0 if drift_summary.all_in_sync else 1

    return 2


def _print_push_summary(summary: PushSummary) -> None:
    print()
    print(f"{'host':40s} {'status':10s} {'duration':10s} error")
    for r in summary.results:
        status = "OK" if r.ok else "FAIL"
        err = r.error or ""
        print(f"{r.host:40s} {status:10s} {r.duration_s:>8.2f}s  {err}")


def _print_drift_summary(summary: DriftSummary, *, verbose: bool) -> None:
    print()
    print("Drift report:")
    for line in summary.reports:
        if line.error is not None:
            print(f"  {line.host:40s} ERROR   {line.error}")
            continue
        if line.in_sync:
            print(f"  {line.host:40s} IN SYNC")
        else:
            diffs = ", ".join(line.differing_paths)
            print(f"  {line.host:40s} DRIFT   ({len(line.differing_paths)} differences: {diffs})")
            if verbose:
                for p in line.differing_paths:
                    print(f"      - {p}")


if __name__ == "__main__":
    sys.exit(main())
