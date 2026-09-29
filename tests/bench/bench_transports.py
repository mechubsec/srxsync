"""Wall-time benchmark: PyEZ vs rustez transport backends.

Reads `inv.yaml` from the current working directory and expects
credentials in the environment (typically populated by sourcing
`~/.srxsync.env`, the same convention used by the integration suite).

Two operations are measured:
  * fetch (20 iterations per backend) — connect, fetch union of all
    target include categories from the source device, close.
  * push  ( 3 iterations per backend) — full merge-push cycle against
    targets[0] with commit-confirmed 1 minute.

Results are printed as a markdown table to stdout. Nothing is written
to disk. See docs/superpowers/specs/2026-04-23-transport-benchmark-design.md
for the rationale behind every knob.

IMPORTANT: Do not run this against production. It mutates the push
target (merge, then commit-confirmed with a 60 s rollback window).
"""

from __future__ import annotations

import asyncio
import contextlib
import statistics
import sys
import time
from pathlib import Path

from srxsync.categories import CategoryModel
from srxsync.inventory import Inventory, load_inventory
from srxsync.orchestrator import Orchestrator, RunConfig
from srxsync.secrets import get_secret
from srxsync.transport import make_transport


def load_config(
    inventory_path: Path = Path("inv.yaml"),
) -> tuple[Inventory, CategoryModel, list[str]]:
    """Load inventory + categories, resolve the fetch include-union.

    Returns:
        (inventory, category_model, union_paths) where union_paths is the
        deduped list of XPath strings that the source device must yield
        to satisfy every target's include list. Same union used by
        Orchestrator.__init__.
    """
    categories = CategoryModel.default()
    inventory = load_inventory(inventory_path, known_categories=categories.known_names())
    union_names: list[str] = []
    seen: set[str] = set()
    for target in inventory.targets:
        for name in target.include:
            if name not in seen:
                union_names.append(name)
                seen.add(name)
    union_paths, _ = categories.resolve(union_names)
    return inventory, categories, union_paths


def bench_fetch(
    backend: str,
    inventory: Inventory,
    union_paths: list[str],
    iters: int = 20,
) -> list[float]:
    """Measure wall-clock seconds for `iters` fetch cycles under the given backend.

    Each iteration:   connect(source) → fetch(union_paths) → close
    Aborts this (backend, op) pair if any iteration raises. Returns any
    samples collected before the failure; prints the error to stderr.
    """
    transport_cls = make_transport(backend)
    samples: list[float] = []
    src = inventory.source
    secret = get_secret(host=src.host, auth=src.auth)
    for iteration in range(iters):
        transport = transport_cls()
        start = time.perf_counter()
        try:
            transport.connect(
                src.host,
                secret.username,
                secret.password,
                ssh_key=secret.ssh_key_path,
            )
            transport.fetch(union_paths)
        except Exception as exc:
            elapsed = time.perf_counter() - start
            print(
                f"bench_fetch[{backend}] iter {iteration + 1}/{iters} failed "
                f"after {elapsed:.2f}s: {exc}",
                file=sys.stderr,
            )
            with contextlib.suppress(Exception):
                transport.close()
            return samples
        with contextlib.suppress(Exception):
            transport.close()
        samples.append(time.perf_counter() - start)
    return samples


def bench_push(
    backend: str,
    inventory: Inventory,
    categories: CategoryModel,
    iters: int = 3,
) -> list[float]:
    """Measure wall-clock seconds for `iters` full merge-push cycles under `backend`.

    Each iteration runs Orchestrator.push against a single-target inventory
    (targets[0]) with commit_confirmed=1 minute. Uses asyncio.run so the
    measured interval includes the event-loop startup, matching CLI reality.

    Aborts the (backend, op) pair on the first failure; returns any samples
    gathered before that.
    """
    transport_cls = make_transport(backend)
    # Shrink the inventory to the first target — spec §Inputs: "targets[0]".
    single = Inventory(source=inventory.source, targets=[inventory.targets[0]])
    cfg = RunConfig(
        mode="merge",
        commit_confirmed_minutes=1,
        max_parallel=1,
        on_error="abort",
        dry_run=False,
    )
    samples: list[float] = []
    for iteration in range(iters):
        orchestrator = Orchestrator(single, categories, transport_factory=transport_cls)
        start = time.perf_counter()
        try:
            summary = asyncio.run(orchestrator.push(cfg))
            elapsed = time.perf_counter() - start
            result = summary.results[0]
            if not result.ok:
                print(
                    f"bench_push[{backend}] iter {iteration + 1}/{iters} failed "
                    f"after {elapsed:.2f}s: {result.error}",
                    file=sys.stderr,
                )
                return samples
            samples.append(elapsed)
        except Exception as exc:
            elapsed = time.perf_counter() - start
            print(
                f"bench_push[{backend}] iter {iteration + 1}/{iters} raised "
                f"after {elapsed:.2f}s: {exc}",
                file=sys.stderr,
            )
            return samples
    return samples


