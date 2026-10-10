# Coder — per-user Claude Code workspaces (pilot, 2026-10-10)

Each user gets their own **workspace**: a pod with a persistent home volume, running Claude Code, git, glab and gpg,
built from one admin-managed **template**. Users sign in through Zitadel; they get a web terminal, SSH (`coder ssh`) or
Claude Code **Remote Control** from claude.ai / the mobile app. They never touch the image, the policy or the cluster.

```
browser / coder CLI ─▶ Cloudflare ─▶ tunnel ─▶ ingress-nginx ─▶ coderd (ns coder) ─▶ coder-db (Postgres, Longhorn)
                          login: Zitadel project "coder" (role grant required)
coderd ─(Terraform, kubernetes provider)─▶ workspace pod + home PVC (ns coder, node3)
workspace agent ─▶ coderd in-cluster (http://coder.coder.svc.cluster.local), not via Cloudflare
```

| Piece | File | Notes |
|---|---|---|
| Postgres | `coder-db.yaml` | same shape as `../zitadel/zitadel-db.yaml`; Secret `coder-db` (`dsn`) |
| Coder server | `coder-values.yaml` | chart `coder-v2/coder` 2.38.0; OIDC only (password login off), telemetry off, default GitHub provider off |
| Workspace image | `workspace/Dockerfile` | Ubuntu 24.04 (digest-pinned), Claude Code **2.1.287** + glab **1.122.0** (checksum-verified), user `coder` uid 1000, no sudo |
| Template | `templates/claude-workspace/main.tf` | pod + 10 Gi Longhorn home, CPU 1–2 / RAM 2–4 GB, non-root, all caps dropped, no SA token |
| Central policy | `workspace-policy.yaml` | Claude Code **managed settings** (read-only at `/etc/claude-code`) + NetworkPolicy |

## Central management

- **Claude Code policy:** edit the `claude-managed-settings` ConfigMap in `workspace-policy.yaml` and apply. Currently:
  auto-update off (the image pins the version), `--dangerously-skip-permissions` disabled, Claude can't read the GPG
  private keys, glab's token file or `.env` files. Users can't override managed settings.
- **Tools / Claude Code version:** bump the pins in `workspace/Dockerfile`, build, import (below), change `image` in
  the template, push the template. Users get it on their next workspace restart (Coder prompts them to update).
- **Network:** workspaces may reach the internet (Anthropic, GitLab via `scm.geekstyle.net`), DNS and coderd only — no
  LAN, cluster services or netbird ranges, and no inbound connections.
- **Who may log in:** Zitadel project **`coder`** (roles `user`, `admin`; role + project check on), app "Coder",
  redirect `https://coder.geekstyle.net/api/v2/users/oidc/callback`. Grant the project role → the person can sign in;
  their Coder account is created on first login. Client id/secret only in Secret `coder-oidc`.

## Image distribution (pilot limitation)

There's no container registry yet, so the image is built on node1 and imported into **node3's** containerd, and the
template pins workspaces to node3 with `imagePullPolicy: Never`:

```bash
docker build -t coder-workspace:<YYYYMMDD> coder/workspace
# short-lived privileged pod on node3 with the containerd socket + k3s binary mounted (see git history), then:
docker save coder-workspace:<YYYYMMDD> | kubectl -n coder exec -i image-import -- k3s ctr -n k8s.io images import --local -
```

Next step for production: enable the GitLab container registry and build the image in CI.

## User onboarding

1. Zitadel: grant the person project `coder` → `user`.
2. They open https://coder.geekstyle.net → "Sign in with geekstyle" → create a workspace from **claude-workspace**.
3. In the workspace terminal: `claude` (sign in with their own Claude account), `glab auth login --hostname scm.geekstyle.net`
   (their own GitLab token), `gpg --quick-gen-key "Name <email>"` if they sign commits. All of it lives in their home volume.
4. Optional: `claude remote-control` to drive the session from claude.ai or the phone.

## Break-glass

Password login is off. If OIDC breaks: `kubectl -n coder exec deploy/coder -- /opt/coder server create-admin-user …`
after temporarily setting `CODER_DISABLE_PASSWORD_AUTH=false`.

## Status

- [x] coder-db, coderd 2.38.0 running (node2), Zitadel project/app/owner grant, workspace image on node3, policy applied
- [ ] Publish `coder.geekstyle.net` (tunnel rule + proxied CNAME) — awaiting owner approval
- [ ] First Owner account + automation token, push the template
- [ ] Optional: GitLab OAuth app as Coder external auth (git/glab authenticate as the user without a PAT)
