#!/bin/bash
# One chat model at a time (README §6.9): chat (Open WebUI), the agent and n8n all use the
# ACTIVE model, named in ConfigMap llm/llm-model (not in Git). Same as the Models page at
# https://agent.ai.local.
#
#   model.sh                 downloaded models, the active one, what's in RAM
#   model.sh use <name>      download it if needed, make it active, free the previous one
#   model.sh remove <name>   delete a downloaded model (not the active one)
#
#   From Windows:  .\infra\scripts\platform.ps1 model [use|remove <name>]
#   Inside Ubuntu: make model M=<name>   (or: bash infra/scripts/model.sh use <name>)
set -euo pipefail
export KUBECONFIG=${KUBECONFIG:-$([ "$EUID" -eq 0 ] && echo /etc/rancher/k3s/k3s.yaml || echo ~/.kube/config)}
DEFAULT=qwen2.5:3b # LiteLLM's fallback until a model is chosen (llm/litellm.yaml)
EMBED=nomic-embed-text

active() { kubectl -n llm get configmap llm-model -o jsonpath='{.data.model}' 2>/dev/null || true; }
current=$(active); current=${current:-$DEFAULT}

case "${1:-list}" in
  list)
    echo "Active chat model: $current"
    echo; echo "== downloaded"; ollama list
    echo; echo "== in RAM"; ollama ps
    ;;
  use)
    name=${2:?usage: model.sh use <name>}
    [[ "$name" =~ ^[A-Za-z0-9][A-Za-z0-9._/:-]*$ ]] || { echo "not a model name: $name" >&2; exit 1; }
    [[ "$name" == "$EMBED"* ]] && { echo "$name is the embedding model, not a chat model" >&2; exit 1; }
    ollama show "$name" >/dev/null 2>&1 || ollama pull "$name"
    ollama show "$name" | grep -qw tools ||
      echo "Note: $name can't call tools; chat works, the agent's tool steps won't."
    kubectl -n llm create configmap llm-model --from-literal=model="$name" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
    kubectl -n llm rollout restart deploy/litellm >/dev/null
    kubectl -n llm rollout status deploy/litellm --timeout=5m >/dev/null
    for m in $(ollama ps | awk 'NR > 1 {print $1}'); do
      [[ "$m" == "$name" || "$m" == "$EMBED"* ]] || { ollama stop "$m"; echo "freed from RAM: $m"; }
    done
    echo "Loading $name and asking it one question..."
    ip=$(kubectl -n llm get svc litellm -o jsonpath='{.spec.clusterIP}')
    start=$(date +%s)
    reply=$(curl -s -m 600 "http://$ip:4000/v1/chat/completions" -H 'Content-Type: application/json' \
      -d '{"model": "chat-default", "messages": [{"role": "user", "content": "Reply with the single word OK."}]}' |
      sed -n 's/.*"content":"\([^"]*\)".*/\1/p')
    echo "$name is active. First answer: \"${reply:-none}\" in $(($(date +%s) - start)) s (includes loading it)."
    ;;
  remove)
    name=${2:?usage: model.sh remove <name>}
    [[ "$name" == "$current" ]] && { echo "$name is active; switch to another model first" >&2; exit 1; }
    [[ "$name" == "$EMBED"* ]] && { echo "$name is used for document search; keep it" >&2; exit 1; }
    ollama rm "$name"
    ;;
  *)
    sed -n '6,8p' "$0"; exit 1
    ;;
esac
