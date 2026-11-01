# Ansible: node OS baseline

Central config for the k3s nodes' operating system. Kubernetes itself is not managed here.

| What | Where |
|---|---|
| Control node | k3-node1, connecting to itself locally |
| Ansible | `~/ansible/.venv` on node1, version pinned in `requirements.txt` |
| Playbooks | this directory (public: no addresses, prefixes or secrets) |
| Inventory | `~/ansible-inventory` on node1 (private, local git until it has a private GitLab project) |
| SSH | user `ubuntu`, key `~/.ssh/ansible_ed25519` on node1 |

## Use

```bash
cd ~/turing-pi-k3/ansible
~/ansible/.venv/bin/ansible-playbook baseline.yml --check --diff    # report drift, change nothing
~/ansible/.venv/bin/ansible-playbook baseline.yml --diff            # apply
```

`--limit k3-node4` and `--tags netplan` narrow a run. Tags: `netplan`, `cloud_init`, `ipv6`, `storage`, `ssh`, `k3s`.

An apply goes one node at a time, worker first and node1 last, and stops at the first failure.

## What it manages

- `/etc/netplan/01-network.yaml`, and that no other netplan file is active
- cloud-init's network config disabled
- the DHCPv6 DUID setting (see `network/README.md`)
- the multipath blacklist for Longhorn, and that `open-iscsi` and `nfs-common` are installed
- checks only: sshd is keys-only with no root login, swap is off

## What it deliberately doesn't do

A file change never restarts anything. Netplan changes run `netplan generate` only, so they take effect at the next
boot. `netplan apply` or `networkctl reload` can drop addresses other software put on `eth0`, such as the kube-vip VIP,
so applying live stays a manual step per node. The same goes for restarting networkd, sshd or multipathd: multipathd
restarts are risky while Longhorn volumes are attached.

## Adding a node

Add its public key to `ubuntu`'s `authorized_keys`, add it to `hosts.yml` in the inventory and create its `host_vars`
file, then run with `--check --diff --limit <node>`.
