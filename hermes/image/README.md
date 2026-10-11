# hermes-image

The Hermes gateway + dashboard image for the geekstyle k3s cluster: the upstream `nousresearch/hermes-agent` image
(pinned by digest) plus our local layer. Source of truth for the image; docs and deployment live in
[turing-pi-k3/hermes](https://github.com/mdella/turing-pi-k3/tree/main/hermes) (`image/` there mirrors this project).

| Path | What |
|---|---|
| `Dockerfile` | `FROM` upstream v0.21.6 → apply `patches/` → bake extras (ddgs, edge-tts, honcho-ai) + bundle the Honcho memory plugin at a pinned commit → `/opt/geekstyle` (MCP servers, timer scripts, Mermaid) → uid 1000, `HERMES_HOME=/home/ubuntu/.hermes`, no s6 |
| `patches/` | `signal-local.patch` (Signal observer + name trigger, Haiku 5.5 defaults, API-server profile model routes), `ssh-no-sync-back.patch` |
| `local-mcp/` | `s3_store.py`, `repo_files.py`, `render_docs.py` (stdio MCP servers) |
| `bin/` | `signal-allowlist-sync.py`, `dm-cost-alert.py`, `set-dashboard-password` |

**Flow:** branch → MR (pipeline builds without pushing: proves the patches still apply) → merge → `main` pushes
`registry.geekstyle.net/geekstyle/platform/hermes-image:<hermes>-<date>-<sha>` and runs the smoke job → roll out by
bumping the tag in the k8s manifests (deliberate, never automatic).

**Upgrading Hermes:** change `HERMES_BASE` (tag + multi-arch index digest from Docker Hub) and `HERMES_VERSION` in
`.gitlab-ci.yml`; if a patch no longer applies the MR build fails at the `git apply` step — refresh the patch from a
checkout of the new version.
