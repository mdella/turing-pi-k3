# GitLab

## Overview

GitLab CE (Community Edition) deployed as a single-pod omnibus installation on K3s.
Includes a Kubernetes-executor GitLab Runner for CI/CD pipelines (used, among other
things, to power scheduled pull-mirror jobs — a workaround for pull mirroring being an
EE-only feature), plus a macOS shell runner on the Mac Studio for jobs that need macOS or
its GPU (see [Runners](#runners)).

## Access

| Detail | Value |
|---|---|
| URL | `https://scm.geekstyle.net` (public, via Cloudflare) — `gitlab.geekstyle.net` was retired 2026-09-27 |
| Pages | `pages.geekstyle.net` |
| Version | `gitlab/gitlab-ce:19.3.3-ce.0` (pinned) |
| IP | `192.168.4.201` (shared ingress-nginx) |
| SSH clone port | `2222` |
| Default admin | `root` |
| Initial root password | Stored in `/etc/gitlab/initial_root_password` inside the pod — **deleted after 24 hours**; reset via `gitlab-rake` if needed |

## Architecture

GitLab CE ships as an omnibus container — PostgreSQL, Redis, Puma, Sidekiq, Workhorse,
and nginx all run inside the single pod. This is intentional for homelab use: simpler
to operate than the full microservice Helm chart, which requires 8+ cores and 16+ GB RAM
dedicated to GitLab alone.

The runner is deployed separately via Helm and uses the Kubernetes executor, spawning
ephemeral pods in the `gitlab` namespace for each CI job.

## Resource Requirements

### Observed Usage (steady-state, ARM64)

| Component | CPU (actual) | Memory (actual) | CPU limit | Memory limit |
|---|---|---|---|---|
| GitLab CE pod | ~80m | ~3.7 Gi | 4000m | 10 Gi |
| GitLab Runner | ~18m | ~20 Mi | — | — |
| **Total** | **~100m** | **~3.7 Gi** | | |

GitLab schedules itself on whichever node has the most headroom. At time of install
it landed on **k3-node4** (worker), which is appropriate — it frees the control-plane
nodes (k3-node1–3) for etcd and the Kubernetes API.

### Impact on Cluster Headroom

Each node has 16 GB RAM. With the full workload stack running, node memory utilisation
before and after GitLab:

| Node | Before GitLab | After GitLab |
|---|---|---|
| k3-node1 | ~43% (6.9 Gi) | ~40% (6.4 Gi) |
| k3-node2 | ~40% (6.4 Gi) | ~43% (6.9 Gi) |
| k3-node3 | ~44% (7.1 Gi) | ~47% (7.5 Gi) |
| k3-node4 (GitLab) | ~39% (6.2 Gi) | **~52% (8.3 Gi)** |

k3-node4 carries the GitLab pod and sits at ~52% — comfortable, with ~7.7 Gi
still free. All nodes remain well within safe operating range.

### CPU Behaviour

GitLab is CPU-quiet at idle (~80m). Spikes occur during:
- **Git push/pull** — Gitaly and Puma spike to ~500m–1000m briefly
- **CI job dispatch** — runner spawns a pod; the job pod itself consumes CPU separately
- **Sidekiq background jobs** — background email, webhooks, cleanup; typically <200m

The 4000m CPU limit gives GitLab full use of 4 cores if needed without starving other
workloads, since no other single pod on the cluster requests more than ~1000m.

### First-Boot Resource Spike

During the initial `gitlab-ctl reconfigure` run (first pod start only), all internal
services (PostgreSQL, Redis, Puma workers, Sidekiq) start simultaneously. Memory
peaks at ~8–9 Gi during this window. A 7 Gi limit caused OOM kills during testing —
the 10 Gi limit exists specifically to survive this startup burst. After reconfigure
completes, steady-state drops to ~3.7 Gi.

### Runner Job Pods

Each CI job spawned by the Kubernetes executor creates an ephemeral pod in the `gitlab`
namespace. These pods exist only for the duration of the job and are cleaned up
automatically. Resource usage depends entirely on the job's workload — the
`alpine/git`-based mirror-sync job uses ~50m CPU and ~100 Mi RAM.

## Storage

| Volume | StorageClass | Size | Mount |
|---|---|---|---|
| `gitlab-data` | Longhorn | 50 Gi | `/etc/gitlab`, `/var/log/gitlab`, `/var/opt/gitlab` (via subPath) |

A single PVC with three subPaths keeps config, logs, and data together while making
it possible to back up or snapshot the whole installation as one Longhorn volume.

## Installation

```bash
kubectl apply -f gitlab.yaml
```

First boot takes **15–20 minutes** on ARM64. The omnibus reconfigure run (database
migrations, asset compilation, service startup) completes before the readiness probe
passes. Do not set a liveness probe — it will kill the pod before init finishes.

Watch progress:

```bash
kubectl logs -n gitlab -l app=gitlab -f
# Or check internal service status once the container is running:
kubectl exec -n gitlab $(kubectl get pod -n gitlab -l app=gitlab -o jsonpath='{.items[0].metadata.name}') -- gitlab-ctl status
```

## GitLab Runner Installation

The runner requires a runner authentication token generated after GitLab is up:

```bash
# 1. Create a runner via the API (get a personal access token first)
PAT=$(kubectl exec -n gitlab $(kubectl get pod -n gitlab -l app=gitlab -o jsonpath='{.items[0].metadata.name}') -- \
  gitlab-rails runner "
token = User.find_by_username('root').personal_access_tokens.create(
  name: 'runner-setup', scopes: ['api'], expires_at: 1.day.from_now
)
puts token.token
")

RUNNER_TOKEN=$(curl -s -X POST "http://gitlab.gitlab.svc.cluster.local/api/v4/user/runners" \
  -H "PRIVATE-TOKEN: $PAT" \
  --form "runner_type=instance_type" \
  --form "description=k3s-cluster-runner" | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])")

# 2. Install via Helm
helm repo add gitlab https://charts.gitlab.io
helm install gitlab-runner gitlab/gitlab-runner \
  --namespace gitlab \
  --set gitlabUrl=http://gitlab.gitlab.svc.cluster.local \
  --set runnerToken=$RUNNER_TOKEN \
  -f gitlab-runner-values.yaml
```

> **Note:** Use `http://gitlab.gitlab.svc.cluster.local` as the GitLab URL — not the
> external hostname. The runner pod resolves internal cluster DNS, not your local
> `/etc/hosts` entry.

## Pull Mirroring (CE workaround)

GitLab CE does not include pull mirroring (EE only). Use a scheduled CI/CD pipeline instead:

1. Create a project in GitLab
2. Add CI/CD variables (Settings → CI/CD → Variables):
   - `UPSTREAM_URL` — source repo URL (embed credentials if private)
   - `GITLAB_TOKEN` — project access token with `write_repository` scope
3. Add `.gitlab-ci.yml` to the project:

```yaml
mirror-sync:
  image: alpine/git
  script:
    - git clone --mirror "$UPSTREAM_URL" repo.git
    - cd repo.git
    - git push --mirror "https://oauth2:${GITLAB_TOKEN}@scm.geekstyle.net/${CI_PROJECT_PATH}.git"
  only:
    - schedules
```

4. Create a schedule under CI/CD → Schedules (e.g. `0 * * * *` for hourly)

## TLS / public access

TLS terminates at Cloudflare; GitLab itself serves plain HTTP behind the ingress
(`listen_https=false`, `external_url 'https://scm.geekstyle.net'`) and takes the client IP
from `CF-Connecting-IP` (trusted `10.42.0.0/16`). Sign-up is off and admins must use 2FA.
Git over SSH (port 2222) is internal only. Cloudflare's free plan caps request bodies at
100 MB, which limits large pushes over HTTPS.

## Runners

| Runner | Executor | Where | Tags | Untagged jobs |
|---|---|---|---|---|
| `k3s-cluster-runner` | Kubernetes (ARM64 job pods) | Helm release `gitlab-runner` in namespace `gitlab` | none | **yes** |
| `mac-studio-mdella` | shell (no containers) | Mac Studio, `~/gitlab-runner/`, LaunchDaemon `com.mdella.gitlab-runner`, runs as `mdella` | `macos`, `shell`, `metal`, `mac-studio` | **no** |

Keep each runner's minor version ≤ GitLab's (both are 19.3.x) and upgrade runners with GitLab.

**Choosing a runner is done per job, with `tags:` in `.gitlab-ci.yml`.** A job runs only on
a runner that has *all* of the job's tags. Jobs without `tags:` go to the cluster runner,
because the Mac runner does not accept untagged jobs.

```yaml
lint:                     # no tags -> k3s cluster runner, in a container
  image: python:3.12-slim
  script:
    - python -m compileall .

mac-build:                # macOS shell runner
  tags: [macos]
  script:
    - uv run pytest

gpu-render:               # needs the Mac's Apple GPU
  tags: [macos, metal]
  script:
    - uv run python render.py
```

To send every job in a file to the Mac, use `default:`:

```yaml
default:
  tags: [macos]
```

On the shell runner, `image:` and `services:` are ignored — jobs run directly on the Mac
with whatever is installed there (`uv` is on its `PATH`). Jobs run as `mdella` with access
to that account, so register it as a project runner (or lock it to projects) rather than
for every project. Tags, "run untagged jobs" and locking are set in GitLab's UI when the
runner is created (Admin → CI/CD → Runners, or Project → Settings → CI/CD → Runners).

## Common Commands

```bash
# Pod and runner status
kubectl get pods -n gitlab

# GitLab logs
kubectl logs -n gitlab -l app=gitlab --tail=50

# Internal service health
kubectl exec -n gitlab $(kubectl get pod -n gitlab -l app=gitlab -o jsonpath='{.items[0].metadata.name}') -- gitlab-ctl status

# Reset root password
kubectl exec -n gitlab -it $(kubectl get pod -n gitlab -l app=gitlab -o jsonpath='{.items[0].metadata.name}') -- \
  gitlab-rake "gitlab:password:reset[root]"

# Get initial root password (valid for 24h after first boot)
kubectl exec -n gitlab $(kubectl get pod -n gitlab -l app=gitlab -o jsonpath='{.items[0].metadata.name}') -- \
  grep 'Password:' /etc/gitlab/initial_root_password

# Runner registration check
kubectl logs -n gitlab -l app=gitlab-runner --tail=20
```

## ARM64 Tuning Notes

The default omnibus puma and sidekiq worker counts are sized for x86 servers with
dedicated RAM. On ARM with shared cluster resources, the following reductions in
`GITLAB_OMNIBUS_CONFIG` prevent OOM during startup:

```
puma['worker_processes'] = 2
sidekiq['concurrency'] = 5
prometheus_monitoring['enable'] = false
```

Disabling the internal Prometheus prevents port conflicts with the cluster's
kube-prometheus-stack.

Memory limit is set to 10 Gi. The container OOM-kills at lower values during the
first-boot reconfigure run when all internal services start simultaneously.

## Files

| File | Purpose |
|---|---|
| `gitlab.yaml` | Namespace, PVC, Deployment, Service, and Ingress |
| `gitlab-runner-values.yaml` | Helm values for the GitLab Runner (token supplied at install time) |
| `tests/test-gitlab.yaml` | Job to verify readiness, liveness, and API endpoints |

- **MCP server** enabled 2026-10-08 (`mcp_server_enabled`, off by default in CE) for Hermes — see `../hermes/README.md`.

## SSO users (2026-10-08)

- GitLab's OIDC client is now the Zitadel app **"GitLab (scm)"** in project **`scm`** (Secret `gitlab-oidc`, same key
  names; previous homelab-project secret backed up off-repo). Anyone signing in needs the `scm` grant.
- **Adding a person** without waiting for admin approval (`omniauth_block_auto_created_users`): create the user in
  `gitlab-rails runner` with a random password, `skip_confirmation`, and an identity
  `provider: "openid_connect", extern_uid: "<their Zitadel user id>"` — their first "Sign in with geekstyle" lands in
  that account. Done for the second user (`ladyofkrypton`, 2026-10-08).
- **`luna-bot`**: plain user for the Luna assistant's GitLab MCP access (PAT scope `mcp`); grant it project/group
  membership deliberately. See `../luna/README.md`.

## Rate limits (2026-10-08)

Sized for a home Starlink uplink (the scarce resource is upload bandwidth). GitLab sees real client IPs through the
tunnel (`real_ip` trusts the pod CIDR), so limits are per visitor, not per cloudflared pod. Set via
`gitlab-rails runner` (`ApplicationSetting`), equivalently Admin → Settings → Network → User and IP rate limits:

| Limit | Value |
|---|---|
| Unauthenticated web | 600 req / 600 s |
| Unauthenticated API | 300 req / 600 s |
| Unauthenticated Git over HTTP | 60 req / 600 s (~20 clones per IP per 10 min) |
| Unauthenticated search | 10 / min |
| Authenticated web, authenticated API | 7200 req / 3600 s each |

Cloudflare edge layer (applied 2026-10-08 via API): rate-limiting rule (zone `http_ratelimit` entrypoint) on host
`scm.geekstyle.net`, 100 req / 10 s per IP → block 10 s (burst test: 130 parallel requests → 429s, recovered within
seconds), and **AI crawler blocking** (`bot_management.ai_bots_protection: block`). **Bot Fight Mode is deliberately
off**: on the free plan it can challenge non-browser clients and cannot be bypassed by rules — that would break
`git clone` from outside and the Hermes / Luna GitLab MCP connections, which reach scm through Cloudflare.
The API token needs Zone → WAF: Edit and Zone → Bot Management: Edit for these.

## GitLab Pages (2026-10-08)

`https://pages.geekstyle.net/<namespace>/<project>/` — **namespace in path** (`gitlab_pages['namespace_in_path']`),
because `<ns>.pages.geekstyle.net` is a 2-level wildcard that Cloudflare's free Universal SSL doesn't cover. Pages nginx
listens on :80 in the same pod (`pages_nginx['listen_https'] = false`, real IP from CF-Connecting-IP); the gitlab Ingress
has a second host `pages.geekstyle.net`; tunnel rule + proxied CNAME; the Cloudflare rate-limit rule covers it too.
A project publishes with a CI job named `pages` that leaves its site in `public/` (runner = the arm64 k8s runner).
First user: `luna/docs` (see `../luna/README.md`).

## Group layout (2026-10-08)

```
geekstyle/               public   umbrella (owner)
├── platform/            private  what runs the homelab (runner-smoke-test moved here; planned: turing-pi-k3 mirror,
│                                 hermes-config, network/OPNsense backups)
├── oss/                 public   forks of upstream we patch (planned: hermes-agent fork instead of a .patch file)
├── projects/            public   things meant to be shared
└── members/             public parent, personal subgroups PRIVATE
    ├── cheshire/        private  owner (Cheshire's workspace)
    └── ladyofkrypton/   private  Anna + luna-bot (Luna's workspace)
luna/docs                public   Luna's Pages site — kept top-level for the short URL pages.geekstyle.net/luna/docs/
```
The old top-level `homelab` group (empty) was deleted; `geekstyle-deletion_scheduled-6` is already pending deletion.
Assistant identities: Mickey none; Cheshire = `cheshire-bot` (Maintainer members/cheshire, Developer platform + projects); Luna =
`luna-bot` (member of `members/ladyofkrypton` only, plus the luna/docs project token held by `luna-publish`).

`geekstyle` group defaults (2026-10-08): default-branch protection = only Maintainers push/merge, no force-push,
developers can't do the initial push; project creation = Maintainers+; subgroup creation = Owners; access requests
("join") off on the group, all subgroups and projects; sharing with groups outside the hierarchy blocked. Instance
defaults for new projects/groups were already **private** (public is always a deliberate choice).

## Upgrade 19.3.3 → 19.4.1 (2026-10-09)

No required stop (next: 19.5). Steps: `gitlab-backup create BACKUP=pre-19.4-20261009` (copied to node1
`~/gitlab-backups/` with `gitlab-secrets-20261009.json`; plain `kubectl exec cat` truncated the stream — copy in 1 MB base64
chunks with a per-chunk sha256 check), pre-pull `gitlab/gitlab-ce:19.4.1-ce.0` on node1, bump the pinned tag, apply
(Recreate: ~4 min to Ready). Checks: all services up incl. gitlab-pages, no pending migrations (6 batched background
migrations finishing — let them complete before the 19.5 stop), both Pages sites 200, MCP server 28 → 43 tools.
Runner chart 0.92.2 → **0.93.0 (runner 19.4.0)**: `helm upgrade gitlab-runner gitlab/gitlab-runner -n gitlab --version
0.93.0 --reuse-values -f gitlab-runner-values.yaml`; smoke pipeline on `geekstyle/platform/runner-smoke-test` passed.

19.4 notes that matter here: MCP tool governance (Free) — write tools default "Always Ask", but verified it does **not**
block external MCP clients (cheshire-bot created and then deleted a test issue via `save_work_item`). New MCP tools include
`add_commit` (native commits), `save_note` (replaces create_*_note), `save_work_item` (needs `type_name: "Issue"`).
Hermes' GitLab MCP connections parked during the downtime and revived on their own.
