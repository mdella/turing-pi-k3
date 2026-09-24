# Paperclip

## Overview

[Paperclip](https://paperclip.ing) is an open-source control plane for AI agents: an org
chart, ticketing, per-agent budgets and scheduled "heartbeats" that wake agents to work.
It runs as a single pod with an embedded PostgreSQL, pinned to k3-node3.

> **Status:** manifest written, not yet deployed.

## Access

| Detail | Value |
|---|---|
| URL | `http://localhost:3110` via port-forward (below) |
| Mode | `authenticated` / `private` — create the admin account on first visit |

```bash
kubectl -n paperclip port-forward svc/paperclip 3110:3100
```

Local port 3110, not 3100, so it doesn't collide with a laptop Paperclip on 3100.
`PAPERCLIP_PUBLIC_URL` in the manifest must match whatever URL the browser uses.

## Installation

Secrets are created by hand and never committed:

```bash
kubectl create namespace paperclip
kubectl -n paperclip create secret generic paperclip-secrets \
  --from-literal=BETTER_AUTH_SECRET="$(openssl rand -hex 32)" \
  --from-literal=CLAUDE_CODE_OAUTH_TOKEN="<output of: claude setup-token>"
kubectl apply -f paperclip.yaml
```

## Claude authentication

Agents use the Claude **subscription**, not an API key. Run `claude setup-token` on a
workstation, sign in with the Claude account, and store the printed `sk-ant-oat…` token as
`CLAUDE_CODE_OAUTH_TOKEN` (about a one-year lifetime). The image already ships Claude Code.

Do **not** also set `ANTHROPIC_API_KEY` in the secret or in the Paperclip UI — when it is
present Claude Code uses it instead of the subscription and bills per token.

Agents share the subscription's usage limits with interactive Claude use. Start with few
agents on relaxed heartbeats and watch weekly usage.

Alternative: `kubectl -n paperclip exec -it deploy/paperclip -- claude`, then `/login`.
The login lands in `/paperclip/.claude/` on the PVC and survives restarts.

## Design notes

| Choice | Why |
|---|---|
| k3-node3 | node4 is reserved for Ollama/RKLLaMA RAM, node1 carries GitLab, node2 is avoided |
| 500m / 1Gi request, 4Gi limit | Scheduler accounts for it; bounded so it can't crowd node3 |
| `local-path`, 50Gi | Pod is pinned; embedded Postgres prefers local NVMe over Longhorn replication |
| `Recreate` strategy | Two pods on one embedded-Postgres data dir would corrupt it |
| Liveness delay 120s | First boot applies ~280 DB migrations |
| Image `ghcr.io/paperclipai/paperclip:2026.916.1` | Official multi-arch image; arm64 variant verified |
