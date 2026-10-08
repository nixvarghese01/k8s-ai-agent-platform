#!/bin/bash
# End-to-end check of the whole platform (README section 10): every layer through its real
# interface, one PASS/FAIL line each, with the measured time. Read-only, except that it adds a
# few requests to the logs and traces (one agent question per feature, one test e-mail, one
# daily briefing file for today). Needs all profiles on; a profile that's off shows SKIP.
# Run inside Ubuntu:  bash infra/scripts/e2e.sh   (or: make e2e)
set -uo pipefail
export KUBECONFIG=${KUBECONFIG:-$([ "$EUID" -eq 0 ] && echo /etc/rancher/k3s/k3s.yaml || echo ~/.kube/config)}
cd "$(dirname "$0")/../.." || exit 1
fails=0

echo "== cluster"
notready=$(kubectl get pods -A --no-headers | awk '$4!="Running" && $4!="Completed"' | wc -l)
restarts=$(kubectl get pods -A --no-headers | awk '$4=="Running" && $5+0>0 {print $1"/"$2"("$5")"}' | tr '\n' ' ')
[ "$notready" = 0 ] && echo "PASS  pods: all Running${restarts:+ (restarted: $restarts)}" || { echo "FAIL  pods: $notready not Running"; fails=$((fails+1)); }
echo "      profiles: $(kubectl -n kube-system get configmap platform-profiles -o jsonpath='{.data.active}' 2>/dev/null)"
if kubectl -n argocd get application platform >/dev/null 2>&1; then
  app=$(kubectl -n argocd get application platform -o jsonpath='{.status.sync.status} {.status.health.status} {.status.sync.revision}')
  [[ "$app" == "Synced Healthy"* ]] && echo "PASS  argocd: ${app:0:22}" || { echo "FAIL  argocd: $app"; fails=$((fails+1)); }
fi

# Everything else from inside the cluster, through the services' own APIs
out=$(mktemp)
kubectl -n ui exec -i deploy/agent-ui -- python - <<'PY' 2>&1 | grep -v '^Defaulted' | tee "$out"
import json, time, httpx, wave, io

fails = 0
def check(name, fn, skip_on=()):
    global fails
    t = time.time()
    try:
        detail = fn()
        print(f"PASS  {name}: {detail} ({time.time() - t:.1f}s)")
    except httpx.ConnectError:
        print(f"SKIP  {name}: not running (profile off?)")
    except Exception as e:
        fails += 1
        print(f"FAIL  {name}: {type(e).__name__}: {str(e)[:160]}")

def ok(cond, detail):
    assert cond, detail
    return detail

L, A = "http://litellm.llm.svc.cluster.local:4000", "http://agent.agent.svc.cluster.local:8000"
H = {"Authorization": "Bearer local"}
def chat(msg):
    d = httpx.post(A + "/chat", json={"message": msg}, timeout=900).json()
    return d, [s["tool"] for s in d["steps"]]

print("== LLM stack")
check("ollama", lambda: ok(httpx.get("http://ollama.llm.svc.cluster.local:11434/api/version", timeout=30).status_code == 200, "up"))
check("litellm chat", lambda: ok("ok" in httpx.post(L + "/v1/chat/completions", headers=H, timeout=300, json={"model": "chat-default", "messages": [{"role": "user", "content": "Reply with the single word OK."}]}).json()["choices"][0]["message"]["content"].lower(), "chat-default answers"))
check("litellm embeddings", lambda: ok(len(httpx.post(L + "/v1/embeddings", headers=H, timeout=120, json={"model": "embed-default", "input": "hello"}).json()["data"][0]["embedding"]) == 768, "768 dims"))

print("== agent")
TOOLS = {"list_dir", "read_file", "search_files", "search_documents", "classify_message", "remember", "recall",
         "forget", "now", "list_events", "add_event", "web_search", "fetch_page", "research"}
