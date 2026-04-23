# Uptime Kuma

## Overview

Uptime Kuma is a self-hosted uptime monitoring tool with a clean web UI. It provides
status checks (HTTP, TCP, ping, DNS, etc.), incident history, and notification alerts
for services across the cluster and beyond.

## Access

| Detail | Value |
|---|---|
| URL | `http://192.168.4.209` |
| First-run | Create admin account on first visit (no default credentials) |

## Installation

```bash
kubectl apply -f uptime-kuma.yaml
```

## Configuration

No credentials to set in advance — Uptime Kuma prompts for an admin username and
password on first login.

## Storage

Data (SQLite database, config) is stored on a 2 Gi local-path PVC. The deployment
uses `strategy: Recreate` to ensure the single replica fully stops before the new
one starts (required for SQLite write safety).

## Common Commands

```bash
# Pod status
kubectl get pods -n uptime-kuma

# Logs
kubectl logs -n uptime-kuma deployment/uptime-kuma

# Restart (picks up any image updates)
kubectl rollout restart deployment/uptime-kuma -n uptime-kuma
```

## Files

| File | Purpose |
|---|---|
| `uptime-kuma.yaml` | Namespace, PVC, Deployment, and LoadBalancer Service |
