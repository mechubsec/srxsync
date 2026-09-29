<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/mechub-mark.svg">
    <img src="docs/assets/mechub-mark-light.svg" width="72" alt="mechub mark">
  </picture>
</p>

<h1 align="center">srxsync</h1>

<p align="center"><strong>Fleet sync for Juniper SRX firewalls</strong><br>
<em>a mechub project — sovereign network-security automation</em></p>

> **Unofficial / community project.** This repository is an independent, community-driven project. It is not affiliated with, endorsed by, sponsored by, or supported by Hewlett Packard Enterprise or Juniper Networks. "HPE", "Juniper", "SRX", "JUNOS", "Security Director" and "Juniper Mist" are trademarks of their respective owners and are used here only to describe what this software interoperates with. Please direct support and licensing questions about those products to the respective vendors.

Keep a fleet of Juniper SRX firewalls in sync with a designated master SRX.
Reads selected configuration sections from the master and pushes them to a
list of target devices, with safety rails (`commit confirmed`), drift
detection, and per-target include lists.

An optional Rust-backed NETCONF transport (`--transport rustez`, Python 3.12
only) is available alongside the default PyEZ backend; see [Transports](#transports).

## Install

```
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
```

Optional extras:

```
pip install -e .[keyring]   # OS keyring secret provider
pip install -e .[vault]     # HashiCorp Vault secret provider
pip install -e .[rust]      # rustez NETCONF backend (Python 3.12 only; --transport rustez)
```

Python 3.11+ required (Python 3.12 exactly for the `[rust]` extra — rustez
ships cp312 wheels only).

## Quickstart

1. Write an inventory file (`inv.yaml`):

    ```yaml
    source:
      host: srx-master.example.net
      auth: { provider: env }

    targets:
      - host: srx-site-a.example.net
        auth: { provider: env }
        include: [objects, policies, nat, qos, zones]
      - host: srx-site-b.example.net
        auth: { provider: env }
        include: [policies, nat]
    ```

    Each target's `include:` explicitly lists the categories it will receive —
    no top-level default, no implicit inheritance. Read the inventory and you
    know exactly what every device gets.

2. Provide credentials out-of-band (see [Secrets](#secrets)):

    ```
    export SRX_USER_SRX_MASTER_EXAMPLE_NET=srxsync
    export SRX_SSH_KEY_SRX_MASTER_EXAMPLE_NET=~/.ssh/id_ed25519
    # repeat per target host
    ```

3. Check first:

    ```
    srxsync check --inventory inv.yaml --verbose
    ```

4. Push (always commit-confirmed by default):

    ```
    srxsync push --inventory inv.yaml --merge --commit-confirmed 5
    ```

## CLI

```
srxsync push  --inventory inv.yaml (--replace | --merge)
              [--commit-confirmed N] [--max-parallel N]
              [--on-error continue|abort] [--dry-run]
              [--transport {pyez,rustez}]

srxsync check --inventory inv.yaml [--verbose] [--transport {pyez,rustez}]
```

| Flag | Meaning |
|---|---|
| `--replace` / `--merge` | Mutually exclusive. `--replace` annotates each category root with `replace="replace"` so Junos wipes slave-specific siblings within synced subtrees. `--merge` only adds/updates. |
| `--commit-confirmed N` | Commit with an N-minute auto-rollback timer; srxsync calls `commit` again to seal. Default: 5. |
| `--max-parallel N` | Concurrent target workers. Default: 5. |
| `--on-error continue\|abort` | On a per-target failure, continue (exit non-zero at end) or cancel remaining work. Default: continue. |
| `--dry-run` | Fetch source + compute per-target payload, print what would change, do not load or commit. |
| `--verbose` (check only) | Show per-category XML diff for drifted targets. |
| `--transport {pyez,rustez}` | NETCONF backend. `pyez` (default) is junos-eznc; `rustez` is the Rust-backed client (install with `pip install -e .[rust]`). Both produce identical results; `rustez` is faster for large fleets. |

Exit 0 only when every target succeeded (push) or is in sync (check).

## Categories

Synced scope is defined in [`srxsync/data/categories.yaml`](srxsync/data/categories.yaml):

| Category | Junos paths |
|---|---|
| `objects` | `security address-book`, `applications` |
| `policies` | `security policies` |
| `nat` | `security nat` |
| `qos` | `class-of-service` |
| `zones` | `security zones` (interfaces pruned — device-specific) |

**Excluded from sync:** `interfaces`, `routing-options`, `protocols`, `system`,
`chassis`, and zone-to-interface bindings. These are device-specific and
never cross-synced.

### Adding a new category

Adding NTP, SNMP, or anything else is a YAML edit, not a code change. Append
to `srxsync/data/categories.yaml`:

```yaml
ntp:
  paths:
    - /configuration/system/ntp
```

Then add `ntp` to the `include:` list of whichever targets should receive it.

## Secrets

Credentials never live in the inventory file. `auth.provider` selects a
`SecretProvider`:

| Provider | Reads |
|---|---|
| `env` | `SRX_USER_<HOST>`, `SRX_PASSWORD_<HOST>` or `SRX_SSH_KEY_<HOST>` (tilde-expanded path). Host dots and dashes become underscores. |
| `netrc` | `~/.netrc` entry matching `machine <host>` |
| `keyring` | OS keyring slot `srxsync/<auth.key>`, stored as `username:password` |
| `vault` | HashiCorp Vault path `auth.path`, `VAULT_ADDR` + `VAULT_TOKEN` env |

Example env-var wiring for `srx-a.example.net`:

```
export SRX_USER_SRX_A_EXAMPLE_NET=srxsync
export SRX_SSH_KEY_SRX_A_EXAMPLE_NET=~/.ssh/id_ed25519
```

## Safety

1. **No partial commits.** Every `load` is paired with `commit confirmed` +
   `confirm`. Script crash or network drop between them → the SRX
   auto-rolls back after the timer expires.
2. **Per-target isolation.** One target's failure never affects another
   (separate `Transport` instances per worker).
3. **Best-effort cleanup.** On exception, `rollback()` + `close()` run;
   cleanup errors are swallowed so the original error is preserved.
4. **Honest exit code.** Exit 0 only if every target reported success;
   `--on-error continue` does not mask failures.

## Testing

Two layers, no device mocks.

```
pytest tests/unit/            # pure logic against XML fixtures
pytest tests/integration/     # real vSRX lab (skipped if tests/lab.yaml missing)
```

### Lab setup

Copy `tests/lab.yaml.example` to `tests/lab.yaml` (gitignored) and fill in
three vSRX hosts (one master + two slaves). Export credentials per host, or
set the defaults once:

```
export SRXSYNC_LAB_USER=srxsync
export SRXSYNC_LAB_SSH_KEY=~/.ssh/id_ed25519
```

The lab tests exercise the full pipeline — drift detection, merge sync,
`--replace` wipe, and commit-confirmed auto-rollback. Every test is
parametrized over both transports (`pyez` and `rustez`) when the `[rust]`
extra is installed; rustez cases are skipped cleanly otherwise. The
commit-confirmed test waits 75 seconds for the Junos rollback timer, so
expect ~3–4 minutes for a full integration run across both backends.

## Architecture

```
CLI → Orchestrator → (CategoryModel, DiffBuilder, DriftDetector, Transport)
                      │                                            │
                      └──── SecretProvider (env/netrc/keyring/vault)
```

- **CategoryModel** (`categories.py`) — loads `data/categories.yaml`,
  resolves category names → paths + prune rules.
- **DiffBuilder** (`diff.py`) — extracts source subtrees, applies prune
  rules, annotates replace-mode category roots.
- **DriftDetector** (`drift.py`) — canonical XML compare of source vs
  target within the synced scope.
- **Transport** (`transport/base.py`) — abstract; two concrete backends
  selected at runtime via `--transport`:
  - `PyEZTransport` (`transport/pyez.py`) — junos-eznc, default.
  - `RustezTransport` (`transport/rustez.py`) — Rust-backed via
    [rustez](https://github.com/fastrevmd-lab/rustEZ) + rustnetconf,
    gated by the `[rust]` extra. Integration tests parametrize both
    backends so parity is enforced.
- **Orchestrator** (`orchestrator.py`) — async semaphore-capped fanout,
  per-target category resolution and lifecycle (`connect → load → commit
  confirmed → confirm → close`), `--on-error` handling, aggregate exit code.
  Master is fetched once with the union of all target includes.

## Benchmarking

A lightweight wall-time comparator lives at
[`tests/bench/bench_transports.py`](tests/bench/bench_transports.py):

    source .venv/bin/activate
    source ~/.srxsync.env
    python tests/bench/bench_transports.py

It measures 20 fetches and 3 merge-pushes per backend against the
inventory in `inv.yaml` and prints a markdown table. See
[`docs/superpowers/specs/2026-04-23-transport-benchmark-design.md`](docs/superpowers/specs/2026-04-23-transport-benchmark-design.md)
for the exact measurement contract.

## Transports

`master` is the single branch. It ships two NETCONF backends behind the
same `Transport` interface, selected with `--transport {pyez,rustez}`:

- **`pyez`** (default) — [PyEZ](https://github.com/Juniper/py-junos-eznc)
  (`jnpr.junos`). Pure Python; `pip install -e .[dev]` and go.
- **`rustez`** (optional) — built on [rustEZ](https://crates.io/crates/rustez) /
  [rustnetconf](https://crates.io/crates/rustnetconf). Requires Python 3.12
  exactly (rustez ships cp312 wheels only; the `[rust]` extra's marker is
  `python_version == "3.12"`, not `>=`, so it stays a no-op resolver skip on
  newer interpreters instead of a failed source build); install with
  `pip install -e .[rust,dev]`.
  The extra is capped at `rustez>=0.8.4,<0.9`, the line parity was
  lab-verified on. Validated against PyEZ by a canonical-XML parity test and
  the parametrized lab suite.

**Locking differs between backends.** PyEZ takes an exclusive config lock at
`connect()`, so `check` and the source fetch lock each device while reading.
rustez only locks at the first `load()`, so `check` on rustez never locks.
Tracked in [#8](https://github.com/mechubsec/srxsync/issues/8).

## License

Licensed under [MIT](LICENSE).

## Contributing

Unless explicitly stated otherwise, contributions submitted for inclusion in this project are licensed under the [MIT License](LICENSE).

---

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/mechub-mark.svg">
    <img src="docs/assets/mechub-mark-light.svg" width="28" alt="">
  </picture><br>
  <sub><code>a mechub project</code> · deterministic decides · the model explains · a human approves<br>
  <a href="https://github.com/fastrevmd-lab">github.com/fastrevmd-lab</a></sub>
</p>
