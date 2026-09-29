# Transport Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `tests/bench/bench_transports.py`, a wall-time benchmark comparing `PyEZTransport` vs `RustezTransport` across fetch and full-push operations, emitting a markdown table to stdout.

**Architecture:** Single Python script that reuses existing srxsync building blocks (`load_inventory`, `CategoryModel`, `make_transport`, `get_secret`, `Orchestrator`) — no new package code, no changes to `srxsync/`. Runs against the same lab used by the integration suite, reading `inv.yaml` and `~/.srxsync.env` exactly like the CLI.

**Tech Stack:** Python 3.11+, stdlib only (`time.perf_counter`, `statistics`, `pathlib`, `asyncio`), plus the srxsync package itself.

**TDD note:** This is a measurement instrument, not a feature. The spec (`docs/superpowers/specs/2026-04-23-transport-benchmark-design.md`) explicitly says "no automated tests." Each task below therefore ends with a **smoke-run checkpoint** instead of a test-runs-red/green cycle: run the script and verify observable output, then commit. The discipline is "does the script still do what it just did plus one more thing?"

**Branch:** `rustperformance` only. Do NOT port to `master`.

**Spec:** [docs/superpowers/specs/2026-04-23-transport-benchmark-design.md](../specs/2026-04-23-transport-benchmark-design.md)

---

## Task 1: Scaffold the bench script file

**Files:**
- Create: `tests/bench/__init__.py`
- Create: `tests/bench/bench_transports.py`

- [ ] **Step 1: Confirm you are on `rustperformance`**

Run: `git branch --show-current`
Expected output: `rustperformance`

If not, stop and switch: `git checkout rustperformance`.

- [ ] **Step 2: Create the empty package marker**

Write `tests/bench/__init__.py` with this exact content:

```python
```

(An empty file. It just marks the directory as a Python package so relative imports, if ever needed, behave predictably. Not strictly required today, but cheap insurance.)

- [ ] **Step 3: Create the script skeleton**

Write `tests/bench/bench_transports.py` with this exact content:

```python
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

import sys


def main() -> int:
    print("bench_transports: scaffold only, no work done yet")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Smoke-run the scaffold**

Run: `python tests/bench/bench_transports.py`
Expected stdout: `bench_transports: scaffold only, no work done yet`
Expected exit code: `0`

- [ ] **Step 5: Commit**

```bash
git add tests/bench/__init__.py tests/bench/bench_transports.py
git commit -m "chore(bench): scaffold bench_transports.py entry point

Empty-behavior entry point plus module docstring explaining the
benchmark contract. No measurement logic yet.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 2: Load inventory and resolve the fetch include set

**Files:**
- Modify: `tests/bench/bench_transports.py`

- [ ] **Step 1: Replace `main()` and imports to load config**

Replace the existing imports and `main()` in `tests/bench/bench_transports.py` with:

```python
from __future__ import annotations

import sys
from pathlib import Path

from srxsync.categories import CategoryModel
from srxsync.inventory import Inventory, load_inventory


def load_config(inventory_path: Path = Path("inv.yaml")) -> tuple[Inventory, CategoryModel, list[str]]:
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


def main() -> int:
    inventory, _, union_paths = load_config()
    print(f"bench_transports: source={inventory.source.host}")
    print(f"bench_transports: push target={inventory.targets[0].host}")
    print(f"bench_transports: union includes {len(union_paths)} path(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Smoke-run the loader**

Run: `python tests/bench/bench_transports.py`
Expected stdout (hosts will reflect your `inv.yaml`):
```
bench_transports: source=<your-source-host>
bench_transports: push target=<your-first-target-host>
bench_transports: union includes <N> path(s)
```

If you see `InventoryError: inventory file not found: inv.yaml`, you are running from the wrong directory — cd into the repo root (`/home/mharman/srxmaster`).

- [ ] **Step 3: Commit**

```bash
git add tests/bench/bench_transports.py
git commit -m "feat(bench): load inventory and resolve fetch include-union

