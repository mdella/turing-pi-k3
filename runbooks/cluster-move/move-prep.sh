#!/bin/bash
# Clean full-cluster power-down, step 1 of 3 (run on k3-node1): backups, scale Longhorn-backed workloads to 0 so every
# volume detaches cleanly, suspend CronJobs, cordon nodes. Safe to re-run. Undo = move-restore.sh.
# Usage: move-prep.sh            (aborts if the Hermes delivery ledger has undelivered messages)
#        FORCE=1 move-prep.sh    (skip that check)
set -euo pipefail
STATE=${STATE:-$HOME/cluster-move/$(date +%Y%m%d)}
mkdir -p "$STATE" && chmod 700 "$STATE"
log() { echo "$(date +%H:%M:%S) == $*"; }

log "1/8 health"
kubectl get nodes --no-headers | awk '{print "   ",$1,$2}'
kubectl get nodes --no-headers | awk '$2!="Ready" && $2!="Ready,SchedulingDisabled"{bad=1} END{exit bad}' || { echo "a node is not Ready"; exit 1; }
kubectl -n longhorn-system get volumes.longhorn.io -o json | python3 -c "
import json,sys;v=json.load(sys.stdin)['items']
bad=[x['metadata']['name'] for x in v if x['status']['state']=='attached' and x['status']['robustness']!='healthy']
print('    longhorn: %d volumes, %d attached, not healthy: %s'%(len(v),sum(x['status']['state']=='attached' for x in v),bad or 'none'))"
kubectl -n mariadb exec mariadb-galera-0 -c mariadb -- sh -c 'mariadb -uroot -p"$MARIADB_ROOT_PASSWORD" -N -e "show status like \"wsrep_cluster_size\""' | sed 's/^/    galera /'

