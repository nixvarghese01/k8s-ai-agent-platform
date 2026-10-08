#!/bin/bash
# Health check for the host services and platform workloads. Read-only except a throwaway
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
# `platform.sh up` starts fresh pods, so a LAST-EXIT here happened in this run:
# "Error" / "OOMKilled" = a real crash. ("Unknown" = node shut down; only seen if k3s was
# started without platform.sh.)
echo "booted $(date -u -d "$(uptime -s)" +%Y-%m-%dT%H:%M:%SZ) (times below are UTC)"
kubectl get pods -A --field-selector=status.phase!=Succeeded -o custom-columns='NAMESPACE:.metadata.namespace,POD:.metadata.name,PHASE:.status.phase,READY:.status.containerStatuses[*].ready,STARTED:.status.containerStatuses[*].state.running.startedAt,LAST-EXIT:.status.containerStatuses[*].lastState.terminated.reason'

echo "== ollama"
curl -s http://127.0.0.1:11434/api/version; echo
ollama list
m=$(kubectl -n llm get configmap llm-model -o jsonpath='{.data.model}' 2>/dev/null || true)  # the active chat model
echo "active chat model: ${m:=qwen2.5:3b}"
curl -s http://127.0.0.1:11434/api/generate \
  -d "{\"model\":\"$m\",\"prompt\":\"Reply with the single word OK.\",\"stream\":false}" |
  grep -o '"response":"[^"]*"\|"total_duration":[0-9]*'

echo "== pod -> ollama / litellm / qdrant"
kubectl -n ui exec deploy/open-webui -- python -c "
import json, urllib.request as u
print('ollama', u.urlopen('http://ollama.llm.svc.cluster.local:11434/api/version').read())
L = 'http://litellm.llm.svc.cluster.local:4000'
print('litellm', u.urlopen(L + '/health/readiness').read()[:80])
print('litellm models', [m['id'] for m in json.load(u.urlopen(L + '/v1/models'))['data']])
print('qdrant', u.urlopen('http://qdrant.storage.svc.cluster.local:6333/readyz').read())"

echo "== litellm chat + embedding (aliases chat-default, embed-default)"
kubectl -n ui exec deploy/open-webui -- python -c "
import json, time, urllib.request as u
def post(path, body):
    r = u.Request('http://litellm.llm.svc.cluster.local:4000/v1/' + path, json.dumps(body).encode(),
                  {'Content-Type': 'application/json'})
    t = time.time(); d = json.load(u.urlopen(r, timeout=600)); return d, time.time() - t
d, s = post('chat/completions', {'model': 'chat-default', 'messages': [{'role': 'user', 'content': 'Reply with the single word OK.'}]})
print('chat  %-30s %.1fs' % (d['choices'][0]['message']['content'].strip()[:30], s))
d, s = post('embeddings', {'model': 'embed-default', 'input': 'hello'})
print('embed dim=%-26d %.1fs' % (len(d['data'][0]['embedding']), s))"

echo "== agent (chat-tools + filesystem MCP; one question that needs a tool)"
kubectl -n ui exec deploy/agent-ui -- python -c "
import httpx
A = 'http://agent.agent.svc.cluster.local:8000'
print('tools', [t['name'] for t in httpx.get(A + '/tools', timeout=60).json()['tools']])
d = httpx.post(A + '/chat', json={'message': 'List the files in my shared folder.'}, timeout=900).json()
print('calls', [s['tool'] for s in d['steps']], '%.1fs' % d['seconds'])"

echo "== rag (collection docs, last index run, one document question)"
Q=http://$(kubectl -n storage get svc qdrant -o jsonpath='{.spec.clusterIP}'):6333
curl -s "$Q/collections/docs" | grep -o '"points_count":[0-9]*'
kubectl -n agent get cronjob rag-index --no-headers -o custom-columns='LAST-RUN:.status.lastScheduleTime,LAST-OK:.status.lastSuccessfulTime'
kubectl -n ui exec deploy/agent-ui -- python -c "
import httpx
d = httpx.post('http://agent.agent.svc.cluster.local:8000/chat', json={'message': 'What is on my todo list?'}, timeout=900).json()
print('steps', [s['tool'] for s in d['steps']], '%.1fs' % d['seconds'], '| sources:', d['answer'].rpartition('Sources: ')[2][:80] or 'none')"

echo "== mlops (postgres, seaweedfs, mlflow, dagster, champion model)"
kubectl -n storage exec deploy/postgres -- psql -U postgres -tAc \
  "select string_agg(datname, ' ') from pg_database where datname in ('mlflow', 'dagster')"
kubectl -n storage exec deploy/seaweedfs -- sh -c 'echo s3.bucket.list | weed shell 2>/dev/null' | grep -E 'mlflow|dagster'
kubectl -n mlops exec deploy/dagster-daemon -- python -c "
import mlflow
from dagster import DagsterInstance
v = mlflow.MlflowClient().get_model_version_by_alias('message-triage', 'champion')
print('champion: message-triage v%s, test_f1 %s' % (v.version, v.tags.get('test_f1')))
r = DagsterInstance.get().get_run_records(limit=1)
print('last run:', r[0].dagster_run.job_name, r[0].dagster_run.status.value, r[0].create_timestamp.strftime('%Y-%m-%d %H:%M UTC') if r else 'none')
" 2>&1 | grep -E '^(champion|last run)'

echo "== qdrant write/read"
Q=http://$(kubectl -n storage get svc qdrant -o jsonpath='{.spec.clusterIP}'):6333
curl -s -X PUT "$Q/collections/verify_test" -H 'Content-Type: application/json' -d '{"vectors":{"size":4,"distance":"Cosine"}}'; echo
curl -s -X PUT "$Q/collections/verify_test/points?wait=true" -H 'Content-Type: application/json' -d '{"points":[{"id":1,"vector":[0.1,0.2,0.3,0.4]}]}'; echo
curl -s -X POST "$Q/collections/verify_test/points/query" -H 'Content-Type: application/json' -d '{"query":[0.1,0.2,0.3,0.4],"limit":1}'; echo
curl -s -X DELETE "$Q/collections/verify_test"; echo

echo "== ingress (https via WSL IP): sign-in page 200, every UI 302 to sign-in, http 308 to https"
IP=$(hostname -I | awk '{print $1}'); echo "wsl ip $IP"
for h in auth chat llm qdrant agent headlamp mlflow dagster s3; do
  curl -sk --resolve "$h.ai.local:443:$IP" -o /dev/null -w "$h.ai.local -> %{http_code} %{redirect_url}\n" "https://$h.ai.local/" |
    sed 's|https://auth.ai.local/?rd=.*|(sign-in)|'
done
curl -s -o /dev/null -w "http://chat.ai.local -> %{http_code} %{redirect_url}\n" -H "Host: chat.ai.local" "http://$IP/"
echo | openssl s_client -connect "$IP:443" -servername chat.ai.local 2>/dev/null | openssl x509 -noout -subject -enddate

echo "== docker"
docker version --format 'engine {{.Server.Version}}'

echo "== resources"
free -h | sed -n '1,3p'
df -h / | tail -1
kubectl top pods -A --no-headers 2>/dev/null