Reuses srxsync.inventory.load_inventory and CategoryModel.default so
the bench picks up exactly what the CLI would. The include union
logic mirrors Orchestrator.__init__ verbatim.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 3: Implement `bench_fetch`

**Files:**
- Modify: `tests/bench/bench_transports.py`

- [ ] **Step 1: Add the fetch benchmark function**

Insert the following imports at the top of the file (merge with existing imports, keep them sorted):

```python
import time

from srxsync.secrets import get_secret
from srxsync.transport import make_transport
```

Add this function anywhere above `main()`:

```python
def bench_fetch(backend: str, inventory: Inventory, union_paths: list[str], iters: int = 20) -> list[float]:
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
            try:
                transport.close()
            except Exception:
                pass
            return samples
        try:
            transport.close()
        except Exception:
            pass
        samples.append(time.perf_counter() - start)
    return samples
```

- [ ] **Step 2: Wire it into `main()`**

Replace the body of `main()` with:

```python
def main() -> int:
    inventory, _, union_paths = load_config()
    print(f"# Transport benchmark (fetch only, scaffolding)\n")
    print(f"Source: {inventory.source.host}")
    print(f"Union includes: {len(union_paths)} path(s)\n")

    pyez_samples = bench_fetch("pyez", inventory, union_paths, iters=2)
    print(f"pyez fetch samples (n=2, smoke): {[f'{s*1000:.0f}ms' for s in pyez_samples]}")
    return 0
```

Note: **`iters=2` is a deliberate smoke-run value for this task only.** It will be raised to 20 in Task 6 when we finalize `main`. Two iterations prove the loop runs without burning four minutes of lab time per edit.

- [ ] **Step 3: Smoke-run**

```bash
source .venv/bin/activate
source ~/.srxsync.env
python tests/bench/bench_transports.py
```

Expected: both sample numbers print, each on the order of several seconds (single-digit to low-double-digit-thousands of ms, depending on lab latency). No tracebacks.

If the fetch fails with `secrets.SecretError`, confirm you sourced `~/.srxsync.env`.

- [ ] **Step 4: Commit**

```bash
git add tests/bench/bench_transports.py
git commit -m "feat(bench): implement bench_fetch with pyez smoke run

Per-iteration timer covers connect+fetch+close. Exceptions abort the
(backend, op) pair and return partial samples so one broken backend
cannot silently drop the other. Main() currently runs 2 iters for
fast iteration; will bump to 20 in the finalize task.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 4: Implement `bench_push`

**Files:**
- Modify: `tests/bench/bench_transports.py`

- [ ] **Step 1: Add imports for the push path**

Add (or merge) at the top of the file:

```python
import asyncio
from dataclasses import replace

from srxsync.orchestrator import Orchestrator, RunConfig
```

- [ ] **Step 2: Add the push benchmark function**

Insert above `main()`:

```python
def bench_push(backend: str, inventory: Inventory, categories: CategoryModel, iters: int = 3) -> list[float]:
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


# `replace` from dataclasses is re-exported here for future tweaking (e.g. dry-run);
# silence linters if it ends up unused.
_ = replace
```

(The `_ = replace` line is defensive — if ruff flags the unused import, remove the `from dataclasses import replace` line entirely and drop this `_ =` line. Only keep it if you find a use for it.)

- [ ] **Step 3: Wire a minimal push smoke run into `main()`**

Replace `main()` with:

```python
def main() -> int:
    inventory, categories, union_paths = load_config()
    print(f"# Transport benchmark (push smoke)\n")
    print(f"Source: {inventory.source.host}  Push target: {inventory.targets[0].host}\n")

    push_samples = bench_push("pyez", inventory, categories, iters=1)
    if push_samples:
        print(f"pyez push sample (n=1, smoke): {push_samples[0]:.1f}s")
    else:
        print("pyez push smoke: failed (see stderr)")
    return 0
```

- [ ] **Step 4: Smoke-run**

```bash
source .venv/bin/activate
source ~/.srxsync.env
python tests/bench/bench_transports.py
```

Expected: one push completes. Wall time ≈ 65–75 s (dominated by the 60 s commit-confirmed window). Output shape:

```
# Transport benchmark (push smoke)

