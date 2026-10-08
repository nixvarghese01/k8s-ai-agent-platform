#!/bin/bash
# The model of each use case (README §6.9): chat (Open WebUI), agent (tool calling) and email
# (n8n triage), in ConfigMap llm/llm-model (not in Git). Same as the Models page at
# https://agent.ai.local, which also shows whether a model fits in RAM.
#
#   model.sh                          the choice per use case, downloaded models, what's in RAM
#   model.sh use <name> [use case]    download if needed and use it for every use case, or only
#                                     for chat, agent or email; frees models no longer used
#   model.sh remove <name>            delete a downloaded model no use case uses
#
#   From Windows:  .\infra\scripts\platform.ps1 model [use|remove <name>]
#   Inside Ubuntu: make model M=<name>   (or: bash infra/scripts/model.sh use <name>)
set -euo pipefail
export KUBECONFIG=${KUBECONFIG:-$([ "$EUID" -eq 0 ] && echo /etc/rancher/k3s/k3s.yaml || echo ~/.kube/config)}
DEFAULT=qwen2.5:3b # LiteLLM's fallback until a model is chosen (llm/litellm.yaml)
EMBED=nomic-embed-text

key() { kubectl -n llm get configmap llm-model -o jsonpath="{.data.$1}" 2>/dev/null || true; }
chat=$(key model); chat=${chat:-$DEFAULT}
agent=$(key agent); agent=${agent:-$chat}
email=$(key email); email=${email:-$chat}

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
    ollama show "$name" >/dev/null 2>&1 || ollama pull "$name"
    for_=${3:-all}
    case "$for_" in
      all) chat=$name agent=$name email=$name ;;
      chat) chat=$name ;;
      agent) agent=$name ;;
      email) email=$name ;;
      *) echo "use case must be chat, agent, email or all" >&2; exit 1 ;;
    esac
    if [[ "$agent" == "$name" ]] && ! ollama show "$name" | grep -qw tools; then
      echo "Note: $name can't call tools; the agent's tool steps won't work with it."
    fi
    # agent/email equal to chat are stored empty, so they follow chat's next change
    kubectl -n llm get configmap llm-model >/dev/null 2>&1 || kubectl -n llm create configmap llm-model >/dev/null
    kubectl -n llm patch configmap llm-model --type merge -p "{\"data\": {\"model\": \"$chat\", \"agent\": \"$([[ $agent == "$chat" ]] || echo "$agent")\", \"email\": \"$([[ $email == "$chat" ]] || echo "$email")\"}}" >/dev/null
    kubectl -n llm rollout restart deploy/litellm >/dev/null
    kubectl -n llm rollout status deploy/litellm --timeout=5m >/dev/null
    for m in $(ollama ps | awk 'NR > 1 {print $1}'); do
      [[ "$m" == "$chat" || "$m" == "$agent" || "$m" == "$email" || "$m" == "$EMBED"* ]] || { ollama stop "$m"; echo "freed from RAM: $m"; }
    done
    echo "Loading $name and asking it one question..."
    ip=$(kubectl -n llm get svc litellm -o jsonpath='{.spec.clusterIP}')
    start=$(date +%s)
    reply=$(curl -s -m 600 "http://$ip:4000/v1/chat/completions" -H 'Content-Type: application/json' \
      -d '{"model": "'"$(case $for_ in agent) echo chat-tools ;; email) echo chat-email ;; *) echo chat-default ;; esac)"'", "messages": [{"role": "user", "content": "Reply with the single word OK."}]}' |
      sed -n 's/.*"content":"\([^"]*\)".*/\1/p')
    echo "chat: $chat   agent: $agent   email: $email"
    echo "First answer from $name: \"${reply:-none}\" in $(($(date +%s) - start)) s (includes loading it)."
    ;;
  remove)
    name=${2:?usage: model.sh remove <name>}
    [[ "$name" == "$chat" || "$name" == "$agent" || "$name" == "$email" ]] &&
      { echo "$name is in use; switch that use case to another model first" >&2; exit 1; }
    [[ "$name" == "$EMBED"* ]] && { echo "$name is used for document search; keep it" >&2; exit 1; }
    ollama rm "$name"
    ;;
  *)
    sed -n '6,9p' "$0"; exit 1
    ;;
esac