check("tools", lambda: ok(TOOLS <= {t["name"] for t in httpx.get(A + "/tools", timeout=60).json()["tools"]}, f"{len(TOOLS)} MCP tools loaded"))
def files():
    d, tools = chat("What files are in my shared folder?")
    return ok("list_dir" in tools and "meeting" in d["answer"], f"list_dir, {d['seconds']}s")
check("file search (workflow 2)", files)
def rag():
    d, tools = chat("What was decided in the meeting on 2026-10-01?")
    return ok("0 EUR" in d["answer"] and "meeting-2026-10-01.md" in d["answer"], f"answer + source, {d['seconds']}s")
check("document Q&A (workflow 3)", rag)
def ocr():
    d, tools = chat("How much rent did I pay for October?")
    return ok("5,000" in d["answer"] and "rent-receipt.pdf p.1" in d["answer"], f"from a scanned PDF, cited p.1, {d['seconds']}s")
check("OCR document (workflow 9)", ocr)
def spam():
    d, tools = chat("Is this message spam? 'URGENT: your account is locked, reply with your PIN to unlock it'")
    return ok(tools == ["classify_message"] and "SPAM" in json.dumps(d["steps"]), f"classify_message -> spam, {d['seconds']}s")
check("spam check (agent tool)", spam)
def memory():  # stores a test fact, asks for it, then deletes it again
    chat("Remember that the e2e check code is 4711")
    try:
        d, tools = chat("What is the e2e check code?")
        return ok("4711" in d["answer"] and any(s["tool"] == "recall (auto)" for s in d["steps"]), f"remembered across conversations, {d['seconds']}s")
    finally:
        chat("Forget that the e2e check code is 4711")
check("memory (workflow 1)", memory)
def calendar():
    d, tools = chat("What's on my calendar this week?")
    return ok("list_events" in tools, f"list_events, {d['seconds']}s")
check("calendar (workflow 5)", calendar)
def research():
    d, tools = chat("Search the web for the latest Kubernetes release")
    if "research profile" in d["answer"]:
        raise httpx.ConnectError("research profile off")
    return ok("Sources:" in d["answer"] and "http" in d["answer"], f"answer with links, {d['seconds']}s")
check("web research (workflow 6)", research)
def planned():
    d, tools = chat("List the files in my shared folder and then tell me what my to-do list says")
    return ok(tools[0] == "plan" and "list_dir" in tools and "cooling stand" in d["answer"], f"{' -> '.join(tools)}, {d['seconds']}s")
check("multi-step plan (workflow 7)", planned)

print("== documents")
Q = "http://qdrant.storage.svc.cluster.local:6333"
check("qdrant collection docs", lambda: ok(httpx.get(Q + "/collections/docs", timeout=30).json()["result"]["points_count"] > 60, f"{httpx.get(Q + '/collections/docs', timeout=30).json()['result']['points_count']} chunks"))

print("== mlops")
T = "http://triage.mlops.svc.cluster.local:3000"
check("model serving (BentoML)", lambda: ok([r["label"] for r in httpx.post(T + "/classify", json={"texts": ["WIN a FREE prize now, call 0900 123", "see you at lunch"]}, timeout=60).json()] == ["spam", "ham"], f"spam/ham right, model v{httpx.post(T + '/model', json={}, timeout=30).json()['version']}"))
check("mlflow", lambda: ok(httpx.get("http://mlflow.mlops.svc.cluster.local:5000/health", timeout=30).text.strip() == "OK", "healthy"))
check("dagster", lambda: ok(httpx.get("http://dagster-webserver.mlops.svc.cluster.local:3000/server_info", timeout=30).status_code == 200, "webserver up"))