def _fmt_duration(seconds: float, unit: str) -> str:
    """Render a duration in ms or s, 3 significant figures."""
    if unit == "ms":
        return f"{seconds * 1000:.0f}ms"
    return f"{seconds:.1f}s"


def _row(backend: str, op: str, samples: list[float], unit: str) -> str:
    """Render one markdown table row. Missing/empty samples produce a 'FAILED' row."""
    if not samples:
        return f"| {backend:<7} | {op:<5} | 0 | FAILED | FAILED | FAILED | FAILED |"
    n = len(samples)
    mn = min(samples)
    md = statistics.median(samples)
    mean = statistics.fmean(samples)
    sd = statistics.stdev(samples) if n > 1 else 0.0
    return (
        f"| {backend:<7} | {op:<5} | {n:>2} | "
        f"{_fmt_duration(mn, unit):>7} | "
        f"{_fmt_duration(md, unit):>7} | "
        f"{_fmt_duration(mean, unit):>7} | "
        f"{_fmt_duration(sd, unit):>7} |"
    )


def render_table(
    *,
    inventory: Inventory,
    fetch_iters: int,
    push_iters: int,
    results: dict[tuple[str, str], list[float]],
) -> str:
    """Build the final markdown table. `results` is keyed by (backend, op)."""
    header = [
        "## Transport benchmark",
        "",
        f"Inventory: inv.yaml  |  Source: {inventory.source.host}  |  "
        f"Push target: {inventory.targets[0].host}",
        f"Fetch iters: {fetch_iters}  |  Push iters: {push_iters}  |  "
        f"Commit-confirmed: 60s",
        "",
        "| backend | op    |  n |     min |  median |    mean |   stdev |",
        "|---------|-------|---:|--------:|--------:|--------:|--------:|",
    ]
    rows: list[str] = []
    for backend in ("pyez", "rustez"):
        rows.append(_row(backend, "fetch", results.get((backend, "fetch"), []), "ms"))
    for backend in ("pyez", "rustez"):
        rows.append(_row(backend, "push", results.get((backend, "push"), []), "s"))
    return "\n".join(header + rows)


FETCH_ITERS = 20
PUSH_ITERS = 3


def _rustez_available() -> bool:
    """True iff the rustez optional extra is importable."""
    try:
        make_transport("rustez")
    except ImportError:
        return False
    return True


def main() -> int:
    inventory, categories, union_paths = load_config()

    backends: list[str] = ["pyez"]
    rustez_ok = _rustez_available()
    if rustez_ok:
        backends.append("rustez")
    else:
        print(
            "warning: rustez extra not installed — running pyez-only. "
            "Install with: pip install -e .[rust]",
            file=sys.stderr,
        )

    print(
        f"# running bench: fetch={FETCH_ITERS} iter, push={PUSH_ITERS} iter, "
        f"backends={backends}",
        file=sys.stderr,
    )

    results: dict[tuple[str, str], list[float]] = {}
    for backend in backends:
        print(f"# bench_fetch[{backend}] ...", file=sys.stderr)
        results[(backend, "fetch")] = bench_fetch(
            backend, inventory, union_paths, iters=FETCH_ITERS
        )
        print(f"# bench_push[{backend}] ...", file=sys.stderr)
        results[(backend, "push")] = bench_push(
            backend, inventory, categories, iters=PUSH_ITERS
        )

    print(render_table(
        inventory=inventory,
        fetch_iters=FETCH_ITERS,
        push_iters=PUSH_ITERS,
        results=results,
    ))

    # Non-zero exit when a backend was degraded, per spec §Graceful degradation.
    return 0 if rustez_ok else 1


if __name__ == "__main__":
    sys.exit(main())
