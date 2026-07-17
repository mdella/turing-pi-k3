# k3s Cluster Notes
_Last updated: 2026-04-03_

## Cluster Overview
- **4 nodes**: k3-node1/2/3 (control-plane+etcd, 192.168.4.101-103), k3-node4 (worker, 192.168.4.104)
- **OS**: Ubuntu 24.04.4 LTS on ARM (Rockchip)
- **k3s version**: v1.35.3+k3s1 (upgraded 2026-04-02)
- **containerd**: 2.2.2-k3s1
- **VIP**: 192.168.4.100 (kube-vip)

## Installed Stack
| Component | Namespace | IP / Access |
|---|---|---|
| cert-manager | cert-manager | — |
| ingress-nginx | ingress-nginx | 192.168.4.201 |
| MetalLB v0.15.3 | metallb-system | Pool: 192.168.4.200–220 |
| Longhorn | longhorn-system | — |
| Prometheus + Grafana | monitoring | 192.168.4.202 |
| OpenBao (Vault fork) | openbao | — |
| Portainer | portainer | 192.168.4.200 |
| Ghost blog | ghost | 192.168.4.204 (temp) |
| openclaw agents gateway | openclaw | 192.168.4.203 |
| AI Services (Ollama/RKLLaMA NPU/LiteLLM/LibreTranslate/Open WebUI) | ai-services | via ingress (ai/chat/translate.geekstyle.net) |

## IP Allocations (MetalLB)
| IP | Service |
|---|---|
| 192.168.4.200 | Portainer |
| 192.168.4.201 | ingress-nginx |
| 192.168.4.202 | Grafana |
| 192.168.4.203 | openclaw |
| 192.168.4.204 | Ghost (temporary) |
| 192.168.4.205+ | Available |

## AI Services (in-cluster)

Self-hosted coding-LLM + translation stack, namespace `ai-services`. Manifests and full benchmarks in the repo under `ai-services/`. Exposed via ingress-nginx (not dedicated MetalLB IPs).

| Component | Node | Access | Notes |
|---|---|---|---|
| Ollama (CPU) | k3-node4 | in-cluster | `qwen2.5-coder:3b` Q4_K_M (~4 GB loaded) |
| RKLLaMA (NPU) | k3-node4 | in-cluster | privileged, 3 NPU cores; `deepseek-coder:1.3b-npu` + `qwen2.5-coder:3b-npu` |
| LiteLLM proxy | k3-node3 | `http://ai.geekstyle.net` | OpenAI-compatible, Bearer auth; routes CPU↔NPU |
| LibreTranslate | k3-node2 | `http://translate.geekstyle.net` | ⚠️ node2 down (failed NVMe) → currently offline |
| Open WebUI | float | `http://chat.geekstyle.net` | Browser chat UI, backed by LiteLLM |

**NPU is enabled** (RK3588 6 TOPS, 3 cores). Benchmark finding: NPU throughput is bandwidth-bound by model size — `deepseek-coder:1.3b-npu` (1.37 GB) = **9.0 tok/s, 53% faster than CPU** (recommended); the larger `qwen2.5-coder:3b-npu` (3.5 GB) saturates LPDDR5 and trails CPU at 4.3 tok/s.

## External Inference (off-cluster)

**Richard's Mac Studio** — external Ollama host, complements the in-cluster Ollama on k3-node4. Beefier box for large models.

| Detail | Value |
|---|---|
| Endpoint | `http://richards-mac-studio.cstone.to:11434` (reached over tunnel, ~50–90 ms RTT) |
| Access | SSH `mdella@richards-mac-studio.cstone.to`; API is plain HTTP (no TLS) |
| Binding | Requires `OLLAMA_HOST=0.0.0.0:11434` on the Mac; default localhost-only binding makes it remotely unreachable |
| Verified | 2026-07-03 — `/api/tags` lists, `qwen3.6:27b` generation OK (~54 tok/s warm; ~5.9 s cold load) |

Installed models (as of 2026-07-03):

