# Coder workspace image: Claude Code + git/glab/gpg for one user. Build on an arm64 node:
#   docker build -t coder-workspace:<YYYYMMDD> coder/workspace
# then import into the workspace nodes' containerd (see ../README.md). Bump the pins on purpose.
FROM ubuntu:24.04@sha256:534baea6a22c03a63003dbc8dbe78fe34bc0d7e595d9a9dc9834884ff530eb55

ARG CLAUDE_VERSION=2.1.287
ARG GLAB_VERSION=1.122.0

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      ca-certificates curl git git-lfs gnupg openssh-client jq less nano vim-tiny tmux procps \
      python3 python3-venv python3-pip unzip zip make ripgrep pinentry-curses locales tzdata \
    && sed -i 's/^# *en_US.UTF-8/en_US.UTF-8/' /etc/locale.gen && locale-gen \
    && rm -rf /var/lib/apt/lists/*

# Claude Code, pinned and checksum-verified; auto-update is off (managed settings) so the image decides the version.
RUN set -eu; base=https://downloads.claude.ai/claude-code-releases/$CLAUDE_VERSION; \
    sum=$(curl -fsSL $base/manifest.json | jq -r '.platforms["linux-arm64"].checksum'); \
    curl -fsSL -o /usr/local/bin/claude $base/linux-arm64/claude; \
    echo "$sum  /usr/local/bin/claude" | sha256sum -c -; chmod 755 /usr/local/bin/claude; claude --version

# GitLab CLI, checksum-verified.
RUN set -eu; base=https://gitlab.com/gitlab-org/cli/-/releases/v$GLAB_VERSION/downloads; deb=glab_${GLAB_VERSION}_linux_arm64.deb; \
    cd /tmp; curl -fsSLO $base/$deb; curl -fsSL $base/checksums.txt | grep " $deb\$" | sha256sum -c -; \
    dpkg -i $deb; rm $deb; glab --version

# Unprivileged user, no sudo. /home/coder is the persistent volume.
RUN userdel -r ubuntu 2>/dev/null || true; useradd -m -u 1000 -s /bin/bash coder; \
    echo 'export GPG_TTY=$(tty)' > /etc/profile.d/gpg-tty.sh; echo '[ -f /etc/profile.d/gpg-tty.sh ] && . /etc/profile.d/gpg-tty.sh' >> /etc/bash.bashrc
ENV LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 EDITOR=nano
USER coder
WORKDIR /home/coder
