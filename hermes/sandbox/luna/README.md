# Luna's tool sandbox (2026-10-11)

> **Superseded 2026-10-11 (k3s cutover):** Luna's tools now run over SSH in pod `sbx-luna` (ns `hermes`, node3,
> image `hermes-image/sandbox`, [`../../k8s/sandboxes.yaml`](../../k8s/sandboxes.yaml), design in [`../ssh/`](../ssh/)); profile
> `terminal.backend: ssh`, `ssh_host: sbx-luna.hermes.svc.cluster.local`. Her `/workspace` and GnuPG dir were copied
> into the pod's PVC. The Docker setup below on node1 is kept for history / rollback only.

Same design as Cheshire's (`../cheshire/README.md`): Luna (profile `luna`) has a shell, file tools and `execute_code`,
all running in **her own Docker container on k3-node1**, never on the host. The gateway still runs on the host; only
tool execution moves into the container. Image: this Dockerfile (Cheshire's, with user `luna`), built locally.

| Setting (profile `config.yaml` → `terminal:`) | Value |
|---|---|
| `backend` | `docker` |
| `docker_image` | `luna-sandbox:20261011` |
| `docker_network` | `false` (`--network none`: no internet, LAN or Hermes API) |
| `docker_run_as_host_user` | `true` (uid 1000 `luna`, not root) |
| `docker_volumes` | `<profile>/sandbox/workspace:/workspace`, `<profile>/sandbox/gnupg:/home/luna/.gnupg` (only persistent, writable paths) |
| `container_persistent` | `false` (/root, /home, /tmp are tmpfs) |
| `container_cpu` / `container_memory` / `container_disk` | 2 / 2048 MB / 10240 MB, plus Hermes defaults (`--cap-drop ALL` + CHOWN/DAC_OVERRIDE/FOWNER, `no-new-privileges`, pids 2048) |

Toolsets: `terminal`, `file`, `code_execution` removed from `agent.disabled_toolsets` and added to
`platform_toolsets.api_server` only (cron's list doesn't include them). `approvals: {mode: smart, unattended_mode:
approve, cron_mode: deny}` because the web chat has no /approve button; the container is the boundary.

No credentials go in: `.env`, config, other profiles, the docker socket and the host home are not visible. Profile
caches/attachments/skills are mounted read-only (uploaded files). Verified 2026-10-11: uid 1000, `--network none`
(DNS fails), no `/home/ubuntu`, no docker socket; a Python task wrote into `/workspace` from the web chat.

**Shared workspace:** Luna is used by two people, and both share the one `/workspace` (Hermes has one container per
profile, not per user). SOUL.md tells her to keep each person's files in their own folder and never open or mention the
other person's. That is behavioural, not enforced — for hard per-person isolation, use separate profiles (as Cheshire)
or Coder workspaces. No GPG key was generated for Luna (the directory exists if one is wanted).

## Rebuild / upgrade

```bash
cd turing-pi-k3/hermes/sandbox/luna && docker build -t luna-sandbox:<YYYYMMDD> .
# set terminal.docker_image in ~/.hermes/profiles/luna/config.yaml, check the delivery ledger, restart hermes-gateway,
# then `docker rm -f` any luna-sandbox container left over from before the restart
```
