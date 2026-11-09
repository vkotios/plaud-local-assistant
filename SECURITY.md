# Security policy

Plaud-local (`vkotios/plaud-local-assistant`) handles private audio, transcripts,
account sessions, and provider credentials. It is based on localplaud and keeps
the same deployment boundaries unless an overlay document says otherwise.

Please report suspected vulnerabilities privately.

## Report a vulnerability

Use **[Report a vulnerability](https://github.com/vkotios/plaud-local-assistant/security/advisories/new)**
to open a private GitHub security report for the maintainer. Do not disclose an
unpatched vulnerability in a public issue or Discussion.

Include the affected revision, deployment mode, impact, and minimal reproduction
steps using synthetic data. Redact credentials, session cookies, signed URLs,
private paths, account identifiers, and recording content. Never test another
person's deployment or data without their permission.

The maintainer will assess the report and coordinate fixes and disclosure with
the reporter. This community project does not promise a response-time SLA or a
bug bounty.

Upstream localplaud advisories may also apply when the issue lives in shared
code; cite the Plaud-local commit and the [upstream pin](docs/UPSTREAM.md) when
reporting.

## Supported revisions

Security fixes land on `main`. There is no maintained release-branch support
matrix yet. Follow security advisories, review changes before upgrading, and
back up your workspace before applying database or deployment changes.

## Deployment guidance

The default server binds to loopback. Before making it reachable over a network,
configure [Web App accounts](docs/accounts.md), a session secret, and HTTPS.
Keep secrets outside Git, explicitly authorize external providers and delivery
destinations, and maintain [workspace backups](docs/backups.md).

Plaud-local specifics:

- Secrets layout, MCP auth, SSRF, and backup checks:
  [docs/security-checklist.md](docs/security-checklist.md)
- Local knowledge MCP (read-only stdio; distinct from `@plaud-ai/mcp`):
  [docs/mcp-knowledge.md](docs/mcp-knowledge.md)
- BLE Note Pro remains **experimental**; Partner authorize is deferred — not GA:
  [docs/adr/0011-ble-experimental-policy.md](docs/adr/0011-ble-experimental-policy.md)
- Private / reverse-engineered Plaud APIs are permanently out of scope (`NOTICE`)

See the [security architecture](docs/adr/0006-security-posture.md),
[release checklist](docs/release-checklist.md), and [deployment guide](docs/deploy.md)
for current boundaries and limitations.
