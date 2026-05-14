# GitLab

## Overview

GitLab CE (Community Edition) deployed as a single-pod omnibus installation on K3s.
Includes a Kubernetes-executor GitLab Runner for CI/CD pipelines. The runner is used
to power scheduled pull-mirror jobs — a workaround for pull mirroring being an EE-only
feature.

## Access

| Detail | Value |
|---|---|
| URL | `http://gitlab.geekstyle.net` |
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
    - git push --mirror "https://oauth2:${GITLAB_TOKEN}@gitlab.geekstyle.net/${CI_PROJECT_PATH}.git"
  only:
    - schedules
```

4. Create a schedule under CI/CD → Schedules (e.g. `0 * * * *` for hourly)

## TLS (pending)

To enable `https://gitlab.geekstyle.net`: NAT port-forward public-IP:80/443 →
192.168.4.201, add DNS A record, uncomment the cert-manager annotation and `tls:` block
in `gitlab.yaml`, test with `letsencrypt-staging`, then switch to `letsencrypt-prod`.
Update `external_url` in `GITLAB_OMNIBUS_CONFIG` to the `https://` URL at the same time.

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
