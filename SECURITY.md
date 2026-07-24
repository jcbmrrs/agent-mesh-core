# Security

## Trust model

`agent-mesh-core` is single-operator personal infrastructure. It assumes:

- One human operator who controls every machine on the tailnet.
- A private [Tailscale](https://tailscale.com/) network as the only network
  boundary. The MCP server and HTTP wrapper bind to the Mac mini's Tailscale
  interface, not `0.0.0.0` or the public internet.
- Every caller reaching the MCP/HTTP services is already trusted. Caller
  identity is an explicit `agent_id` parameter supplied by the caller, not
  derived from any session, certificate, or transport-level identity.

The app layer deliberately does **not** provide:

- Authentication of callers.
- Authorization or per-agent permission scoping.
- Protection against one trusted caller passing another caller's `agent_id`
  (anti-spoofing).
- Encryption beyond whatever Tailscale/WireGuard already provides at the
  network layer.
- Rate limiting, quota enforcement, or protection against a misbehaving (but
  trusted) client sending excessive load.

If your threat model includes untrusted or semi-trusted callers on the same
network, do not deploy this as-is — treat it as a design reference instead.
Multi-tenant authorization would need to be designed and added; it is not a
missing feature awaiting a patch, it's out of scope for this project's stated
purpose.

## What the filesystem/locking layer does defend against

Within the trusted-caller assumption above, the coordinator still defends
against local-disk correctness failures: concurrent writers, partial writes,
symlink traversal outside the mesh root, and crashed claimants leaving
orphaned processing state. See `AGENTS.md`'s "Key invariants" section and
`docs/IMPLEMENTATION_PLAN_v2.md` for the specifics — those protections are
real and apply regardless of the network trust model.

## Reporting a concern

This is a personal project maintained by one person in spare time, not a
supported product. If you find a real security issue (something that breaks
the trust model above, not something already documented as out of scope),
open a GitHub issue or reach out directly. There is no bug bounty and no SLA
on response time.
