# Paperclip

## Overview

[Paperclip](https://paperclip.ing) is an open-source control plane for AI agents: an org
chart, ticketing, per-agent budgets and scheduled "heartbeats" that wake agents to work.
It runs as a single pod with an embedded PostgreSQL, pinned to k3-node3.

> **Status:** deployed 2026-09-24 on k3-node3.

## Access

| Detail | Value |
|---|---|
| URL | `http://localhost:3110` via port-forward (below) |
| Mode | `authenticated` / `private` — create the admin account on first visit |

```bash
kubectl -n paperclip port-forward svc/paperclip 3110:3110
```

Away from the home LAN (API server unreachable), tunnel through a netbird peer instead —
this runs the port-forward on node3 and carries it back over SSH:

```bash
ssh -J rpi-sr-101 -L 3110:127.0.0.1:3110 ubuntu@100.101.7.201 \
  'sudo k3s kubectl -n paperclip port-forward svc/paperclip 3110:3110'
```

Local port 3110, not 3100, so it doesn't collide with a laptop Paperclip on 3100.
`PAPERCLIP_PUBLIC_URL` in the manifest must match whatever URL the browser uses, and
for a `localhost` URL the pod's `PORT` must equal the local port: Paperclip rewrites a
loopback public URL's port to its own listen port. That's why the pod listens on 3110.

## Installation

Secrets are created by hand and never committed:

```bash
kubectl create namespace paperclip
kubectl -n paperclip create secret generic paperclip-secrets \
  --from-literal=BETTER_AUTH_SECRET="$(openssl rand -hex 32)" \
  --from-literal=CLAUDE_CODE_OAUTH_TOKEN="<output of: claude setup-token>"
kubectl apply -f paperclip.yaml
```

## Agent logins

Agents use the Claude and ChatGPT **subscriptions**, not API keys. Never set
`ANTHROPIC_API_KEY` or `OPENAI_API_KEY` on an agent (or in the secret): Paperclip lets a
per-agent key win over the subscription login, and that bills per token. Agents share the
subscriptions' usage limits with interactive use — start with few agents on relaxed
heartbeats and watch weekly usage.

> The `CLAUDE_CODE_OAUTH_TOKEN` in `paperclip-secrets` does **not** reach agents: Paperclip
> blanks inherited credentials (`CLAUDE_CODE_OAUTH_TOKEN`, `CLAUDE_CONFIG_DIR`, `CODEX_HOME`,
> API keys…) in every agent process. It only serves manual `claude` use inside the pod.

All commands below run from a workstation and need a TTY (`ssh -t`, `exec -it`). They run as
`node` via `gosu` — the server's user — so agents can read what they write. Off the home LAN,
add `-J rpi-sr-101` and use `ubuntu@100.101.7.201`.

### Claude (per-company connection, via the UI)

1. In the Paperclip UI, start the Claude sign-in. It shows a one-time command with an
   attempt directory: `CLAUDE_CONFIG_DIR='/paperclip/instances/default/ai-local-logins/<id>'`.
2. Run the login in the pod with that `<id>`:

   ```bash
   ssh -t ubuntu@k3-node3 "sudo k3s kubectl -n paperclip exec -it deploy/paperclip -c paperclip -- \
     gosu node env -u CLAUDE_CODE_OAUTH_TOKEN \
     CLAUDE_CONFIG_DIR=/paperclip/instances/default/ai-local-logins/<id> \
     claude auth login --claudeai"
   ```

   Open the printed URL, approve, paste the code back. `env -u` hides the container token so
   Claude Code can't treat itself as already logged in and skip storing the credential.
3. Back in the UI, finish the sign-in. Paperclip copies the credential into its encrypted
   database as the company's default Anthropic **subscription** connection and **deletes the
   attempt directory** — a vanished directory means success. Attempts expire if left open.

### Codex (host login, shared by every Codex agent)

```bash
ssh -t ubuntu@k3-node3 "sudo k3s kubectl -n paperclip exec -it deploy/paperclip -c paperclip -- \
  gosu node env -u OPENAI_API_KEY codex login --device-auth"
```

Open the printed URL, sign in to ChatGPT, enter the code. The login lands in
`/paperclip/.codex/auth.json` on the PVC; Paperclip symlinks it into each Codex agent's
managed `CODEX_HOME`, so refreshed tokens stay live. Device login may need enabling in the
ChatGPT account's security settings. If the Codex agent screen still reports it
unconnected, use the UI's Codex sign-in instead — same `--device-auth` flow, into a
Paperclip-managed attempt directory, finished in the UI like Claude.

### Check

```bash
# Codex: expect "Logged in using ChatGPT"
sudo k3s kubectl -n paperclip exec deploy/paperclip -c paperclip -- \
  gosu node env -u OPENAI_API_KEY codex login status
```

For Claude, and for each agent, use the agent's **Test** button in the UI — the Claude
credential lives in Paperclip's database, not in a directory the CLI can read.

## Design notes

| Choice | Why |
|---|---|
| k3-node3 | node4 is reserved for Ollama/RKLLaMA RAM, node1 carries GitLab, node2 is avoided |
| 500m / 1Gi request, 4Gi limit | Scheduler accounts for it; bounded so it can't crowd node3 |
| `local-path`, 50Gi | Pod is pinned; embedded Postgres prefers local NVMe over Longhorn replication |
| `Recreate` strategy | Two pods on one embedded-Postgres data dir would corrupt it |
| No `fsGroup`; init container `chmod 0700` on the DB dir | The entrypoint chowns `/paperclip` itself; `fsGroup` adds group bits on every start and Postgres then refuses the data dir |
| Probes send `Host: localhost`; pod listens on 3110 | Pod-IP hostnames get 403; loopback public URLs are rewritten to the listen port |
| Liveness delay 120s | First boot applies ~280 DB migrations |
| Image `ghcr.io/paperclipai/paperclip:2026.916.1` | Official multi-arch image; arm64 variant verified |