| Model | Size | Params / notes |
|---|---|---|
| `gpt-oss:120b` | 65 GB | 116.8B, MXFP4, 131K ctx, tools + thinking (daily driver) |
| `qwen3-coder-next:q4_K_M` | 51 GB | 79.7B, 262K ctx, tools (coding-tuned) |
| `huihui_ai/qwen3-next-abliterated:80b-a3b-instruct` | 48 GB | 79.7B, 262K ctx |
| `huihui_ai/gemma-4-abliterated:48b` | 33 GB | 48.7B, tools + thinking |
| `qwen3.6:27b` | 17 GB | 27.8B, **vision**, 262K ctx, tools + thinking |

### FLUX.2 text-to-image on the Mac Studio (added 2026-07-04)

Runs **FLUX.2 [dev] Q8_0 GGUF** + Turbo LoRA via ComfyUI (headless, MPS), reachable from a laptop's Claude Code as an MCP tool. Full setup + `flux2_mcp.py` in repo under `mac-studio-flux2/`.

| Detail | Value |
|---|---|
| Engine | ComfyUI 0.22.0 (app-bundled server + venv) on the Mac; base path `/Users/jax/Documents/ComfyUI-v1` |
| Model | `flux2-dev-Q8_0.gguf` (34.5 GB, `city96/FLUX.2-dev-gguf`) via `ComfyUI-GGUF` node — **fp8 does NOT work on MPS**, GGUF→bf16 does |
| Endpoint | ComfyUI bound to netbird IP `100.101.193.15:8199` (not LAN/public) |
| Laptop route | laptop → `k3-node1:8199` (socat systemd forwarder) → netbird → Mac. k3-node1 is the only node on netbird (until Ziti connector) |
| Client | `flux2_mcp.py` stdio MCP server; `claude mcp add flux2 -- uv run ~/flux2_mcp.py` |
| Perf | ~2–3 min per 1024² image (8-step turbo). No auth on ComfyUI — trusted-LAN only. |

---

## Issues Fixed (2026-04-02)

### openclaw: 35-day CrashLoopBackOff
- **Root cause**: `multipathd` was intercepting Longhorn's iSCSI block devices (IET VIRTUAL-DISK), causing `Can't open blockdev` kernel errors and EIO on all filesystem writes. The ext4 journal was also dirty from constant crash cycling.
- **Fix**:
  1. Added blacklist to `/etc/multipath.conf` on all 4 nodes:
     ```
     blacklist {
         device {
             vendor "IET"
             product "VIRTUAL-DISK"
         }
     }
     ```
  2. `systemctl restart multipathd` on each node
  3. Ran `e2fsck -y /dev/sda` to replay dirty journal
  4. Removed stale `configMode` key from `/home/node/.openclaw/openclaw.json` (schema changed in newer version)
- **Watch for**: If any Longhorn volume shows EIO errors or `Can't open blockdev` in dmesg, check `fuser /dev/sda` from a privileged node pod — multipathd may have reclaimed the device.

### openclaw: MetalLB IP pending (37 days)
- **Root cause**: Service annotation requested dual-stack IPs (`192.168.4.203,fd00::203`) but service was `SingleStack` IPv4.
- **Fix**: Patched annotation to `metallb.universe.tf/loadBalancerIPs: 192.168.4.203`

