#!/bin/bash
# Undo cutover.sh: k3s copies to 0, consumers back to node1, host units back on. node1's ~/.hermes was only read by
# the cutover, so Hermes resumes exactly where it stopped; anything said since cutover stays only in the k3s volume.
set -euo pipefail
cd "$(dirname "$0")"
NS=hermes
UNITS="hermes-allowlist-sync.timer hermes-dm-cost-alert.timer signal-cli-backup.timer hermes-gateway hermes-dashboard signal-cli"
say() { printf '\n== %s\n' "$*"; }

say "stop the k3s copies (gateway + signal-cli first: never two at once)"
for c in hermes-allowlist-sync hermes-dm-cost-alert signal-cli-backup; do kubectl -n $NS patch cronjob $c -p '{"spec":{"suspend":true}}'; done
kubectl -n $NS scale deploy/hermes deploy/signal-cli deploy/sbx-cheshire deploy/sbx-luna --replicas=0
kubectl -n $NS wait --for=delete pod -l app.kubernetes.io/name=hermes --timeout=180s || true
kubectl -n $NS wait --for=delete pod -l app.kubernetes.io/name=signal-cli --timeout=180s || true
kubectl -n $NS patch cronjob signal-cli-backup-offnode -p '{"spec":{"suspend":false}}'

say "host units back on"
sudo systemctl enable --now $UNITS

say "Luna + Cheshire bridges back to node1"
for p in luna cheshire; do
  sed -i 's#hermes-api\.hermes\.svc\.cluster\.local:8642#192.168.4.101:8642#g' ../../$p/$p.yaml
  kubectl apply -f ../../$p/$p.yaml >/dev/null && kubectl -n $p rollout restart deploy/$p-webui && kubectl -n $p rollout status deploy/$p-webui --timeout=300s
done

say "tunnel rule hermes.geekstyle.net -> node1:9119"
TID=$(~/bin/cf GET "accounts/{account}/cfd_tunnel?name=k3s-geekstyle&is_deleted=false" | python3 -c 'import sys,json;print(json.load(sys.stdin)["result"][0]["id"])')
~/bin/cf GET "accounts/{account}/cfd_tunnel/$TID/configurations" | python3 -c '
import sys, json
cfg = json.load(sys.stdin)["result"]["config"]
hits = [r for r in cfg["ingress"] if r.get("hostname") == "hermes.geekstyle.net"]
assert len(hits) == 1, hits
hits[0]["service"] = "http://192.168.4.101:9119"
json.dump({"config": cfg}, open("/tmp/hermes-tunnel.json", "w"))'
~/bin/cf PUT "accounts/{account}/cfd_tunnel/$TID/configurations" "$(cat /tmp/hermes-tunnel.json)" | python3 -c 'import sys,json;print("tunnel update success:", json.load(sys.stdin)["success"])'
rm -f /tmp/hermes-tunnel.json

say "rolled back — check Luna's reply and a Signal message (hermes/README.md)"
