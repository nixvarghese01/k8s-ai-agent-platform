#!/bin/bash
# The model of each use case (README §6.9): chat (Open WebUI), agent (tool calling) and email
# (n8n triage), in ConfigMap llm/llm-model (not in Git). Same as the Models page at
# https://agent.ai.local, which also shows whether a model fits in RAM.
#
#   model.sh                          the choice per use case, downloaded models, what's in RAM
#   model.sh use <name> [use case]    download if needed and use it for every use case, or only
#                                     for chat, agent or email; frees models no longer used
#   model.sh revert                   back to the models before the last change
#   model.sh history                  who changed what, when (the Models page's History)
#   model.sh remove <name>            delete a downloaded model no use case uses
#
#   From Windows:  .\infra\scripts\platform.ps1 model [use|revert|history|remove <name>]
#   Inside Ubuntu: make model M=<name>   (or: bash infra/scripts/model.sh use <name>)
set -euo pipefail
export KUBECONFIG=${KUBECONFIG:-$([ "$EUID" -eq 0 ] && echo /etc/rancher/k3s/k3s.yaml || echo ~/.kube/config)}
DEFAULT=qwen2.5:3b # LiteLLM's fallback until a model is chosen (llm/litellm.yaml)
EMBED=nomic-embed-text
WHO="cli:${SUDO_USER:-$(id -un)}"

key() { kubectl -n llm get configmap llm-model -o jsonpath="{.data.$1}" 2>/dev/null || true; }
chat=$(key model); chat=${chat:-$DEFAULT}
agent=$(key agent); agent=${agent:-$chat}
email=$(key email); email=${email:-$chat}
before="$chat $agent $email"

# The audit trail (issue #30): history entries in the ConfigMap, shared with the Models page.
# Written with `kubectl replace`, which fails on a concurrent change (resourceVersion) and is
# retried, so an entry never overwrites someone else's.
#   audit <action> "<chat agent email before>" "<... after>" <note>    record an entry
#   audit_show                                                          print the history
#   audit_previous "<chat agent email now>"                             what revert goes back to
audit() {
  python3 - "$@" "$WHO" <<'PY'
import datetime, json, subprocess, sys, zoneinfo
action, before, after, note, by = sys.argv[1:6]
triple = lambda s: dict(zip(("chat", "agent", "email"), s.split())) if s.strip() else None
entry = {"at": datetime.datetime.now(zoneinfo.ZoneInfo("Asia/Dubai")).strftime("%Y-%m-%d %H:%M:%S"), "by": by,
         "action": action, "before": triple(before), "after": triple(after), "note": note}
for _ in range(5):
    cm = json.loads(subprocess.run(["kubectl", "-n", "llm", "get", "configmap", "llm-model", "-o", "json"],
                                   capture_output=True, text=True, check=True).stdout)
    data = cm.setdefault("data", {})
    data["history"] = json.dumps((json.loads(data.get("history") or "[]") + [entry])[-50:])
    r = subprocess.run(["kubectl", "replace", "-f", "-"], input=json.dumps(cm), capture_output=True, text=True)
    if r.returncode == 0:
        break
    if "the object has been modified" not in r.stderr:
        sys.exit(r.stderr)
PY
}
audit_show() {
  kubectl -n llm get configmap llm-model -o jsonpath='{.data.history}' 2>/dev/null | python3 -c '
import json, sys
def fmt(c):
    if not c:
        return ""
    if len(set(c.values())) == 1:
        return next(iter(c.values())) + " everywhere"
    return " · ".join(k + " " + v for k, v in c.items())
rows = json.loads(sys.stdin.read() or "[]")
for e in reversed(rows):
    print(e["at"], " ", e["by"].ljust(12), e["action"].ljust(8), fmt(e.get("before")).ljust(34), "->",
          fmt(e.get("after")).ljust(34), (e.get("note") or "")[:60])
print("(%d entries)" % len(rows))'
}
audit_previous() {
  kubectl -n llm get configmap llm-model -o jsonpath='{.data.history}' 2>/dev/null | python3 -c '
import json, sys
now = dict(zip(("chat", "agent", "email"), sys.argv[1].split()))
for e in reversed(json.loads(sys.stdin.read() or "[]")):
    if e["action"] in ("apply", "revert") and e.get("after") == now and e.get("before"):
        print(e["before"]["chat"], e["before"]["agent"], e["before"]["email"])
        break' "$1"
}

