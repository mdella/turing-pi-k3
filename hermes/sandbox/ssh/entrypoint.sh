#!/bin/sh
# Copy the mounted host key + authorized_keys into a private dir with the modes sshd insists on, then run sshd
# in the foreground (logs to stderr → kubectl logs).
set -eu
install -d -m 700 /run/sshd
install -m 600 /etc/sandbox-ssh/hostkey/ssh_host_ed25519_key /run/sshd/ssh_host_ed25519_key
install -m 600 /etc/sandbox-ssh/authorized/authorized_keys /run/sshd/authorized_keys
mkdir -p "$HOME/.hermes"
exec /usr/sbin/sshd -D -e -f /etc/ssh/sshd_config
