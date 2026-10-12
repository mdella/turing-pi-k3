#!/bin/bash
# Clean full-cluster power-down, step 3 of 3 (run on k3-node1 after all four nodes are powered on).
# Waits for the cluster, checks the new network path, uncordons, waits for Galera recovery, scales the workloads
# recorded by move-prep.sh back up (StatefulSets first), resumes CronJobs, then runs smoke checks. Safe to re-run.
set -uo pipefail
STATE=${STATE:-$(ls -d $HOME/cluster-move/*/ | tail -1)}; STATE=${STATE%/}
[ -s "$STATE/workloads.json" ] || { echo "no $STATE/workloads.json"; exit 1; }
log() { echo "$(date +%H:%M:%S) == $*"; }
echo "state: $STATE"

log "1/7 API + nodes Ready (max 15 min)"
for i in $(seq 180); do
  R=$(kubectl get nodes --no-headers 2>/dev/null | awk '$2 ~ /^Ready/' | wc -l); [ "$R" = 4 ] && break; sleep 5
done
kubectl get nodes --no-headers | awk '{print "   ",$1,$2}'; [ "$R" = 4 ] || { echo "not all nodes Ready"; exit 1; }

log "2/7 network path (Arista): node1 -> OPNsense / node2"
for t in 192.168.4.1 192.168.1.1 192.168.4.102; do
  ping -c 10 -i 0.2 -q $t 2>/dev/null | awk -v t=$t -F'/' '/rtt|round-trip/{print "    "t" avg "$5" ms (wireless hop was 5-6 ms; wired should be <1)"}'
done

log "3/7 uncordon"
kubectl uncordon k3-node1 k3-node2 k3-node3 k3-node4 >/dev/null; kubectl get nodes --no-headers | awk '{print "   ",$1,$2}'

log "4/7 Longhorn + Galera (max 15 min)"
kubectl -n longhorn-system rollout status ds/longhorn-manager --timeout=600s | tail -1
for i in $(seq 90); do
  G=$(kubectl -n mariadb get mariadb mariadb-galera -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}')
  [ "$G" = True ] && break; sleep 10
done
echo "    galera Ready=$G"; kubectl -n mariadb exec mariadb-galera-0 -c mariadb -- sh -c 'mariadb -uroot -p"$MARIADB_ROOT_PASSWORD" -N -e "show status like \"wsrep_cluster_size\""' 2>/dev/null | sed 's/^/    /'

log "5/7 scale workloads back up"
scale() { python3 -c "import json,sys;[print(k+'/'+str(v)) for k,v in json.load(open(sys.argv[1])).items() if k.startswith(sys.argv[2])]" "$STATE/workloads.json" $1 |
  while IFS=/ read -r kind ns n r; do kubectl -n $ns scale $kind/$n --replicas=$r >/dev/null; echo "    $r -> $ns/$n"; echo "$kind $ns $n" >> "$STATE/.scaled-$1"; done; }
rm -f "$STATE"/.scaled-*
scale statefulsets
while read -r kind ns n; do kubectl -n $ns rollout status $kind/$n --timeout=600s >/dev/null && echo "    ready $ns/$n" || echo "    NOT READY $ns/$n"; done < "$STATE/.scaled-statefulsets"
scale deployments
while read -r kind ns n; do t=300; [ $n = gitlab ] && t=1500
  kubectl -n $ns rollout status $kind/$n --timeout=${t}s >/dev/null && echo "    ready $ns/$n" || echo "    NOT READY $ns/$n"; done < "$STATE/.scaled-deployments"

log "6/7 resume CronJobs"
while read -r cj; do kubectl -n ${cj%/*} patch cronjob ${cj#*/} -p '{"spec":{"suspend":false}}' >/dev/null && echo "    $cj"; done < "$STATE/cronjobs.txt"

log "7/7 smoke checks"
kubectl -n longhorn-system get volumes.longhorn.io -o json | python3 -c "
import json,sys;v=json.load(sys.stdin)['items']
bad=[x['status'].get('kubernetesStatus',{}).get('pvcName') for x in v if x['status']['state']=='attached' and x['status']['robustness']!='healthy']
print('    longhorn: %d attached, not healthy: %s'%(sum(x['status']['state']=='attached' for x in v),bad or 'none'))"
echo "    pods not Running/Succeeded:"; kubectl get pods -A --no-headers | awk '$4!="Running" && $4!="Completed"{print "      "$1"/"$2" "$4}'
kubectl -n openbao exec openbao-0 -- bao status 2>/dev/null | awk '/Sealed/{print "    openbao sealed="$2}'
for u in https://scm.geekstyle.net/users/sign_in https://blog.geekstyle.net/ https://auth.geekstyle.net/.well-known/openid-configuration https://luna.geekstyle.net/; do
  curl -s -o /dev/null -m 15 -w "    %{http_code} $u\n" $u; done
kubectl -n hermes exec deploy/hermes -c gateway -- sh -c 'grep -m1 -o "/opt/hermes/.venv" /proc/1/maps >/dev/null && echo "    hermes venv ok" || echo "    hermes venv WRONG (installs/ trap)"'
for a in luna cheshire; do
  kubectl -n $a exec deploy/$a-webui -c open-webui -- python3 -c "
import urllib.request,json
r=urllib.request.Request('http://127.0.0.1:8080/v1/chat/completions',data=json.dumps({'model':'$a','messages':[{'role':'user','content':'Reply with just the word ok.'}]}).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer injected-by-bridge'})
print('    $a reply:',json.load(urllib.request.urlopen(r,timeout=180))['choices'][0]['message']['content'])" 2>&1 | tail -1
done
echo; echo "Done. Manually: send Mickey a Signal message; Ziti/netbird on hosts: 'netbird status' on a node."
