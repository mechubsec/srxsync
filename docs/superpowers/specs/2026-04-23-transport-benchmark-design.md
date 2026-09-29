# transport-benchmark — wall-time bench for pyez vs rustez

**Date:** 2026-04-23
**Branch:** `rustperformance` (not to be ported to `master`)
**Spec for implementation plan:** `docs/superpowers/plans/2026-04-23-transport-benchmark.md` (to be written)

## Goal

Measure and compare wall-clock time for the two transport backends
(`PyEZTransport`, `RustezTransport`) on two operations: read-only
config fetch, and a full push lifecycle. Produce numbers that inform
"is rustez worth the extra dependency" without adding test
infrastructure, metrics plumbing, or a committed history of past runs.

## Non-goals

- CPU time, memory, syscall, or network-byte measurement.
- Statistical rigor beyond min/median/mean/stdev of wall time.
- Warmup iterations, JIT-style priming, or outlier filtering.
- Persisting results to disk, committing run logs, or tracking
  regressions over time.
- Multi-target concurrency, fleet-scale timing, or orchestrator-level
  measurement.
- Integration with pytest (no markers, no collection).
- Portability to the `master` branch. This tool lives on
  `rustperformance` only.

## Architecture

```
bench_transports.py (script)
    │
    ├── load_inventory("inv.yaml")       # reuse
    ├── CategoryModel()                  # reuse, for include list union
    ├── make_transport("pyez" | "rustez")# reuse factory
    │
    ├── bench_fetch(backend, n=20)
    │       for _ in range(n):
    │           t0 = perf_counter()
    │           t = make_transport(backend)
    │           t.connect(source); t.fetch(includes); t.close()
    │           samples.append(perf_counter() - t0)
    │
    ├── bench_push(backend, n=3)
    │       for _ in range(n):
    │           t0 = perf_counter()
    │           <full connect→fetch→diff→load --merge→
    │            commit-confirmed(1)→confirm→close against first target>
    │           samples.append(perf_counter() - t0)
    │
    └── print_markdown_table(results)
```

Single file. No new package code. No changes to `srxsync/`.

## File layout

| File | Purpose |
|---|---|
| `tests/bench/__init__.py` | empty, marks directory as a package (optional — script imports work without it, but keeps imports tidy) |
| `tests/bench/bench_transports.py` | the script |

Not collected by pytest (filename does not match `test_*`). Runnable
directly: `python tests/bench/bench_transports.py`.

## Inputs and environment

- Reads `inv.yaml` from the current working directory (same convention
  as `srxsync` CLI).
- Expects credentials in environment per the existing secret-provider
  contract, typically populated by sourcing `~/.srxsync.env`.
- Uses the `source` stanza of the inventory for the fetch benchmark.
- Uses `targets[0]` for the push benchmark.
- Requires `[rust]` extra installed to run the rustez rows. If the
  `rustez` module is not importable, print a warning, run pyez-only,
  and exit 1.

## Measurement contract

| Parameter | Value | Why |
|---|---|---|
| Clock | `time.perf_counter()` | Monotonic, highest resolution available. |
| Warmup | none | Transparency over synthetic numbers. First-iteration startup cost (importing libs, opening SSH) is part of reality. |
| Fetch iters | 20 | Enough for a stable median; ~2 min wall time at ~5 s/fetch. |
| Push iters | 3 | Dominated by the 60 s commit-confirmed sleep, so more iters mostly measure Junos not the backend. 3 is enough to notice gross regressions. |
| Fetch scope | union of all target `include:` categories | Representative of a real orchestrator fetch. |
| Push mode | `--merge` | Idempotent across runs — no state change if the lab is already in sync, so the benchmark can be repeated safely. |
| Commit-confirmed timer | 1 minute | Junos minimum. Shortest end-to-end push we can legitimately measure. |
| Concurrency | serial, one host at a time | Isolates backend overhead, not orchestrator. |

## Output format

Single markdown table written to stdout. Example shape:

```
## Transport benchmark

Inventory: inv.yaml  |  Source: srx-master.lab  |  Push target: srx-site-a.lab
Fetch iters: 20  |  Push iters: 3  |  Commit-confirmed: 60s

| backend | op    |  n | min    | median | mean   | stdev  |
|---------|-------|---:|-------:|-------:|-------:|-------:|
| pyez    | fetch | 20 | 4832ms | 5012ms | 5041ms |  184ms |
| rustez  | fetch | 20 |  812ms |  874ms |  889ms |   42ms |
| pyez    | push  |  3 | 68.1s  | 68.4s  | 68.5s  |  0.3s  |
| rustez  | push  |  3 | 64.2s  | 64.5s  | 64.4s  |  0.2s  |
```

Units: ms for fetch, s for push, chosen per-row based on magnitude.
Numbers rendered to 3 significant figures.

## Error handling

- Any exception during a timed iteration aborts the bench for that
  (backend, op) pair, reports the partial samples (if any) plus an
  error line, and continues to the next pair. One broken backend must
  not silently drop the other.
- Inventory load errors, missing creds, and unreachable hosts fail
  fast with a clear message and non-zero exit. Do not mask.
- Push iterations that commit successfully but fail to confirm are
  treated as failed iterations and **not** included in the sample.
  Log the failure and continue.

## Safety

- Read-only fetch is always safe.
- Push uses `--merge` with `commit confirmed 1`. If the script crashes
  or the operator aborts between `commit confirmed` and `confirm`,
  Junos auto-rolls back in 60 s. No manual cleanup required.
- The benchmark should not be run against production. Document this
  in the script docstring; don't add gating code — that's a
  responsibility, not a mechanism.

## Invocation

```
source .venv/bin/activate
source ~/.srxsync.env
python tests/bench/bench_transports.py
```

No CLI flags. Defaults are the spec values.

## Dependencies

- stdlib: `time`, `statistics`, `sys`, `pathlib`
- srxsync: `srxsync.inventory.load_inventory`,
  `srxsync.transport.make_transport`,
  `srxsync.categories.CategoryModel`,
  `srxsync.diff.DiffBuilder` (for the push path)

No new third-party dependencies.

## Testing

This tool is a measurement instrument, not a feature. It has no
automated tests. Validation is a single manual run on the lab:
numbers come out, no exceptions, units look right, both backends
represented.

## Open risks

- First-iteration import cost is bundled into iteration 1. If that
  skews the median meaningfully (e.g., a 3 s import on a 1 s
  operation), the min column is the honest number to quote. This is
  a known trade-off, not a bug.
- Lab-link latency will dominate short operations and vary run-to-run.
  Numbers are only comparable within a single invocation, not across
  runs on different days or networks. Note this in the script
  docstring.
