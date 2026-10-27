# Honcho — agent memory server (k3s)

[Honcho](https://github.com/plastic-labs/honcho) v3.4.1 (Plastic Labs, open source): stores conversations between
peers (people and agents), derives long-term "conclusions" about each peer, and answers questions about them.
Deployed 2026-09-24. The server is API-only; a web UI (Hombre, below) is deployed alongside it.

## Access
| From | URL |
|---|---|
| netbird peers | `http://100.101.160.239:8800` (node1) — or node2 `100.101.47.92:8800`, node3 `100.101.7.201:8800`, node4 `100.101.238.181:8800` |
| home LAN | `http://192.168.4.10{1,3,4}:30800` (NodePort) |
| inside the cluster | `http://honcho-api.honcho.svc.cluster.local:8000` |

Every API call needs `Authorization: Bearer <JWT>` (`AUTH_USE_AUTH=true`). Health check: `GET /health` (no token).

## Web UI — Hombre
[Hombre](https://github.com/lovethatbrandx/hombre) (community project, AGPL-3.0, pinned to commit `a845120a`): browse
workspaces, peers, sessions, messages and conclusions, and chat with a peer.

| From | URL |
|---|---|
| netbird peers | `http://100.101.160.239:8801` (or node2 `100.101.47.92:8801`, node3 `100.101.7.201:8801`, node4 `100.101.238.181:8801`) |
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
**`--expires` works since v3.3.0** (fixed upstream; noted 2026-10-27, not yet re-tested here). Before that, v3.0.12 wrote `exp` as a date string and PyJWT 2.12 rejected it, so every expiring token
fails with `401 Invalid JWT` (verified 2026-09-24). Tokens therefore don't expire; to revoke them all, replace
`AUTH_JWT_SECRET` in `honcho-secrets` and restart `honcho-api`/`honcho-deriver`. Recheck on upgrade.

## Clients
- **Hermes Agent** (ns `hermes`, k3s since 2026-10-11) — in-cluster `http://honcho-api.honcho.svc.cluster.local:8000`,
  one workspace per profile, each with its own workspace-scoped token: `hermes` (Sorcerer Mickey), `cheshire`, `luna`.
  (Until 2026-10-11 Mickey ran on node1 and used the relay on `127.0.0.1:8800`.) See `../hermes/README.md`.

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
| LLM — local | Mac Studio `qwen3-coder-next` on llama-server `http://100.101.193.15:8080/v1` for **deriver + summary** (high volume, runs on every batch). Shares the coder's 4 slots with human users. |
| LLM — Claude | **`claude-sonnet-5-5`** (Anthropic API) for **dialectic (all levels) + dream** (since 2026-09-24; `claude-sonnet-5` until 2026-10-13). Key `LLM_ANTHROPIC_API_KEY` in `honcho-secrets` (env is read at pod start → `kubectl rollout restart` after changing it). Needs the prefill patch below. Verified: low/medium/high answers in 6–8 s, prompt caching active; ~1–3 ¢ per question. |
| Embeddings | `EMBED_MESSAGES=true`: every message and conclusion is embedded by in-cluster Ollama (node4, CPU) `nomic-embed-text`, 768 dims, ~0.2 s per call, stored in pgvector (`VECTOR_STORE_TYPE=pgvector`). **Not Anthropic** — Anthropic has no embeddings API, so `LLM_ANTHROPIC_API_KEY` plays no part; embeddings and search keep working if that token is revoked (only questions/dream break). |
| netbird relay | `honcho-netbird-relay` DaemonSet: `socat` on each node's host network — :8800 → API, :8801 → Hombre |
| Placement | prefers node3/node4 (node1 hosts GitLab); Redis cache off |

**Why the relay:** netbird's firewall accepts traffic to a node's own ports but drops traffic kube-proxy forwards on to
a pod. The NodePort answers on the LAN but times out over netbird; host-network processes (SSH, kubelet, the relay)
work. All four nodes are netbird peers (node1 100.101.160.239, node2 100.101.47.92, node3 100.101.7.201, node4 100.101.238.181).

## Behavior to know
- **Conclusions are not instant.** The deriver batches per session until ~1,024 new tokens
  (`DERIVER_REPRESENTATION_BATCH_TARGET_INPUT_TOKENS`) or 30 min (`…_BATCH_MAX_AGE_SECONDS=1800`).
  A short chat is processed ~30 min later. `chat()` still sees recent messages right away.
- The Mac coder must be up for new conclusions/summaries: if someone runs `ai-mem big`, the deriver fails until `ai-mem coder` (questions still work — they're on Sonnet).
- Privacy: questions and dream consolidation send the relevant stored conclusions/messages to Anthropic; message ingestion and conclusion extraction stay local.

## Verified 2026-09-24
End-to-end over netbird with the Python SDK (workspace `e2e-test`, kept as a demo — safe to delete):
- 5 messages added; `alice.chat(...)` answered correctly from the coder in 11 s.
- Deriver age-flushed the batch after 30 min (LLM call 10.5 s) and stored **9 correct conclusions** about Alice
  (name, homelab, Ghost, GitLab, local LLMs, prefers Python, dark mode, building agent memory, dislikes phone-home tools).
- Unauthenticated calls → 401. Hombre over netbird on all three nodes: data only with login (401 otherwise).

## Verified 2026-10-19 — embeddings
- Config: `EMBED_MESSAGES=true`, `EMBEDDING_MODEL_CONFIG__MODEL=nomic-embed-text` (transport `openai`, base URL
  `http://ollama.ai-services.svc.cluster.local:11434/v1`), `EMBEDDING_VECTOR_DIMENSIONS=768`.
- A test call from the `honcho-api` pod returned a 768-dim vector. In the previous 24 h, 56 of 56 new messages got an
  embedding (1,133 in total), and the deriver's `search_memory`/`search_messages` tools used them, with no errors.
- To check again:
  ```bash
  kubectl -n honcho exec honcho-db-0 -- sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "
    select count(*) from messages where created_at > now()-interval '\''24 hours'\'';
    select count(*) from message_embeddings where created_at > now()-interval '\''24 hours'\'';"'
  ```
  The two counts should match.

## Backups
`honcho-db-backup` CronJob (`backup.yaml`), nightly **01:30 UTC**: `pg_dump -Fc` → `honcho-backups` Longhorn PVC (5 Gi),
each dump checked with `pg_restore --list`, **14 days** kept. First run 2026-09-24: 104 KB, 12 tables; restore test into
a scratch DB matched the live DB (9 conclusions, 5 messages, vector dim 768).
- In-cluster only (protects against corruption/mistakes, not losing the cluster). The usual target, SeaweedFS S3, was down
  on 2026-09-24 (filers crash-looping since node2 failed); it is healthy again, but the S3 upload step is still TODO.
- Run now: `kubectl create job -n honcho backup-$(date +%s) --from=cronjob/honcho-db-backup`
- Restore (into the live DB, after stopping api/deriver):
  ```bash
  kubectl scale deploy/honcho-api deploy/honcho-deriver -n honcho --replicas=0
  # in a pod mounting honcho-backups (see the restore-test job pattern in git history):
  pg_restore -h honcho-db -U honcho -d honcho --clean --if-exists --no-owner /backups/honcho-<timestamp>.dump
  kubectl scale deploy/honcho-api deploy/honcho-deriver -n honcho --replicas=1
  ```

## Local patch — Claude 5 models
Honcho up to v3.4.1 (checked 2026-10-27; first written for v3.0.12) only knows Claude 4-class models reject assistant prefill; Claude 5
models (Sonnet 5, Opus 5/5.5, Fable 5/5.1) do too, so structured-output calls would 400. `patches/anthropic-configmap.yaml`
mounts a patched `src/llm/backends/anthropic.py` (one function, see `patches/anthropic-prefill.patch`) over the image file
in api + deriver. **On upgrade:** regenerate from the new image's file, or drop it if upstream fixes the check.
Also: never set `*_THINKING_BUDGET_TOKENS` or `*_TEMPERATURE` for Claude 5 models — both are rejected (400).

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

## Upgrade 3.0.12 → 3.4.1 (2026-10-27)

Why: Starlette CVE-2026-48710 (fixed in 3.3.0), the JWT `--expires` fix, deriver reliability (malformed structured output is
retried instead of silently dropped), summary budgets, and a smaller image (627 → 426 MB). Steps:
1. Fresh dump `honcho-2026-10-27T162859Z.dump` (Job from CronJob `honcho-db-backup`; 49M, 12 tables) + Longhorn snapshot
   `honcho-db-pre-3-4-1` of `data-honcho-db-0`.
2. **Prefill patch regenerated:** upstream 3.4.1 still lists only the Claude 4 prefixes. Built from the image's own
   `anthropic.py` (sha256 equal to GitHub tag v3.4.1), same one-function change; `patches/` updated. The ConfigMap file
   keeps `kind`/`metadata` *after* `data` (so preserve that when regenerating).
3. Image pinned `v3.4.1@sha256:dc55e09c…`, pre-pulled on node3. The init container's `provision_db.py` ran the migrations
   (incl. concurrent queue indexes, `deletion_generation`); embeddings stayed at 768 dims. The DB StatefulSet was untouched.
4. Checks: `/openapi.json` reports 3.4.1, the patch is mounted in api and deriver, startup is clean, a read-only dialectic query on
   workspace `hermes` (Sonnet via the patched path) answered correctly in 6 s, responses carry the new `uid` field, a
   Cheshire test turn stored 4 messages with 4 embeddings and queued 4 deriver items. Hermes's key is workspace-scoped
   (401 on other workspaces). Rollback: restore the dump or the snapshot, then go back to the previous image + patch from git.

