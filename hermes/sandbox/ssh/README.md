# SSH tool sandbox as a k3s pod (test, 2026-10-11)

Step 1 of moving Hermes into k3s: Docker-in-a-pod is out (the docker/containerd socket is root on the node), so Cheshire's
and Luna's sandboxes would become **pods reached over SSH** with Hermes' built-in `ssh` terminal backend. This is the
proof that it works and stays as isolated as the Docker sandboxes.

| File | What |
|---|---|
| `Dockerfile` | same tools as `../cheshire` / `../luna` (python 3.12, git, gpg, pandoc, poppler, python-docx/pptx, openpyxl, matplotlib…) + **unprivileged sshd** (uid 1000, :2222) |
| `sshd_config` | keys only, `AllowUsers sandbox`, no TCP/agent/stream/X11 forwarding, no tunnels, no user env/rc; `StrictModes no` (k8s emptyDirs are world-writable) |
| `entrypoint.sh` | copies the mounted host key + `authorized_keys` into `/run/sshd` (0600), runs `sshd -D -e` |
| `sandbox-test.yaml` | Deployment `sbx-test` + Service + NetworkPolicy `hermes-sandboxes` in ns `hermes` |
| `../../patches/ssh-no-sync-back.patch` | local Hermes patch, see "Finding" below |

Pod hardening: runAsNonRoot uid 1000, **all capabilities dropped (CapEff/CapBnd = 0, stricter than Docker's 3)**,
no-new-privileges, read-only root filesystem, seccomp RuntimeDefault, no service-account token, no service links.
Writable: `/workspace`, `/home/sandbox`, `/tmp`, `/run` (emptyDirs in the test; production: a Longhorn PVC per sandbox for
`/workspace`). NetworkPolicy: **no egress at all** (not even DNS — same as `--network none`); ingress only TCP 2222
from the gateway (today node1's host: `192.168.4.101`/`10.42.0.1`; later a podSelector for the gateway pod).
Host key + `authorized_keys` live in Secret `sbx-test-ssh` (created out of band; the gateway's private key never enters
the cluster in this test).

## Results (2026-10-11)

Isolation, checked over SSH: uid 1000, no DNS, no internet, no Kubernetes API, no `/var/run/secrets`, rootfs read-only,
capabilities 0, NoNewPrivs 1; `ssh -L` → "administratively prohibited"; a pod on node3 can't reach port 22/2222.

Hermes tools, driven through `model_tools.handle_function_call` with `TERMINAL_ENV=ssh` (no LLM, scratch HERMES_HOME):

| Tool | Result |
|---|---|
| `terminal` | ✅ 0.1–0.8 s per call; `cd` and exported env persist between calls |
| `write_file` / `read_file` / `patch` / `search_files` | ✅ (all run remotely) |
| `execute_code` | ✅ remote kernel; python-docx wrote a .docx; RPC back to Hermes tools (`hermes_tools.terminal`) works |
| `/workspace` across env teardown | ✅ kept (pod volume) |

**Finding — sync-back.** The SSH backend uploads the profile's skills/caches into the sandbox's `~/.hermes` and, on
teardown, **copies changes back onto the host (last-write-wins)**. Verified: a sandbox overwrote
`skills/canary/SKILL.md` and the host copy became `TAMPERED` — a prompt-injected sandbox could rewrite the assistant's
skills. Docker mounts those read-only, so this would be a regression. Fix: `patches/ssh-no-sync-back.patch` (sync-back
only if `TERMINAL_SSH_SYNC_BACK=1`); re-tested → host copy stays `ORIGINAL`. Applied to the live checkout (inert: the
gateway uses docker/local backends) and saved in `~/.hermes/local-patches/`; re-apply after `hermes update`.

Not tested yet: a full gateway profile with `terminal.backend: ssh` (the per-profile `terminal:` block already works for
docker, so expected the same), and approvals behaviour over SSH (same code path as docker).

## Profile config (when switching a profile over)

```yaml
terminal:
  backend: "ssh"
  ssh_host: "sbx-<profile>.hermes.svc.cluster.local"
  ssh_user: "sandbox"
  ssh_port: 22
  ssh_key: "<path to the profile's sandbox client key>"   # one key per profile, authorized only on its own sandbox
  cwd: "/workspace"
```
Pin the host key in the gateway's `known_hosts` (Hermes uses `StrictHostKeyChecking=accept-new`).

## Remove the test

`kubectl -n hermes delete -f sandbox-test.yaml && kubectl -n hermes delete secret sbx-test-ssh`
