#!/bin/bash
# Clean full-cluster power-down, step 2 of 3 (run on k3-node1 AFTER move-prep.sh). Powers off node4, node3, node2
# (via a one-shot privileged pod pinned to each node — nodeName bypasses the cordon), waits for each to stop
# answering ping, then powers off node1 itself. etcd keeps quorum until node2 goes; after that the API is gone,
# which is why node1 is last and nothing after that point uses kubectl.
# Then: BMC → slots are already off; unplug the Turing Pi.
set -uo pipefail
IP=([1]=192.168.4.101 [2]=192.168.4.102 [3]=192.168.4.103 [4]=192.168.4.104)
kubectl get nodes --no-headers | grep -q "SchedulingDisabled" || { echo "nodes not cordoned — run move-prep.sh first"; exit 1; }
read -rp "Power off the whole cluster now? Type 'poweroff': " a; [ "$a" = poweroff ] || exit 1
for n in 4 3 2; do
  echo "$(date +%H:%M:%S) == powering off k3-node$n"
  kubectl -n kube-system delete pod poweroff-$n --ignore-not-found >/dev/null 2>&1
  kubectl -n kube-system run poweroff-$n --restart=Never --image=alpine:3.20 --overrides='{"spec":{"nodeName":"k3-node'$n'","hostPID":true,"tolerations":[{"operator":"Exists"}],"containers":[{"name":"p","image":"alpine:3.20","securityContext":{"privileged":true},"command":["nsenter","-t","1","-m","-u","-n","-i","-p","--","sh","-c","sleep 2; systemctl poweroff"]}]}}' >/dev/null
  for i in $(seq 90); do ping -c1 -W1 ${IP[$n]} >/dev/null 2>&1 || break; sleep 2; done
  ping -c1 -W1 ${IP[$n]} >/dev/null 2>&1 && { echo "   k3-node$n still answers after 3 min — check it (BMC console), then re-run"; exit 1; }
  echo "   k3-node$n is down"; sleep 10      # let systemd finish flushing disks after the NIC goes away
done
echo "$(date +%H:%M:%S) == powering off k3-node1 (this session ends here)"
sync; sudo systemctl poweroff
