# Cheshire's tool sandbox (2026-10-09)

Cheshire (profile `cheshire`) has a shell, file tools and `execute_code` — all running in **his own Docker container on
k3-node1**, never on the host. Mickey and Luna are unchanged (no terminal). The gateway process itself still runs on the
host; only tool execution moves into the container.

| Setting (profile `config.yaml` → `terminal:`) | Value | Why |
|---|---|---|
| `backend` | `docker` | commands, file ops and Python run in a container |
| `docker_image` | `cheshire-sandbox:20261009` (this Dockerfile, built locally) | python:3.12-slim (digest-pinned) + git, gnupg, pandoc, poppler-utils, jq, pypdf, reportlab, pdfplumber, pymupdf, python-docx, python-pptx, openpyxl, matplotlib |
| `docker_network` | `false` | `--network none`: no internet, no LAN, no Hermes API (verified) |
| `docker_run_as_host_user` | `true` | runs as uid 1000 (`cheshire`), not root |
| `docker_volumes` | `<profile>/sandbox/workspace:/workspace`, `<profile>/sandbox/gnupg:/home/cheshire/.gnupg` | the only writable, persistent paths |
| `container_persistent` | `false` | /root, /home, /tmp are tmpfs; everything outside the two volumes resets |
| `container_cpu` / `container_memory` | 2 / 2048 MB | plus Hermes defaults: `--cap-drop ALL` (+CHOWN, DAC_OVERRIDE, FOWNER), `no-new-privileges`, pids 2048 |

Hermes also mounts the profile's own caches/attachments/skills **read-only** (so he can work on files you upload).
No credentials are passed in: `.env`, config and other profiles are not visible. Verified: no network/LAN, no docker
socket, rootfs and read-only mounts not writable, `mount`/`su` fail.

Toolsets: `terminal`, `file`, `code_execution` removed from `agent.disabled_toolsets` and added to
`platform_toolsets.api_server` (web chat only; cron jobs still don't get them).

## GPG

Key `Cheshire (assistant bot) <cheshire-bot@noreply.scm.geekstyle.net>`, ed25519 sign + cv25519 encrypt subkey,
expires 2028-10-08, fingerprint `6CADE7340345F56C8BC77E151703DFD6EF28BECB`. No passphrase (unattended use); the secret
key lives only in `<profile>/sandbox/gnupg` (0700). Public key added to cheshire-bot's GitLab account (so signed commits
show Verified). Uses: **signing** documents/releases and **encrypting** to public keys in his keyring — not decrypting
for others. SOUL.md tells him never to export the secret key.

## Not done / open

- **Signed git commits** need network + a push credential inside the sandbox. Today he commits via the host-side `repos`
  / GitLab tools (API commits, unsigned). Option: Hermes' iron-proxy egress (`hermes egress`) — network only to scm,
  token swapped in host-side so the sandbox never sees it.
- **Command approvals:** the web chat is an "unattended" platform (no /approve button), and Hermes' default
  `approvals.unattended_mode: deny` refuses commands its guard flags (e.g. `python3 -c`). Ordinary commands work.
  Switching Cheshire to `approve` (container is the boundary) is the owner's call.

## Rebuild / upgrade

```bash
cd turing-pi-k3/hermes/sandbox/cheshire && docker build -t cheshire-sandbox:<YYYYMMDD> .
# set terminal.docker_image in ~/.hermes/profiles/cheshire/config.yaml, check the delivery ledger, restart hermes-gateway
```
Changing the image recreates the container; `/workspace` and the keyring survive.