log "2/8 Hermes delivery ledger"
if kubectl -n hermes get deploy hermes -o jsonpath='{.spec.replicas}' | grep -qx 0; then echo "    hermes already scaled down"; else
  PENDING=$(kubectl -n hermes exec deploy/hermes -c gateway -- python3 -c "
import sqlite3,os;c=sqlite3.connect(os.path.expanduser('~/.hermes/state.db'))
r=c.execute(\"select state,count(*) from delivery_obligations group by state\").fetchall();print(r)
import sys;sys.exit(0)" )
  echo "    $PENDING"
  if echo "$PENDING" | grep -qvE "^\[(\('(delivered|failed|abandoned|expired)', [0-9]+\)(, )?)*\]$" && [ "${FORCE:-0}" != 1 ]; then
    echo "    undelivered messages in the ledger — wait and re-run, or FORCE=1"; exit 1; fi
fi

log "3/8 etcd snapshot"
SNAP=pre-move-$(date +%Y%m%d-%H%M)
sudo k3s etcd-snapshot save --name "$SNAP" 2>&1 | tail -1
sudo sh -c "cp /var/lib/rancher/k3s/server/db/snapshots/$SNAP* '$STATE/' && chown $(id -u):$(id -g) '$STATE'/$SNAP*"
ls -l "$STATE"/$SNAP* | awk '{print "   ",$5,$9}'

log "4/8 database dumps (Galera, Ghost MariaDB) + nightly pg backup jobs now"
if [ ! -s "$STATE/galera-all.sql.gz" ]; then
  kubectl -n mariadb exec mariadb-galera-0 -c mariadb -- sh -c 'mariadb-dump -uroot -p"$MARIADB_ROOT_PASSWORD" --all-databases --single-transaction --routines --events --triggers' | gzip > "$STATE/galera-all.sql.gz"
fi
if [ ! -s "$STATE/ghost-mariadb.sql.gz" ] && kubectl -n ghost get pod mariadb-0 >/dev/null 2>&1; then
  kubectl -n ghost exec mariadb-0 -- sh -c 'mariadb-dump -uroot -p"$MYSQL_ROOT_PASSWORD" --all-databases --single-transaction --routines --events --triggers' | gzip > "$STATE/ghost-mariadb.sql.gz"
fi
ls -l "$STATE"/*.sql.gz | awk '{print "   ",$5,$9}'
for cj in honcho/honcho-db-backup zitadel/zitadel-db-backup ghost/ghost-db-backup; do
  ns=${cj%/*}; n=${cj#*/}; j=premove-$n-$(date +%H%M)
  kubectl -n $ns get job "$j" >/dev/null 2>&1 || kubectl -n $ns create job "$j" --from=cronjob/$n >/dev/null
  kubectl -n $ns wait --for=condition=complete job/$j --timeout=600s >/dev/null && echo "    $cj ok" || { echo "    $cj FAILED"; exit 1; }
done

log "5/8 suspend CronJobs"
[ -s "$STATE/cronjobs.txt" ] || kubectl get cronjobs -A -o jsonpath='{range .items[?(@.spec.suspend!=true)]}{.metadata.namespace}/{.metadata.name}{"\n"}{end}' > "$STATE/cronjobs.txt"
while read -r cj; do kubectl -n ${cj%/*} patch cronjob ${cj#*/} -p '{"spec":{"suspend":true}}' >/dev/null; done < "$STATE/cronjobs.txt"
echo "    suspended $(wc -l < "$STATE/cronjobs.txt") (list: $STATE/cronjobs.txt)"

log "6/8 scale Longhorn-backed workloads to 0"
if [ ! -s "$STATE/workloads.json" ]; then
python3 - "$STATE/workloads.json" <<'EOF'
import json,subprocess,sys
k=lambda *a: json.loads(subprocess.check_output(['kubectl',*a,'-o','json']))
lh={(p['metadata']['namespace'],p['metadata']['name']) for p in k('get','pvc','-A')['items'] if p['spec'].get('storageClassName')=='longhorn'}
out={}
for kind in ('deployments','statefulsets'):
  for o in k('get',kind,'-A')['items']:
    if o['metadata'].get('ownerReferences'): continue          # operator-managed (e.g. Galera) — not ours to scale
    ns=o['metadata']['namespace']; sp=o['spec']; t=sp['template']['spec']
    claims={v['persistentVolumeClaim']['claimName'] for v in t.get('volumes',[]) if 'persistentVolumeClaim' in v}
    claims|={f"{c['metadata']['name']}-{o['metadata']['name']}-{i}" for c in sp.get('volumeClaimTemplates',[]) for i in range(sp.get('replicas',1))}
    if any((ns,c) in lh for c in claims) and sp.get('replicas',0)>0:
      out[f"{kind}/{ns}/{o['metadata']['name']}"]=sp['replicas']
json.dump(out,open(sys.argv[1],'w'),indent=1); print('    recorded',len(out),'workloads')
EOF
fi
python3 -c "import json,sys;[print(k) for k,v in json.load(open(sys.argv[1])).items() if k.startswith('deployments')]" "$STATE/workloads.json" | while IFS=/ read -r kind ns n; do kubectl -n $ns scale $kind/$n --replicas=0 >/dev/null; echo "    0 <- $ns/$n"; done
python3 -c "import json,sys;[print(k) for k,v in json.load(open(sys.argv[1])).items() if k.startswith('statefulsets')]" "$STATE/workloads.json" | while IFS=/ read -r kind ns n; do kubectl -n $ns scale $kind/$n --replicas=0 >/dev/null; echo "    0 <- $ns/$n (sts)"; done

log "7/8 wait for Longhorn volumes to detach (max 10 min)"
for i in $(seq 120); do
  A=$(kubectl -n longhorn-system get volumes.longhorn.io -o jsonpath='{range .items[?(@.status.state!="detached")]}{.status.kubernetesStatus.namespace}/{.status.kubernetesStatus.pvcName} {end}')
  [ -z "$A" ] && break; sleep 5
done
[ -z "$A" ] && echo "    all detached" || { echo "    still attached: $A"; exit 1; }

log "8/8 cordon all nodes"
kubectl cordon k3-node1 k3-node2 k3-node3 k3-node4 >/dev/null && kubectl get nodes --no-headers | awk '{print "   ",$1,$2}'
echo; echo "Prep done. State in $STATE. Next: move-shutdown.sh (powers off node4, node3, node2, then node1)."
