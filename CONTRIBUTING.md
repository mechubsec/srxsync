# Contributing to srxsync

Thanks for looking at srxsync. This document covers how to get a dev
environment running, how the project is tested and linted, and — because
this tool pushes configuration to live Juniper SRX firewalls — the safety
expectations that apply to any change touching the push/commit path.

## Setup

```
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
```

Python 3.11+ is required.

## Lint, type-check, test

```
ruff check .
mypy srxsync
pytest tests/unit
```

`tests/integration/` exercises a real vSRX lab and is skipped automatically
unless a `tests/lab.yaml` is present locally (see `tests/lab.yaml.example`).
CI never runs it — there is no lab reachable from a GitHub Actions runner.
Don't add tests there expecting CI coverage; put the behavior under test in
`tests/unit` against fixtures instead.

## The device-mutating path gets extra scrutiny

srxsync's `push` command loads configuration onto live firewalls. Any
change that touches `load`, `commit`, `commit confirmed`, the diff/payload
computation feeding those calls, or the `--dry-run` / `--commit-confirmed`
flags needs to hold to a few non-negotiable rules:

- **Deterministic code decides, not a model.** If your change involves any
  LLM-assisted code generation or an AI agent, the agent may draft, explain,
  or summarize — it must never be the thing deciding what gets pushed to a
  device. That decision stays in reviewable, deterministic code.
- **No partial commits.** Every `load` must be paired with a `commit
  confirmed` (or an explicit rollback) so a mid-run failure never leaves a
  target half-configured. See the existing behavior in
  `srxsync/orchestrator.py` before changing this.
- **Nothing runs unattended against real hardware.** `tests/integration/`
  requires an explicit `--run-integration` flag and a local `tests/lab.yaml`
  — never wire it into a default CI job, a cron, or anything a model can
  trigger without a human in the loop.
- **`--dry-run` must stay a true dry run.** If you touch the dry-run path,
  verify by hand that it still performs zero `load`/`commit` calls.

If you're not sure whether a change touches this path, flag it in your PR
description rather than guessing.

## Review

Open a PR against `master`. Expect scrutiny in rough order of severity:

1. Correctness of the config diff/push/commit-confirmed logic.
2. Safety-rail regressions (partial commits, dry-run leaking a real push,
   secret handling in the credential providers).
3. Everything else (style, test coverage, docs).

## Licensing

srxsync is MIT-licensed (see `LICENSE`). By submitting a contribution, you
agree it's licensed under the same terms.