print("== automation (n8n)")
N = "http://n8n.automation.svc.cluster.local:5678/webhook"
# The model is trained on SMS spam (README 6.12): it catches prize/premium-number spam, but
# phishing e-mails like "verify at paypa1-verify.top" still score as ham (~0.33); known gap
check("email triage: spam (workflow 4)", lambda: ok(httpx.post(N + "/email-triage", timeout=300, json={"from": "promo@win.top", "subject": "Winner", "body": "Congratulations! You WON a FREE cash prize. Call 09061701461 now to claim, T&C apply"}).json()["verdict"] == "spam", "spam"))
def mail():
    r = httpx.post(N + "/email-triage", timeout=600, json={"from": "maria@company.com", "subject": "Review moved", "body": "The design review moves to Thursday 3pm. Can you update the slides?"}).json()
    return ok(r["verdict"] == "ham" and r.get("category") and r.get("summary"), f"ham, {r.get('category')}: {r.get('summary', '')[:50]}")
check("email triage: normal mail", mail)
check("daily briefing (workflow 10)", lambda: ok(httpx.get(N + "/daily-briefing", timeout=900).json()["fileName"].startswith("/briefings/"), "written to briefings/"))

print("== observability")
P = "http://prometheus.observability.svc.cluster.local:9090"
check("prometheus targets", lambda: ok(all(t["health"] == "up" for t in httpx.get(P + "/api/v1/targets", timeout=30).json()["data"]["activeTargets"]), f"{len(httpx.get(P + '/api/v1/targets', timeout=30).json()['data']['activeTargets'])} up"))
check("grafana", lambda: ok(httpx.get("http://grafana.observability.svc.cluster.local:3000/api/health", timeout=30).json()["database"] == "ok", "healthy"))
def traces():
    projects = {p["name"]: p for p in httpx.get("http://phoenix.observability.svc.cluster.local:6006/v1/projects", timeout=30).json()["data"]}
    n = len(httpx.get("http://phoenix.observability.svc.cluster.local:6006/v1/projects/agent/spans", params={"limit": 50}, timeout=30).json()["data"])
    return ok({"agent", "litellm"} <= set(projects) and n > 0, f"projects agent + litellm, {n}+ agent spans")
check("phoenix traces", traces)

print("== voice (workflow 8)")
V = "http://voice.voice.svc.cluster.local:8000"
def voice():
    wav = httpx.post(V + "/v1/audio/speech", json={"input": "When is my gym membership due?"}, timeout=300).content
    text = httpx.post(V + "/v1/audio/transcriptions", files={"file": ("q.wav", wav, "audio/wav")}, timeout=300).json()["text"]
    return ok("gym" in text.lower(), f"speech -> text: {text!r}")
check("speech round trip", voice)

print("== sign-on guards (a pod must not be able to sign in by sending Remote-* headers)")
def blocked(url):
    try:
        httpx.get(url, timeout=5)
    except (httpx.ConnectError, httpx.ConnectTimeout):
        return "blocked"
    raise AssertionError("reachable from a pod")
check("open webui only via traefik", lambda: blocked("http://open-webui.ui.svc.cluster.local:8080/health"))
check("seaweedfs admin only via traefik", lambda: blocked("http://seaweedfs.storage.svc.cluster.local:23646/"))
forged = {"Remote-User": "admin", "Remote-Email": "x@ai.local", "Remote-Groups": "admins", "browser-id": "e2e"}
check("grafana ignores forged header", lambda: ok(httpx.get("http://grafana.observability.svc.cluster.local:3000/api/user", headers=forged, timeout=10).status_code == 401, "401"))
def n8n_forged():
    r = httpx.get("http://n8n.automation.svc.cluster.local:5678/rest/login", headers=forged, timeout=10)
    return ok(r.status_code == 401 and "n8n-auth" not in r.headers.get("set-cookie", ""), "401, no session")
check("n8n ignores forged header", n8n_forged)

