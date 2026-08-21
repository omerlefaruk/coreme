# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| 0.1.x | yes (pre-1.0; upgrade early and often) |

## Reporting a vulnerability

Do not open a public issue for security problems.

Use GitHub's "Report a vulnerability" flow under the repository's Security
tab (private advisory). Include: affected version/commit, reproduction
steps, and impact. You will get a response within a few days.

## Scope notes

- Secret **values** must never enter Git, hub payloads, or structured
  evidence; reports about secret leakage are high priority.
- The hub is designed to sit behind a TLS-terminating proxy; it serves
  plain HTTP on localhost by default.
- Machine and ops tokens are stored hashed; enrollment-token design lands
  with PLAN W2.
