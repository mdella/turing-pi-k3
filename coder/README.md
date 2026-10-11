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
| Coder server | `coder-values.yaml` | chart `coder-v2/coder` 2.38.0; OIDC only (password login and Coder's default GitHub login/git-auth off), telemetry off; **GitLab external auth** (OAuth app "Coder (coder.geekstyle.net)" in GitLab, Secret `coder-gitlab-oauth`) |
| Workspace image | `workspace/Dockerfile` (+ `.gitlab-ci.yml`; source of truth: GitLab `geekstyle/platform/coder-workspace`) | Ubuntu 24.04 (digest-pinned), Claude Code **2.1.296** + glab **1.122.0** (checksum-verified; `/usr/local/bin/glab` wrapper uses the Coder GitLab login), user `coder` uid 1000, no sudo |
| Template | `templates/claude-workspace/main.tf` | image from the GitLab registry, pod + 10 Gi Longhorn home, CPU 1–2 / RAM 2–4 GB, non-root, all caps dropped, no SA token |
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

## Image distribution — GitLab container registry (2026-10-11)

The image lives at **`registry.geekstyle.net/geekstyle/platform/coder-workspace:<tag>`** (GitLab project
`geekstyle/platform/coder-workspace`, private). Workspaces pull it with the read-only deploy token `k3s-coder-pull`
(Secret `coder/registry-pull`, `imagePullSecrets` in the template) and can run on any node (preferred: not node1/node4).
Registry setup: `../gitlab/README.md`.

**Built by CI** in the GitLab project (source of truth for the image; `workspace/` here is a mirror for reference):
kaniko on the in-cluster k3s runner (unprivileged). MRs build without pushing; merges to `main` push
`:<YYYYMMDD>-<sha>`, `:<sha>` and `:main`, then a smoke job checks uid 1000, no sudo, Claude Code/glab/gpg versions.
Cleanup policy: keep the 10 newest tags (and `main`), delete older than 30 days, daily.

**Rollout is deliberate:** set `local.image` in `templates/claude-workspace/main.tf` to the new tag and
`coder templates push`; users get it on their next restart (`coder update <ws>`). The image is a template *local* on
purpose — Coder keeps a template variable's first value across pushes, so changing a variable default does nothing.


## User onboarding

1. Zitadel: grant the person project `coder` → `user`.
2. They open https://coder.geekstyle.net → "Sign in with geekstyle" → create a workspace from **claude-workspace**.
3. In the workspace terminal: `claude` (sign in with their own Claude account), `glab auth login --hostname scm.geekstyle.net`
   (only if they skipped "Connect GitLab"), `gpg --quick-gen-key "Name <email>"` if they sign commits. All of it lives in their home volume.
4. Optional: `claude remote-control` to drive the session from claude.ai or the phone.

**Pre-creating someone** (so a workspace is ready before their first login):
`coder users create --username <u> --email <their Zitadel email> --login-type oidc`, then **activate** them
(`PUT /api/v2/users/<u>/status/activate`; the CLI `users activate` only prompts) — pre-created users are *dormant*
and their workspace agents get 401 "User is not active" until then. `coder create <u>/<ws> --template claude-workspace`.
Their first Zitadel login links to the account by email.

## Break-glass

Password login is off. If OIDC breaks: `kubectl -n coder exec deploy/coder -- /opt/coder server create-admin-user …`
after temporarily setting `CODER_DISABLE_PASSWORD_AUTH=false`.

## Status

- [x] coder-db, coderd 2.38.0 running (node2), Zitadel project/app/owner grant, policy applied
- [x] `coder.geekstyle.net` published (tunnel rule + proxied CNAME, no Access — Zitadel role check is the gate)
- [x] Owner `mdella` (first created via /setup with a password → switched to `login_type=oidc` in the DB so Zitadel login works; avoid /setup next time), automation token in `~/.coder-admin` on node1 (0600), CLI `~/bin/coder`
- [x] Template `claude-workspace` pushed; test workspace `mdella/pilot`: agent connected, Claude Code 2.1.287, glab, gpg, uid 1000, managed settings applied, internet OK, LAN blocked
- [x] GitLab OAuth app as Coder external auth (git/glab authenticate as the user without a PAT)
- [x] Image moved to the GitLab container registry (2026-10-11); node3 pin and manual containerd import retired
- [x] CI build (2026-10-11): pipeline #154 built + smoke-tested `20261011-9147152f`; template rolled to it, pilot verified pulling from the registry
- [x] 2026-10-11: Claude Code 2.1.296 (MR !1 → pipeline #156 → `20261011-a640ac67`), template rolled; user **anna** (ladyofkrypton, Zitadel `coder` → user) pre-created + activated, workspace `anna/workspace` ready
