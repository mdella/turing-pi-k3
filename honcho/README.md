# Honcho — agent memory server (k3s)

[Honcho](https://github.com/plastic-labs/honcho) v3.0.12 (Plastic Labs, open source): stores conversations between
peers (people and agents), derives long-term "conclusions" about each peer, and answers questions about them.
Deployed 2026-09-24. The server is API-only; a web UI (Hombre, below) is deployed alongside it.

## Access
| From | URL |
|---|---|
| netbird peers | `http://100.101.160.239:8800` (node1) — or node3 `100.101.7.201:8800`, node4 `100.101.238.181:8800` |
| home LAN | `http://192.168.4.10{1,3,4}:30800` (NodePort) |
| inside the cluster | `http://honcho-api.honcho.svc.cluster.local:8000` |

Every API call needs `Authorization: Bearer <JWT>` (`AUTH_USE_AUTH=true`). Health check: `GET /health` (no token).

## Web UI — Hombre
[Hombre](https://github.com/lovethatbrandx/hombre) (community project, AGPL-3.0, pinned to commit `a845120a`): browse
workspaces, peers, sessions, messages and conclusions, and chat with a peer.

| From | URL |
|---|---|
| netbird peers | `http://100.101.160.239:8801` (or node3 `100.101.7.201:8801`, node4 `100.101.238.181:8801`) |
| home LAN | `http://192.168.4.101:30801` |

- Login: user `admin`; password in the cluster:
  `kubectl get secret hombre-secrets -n honcho -o jsonpath='{.data.DASHBOARD_PASSWORD}' | base64 -d; echo`
- Its backend holds a Honcho **admin** token (in `hombre-secrets`) and proxies `/api/*` → Honcho `/v3/*`; the browser never sees the token.
- **Never run it without `DASHBOARD_USER`/`DASHBOARD_PASSWORD`**: it falls back to "open access mode" (full Honcho admin for anyone).
- Built locally (`hombre/Dockerfile`): upstream's image isn't publicly pullable and its Dockerfile adds a Docker CLI
  (x86_64-only) for container-control features that need the Docker socket — dropped here, so those Settings buttons
  (restart Honcho, view container logs) won't work on k3s. Image lives only in node1's containerd, so the pod is pinned to node1.
- Rebuild/upgrade:
  ```bash
  git clone https://github.com/lovethatbrandx/hombre && cd hombre && git checkout <commit>
  cp <repo>/honcho/hombre/Dockerfile Dockerfile
  docker build -t localhost/hombre:<commit> . && docker save localhost/hombre:<commit> | sudo k3s ctr images import -
  # update the image tag in hombre.yaml, then kubectl apply -f hombre.yaml
  ```
- Data (trash/exports, access logs, its own settings file) on a 1 Gi local-path volume at `/data`.

## Tokens
Issue from the API pod (the signing secret lives in the `honcho-secrets` Secret):
```bash
# one workspace (preferred for apps/agents)
kubectl exec -n honcho deploy/honcho-api -c api -- /app/.venv/bin/python scripts/generate_jwt.py --workspace <name> --print-only
# full access (admin) — keep private
kubectl exec -n honcho deploy/honcho-api -c api -- /app/.venv/bin/python scripts/generate_jwt.py --admin --print-only
```
**Do not use `--expires`.** v3.0.12 writes `exp` as a date string and PyJWT 2.12 rejects it, so every expiring token
fails with `401 Invalid JWT` (verified 2026-09-24). Tokens therefore don't expire; to revoke them all, replace
`AUTH_JWT_SECRET` in `honcho-secrets` and restart `honcho-api`/`honcho-deriver`. Recheck on upgrade.

## Using it
Python SDK (`pip install honcho-ai`, tested 2.5.0):
```python
from honcho import Honcho
h = Honcho(base_url="http://100.101.160.239:8800", api_key=TOKEN, workspace_id="my-app")
alice, bot = h.peer("alice"), h.peer("assistant")
s = h.session("chat-1")
s.add_messages([alice.message("I prefer Python over Go."), bot.message("Noted!")])
print(alice.chat("What language does this user prefer?"))
```
Upstream also ships an MCP server (`mcp/`, not deployed) and a CLI (`honcho-cli/`) for agent integrations.

## Design
| Part | Details |
|---|---|
| `honcho-api` | FastAPI on :8000. Init container runs migrations **and** `scripts/configure_embeddings.py --yes` (migrations create `vector(1536)`; this resizes to 768 — both API and deriver refuse to start on a mismatch). Idempotent. |
| `honcho-deriver` | Background worker that turns messages into conclusions |
| `honcho-db` | `pgvector/pgvector:pg15` StatefulSet, 10 Gi Longhorn PVC |
| LLM | Mac Studio `qwen3-coder-next` on llama-server `http://100.101.193.15:8080/v1` for deriver, summary, dialectic (all levels), dream. Dialectic input capped at 40K to fit the 64K slot. Shares the coder's 4 slots with human users. |
| Embeddings | in-cluster Ollama (node4, CPU) `nomic-embed-text`, 768 dims, ~0.2 s per call |
| netbird relay | `honcho-netbird-relay` DaemonSet: `socat` on each node's host network — :8800 → API, :8801 → Hombre |
| Placement | prefers node3/node4 (node1 hosts GitLab); Redis cache off; no OpenAI/Anthropic/Gemini keys used |

**Why the relay:** netbird's firewall accepts traffic to a node's own ports but drops traffic kube-proxy forwards on to
a pod. The NodePort answers on the LAN but times out over netbird; host-network processes (SSH, kubelet, the relay)
work. All three running nodes are netbird peers (node1 100.101.160.239, node3 100.101.7.201, node4 100.101.238.181).

## Behavior to know
- **Conclusions are not instant.** The deriver batches per session until ~1,024 new tokens
  (`DERIVER_REPRESENTATION_BATCH_TARGET_INPUT_TOKENS`) or 30 min (`…_BATCH_MAX_AGE_SECONDS=1800`).
  A short chat is processed ~30 min later. `chat()` still sees recent messages right away.
- The Mac coder must be up: if someone runs `ai-mem big`, deriver and dialectic calls fail until `ai-mem coder`.
- Postgres volume runs with 2 of 3 Longhorn replicas while node2 is down. **No database backup is set up yet.**

## Verified 2026-09-24
End-to-end over netbird with the Python SDK (workspace `e2e-test`, kept as a demo — safe to delete):
- 5 messages added; `alice.chat(...)` answered correctly from the coder in 11 s.
- Deriver age-flushed the batch after 30 min (LLM call 10.5 s) and stored **9 correct conclusions** about Alice
  (name, homelab, Ghost, GitLab, local LLMs, prefers Python, dark mode, building agent memory, dislikes phone-home tools).
- Unauthenticated calls → 401. Hombre over netbird on all three nodes: data only with login (401 otherwise).

## Install / rebuild
```bash
kubectl create namespace honcho
PW=$(openssl rand -hex 24)
kubectl create secret generic honcho-secrets -n honcho \
  --from-literal=POSTGRES_PASSWORD="$PW" \
  --from-literal=DB_CONNECTION_URI="postgresql+psycopg://honcho:$PW@honcho-db.honcho.svc.cluster.local:5432/honcho" \
  --from-literal=AUTH_JWT_SECRET="$(openssl rand -hex 32)" \
  --from-literal=LLM_OPENAI_API_KEY=local
kubectl exec -n ai-services ollama-0 -- ollama pull nomic-embed-text
kubectl apply -f honcho.yaml
```