Source: <host>  Push target: <host>

pyez push sample (n=1, smoke): 6X.Xs
```

If the push fails, read stderr carefully — a merge-push of the already-synced lab should succeed with no state change.

- [ ] **Step 5: Commit**

```bash
git add tests/bench/bench_transports.py
git commit -m "feat(bench): implement bench_push via Orchestrator

Reuses Orchestrator.push against a single-target inventory so the
measured path is identical to production. asyncio.run is inside the
timed region — matches CLI reality. Failed iterations abort the
(backend, op) pair and return partial samples.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 5: Stats + markdown table formatter

**Files:**
- Modify: `tests/bench/bench_transports.py`

- [ ] **Step 1: Add the stats/formatter imports**

Add to the top of the file (merge, keep sorted):

```python
import statistics
```

- [ ] **Step 2: Add the formatter**

Insert above `main()`:

```python
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
```

- [ ] **Step 3: Verify the formatter in isolation**

Drop this at the bottom of `main()` temporarily (will be replaced in Task 6):

```python
def main() -> int:
    inventory, _, _ = load_config()
    fake_results = {
        ("pyez",   "fetch"): [5.012, 4.832, 5.201, 5.041, 4.998],
        ("rustez", "fetch"): [0.874, 0.812, 0.889, 0.901, 0.867],
        ("pyez",   "push"):  [68.1, 68.4, 68.5],
        ("rustez", "push"):  [64.2, 64.5, 64.4],
    }
    print(render_table(
        inventory=inventory,
        fetch_iters=20,
        push_iters=3,
        results=fake_results,
    ))
    return 0
```

- [ ] **Step 4: Smoke-run the formatter**

Run: `python tests/bench/bench_transports.py`

Expected output: a well-aligned markdown table that looks like the example in the spec. Verify:
- four data rows, two fetch (ms units), two push (s units)
- numbers line up under their headers
- no tracebacks

- [ ] **Step 5: Commit**

```bash
git add tests/bench/bench_transports.py
git commit -m "feat(bench): stats + markdown table formatter

Per-row min/median/mean/stdev. ms for fetch, s for push. Empty sample
lists render as FAILED so a broken backend is visible, not silent.
Main() currently prints fake numbers for formatter validation — real
wiring lands in the next task.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 6: Wire real runs, handle missing rustez

**Files:**
- Modify: `tests/bench/bench_transports.py`

- [ ] **Step 1: Replace `main()` with the final orchestration**

Replace the entire `main()` function body with:

```python
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
```

- [ ] **Step 2: Clean up**

Remove any remaining temporary scaffolding:
- The `_ = replace` line from Task 4 (if ruff didn't need it).
- The `from dataclasses import replace` import (if `replace` is unused).
- Any `fake_results` leftovers.

Run: `python -m ruff check tests/bench/`
Expected: `All checks passed!`

- [ ] **Step 3: Full smoke-run (this is the real thing — ~5 minutes)**

```bash
source .venv/bin/activate
source ~/.srxsync.env
python tests/bench/bench_transports.py
```

Expected wall time: ~4–6 minutes (20 fetches per backend at ~5 s pyez / ~1 s rustez = ~2 min, plus 3 pushes per backend at ~65 s = ~6.5 min if rustez is available; ~3.5 min pyez-only).

Expected stdout: the final markdown table with real numbers in every cell.
Expected stderr: status lines (`# bench_fetch[pyez] ...` etc.) and, if rustez isn't installed, the warning banner.
Expected exit code: `0` if both backends ran, `1` if pyez-only.

- [ ] **Step 4: Commit**

