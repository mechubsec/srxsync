# Security Policy

## Reporting a vulnerability

Please report suspected security issues privately using [GitHub Security
Advisories](https://github.com/fastrevmd-lab/srxsync/security/advisories/new)
for this repository. Do not open a public issue for anything that could be
exploited before a fix ships.

Include what you can: affected version/commit, a reproduction or PoC, and
the impact you'd expect (e.g. "attacker with read access to the inventory
file can exfiltrate device credentials", "malicious target config causes an
unintended device mutation").

## Scope

srxsync pushes configuration to live Juniper SRX firewalls. In addition to
the usual software vulnerability classes (dependency CVEs, injection,
unsafe deserialization), the following are in scope and treated as
security issues, not ordinary bugs:

- **Wrong-target pushes.** Any bug that could cause srxsync to load or
  commit configuration onto a device other than the one the operator
  intended — inventory parsing errors, target-list corruption, host
  resolution mistakes.
- **Partial-apply / no-rollback failures.** Any path where a `load` can
  reach a device without a paired `commit confirmed` or explicit rollback,
  leaving a target in a half-configured state.
- **Credential-provider weaknesses.** Issues in `srxsync/secrets/` (env,
  netrc, keyring, Vault providers) that could leak, log, or mishandle
  device credentials.
- **Bypassing safety rails.** Any way to skip or defeat `--commit-confirmed`
  or `--dry-run` such that a dry run performs a real push, or a
  commit-confirmed push becomes an unconfirmed one.

Denial-of-service against a target SRX (e.g. flooding it with NETCONF
requests) is in scope. Vulnerabilities that require an attacker to already
have write access to the inventory/config files being pushed are lower
severity but still worth reporting — see them as an operator-trust
boundary, not a hard wall.

## Supported versions

srxsync does not yet have tagged releases; security fixes are made against
`master`.
