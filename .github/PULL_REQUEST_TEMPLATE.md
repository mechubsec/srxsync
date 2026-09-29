## What does this change do, and why?

<!-- One or two sentences. -->

## Does this touch the push/commit path?

<!-- load, commit, commit confirmed, diff/payload computation, or the
     --dry-run / --commit-confirmed flags in srxsync/orchestrator.py or
     srxsync/transport/. If yes, say what you verified by hand (e.g. "ran
     --dry-run and confirmed zero load/commit calls"). If no, delete this
     section. -->

- [ ] This PR touches the device push/commit path
- [ ] If checked above: no partial-commit regression, `--dry-run` still
      performs zero `load`/`commit` calls, no model output decides what
      gets pushed

## Checklist

- [ ] `ruff check .` passes
- [ ] `mypy srxsync` passes
- [ ] `pytest tests/unit` passes
- [ ] Any new/changed test fixtures use synthetic data (no real device
      hostnames, serials, or credentials)
