# coder-workspace

The image every Coder workspace runs (https://coder.geekstyle.net, template `claude-workspace`): Ubuntu 24.04 with
Claude Code, glab, git, gpg, Python and tmux, user `coder` (uid 1000), no sudo.

- **Change tools or versions** (e.g. bump `CLAUDE_VERSION`): edit `Dockerfile` on a branch and open an MR. The MR
  pipeline builds the image without pushing.
- **On merge to main** CI builds and pushes `registry.geekstyle.net/geekstyle/platform/coder-workspace:<YYYYMMDD>-<sha>`
  (also `:<sha>` and `:main`) and smoke-tests it.
- **Roll out** by setting that tag as `image` in the Coder template and pushing the template — users get it on their
  next workspace restart. Claude Code policy (managed settings) is not in the image; it's a ConfigMap in the cluster.

Builds run on the in-cluster k3s runner with kaniko (unprivileged, no Docker daemon). The registry is LAN/netbird-only.
Docs: https://github.com/mdella/turing-pi-k3/tree/main/coder
