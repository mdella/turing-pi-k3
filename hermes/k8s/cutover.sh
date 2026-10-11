#!/bin/bash
# Move Hermes from node1's systemd units into k3s (ns hermes). Run on k3-node1 as ubuntu, from this directory.
#   ./cutover.sh            do it (asks once before stopping anything)
#   ./rollback.sh           undo: pods to 0, consumers back to node1, host units back on
#
# Order matters — never two copies of the gateway or signal-cli at once:
#   preflight -> stop + disable host units -> copy state into the volumes (pod on node1, host dirs read-only)
#   -> rewrite configs (migrate_config.py) -> start signal-cli, sandboxes, gateway -> point Luna/Cheshire bridges and
#   the hermes.geekstyle.net tunnel rule at the pods -> resume timers as CronJobs -> verify.
# node1's ~/.hermes and signal-cli data are only READ, so rollback restarts from exactly the pre-cutover state
# (anything said to the assistants after cutover lives only in the k3s copy).
set -euo pipefail
cd "$(dirname "$0")"
NS=hermes
H=/home/ubuntu/.hermes
UNITS="hermes-allowlist-sync.timer hermes-dm-cost-alert.timer signal-cli-backup.timer hermes-gateway hermes-dashboard signal-cli"
IMG=$(kubectl -n $NS get deploy hermes -o jsonpath='{.spec.template.spec.containers[0].image}')
say() { printf '\n== %s\n' "$*"; }
die() { echo "ABORT: $*" >&2; exit 1; }

say "preflight"
for d in hermes signal-cli sbx-cheshire sbx-luna; do
  r=$(kubectl -n $NS get deploy $d -o jsonpath='{.spec.replicas}'); [ "$r" = 0 ] || die "deploy/$d has $r replicas (expected 0)"
done
q=$(sqlite3 "$H/state.db" "select count(*) from delivery_obligations where state in ('pending','attempting','failed')")
[ "$q" = 0 ] || die "$q Signal deliveries queued — they would replay; wait or mark abandoned (hermes/README.md)"
kubectl -n $NS get deploy hermes-render mac-studio-relay -o jsonpath='{range .items[*]}{.metadata.name}={.status.readyReplicas}{" "}{end}'; echo
pol=$(kubectl -n longhorn-system get settings.longhorn.io node-down-pod-deletion-policy -o jsonpath='{.value}')
[ "$pol" = do-nothing ] && echo "WARNING: Longhorn node-down-pod-deletion-policy=do-nothing — a dead node will NOT fail Hermes over (see README)"
echo "image: $IMG"
read -r -p "Stop Hermes on node1 and move it into k3s now? [yes/N] " ok; [ "$ok" = yes ] || die "not confirmed"

say "safety backup of signal-cli (host script)"
sudo /usr/local/sbin/signal-cli-backup.sh

say "stop + disable host units (disable = a reboot can't bring a second copy back)"
sudo systemctl disable --now $UNITS
for c in $(docker ps -q --filter ancestor=cheshire-sandbox:20261009 --filter ancestor=luna-sandbox:20261011); do docker rm -f "$c"; done
for u in hermes-gateway signal-cli; do systemctl is-active -q $u && die "$u still active"; done

say "copy state into the volumes (Job on node1, host dirs mounted read-only)"
kubectl -n $NS create configmap hermes-migrate --from-file=migrate_config.py --dry-run=client -o yaml | kubectl apply -f -
kubectl -n $NS delete job hermes-migrate --ignore-not-found --wait
kubectl apply -f - <<EOF
apiVersion: batch/v1
kind: Job
metadata: { name: hermes-migrate, namespace: $NS }
spec:
  backoffLimit: 0
  template:
    spec:
      restartPolicy: Never
      nodeSelector: { kubernetes.io/hostname: k3-node1 }
      imagePullSecrets: [{ name: registry-pull }]
      automountServiceAccountToken: false
      securityContext: { runAsUser: 0 }   # root: volume roots/subPath dirs were created by kubelet as root; chowned to 1000 below
      containers:
        - name: copy
          image: $IMG
          command:
            - sh
            - -c
            - |
              set -eu
              # top-level entries, not ".": the volume roots belong to root (tar can't chmod/utime them)
              cd /src/hermes && find . -mindepth 1 -maxdepth 1 | tar --exclude=./hermes-agent --exclude=./tools --exclude=./installs --exclude=./bin \\
                  --exclude=./local-mcp --exclude=./local-patches --exclude=./node_modules \\
                  --exclude='./profiles/*/sandbox' --exclude='./profiles/*/sandboxes' \\
                  --exclude='./*.bak-sync' --exclude='./.env.bak-allowlist' -cf - -T - | tar -C /dst/state -xpf -
              cd /src/signal && find . -mindepth 1 -maxdepth 1 | tar -cf - -T - | tar -C /dst/signal -xpf -
              for p in cheshire luna; do
                mkdir -p /dst/sbx-\$p/workspace /dst/sbx-\$p/gnupg
                [ -d /src/hermes/profiles/\$p/sandbox/workspace ] && cp -a /src/hermes/profiles/\$p/sandbox/workspace/. /dst/sbx-\$p/workspace/
                [ -d /src/hermes/profiles/\$p/sandbox/gnupg ] && cp -a /src/hermes/profiles/\$p/sandbox/gnupg/. /dst/sbx-\$p/gnupg/
              done
              /opt/hermes/.venv/bin/python /migrate/migrate_config.py /dst/state
              chown -R 1000:1000 /dst/state /dst/signal /dst/sbx-cheshire /dst/sbx-luna
              chmod 700 /dst/sbx-cheshire/gnupg /dst/sbx-luna/gnupg
              du -sh /dst/state /dst/signal /dst/sbx-cheshire /dst/sbx-luna
          volumeMounts:
            - { name: src-hermes, mountPath: /src/hermes, readOnly: true }
            - { name: src-signal, mountPath: /src/signal, readOnly: true }
            - { name: state, mountPath: /dst/state }
            - { name: signal, mountPath: /dst/signal }
            - { name: sbx-cheshire, mountPath: /dst/sbx-cheshire }
            - { name: sbx-luna, mountPath: /dst/sbx-luna }
            - { name: migrate, mountPath: /migrate }
      volumes:
        - { name: src-hermes, hostPath: { path: $H, type: Directory } }
        - { name: src-signal, hostPath: { path: /home/ubuntu/.local/share/signal-cli, type: Directory } }
        - { name: state, persistentVolumeClaim: { claimName: hermes-state } }
        - { name: signal, persistentVolumeClaim: { claimName: signal-cli-data } }
        - { name: sbx-cheshire, persistentVolumeClaim: { claimName: sbx-cheshire-data } }
        - { name: sbx-luna, persistentVolumeClaim: { claimName: sbx-luna-data } }
        - { name: migrate, configMap: { name: hermes-migrate } }