```bash
git add tests/bench/bench_transports.py
git commit -m "feat(bench): wire real fetch+push runs with rustez fallback

Final main(): iterate backends (pyez always, rustez if extra present),
run 20 fetches and 3 pushes each, emit markdown table to stdout.
Status lines go to stderr so the table is a clean copy-paste. Exit 1
if rustez is unavailable — degraded mode should fail CI-style uses.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 7: Final validation + docs touch

**Files:**
- Modify: `tests/bench/bench_transports.py` (docstring only, if needed)
- Modify: `README.md` (add a one-line pointer in the rustperformance README)

- [ ] **Step 1: Lint + typecheck one last time**

```bash
source .venv/bin/activate
python -m ruff check srxsync/ tests/
python -m mypy srxsync/
```

Expected: `ruff` clean, `mypy` clean.

Note: the benchmark file is under `tests/bench/` not `srxsync/`, so mypy (configured to check `srxsync/`) will ignore it. That is intentional — the benchmark is a script, not library code. If the unit tests start failing for any reason, stop and diagnose before continuing.

```bash
pytest tests/unit/ -q
```

Expected: 43 passed.

- [ ] **Step 2: Add a README pointer (rustperformance branch only)**

Open `README.md`. Find the section that mentions the `rustez` transport backend (look for `--transport rustez` or a paragraph about the `[rust]` extra). Immediately after that paragraph or block, add:

```markdown
### Benchmarking

A lightweight wall-time comparator lives at `tests/bench/bench_transports.py`:

    source .venv/bin/activate
    source ~/.srxsync.env
    python tests/bench/bench_transports.py

It measures 20 fetches and 3 merge-pushes per backend against the
inventory in `inv.yaml` and prints a markdown table. See
[`docs/superpowers/specs/2026-04-23-transport-benchmark-design.md`](docs/superpowers/specs/2026-04-23-transport-benchmark-design.md)
for the exact measurement contract.
```

If the README does not have a natural home for this after a quick read, insert it as a standalone `### Benchmarking` section immediately before `## Architecture`.

- [ ] **Step 3: Verify the README renders cleanly**

Run: `git diff README.md`
Expected: a clean additive diff, no accidental deletions.

- [ ] **Step 4: Commit README**

```bash
git add README.md
git commit -m "docs: document tests/bench/bench_transports.py

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

- [ ] **Step 5: Push**

```bash
git push origin rustperformance
```

Expected: push succeeds; no PR is opened (branches remain unmerged per user policy).

- [ ] **Step 6: (Optional) Capture the actual numbers in a note**

If the last bench run produced interesting numbers, quote them in the push message or in a follow-up note to the user. Do **not** commit the numbers to the repo — the spec explicitly forbids persisted run logs.

---

## Self-Review Notes

**Spec coverage — every normative paragraph of the spec maps to a task:**

| Spec section | Task |
|---|---|
| Goal, Non-goals | 0 (informational) |
| Architecture diagram | 2, 3, 4 (each box is one task) |
| File layout (`tests/bench/__init__.py`, `bench_transports.py`) | 1 |
| Inputs and environment (`inv.yaml`, env creds, `targets[0]`, `[rust]` optional) | 2, 4, 6 |
| Measurement contract (clock, warmup, iters, scope, mode, commit-confirmed, concurrency) | 3 (fetch side), 4 (push side), 6 (iter constants) |
| Output format (stdout markdown, ms/s units) | 5 |
| Error handling (abort pair, partial samples, failed-push not counted) | 3, 4 |
| Graceful degradation (rustez missing → warn, pyez-only, exit 1) | 6 |
| Safety (merge + commit-confirmed 1min) | 4 |
| Invocation (`python tests/bench/bench_transports.py`) | 1 onward |
| Dependencies (stdlib + srxsync internals) | imports in 2, 3, 4, 5 |
| Testing (no automated tests) | plan header TDD note |

**Placeholder scan:** no "TBD" / "TODO" / "handle appropriately" in the task bodies. Every code block is complete and self-contained.

**Type consistency:** `bench_fetch` returns `list[float]`, `bench_push` returns `list[float]`, `render_table` accepts `dict[tuple[str, str], list[float]]`. `make_transport` returns `type[Transport]`, used via `transport_cls()`. Names match across tasks (`inventory`, `categories`, `union_paths`, `backend`, `iters`).

**Ambiguity check:** commit-confirmed timer is always 1 minute; push mode is always `merge`; target is always `targets[0]`; no CLI flags, no env-var overrides. Every knob has one value.
