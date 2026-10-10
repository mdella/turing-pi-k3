#!/bin/sh
# glab with the user's GitLab login from Coder ("Connect GitLab"), refreshed on every call; a token the user set wins.
if [ -z "${GITLAB_TOKEN:-}" ] && command -v coder >/dev/null 2>&1; then
  t=$(coder external-auth access-token gitlab 2>/dev/null) && [ -n "$t" ] && GITLAB_TOKEN=$t && export GITLAB_TOKEN
fi
exec /usr/bin/glab "$@"