# Set the three models, restart LiteLLM, free models no use case uses
apply_choice() {
  chat=$1 agent=$2 email=$3
  # agent/email equal to chat are stored empty, so they follow chat's next change
  kubectl -n llm get configmap llm-model >/dev/null 2>&1 || kubectl -n llm create configmap llm-model >/dev/null
  kubectl -n llm patch configmap llm-model --type merge -p "{\"data\": {\"model\": \"$chat\", \"agent\": \"$([[ $agent == "$chat" ]] || echo "$agent")\", \"email\": \"$([[ $email == "$chat" ]] || echo "$email")\"}}" >/dev/null
  kubectl -n llm rollout restart deploy/litellm >/dev/null
  kubectl -n llm rollout status deploy/litellm --timeout=5m >/dev/null
  for m in $(ollama ps | awk 'NR > 1 {print $1}'); do
    [[ "$m" == "$chat" || "$m" == "$agent" || "$m" == "$email" || "$m" == "$EMBED"* ]] || { ollama stop "$m"; echo "freed from RAM: $m"; }
  done
}

# A test question through LiteLLM; LiteLLM may need a few seconds after its restart
smoke_test() {
  echo "Loading the models and asking a test question..."
  ip=$(kubectl -n llm get svc litellm -o jsonpath='{.spec.clusterIP}')
  start=$(date +%s) reply=""
  for _ in $(seq 12); do
    reply=$(curl -s -m 600 "http://$ip:4000/v1/chat/completions" -H 'Content-Type: application/json' \
      -d '{"model": "chat-tools", "messages": [{"role": "user", "content": "Reply with the single word OK."}]}' |
      sed -n 's/.*"content":"\([^"]*\)".*/\1/p') || true
    [ -n "$reply" ] && break
    sleep 5
  done
  echo "chat: $chat   agent: $agent   email: $email"
  echo "Agent's first answer: \"${reply:-none}\" in $(($(date +%s) - start)) s (includes loading)."
}

case "${1:-list}" in
  list)
    echo "chat: $chat   agent: $agent   email: $email"
    echo; echo "== downloaded"; ollama list
    echo; echo "== in RAM"; ollama ps
    ;;
  use)
    name=${2:?usage: model.sh use <name>}
    [[ "$name" =~ ^[A-Za-z0-9][A-Za-z0-9._/:-]*$ ]] || { echo "not a model name: $name" >&2; exit 1; }
    [[ "$name" == "$EMBED"* ]] && { echo "$name is the embedding model, not a chat model" >&2; exit 1; }
    if ! ollama show "$name" >/dev/null 2>&1; then
      ollama pull "$name"
      audit download "" "" "$name"
    fi
    case "${3:-all}" in
      all) set -- "$name" "$name" "$name" ;;
      chat) set -- "$name" "$agent" "$email" ;;
      agent) set -- "$chat" "$name" "$email" ;;
      email) set -- "$chat" "$agent" "$name" ;;
      *) echo "use case must be chat, agent, email or all" >&2; exit 1 ;;
    esac
    if [[ "$2" == "$name" ]] && ! ollama show "$name" | grep -qw tools; then
      echo "Note: $name can't call tools; the agent's tool steps won't work with it."
    fi
    apply_choice "$@"
    audit apply "$before" "$*" "from model.sh"
    smoke_test
    ;;
  revert)
    read -r p_chat p_agent p_email <<<"$(audit_previous "$before")" || true
    [ -n "${p_chat:-}" ] || { echo "Nothing to revert to: no recorded change led to the current models." >&2; exit 1; }
    echo "Reverting to: chat $p_chat, agent $p_agent, email $p_email"
    apply_choice "$p_chat" "$p_agent" "$p_email"
    audit revert "$before" "$p_chat $p_agent $p_email" "from model.sh"
    smoke_test
    ;;
  history)
    audit_show
    ;;
  remove)
    name=${2:?usage: model.sh remove <name>}
    [[ "$name" == "$chat" || "$name" == "$agent" || "$name" == "$email" ]] &&
      { echo "$name is in use; switch that use case to another model first" >&2; exit 1; }
    [[ "$name" == "$EMBED"* ]] && { echo "$name is used for document search; keep it" >&2; exit 1; }
    ollama rm "$name"
    audit delete "" "" "$name"
    ;;
  *)
    sed -n '6,12p' "$0"; exit 1
    ;;
esac
