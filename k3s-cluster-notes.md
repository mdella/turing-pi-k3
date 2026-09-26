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
| Honcho agent memory (v3.0.12) + Hombre UI | honcho | API netbird `:8800` / LAN `:30800` (JWT); UI netbird `:8801` / LAN `:30801` (login) |

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
| LibreTranslate | k3-node2 | `http://translate.geekstyle.net` | ✅ back online 2026-09-26 (node2 rebuilt) |
| Open WebUI | float | `http://chat.geekstyle.net` | Browser chat UI, backed by LiteLLM |

**NPU is enabled** (RK3588 6 TOPS, 3 cores). Benchmark finding: NPU throughput is bandwidth-bound by model size — `deepseek-coder:1.3b-npu` (1.37 GB) = **9.0 tok/s, 53% faster than CPU** (recommended); the larger `qwen2.5-coder:3b-npu` (3.5 GB) saturates LPDDR5 and trails CPU at 4.3 tok/s.

## Honcho — agent memory (added 2026-09-24)

Self-hosted [Honcho](https://github.com/plastic-labs/honcho) v3.0.12 in namespace `honcho`; full details in repo `honcho/README.md`.
- **Access:** netbird peers `http://100.101.160.239:8800` (or node3 `100.101.7.201`, node4 `100.101.238.181`); LAN `http://192.168.4.101:30800`. API, JWT required.
- **Web UI (Hombre):** `http://100.101.160.239:8801` over netbird, `http://192.168.4.101:30801` on the LAN; login `admin`, password in secret `hombre-secrets`. Built locally, pinned to node1.
- **Models:** deriver + summary = Mac Studio `qwen3-coder-next` (llama-server :8080); dialectic + dream = `claude-sonnet-5` (Anthropic key in secret `honcho-secrets`, needs the local prefill patch); embeddings = in-cluster Ollama `nomic-embed-text` (768 dims).
- **Backup:** nightly 01:30 UTC `pg_dump` → Longhorn PVC `honcho-backups`, 14 days, restore-tested (SeaweedFS S3 was down).
- **Gotchas:** tokens with `--expires` are rejected (string `exp` vs PyJWT) → issue non-expiring, workspace-scoped tokens; rotate by changing `AUTH_JWT_SECRET`. Migrations create `vector(1536)` → the API init container runs `configure_embeddings.py --yes`. Conclusions appear ~30 min after a short chat (deriver batching).
- **netbird + NodePorts:** netbird's firewall drops traffic that kube-proxy forwards to pods, so NodePorts time out over netbird while host ports work. Honcho uses a host-network `socat` DaemonSet on :8800. Same would apply to any future service exposed to netbird.
- All three running nodes are netbird peers: node1 100.101.160.239, node3 100.101.7.201, node4 100.101.238.181.

## Hermes Agent — "Sorcerer Mickey" (added 2026-09-24)

Personal AI assistant on **k3-node1** (host install, not k8s); full notes in repo `hermes/README.md`.
- Hermes v0.21.4 as `ubuntu`, model `claude-sonnet-5`, memory = Honcho workspace `hermes` (via `127.0.0.1:8800` relay).
- CLI (`hermes chat` over SSH): full tools. **Signal** (dedicated number via `signal-cli` 0.14.8 on `127.0.0.1:8093`): DM with pairing + group "Disney Gang 2025", **chat-only tools** (no terminal/files — node1 has kubectl admin + passwordless sudo).
- Group wake-up: @-mention or addressed by name (regex `signal.mention_patterns`, needs local patch `hermes/patches/`, re-apply after `hermes update`).
- Services: `signal-cli.service`, `hermes-gateway.service` (system units, boot-enabled). ~500 MB RSS total on node1.
- Gotchas: Honcho JWT must be `apiKey` in `honcho.json` (Hermes treats netbird/LAN URLs as local and ignores env keys); signal-cli needs Java 25 + ARM64 libsignal from exquo/signal-libs-build; web search needs `ddgs`.

## Public IPv6 access — ping + SSH (added 2026-09-25)

Nodes get SLAAC global addresses from the OPNsense LAN (Starlink-delegated /64, **prefix can change**).
- **OPNsense** (192.168.1.1, managed via API key in `~/.opnsense-api` on node1, 0600):
  - alias `k3s_nodes_v6` — type *Dynamic IPv6 Host*, interface LAN, content = the 4 nodes' SLAAC host IDs (`::xxxx:xxff:fexx:xxxx`, EUI-64 from MAC, stable) → follows prefix changes automatically.
  - alias `k3s_cluster` → `k3s_nodes_v6` (old static `…22b9:7c0c::f:10x` entries removed; that prefix is no longer on the LAN).
  - rules (WAN/Starlink, in, IPv6, source any): ICMPv6 type 128 (echo request) → `k3s_cluster`; TCP 22 → `k3s_cluster`.
  - config backup before the change: `~/opnsense-backups/config-before-ipv6-20260925.xml` on node1 (not in repo — contains secrets).
- **Nodes: SSH keys-only** — `/etc/ssh/sshd_config.d/00-hardening.conf` (PasswordAuthentication/KbdInteractive no, PermitRootLogin no, MaxAuthTries 4). `00-` so it beats `50-cloud-init.conf` (sshd: first value wins). node2 got it at rebuild (cloud-init).
- **Fixed 2026-09-26 — dead IPv6 gateway on nodes:** `/etc/netplan/01-network.yaml` had `::/0 via fd00::1` (and `fd00::1` as DNS). Nothing answers at fd00::1, so the default route was ECMP over {fd00::1 (FAILED), router fe80 (RA)} hashed per destination → replies to ~half of outside hosts silently dropped (also the earlier ghcr.io IPv6 pull failures on node1). Removed on nodes 1/3/4 (backup `/root/01-network.yaml.bak-20260926`); node2 rebuilt without it. IPv6 default now comes from RA only. Don't re-add a static `::/0` (the guide §3.2 template still has it — skip those lines).
- Test from outside over IPv6 (e.g. the Ziti controller): `ping -6 <node>`; `ssh ubuntu@<node-v6>`.

## k3-node2 rebuild — failed NVMe replaced (2026-09-26)

Rebuilt unattended from node1 over the BMC; runbook for any future node rebuild:
- **BMC** Turing Pi 2.5.1, fw 2.3.4 at `192.168.1.223` (`turingpi.local`). (change the factory login if not done).
  - node1 can't talk to the BMC through OPNsense (asymmetric path → pf drops after handshake). Workaround: temporary on-link address on node1:
    `sudo ip addr add 192.168.1.250/32 dev eth0; sudo ip route add 192.168.1.223/32 dev eth0 src 192.168.1.250` (remove afterwards).
  - `tpi` 1.0.7 on node1: `TPI_HOSTNAME=192.168.1.223 TPI_USERNAME=root TPI_PASSWORD=… tpi …` (without creds it hangs on an interactive prompt).
  - **Gotcha:** after `tpi flash` the node's USB stays in **Flash** mode → it sits in maskrom and never boots (node2 had been stuck like this). Fix: `tpi usb device -n 2`, then power off/on.
- **Image:** Joshua-Riek ubuntu-rockchip **v2.4.0** `ubuntu-24.04-preinstalled-server-arm64-turing-rk1.img.xz` (same u-boot/kernel as the other nodes). Pre-seeded the image's `CIDATA` (cloud-init NoCloud) partition before flashing: hostname, static netplan (MAC match `06:8f:86:bd:ec:28` → eth0, 192.168.4.102/22 + fd00::102, **no** `::/0 via fd00::1`), user keys only (no password SSH, NOPASSWD sudo, random console password kept on node1 `~/node2-rebuild/console-password`), sshd hardening, k8s modules/sysctl, multipath blacklist, registries.yaml, /etc/hosts. Files kept in `~/node2-rebuild/` on node1.
  - RK1 MAC = SLAAC EUI-64 host ID with the U/L bit flipped (node2 `::48f:86ff:febd:ec28` → `06:8f:86:bd:ec:28`).
- **Flash:** `tpi flash -n 2 -i <img> --sha256 …` — 4.5 GB raw took 13 min incl. CRC verify.
- **First boot:** unattended-upgrades runs a full upgrade (~20 min) holding the dpkg lock; then packages (avahi, libnss-mdns, open-iscsi, nfs-common, multipath-tools, jq, curl), reboot, `echo y | sudo ubuntu-rockchip-install /dev/nvme0n1` (prompts y/N!), reboot → root on `nvme0n1p2`, already full size (938G).
- **Cluster side (before join):** `k3s etcd-snapshot save`; `etcdctl member remove <old node2 id>` (etcdctl v3.7.2 now in `/usr/local/bin` on node1); `kubectl delete node k3-node2`; delete stale Longhorn replicas on node2 → Longhorn drops its node CR.
- **Join:** node3's `/etc/rancher/k3s/config.yaml` with `node-name: k3-node2`, `INSTALL_K3S_VERSION=v1.35.3+k3s1`. system-upgrade-controller then runs its same-version plan once (cordon → uncordon, first pod may Error — harmless). Labels re-added: `node.longhorn.io/create-default-disk=true`, `mariadb-galera=true`.
- **netbird:** re-enrolled 2026-09-26 (setup key from self-hosted https://netbird.cstone.com), `k3-node2.cstone.to` = 100.101.47.92, v0.79.0.
- **Not restored on node2 (needs input):** Ziti edge router `k3-node2` (re-enroll against ctrl.cstone.com; old static `22b9:7c0c::f:102` prefix is gone), stale Released local-path PVs `mariadb-storage-1` / `pvc-102c8cb9…` (old Galera-1, now on node4).

## External Inference (off-cluster)

**Richard's Mac Studio** — external Ollama host, complements the in-cluster Ollama on k3-node4. Beefier box for large models.

| Detail | Value |
|---|---|
| Endpoint | `http://richards-mac-studio.cstone.to:11434` (reached over tunnel, ~50–90 ms RTT) |
| Access | SSH `mdella@richards-mac-studio.cstone.to` (use `-o BatchMode=yes` — else it falls to a password prompt and trips MaxAuthTries); API is plain HTTP (no TLS) |
| Version | Ollama **0.34.3** (Homebrew formula, `/opt/homebrew/bin/ollama`); upgrade as `sudo su - jax` then `brew upgrade ollama` + `sudo launchctl kickstart -k system/com.ollama.serve` |
| Service | launchd **system daemon** `com.ollama.serve` — persistent across reboots; env baked into its plist: `OLLAMA_HOST=0.0.0.0:11434`, `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_CONTEXT_LENGTH=32768`, `OLLAMA_NUM_PARALLEL=4`, `OLLAMA_MAX_LOADED_MODELS=1`, `OLLAMA_KV_CACHE_TYPE=q8_0`, `OLLAMA_MODELS=/Users/Shared/ollama/models` (multi-user tuning 2026-09-22; plist `/Library/LaunchDaemons/com.ollama.serve.plist`, backup `.bak-20260922`; env changes need `launchctl bootout` + `bootstrap`, not just kickstart). **Caveat:** Ollama 0.34.1 forces `qwen3next` models (both `qwen3-coder-next` tags, `qwen3-next-abliterated`) to 1 slot — "architecture does not currently support parallel requests" — so those queue; other models get 4 slots |
| Verified | 2026-09-17 — v0.34.1, `/api/tags` lists 9 models, bound `*:11434`; new pulls load-tested + benchmarked, redundant tags pruned (~55 GB reclaimed) |

Installed models (9, as of 2026-09-17):

| Model | Size | Params / quant | Notes |
|---|---|---|---|
| `qwen3-coder-next:q8_0` | 85 GB | 79.7B Q8_0 (qwen3next) | coding, high-quality quant (54 tok/s) |
| `openbiollm-70b:latest` | 75 GB | 70.6B Q8_0 (llama) | biomedical |
| `gpt-oss:120b` | 65 GB | 116.8B MXFP4 (gptoss) | 131K ctx, tools + thinking (daily driver) |
| `qwen3-coder-next:q4_K_M` | 52 GB | 79.7B Q4_K_M (qwen3next) | coding, faster/lighter quant (60 tok/s) |
| `huihui_ai/qwen3-next-abliterated:80b-a3b-instruct` | 48 GB | 79.7B Q4_K_M | abliterated |
| `huihui_ai/gemma-4-abliterated:48b` | 33 GB | 48.7B Q4_K_M | tools + thinking |
| `huihui_ai/qwen3-vl-abliterated:30b` | 20 GB | 31.1B Q4_K_M (qwen3vl) | **vision** + thinking (88 tok/s) |
| `qwen3.8:27b` | 18 GB | nvfp4 | general |
| `medgemma:27b` | 17 GB | 27.4B Q4_K_M (gemma3) | **official current MedGemma, multimodal (Text+Image)**, 30 tok/s |

Pruned 2026-09-17 (~55 GB): `medgemma-27b-it:latest` (old import), `qwen3.6:27b` (older than 3.8), `qwen3.8:27b-mlx` (dup digest), `qwen3-vl:8b` + `:8b-instruct` (superseded by 30b).

**Benchmark, new pulls vs pre-existing** (M3 Ultra 96 GB, cold load + 200-tok gen, `/api/generate`):

| Pair | Load | Gen tok/s | Takeaway |
|---|---|---|---|
| qwen3-vl **30b** (new) | 12.2s | **87.9** | ~same gen speed as 8b for ~4× params — clear win |
| qwen3-vl 8b (pruned) | 4.8s | 84.8 | |
| medgemma **:27b** Q4 (new) | 11.4s | **30.0** | +38% faster than old Q8 + multimodal + current version |
| medgemma-27b-it Q8 (pruned) | 8.1s | 21.7 | |
| coder **q8_0** (new) | 27.1s | 53.6 | higher-precision, ~11% slower gen than q4 |
| coder q4_K_M (kept) | 33.6s | 60.5 | faster daily driver; keep for speed |

(Prompt-eval t/s omitted — prompts were only ~27 tokens, too small to be a stable measure; gen tok/s is the reliable metric.)

**Quality eval (2026-09-17, temp 0 greedy, single run).** Coder = pass@1 with hidden test cases (code executed); Medical = accuracy on multiple-choice, easy tier (textbook facts) + hard tier (clinical vignettes):

| Contest | Easy tier | Hard tier | Verdict |
|---|---|---|---|
| coder `q4_K_M` | 8/8 | 8/8 | **q4 is the default** — no q8 advantage found across 16 problems, and it's faster + 33 GB smaller |
| coder `q8_0` | 8/8 | 7/8 (real bug in an expr-parser) | keep only if you want the option; evidence doesn't justify it as default |
| `medgemma:27b` | 15/15 | 15/15 | **medgemma is the medical daily driver** — perfect 30/30 at 4× smaller and ~2× faster than the 70B |
| `openbiollm-70b` | 15/15 | 14/15 (missed inferior-MI artery) | keep as a second opinion |

Caveat: single greedy run on modest sets — read q4>q8 and medgemma>openbiollm as "no gap / slight edge," not proof. Harness in the repo history if a re-run is wanted.

**Concurrency test (2026-09-22, NUM_PARALLEL=4, 200-tok gen each, warm):**

| Model | n=1 | n=2 | n=4 | n=8 | Behavior |
|---|---|---|---|---|---|
| `qwen3-coder-next:q4_K_M` aggregate t/s | 63 | 64 | 60 | 60 | **serialized** (qwen3next forced to 1 slot): worst latency 3→6→13→27 s |
| `gpt-oss:120b` aggregate t/s | 67 | 95 | 122 | 122 | **batched**: 4 slots, 1.8× total throughput; per-user drops 69→31 t/s; n=8 = two waves of 4 |
| coder on Ollama **0.34.3** (upgraded 2026-09-22) | 64 | 63 | 63 | 63 | still serialized — same `qwen3next` 1-slot warning |
| coder on **llama.cpp `llama-server` b10964** `--parallel 4 -c 131072 -fa on -ctk/-ctv q8_0` | 61 | 91 | 121 | 125 | **batched**: 4×32K slots, worst latency at n=4 6.6 s (vs 12.7 s Ollama) |

llama-server notes: Ollama's own GGUF blob for qwen3next does **not** load in upstream llama.cpp (`tensor 'blk.0.ssm_dt.bias' not found` — Ollama re-lays-out the tensors), so it uses the official `Qwen/Qwen3-Coder-Next-GGUF` Q4_K_M split (4 files, 48.4 GB) at `/Users/Shared/llama-models/qwen3-coder-next-q4/`. llama.cpp via `brew install llama.cpp` (jax). Output verified coherent. ~47 GB RSS; **not running persistently** — it sits outside Ollama's `MAX_LOADED_MODELS` accounting, so running both risks OOM on the 96 GB box.


### Multi-user coder: llama-server on the Mac Studio (added 2026-09-22)

The coder runs as a second engine next to Ollama because Ollama serializes `qwen3next`.

| Detail | Value |
|---|---|
| Endpoint | `http://richards-mac-studio.cstone.to:8080/v1` (OpenAI-compatible, model id `qwen3-coder-next`; no auth, same as Ollama) |
| Service | launchd system daemon `com.cstone.llama-server` (runs as jax), plist in repo `mac-studio-flux2/com.cstone.llama-server.plist`, log `/Users/Shared/llama-models/llama-server.log` |
| Engine / model | llama.cpp b10964 (`brew install llama.cpp`); official `Qwen/Qwen3-Coder-Next-GGUF` Q4_K_M split in `/Users/Shared/llama-models/qwen3-coder-next-q4/` |
| Settings | `--parallel 4 -c 262144` (4×64K, raised from 4×32K on 2026-09-23 — Qwen Code's base prompt is ~17K; cost +1.6 GB), `-fa on -ctk/-ctv q8_0`, `--sleep-idle-seconds 300`, `--metrics` |
| Memory | 48.8 GB loaded (47.2 at 32K slots); **0.2 GB asleep** after 5 idle min; wake 3 s warm / ~25–50 s cold |

**Memory sharing with Ollama.** Ollama cannot see llama-server's memory: loading `gpt-oss:120b` while the coder was awake pushed swap 0.9→11.6 GB in 30 s (test aborted). Sharing works by time: both engines unload after 5 idle minutes. While the coder is awake, only Ollama models up to ~35 GB are safe alongside it (`qwen3-vl:30b`, `qwen3.8:27b`, `medgemma:27b`, `gemma-4:48b` borderline at 33 GB). **Not safe** alongside: `gpt-oss:120b`, `openbiollm-70b`, `qwen3-next-abliterated`, and Ollama's own coder tags.

**Agent CLI on k3-node1 (in progress, 2026-09-23):** planning notes in repo `node1-coder-cli/` (endpoint facts, CLI choice, install, test plan, open questions). Verified from node1: `:8080` reachable over netbird, OpenAI tool calling works.

For large jobs use `/usr/local/bin/ai-mem` on the Mac (source in repo, `mac-studio-flux2/ai-mem`):
- `ai-mem status` shows what holds memory
- `ai-mem big` stops llama-server so Ollama can load a large model
- `ai-mem coder` unloads Ollama models and restarts llama-server

Tested: `big` then gpt-oss loaded cleanly (53 s cold), `coder` then back to 47 GB with no swap growth. After `big`, the coder stays stopped until `ai-mem coder` or a reboot. Non-interactive SSH has no `/usr/local/bin` in PATH, so use the full path there.

### FLUX.2 text-to-image on the Mac Studio (added 2026-07-04)

Runs **FLUX.2 [dev] Q8_0 GGUF** + Turbo LoRA via ComfyUI (headless, MPS), reachable from a laptop's Claude Code as an MCP tool. Full setup + `flux2_mcp.py` in repo under `mac-studio-flux2/`.

| Detail | Value |
|---|---|
| Engine | ComfyUI 0.22.0 (app-bundled server + venv) on the Mac; base path `/Users/jax/Documents/ComfyUI-v1` |
| Model | `flux2-dev-Q8_0.gguf` (34.5 GB, `city96/FLUX.2-dev-gguf`) via `ComfyUI-GGUF` node — **fp8 does NOT work on MPS**, GGUF→bf16 does |
| Endpoint | ComfyUI bound to netbird IP `100.101.193.15:8199` (not LAN/public) |
| Laptop route | laptop → `k3-node1:8199` (socat systemd forwarder) → netbird → Mac. node1, node3 and node4 are all netbird peers (verified 2026-09-24); the forwarder lives on node1 |
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