print(f"in-cluster failures: {fails}")
PY
n=$(sed -n 's/^in-cluster failures: //p' "$out"); rm -f "$out"
fails=$((fails + ${n:-1}))  # no count line = the script itself crashed
echo "== storage and jobs"
dbs=$(kubectl -n storage exec deploy/postgres -- psql -U postgres -tAc "select count(*) from pg_database where datname in ('mlflow','dagster')" 2>/dev/null)
[ "$dbs" = 2 ] && echo "PASS  postgres: mlflow + dagster databases" || { echo "FAIL  postgres: $dbs"; fails=$((fails+1)); }
buckets=$(kubectl -n storage exec deploy/seaweedfs -- sh -c 'echo s3.bucket.list | weed shell 2>/dev/null' | grep -c -E 'mlflow|dagster|triage')
[ "$buckets" = 3 ] && echo "PASS  seaweedfs: buckets mlflow, dagster, triage" || { echo "FAIL  seaweedfs: $buckets of 3 buckets"; fails=$((fails+1)); }
echo "      rag-index last run: $(kubectl -n agent get cronjob rag-index -o jsonpath='{.status.lastSuccessfulTime}')"
kubectl -n mlops exec deploy/dagster-webserver -- python -c "
from dagster import DagsterInstance
for job in ('triage_training', 'triage_monitoring'):
    r = DagsterInstance.get().get_run_records(filters=__import__('dagster').RunsFilter(job_name=job), limit=1)
    print(f\"      dagster {job}: {r[0].dagster_run.status.value} at {r[0].create_timestamp:%Y-%m-%d %H:%M} UTC\" if r else f'      dagster {job}: no runs')
" 2>/dev/null

echo "== sign-on and HTTPS (as the browser sees it, via Traefik)"
IP=$(hostname -I | awk '{print $1}')
for h in auth chat llm agent qdrant headlamp mlflow dagster s3 triage phoenix grafana n8n argocd; do
  code=$(curl -s --cacert /var/lib/local-ai-ca/ca.crt --resolve "$h.ai.local:443:$IP" -o /dev/null -w "%{http_code} %{redirect_url}" "https://$h.ai.local/" 2>/dev/null)
  case "$h:$code" in
    auth:200*) echo "PASS  https://auth.ai.local: sign-in page, trusted certificate" ;;
    *:302\ https://auth.ai.local/*) printf "PASS  https://%s.ai.local: protected (302 to sign-in)\n" "$h" ;;
    *) printf "FAIL  https://%s.ai.local: %s\n" "$h" "$code"; fails=$((fails+1)) ;;
  esac
done
# ArgoCD over OpenID Connect: it reaches Authelia in-cluster, and Authelia accepts the client
if kubectl -n argocd get deploy argocd-server >/dev/null 2>&1; then
  argo=$(kubectl -n argocd get pod -l app.kubernetes.io/name=argocd-server -o jsonpath='{.items[0].status.podIP}')
  authz=$(curl -s -o /dev/null -w '%{redirect_url}' -H 'Host: argocd.ai.local' -H 'X-Forwarded-Proto: https' "http://$argo:8080/auth/login")
  flow=$(curl -s --cacert /var/lib/local-ai-ca/ca.crt --resolve "auth.ai.local:443:$IP" -o /dev/null -w '%{redirect_url}' "$authz" 2>/dev/null)
  [[ "$authz" == https://auth.ai.local/api/oidc/authorization?client_id=argocd* && "$flow" == *flow=openid_connect* ]] &&
    echo "PASS  argocd sign-on: OpenID Connect through Authelia" || { echo "FAIL  argocd sign-on: ${authz:0:80} -> ${flow:0:80}"; fails=$((fails+1)); }
fi
kubectl -n ui get middleware headlamp-token >/dev/null 2>&1 && echo "PASS  headlamp sign-on: token middleware present" ||
  { echo "FAIL  headlamp sign-on: Middleware ui/headlamp-token missing (run deploy.sh)"; fails=$((fails+1)); }

echo
[ "$fails" = 0 ] && echo "ALL PASSED" || echo "$fails check(s) FAILED"
exit $((fails > 0))
