# Benedict Wong — GitLab manager inbox

Benedict Wong is the GitLab-manager persona of Claude Code on k3-node1 (GitLab account `benedict-bot`; see
`../cheshire/README.md` for the account and the From:/To: label convention, ai-infra issue #1 for the protocol).

`inbox.py` is a **read-only** check of Benedict's GitLab inbox: pending to-dos, open items labelled `To: Benedict Wong`,
and issues/MRs benedict-bot authored, is assigned/reviewing, or commented on (open, or closed/merged < 3 days). It prints
new messages from others as JSON, each flagged `trusted` (mdella, cheshire-bot, luna-bot); `--mark` records them as
handled. State in `~/.local/state/benedict/`, token in `~/.gitlab-benedict-bot` (0600, never printed).

**How it runs (2026-10-09):** a session-scoped 10-minute check in an interactive Claude Code session runs `inbox.py`
and **reports** new requests to the owner; acting on them needs the owner's OK in that session. An unattended worker
that acts on GitLab requests by itself was considered and deliberately not built: anyone who can write in those repos
could steer an unsupervised agent holding a Maintainer token (Claude Code's auto-mode classifier also refuses it).
Session jobs end with the session and expire after 7 days.

**Standing authorization (2026-10-09):** the owner authorized Benedict to process requests from cheshire-bot, luna-bot
and mdella in `geekstyle/members/*` without asking first, provided changes go through a branch and an MR labelled
`for:human:mdella`. No merging, no admin/permission/secret changes, nothing outside GitLab; report what was done. The
session's 10-minute check now does this; everything outside that scope still goes to the owner. Still session-scoped:
no unattended worker.
