#!/bin/bash
# Health check for the host services and Week 1 workloads. Read-only except a throwaway
# Qdrant collection (verify_test) that it creates and deletes.
# Run inside Ubuntu:  bash infra/scripts/status.sh
export KUBECONFIG=${KUBECONFIG:-~/.kube/config}

echo "== uptime / boots"
uptime -p
journalctl --list-boots --no-pager 2>/dev/null | tail -3

echo "== services"
for s in k3s ollama docker containerd; do
  printf "%-11s %s %s\n" "$s" "$(systemctl is-active $s)" "$(systemctl is-enabled $s)"
done

echo "== cluster"
kubectl get nodes --no-headers
# Kubernetes' RESTARTS counter includes every WSL/k3s stop since the pod was created, so show
# the state since this start instead. LAST-EXIT "Unknown" = node was shut down (normal);
# "Error" / "OOMKilled" after STARTED = a real crash.
echo "booted $(date -u -d "$(uptime -s)" +%Y-%m-%dT%H:%M:%SZ) (times below are UTC)"
kubectl get pods -A --field-selector=status.phase!=Succeeded -o custom-columns='NAMESPACE:.metadata.namespace,POD:.metadata.name,PHASE:.status.phase,READY:.status.containerStatuses[*].ready,STARTED:.status.containerStatuses[*].state.running.startedAt,LAST-EXIT:.status.containerStatuses[*].lastState.terminated.reason'

echo "== ollama"
curl -s http://127.0.0.1:11434/api/version; echo
ollama list
curl -s http://127.0.0.1:11434/api/generate \
  -d '{"model":"llama3.2:3b","prompt":"Reply with the single word OK.","stream":false}' |
  grep -o '"response":"[^"]*"\|"total_duration":[0-9]*'

echo "== pod -> ollama / qdrant"
kubectl -n ui exec deploy/open-webui -- python -c "
import urllib.request as u
print('ollama', u.urlopen('http://ollama.llm.svc.cluster.local:11434/api/version').read())
print('qdrant', u.urlopen('http://qdrant.storage.svc.cluster.local:6333/readyz').read())"

echo "== qdrant write/read"
Q=http://$(kubectl -n storage get svc qdrant -o jsonpath='{.spec.clusterIP}'):6333
curl -s -X PUT "$Q/collections/verify_test" -H 'Content-Type: application/json' -d '{"vectors":{"size":4,"distance":"Cosine"}}'; echo
curl -s -X PUT "$Q/collections/verify_test/points?wait=true" -H 'Content-Type: application/json' -d '{"points":[{"id":1,"vector":[0.1,0.2,0.3,0.4]}]}'; echo
curl -s -X POST "$Q/collections/verify_test/points/query" -H 'Content-Type: application/json' -d '{"query":[0.1,0.2,0.3,0.4],"limit":1}'; echo
curl -s -X DELETE "$Q/collections/verify_test"; echo

echo "== ingress (via WSL IP)"
IP=$(hostname -I | awk '{print $1}'); echo "wsl ip $IP"
for h in chat.local qdrant.local; do
  curl -s -o /dev/null -w "$h -> %{http_code}\n" -H "Host: $h" "http://$IP/"
done

echo "== docker"
docker version --format 'engine {{.Server.Version}}'

echo "== resources"
free -h | sed -n '1,3p'
df -h / | tail -1
kubectl top pods -A --no-headers 2>/dev/null