### MariaDB (Ghost): Pending for 9 days
- **Root cause**: StatefulSet had a bug — explicit `volumes` entry pointing to static PVC `mariadb-data` (didn't exist), while `volumeClaimTemplate` correctly created `mariadb-data-mariadb-0`. VolumeMount also used wrong name `data`.
- **Fix**: Patched StatefulSet to remove explicit `volumes` entry and rename volumeMount from `data` → `mariadb-data`.

### Orphaned Longhorn instance managers
- **Root cause**: After Longhorn upgrade to v1.11.1 (12 days prior), two v1.11.0 instance managers were not cleaned up automatically.
  - `instance-manager-c7677f051429ad13feef7b6b...` on k3-node1 — consuming **9.1 GiB RAM** (caused 86% memory)
  - `instance-manager-9b57b00ff6c03ebbd4089a49...` on k3-node3 — consuming 223 MiB
- **Fix**: `kubectl delete instancemanager <name> -n longhorn-system` — k3-node1 memory dropped from 86% → 28%.

### MetalLB: upgraded from `main` to v0.15.3 (2026-04-03)
- Was running the floating `main` development branch tag — not a stable release.
- Applied `metallb-native.yaml` for v0.15.3; all 5 LoadBalancer IPs held without interruption.
- Migrated deprecated `metallb.universe.tf/*` annotations to `metallb.io/*` on openclaw and ghost services.

### Stale test pods
- Deleted: `bao-test`, `bao-inject-test`, `bao-inject-test2` from `default` namespace (leftover OpenBao sidecar injection tests).

### k3s version skew
- k3-node4 was on v1.34.3+k3s3, nodes 1-3 on v1.34.5+k3s1.
- **Fix**: Deployed `system-upgrade-controller` and upgrade Plans — all nodes now on v1.35.3+k3s1.

---

## Ghost Deployment Notes
- **Temp URL**: `http://192.168.4.204`
- **Future URL**: `https://blog.geekstyle.net` (DNS + NAT not yet configured)
- **Database**: MariaDB 10.11.16 LTS (in-cluster, `ghost` namespace)
- **Content PVC**: `ghost-content`, 5Gi Longhorn
- **MariaDB PVC**: `mariadb-data-mariadb-0`, 1Gi Longhorn

### Enabling TLS for blog.geekstyle.net
1. Set up NAT port-forward: public-IP:80/443 → 192.168.4.201
2. Point DNS: `A blog.geekstyle.net → <public-IP>`
3. Edit ingress to uncomment cert-manager annotation and `tls:` block:
   ```bash
   kubectl edit ingress ghost -n ghost
   # uncomment: cert-manager.io/cluster-issuer: letsencrypt-staging
   # uncomment: tls: section
   ```
4. Test with staging, then switch annotation to `letsencrypt-prod`
5. Update Ghost URL:
   ```bash
   kubectl set env deployment/ghost -n ghost url=https://blog.geekstyle.net
   ```

### cert-manager ClusterIssuers
Both are created and registered with Let's Encrypt:
- `letsencrypt-staging` — use first to test
- `letsencrypt-prod` — use for production
- Email: `admin@geekstyle.net` (update if needed)

---

## Open Issues / TODO

### High Priority
- **OpenBao no auto-unseal** — Uses Shamir (5 shares, threshold 3). If cluster reboots, OpenBao will come up sealed and require manual key entry. Configure auto-unseal via KMS (AWS KMS, Azure Key Vault, GCP KMS, or transit seal against another instance) before relying on it for production workloads.

### Medium Priority
- ~~**MariaDB 10.4 EOL**~~ — Upgraded to MariaDB 10.11.16 LTS 2026-04-03. Dump-and-restore used (10.4→10.11 is too large a jump for safe in-place upgrade). Backup kept at `/home/ubuntu/ghost-db-backup-20260403.sql`.
- ~~**Deprecated MetalLB annotations**~~ — Fixed 2026-04-03. Migrated `metallb.universe.tf/*` → `metallb.io/*` on openclaw and ghost services.

### Low Priority
- **Ghost image tag** — Using `ghost:5-alpine` (floating tag). Pin to a specific minor version (e.g. `ghost:5.109-alpine`) to prevent unexpected breaking updates.
- **Longhorn recurring snapshots** — Only `openclaw` has a daily snapshot job. Consider adding recurring snapshot/backup jobs for `ghost-content` and `mariadb-data-mariadb-0`.

---

## Useful Commands

```bash
# Node status + versions
kubectl get nodes -o wide

# All non-running pods
kubectl get pods -A --field-selector=status.phase!=Running

# Node memory/CPU usage
kubectl top nodes

# Longhorn volume health
kubectl get volumes -n longhorn-system

# Check multipathd holding a Longhorn device (run from privileged node pod)
fuser /dev/sda

# Future k3s upgrades — just update the version in both Plans:
kubectl edit plan k3s-server-upgrade -n system-upgrade
kubectl edit plan k3s-agent-upgrade -n system-upgrade

# OpenBao status
kubectl exec -n openbao openbao-0 -- bao status

# Ghost logs
kubectl logs -n ghost -l app=ghost --tail=50
```