EOF
for _ in $(seq 120); do  # wait for complete OR failed (kubectl wait only watches one condition)
  st=$(kubectl -n $NS get job hermes-migrate -o jsonpath='{.status.succeeded}/{.status.failed}')
  case "$st" in 1/*) break ;; */1) kubectl -n $NS logs job/hermes-migrate | tail -30; die "copy failed (host units are stopped: ./rollback.sh)" ;; esac
  sleep 5
done
[ "${st%%/*}" = 1 ] || die "copy timed out (host units are stopped: ./rollback.sh)"
kubectl -n $NS logs job/hermes-migrate | tail -25

say "start signal-cli, sandboxes, gateway"
kubectl -n $NS scale deploy/signal-cli --replicas=1 && kubectl -n $NS rollout status deploy/signal-cli --timeout=300s
kubectl -n $NS scale deploy/sbx-cheshire deploy/sbx-luna --replicas=1
kubectl -n $NS rollout status deploy/sbx-cheshire --timeout=300s && kubectl -n $NS rollout status deploy/sbx-luna --timeout=300s
kubectl -n $NS scale deploy/hermes --replicas=1 && kubectl -n $NS rollout status deploy/hermes --timeout=600s
for p in luna cheshire; do
  kubectl -n $NS exec deploy/hermes -c gateway -- sh -c "k=\$(sed -n 's/^API_SERVER_KEY=//p' $H/profiles/$p/.env); curl -s -o /dev/null -w '/p/$p/v1/models -> %{http_code}\n' -H \"Authorization: Bearer \$k\" http://127.0.0.1:8642/p/$p/v1/models"
done

say "point Luna + Cheshire bridges at the pod"
for p in luna cheshire; do
  sed -i 's#192\.168\.4\.101:8642#hermes-api.hermes.svc.cluster.local:8642#g' ../../$p/$p.yaml
  kubectl apply -f ../../$p/$p.yaml >/dev/null && kubectl -n $p rollout restart deploy/$p-webui && kubectl -n $p rollout status deploy/$p-webui --timeout=300s
done

say "tunnel rule hermes.geekstyle.net -> dashboard Service"
TID=$(~/bin/cf GET "accounts/{account}/cfd_tunnel?name=k3s-geekstyle&is_deleted=false" | python3 -c 'import sys,json;print(json.load(sys.stdin)["result"][0]["id"])')
~/bin/cf GET "accounts/{account}/cfd_tunnel/$TID/configurations" | python3 -c '
import sys, json
cfg = json.load(sys.stdin)["result"]["config"]
hits = [r for r in cfg["ingress"] if r.get("hostname") == "hermes.geekstyle.net"]
assert len(hits) == 1, hits
hits[0]["service"] = "http://hermes-dashboard.hermes.svc.cluster.local:9119"
json.dump({"config": cfg}, open("/tmp/hermes-tunnel.json", "w"))'
~/bin/cf PUT "accounts/{account}/cfd_tunnel/$TID/configurations" "$(cat /tmp/hermes-tunnel.json)" | python3 -c 'import sys,json;print("tunnel update success:", json.load(sys.stdin)["success"])'
rm -f /tmp/hermes-tunnel.json

say "timers -> CronJobs"
for c in hermes-allowlist-sync hermes-dm-cost-alert signal-cli-backup; do kubectl -n $NS patch cronjob $c -p '{"spec":{"suspend":false}}'; done
kubectl -n $NS patch cronjob signal-cli-backup-offnode -p '{"spec":{"suspend":true}}'

say "done — now verify by hand:"
cat <<'EOT'
  1. Luna:     https://luna.geekstyle.net — ask something; then ask her to write a file (sandbox) and draw a diagram (render)
  2. Cheshire: https://cheshire.geekstyle.net — same, plus `gpg --list-secret-keys` in his sandbox (key copied)
  3. Mickey:   send a Signal DM / group message mentioning him; check `kubectl -n hermes logs deploy/signal-cli`
  4. Dashboard: https://hermes.geekstyle.net (Access + OIDC)
  5. kubectl -n hermes create job --from=cronjob/signal-cli-backup backup-now   (new backup path works)
  Rollback at any point: ./rollback.sh
EOT
