# Mac Studio FLUX.2 — text-to-image engine + Claude Code MCP

Run **FLUX.2 [dev]** (Black Forest Labs, Nov 2025) text-to-image on Richard's Mac Studio
(M3 Ultra, 96 GB) via ComfyUI, and drive it from a laptop's Claude Code through an MCP tool
— routed over netbird via k3-node1 (until a Ziti connector replaces the hop).

## Layout & Mac sync

- **`workflows/`** — the ComfyUI workflow JSONs (FLUX.2 + FLUX.1 t2i/img2img/Redux/ControlNet).
- Root — infra: `flux2_mcp.py` (MCP server), `com.cstone.comfyui.plist` (launchd), `comfyui-forward.service` (k3-node1 socat).
- The Mac has a clone at `/Users/jax/turing-pi-k3`; ComfyUI's `user/default/workflows` is a **symlink** to `mac-studio-flux2/workflows/`, so UI-saved workflows land in git. Commit on the Mac (`git add mac-studio-flux2 && git commit`); pushing from the Mac needs GitHub creds for `jax` (else push from the k3 admin host, `git pull` on the Mac).

## Architecture

```
MacBook ──(home LAN)──▶ k3-node1:8199 ──(netbird)──▶ Mac Studio 100.101.193.15:8199 ──▶ ComfyUI + FLUX.2
   │                         │                              │
 Claude Code            socat forwarder              headless ComfyUI (MPS),
 + flux2 MCP            (systemd service)             bound to netbird IP only
```

- **Mac Studio** runs ComfyUI headless, bound to its netbird IP `100.101.193.15:8199` (not LAN/public).
- **k3-node1** (one of the netbird peers — node3/node4 are peers too) runs a `socat` forwarder: `192.168.4.101:8199 → 100.101.193.15:8199`.
- **Laptop** runs a tiny stdio MCP server (`flux2_mcp.py`) that calls ComfyUI's HTTP API through k3-node1.
  No netbird/VPN or ComfyUI needed on the laptop.

## Why GGUF (not fp8)

Apple MPS has **no fp8 (`Float8_e4m3fn`) support**, so the `fp8mixed` 32B checkpoint fails on the sampler.
The fix is the **GGUF** build (`city96/FLUX.2-dev-gguf`, Q8_0, 34.5 GB) via the `ComfyUI-GGUF` node —
weights dequantize to bf16, which MPS runs. The fp8 *text encoder* works fine and is kept.

## Models (in the ComfyUI base path on the Mac: `/Users/jax/Documents/ComfyUI-v1/models/`)

| File | Folder | From |
|---|---|---|
| `flux2-dev-Q8_0.gguf` (34.5 GB) | `diffusion_models/` | `city96/FLUX.2-dev-gguf` |
| `mistral_3_small_flux2_fp8.safetensors` (18 GB) | `text_encoders/` | `Comfy-Org/flux2-dev` |
| `flux2-vae.safetensors` | `vae/` | `Comfy-Org/flux2-dev` |
| `Flux2TurboComfyv2.safetensors` (turbo LoRA, 8-step) | `loras/` | `Comfy-Org/flux2-dev` |

Custom node: `ComfyUI-GGUF` (in `custom_nodes/`), plus `pip install gguf` in the venv.

## Mac Studio — run ComfyUI headless

Comfy Desktop is now the todesktop build (`/Applications/Comfy Desktop.app`, no Homebrew cask).
Its Python venv + ComfyUI code live at fixed paths, and the headless service uses them directly
(the frontend package is in the venv now, so no `--front-end-root` is needed):

```bash
/Users/jax/Documents/ComfyUI-v1/.venv/bin/python3 -s \
  /Users/jax/ComfyUI-Installs/ComfyUI/ComfyUI/main.py \
  --base-directory /Users/jax/Documents/ComfyUI-v1 \
  --user-directory /Users/jax/Documents/ComfyUI-v1/user \
  --database-url sqlite:////Users/jax/Documents/ComfyUI-v1/user/comfyui.db \
  --extra-model-paths-config "/Users/jax/Library/Application Support/Comfy Desktop/shared_model_paths.yaml" \
  --input-directory /Users/jax/Documents/ComfyUI-v1/input \
  --output-directory /Users/jax/Documents/ComfyUI-v1/output \
  --listen 0.0.0.0 --port 8199 --enable-manager \
  --disable-auto-launch --dont-print-server --disable-metadata
```

`com.cstone.comfyui.plist` wraps exactly this. Install it as the **jax** user:

```bash
cp com.cstone.comfyui.plist ~/Library/LaunchAgents/
launchctl enable   gui/$(id -u)/com.cstone.comfyui
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.cstone.comfyui.plist
```

Bootstrap works over SSH **only while jax is logged into the desktop** (Aqua session live) — the job
lands in the `gui/<uid>` domain and inherits WindowServer/Metal from that session. With no live GUI
session the sampler hangs at 0% on Metal init; if that happens, run the bootstrap from a Terminal on
the Mac after logging in. Quit `Comfy Desktop.app` first so it isn't holding port 8199.

**Reboot caveat:** FileVault is ON and there's no auto-login, so a cold reboot stops at the FileVault
unlock screen and no GUI session exists until someone logs in. The service therefore auto-starts
**when jax logs into the desktop** (and `KeepAlive` restarts it on crash) — not on an unattended boot.
For truly unattended start you'd need FileVault off + auto-login (GPU/Metal still needs a GUI session,
so a root LaunchDaemon is not a substitute).

## k3-node1 — forwarder

`comfyui-forward.service` → `/etc/systemd/system/`, then `systemctl enable --now comfyui-forward`.
Requires `socat`. netbird ACL already permits node1 → Mac on 8199.

## Laptop — Claude Code MCP

```bash
brew install uv                       # runtime for the MCP server
curl -fsSL https://raw.githubusercontent.com/mdella/turing-pi-k3/main/mac-studio-flux2/flux2_mcp.py -o ~/flux2_mcp.py
claude mcp add flux2 -- uv run /Users/$USER/flux2_mcp.py
```

Then ask Claude Code to "generate an image of …". Override the endpoint with `COMFYUI_URL` if needed.

- Render time: ~2–3 min (8-step turbo). If Claude Code's MCP tool timeout is hit, raise it or drop `steps` to 4.
- **Security:** ComfyUI has no auth; via node1 it's reachable to the home LAN. Trusted-network only.
