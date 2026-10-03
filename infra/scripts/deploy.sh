#!/bin/bash
# README §6.5: apply every manifest under infra/k3s and wait for the workloads.
# Run inside Ubuntu from the repo root:  bash infra/scripts/deploy.sh
set -euxo pipefail
export KUBECONFIG=${KUBECONFIG:-~/.kube/config}
cd "$(dirname "$0")/../.."

kubectl apply -f infra/k3s/namespaces.yaml

# Secrets live only in the cluster, never in Git. Create each one once; keep it on re-deploy.
set +x
if ! kubectl -n ui get secret open-webui-secret >/dev/null 2>&1; then
  # Signs Open WebUI login sessions; a stable key keeps users logged in across restarts
  kubectl -n ui create secret generic open-webui-secret \
    --from-literal=WEBUI_SECRET_KEY="$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')"
fi
set -x

kubectl apply -R -f infra/k3s/
kubectl -n llm rollout status deploy/litellm --timeout=10m
kubectl -n storage rollout status deploy/qdrant --timeout=10m
kubectl -n ui rollout status deploy/open-webui --timeout=15m
kubectl -n ui rollout status deploy/headlamp --timeout=5m
# Built locally: run `make images` first (infra/scripts/build-images.sh)
kubectl -n agent rollout status deploy/mcp-filesystem --timeout=5m
kubectl -n agent rollout status deploy/mcp-rag --timeout=5m
kubectl -n agent rollout status deploy/agent --timeout=5m
kubectl -n ui rollout status deploy/agent-ui --timeout=5m
kubectl get pods,pvc,ingress -A --field-selector metadata.namespace!=kube-system
