#!/bin/bash
# Delete everything deploy.sh created, including PersistentVolumeClaims, so Open WebUI chats,
# accounts and Qdrant vectors are gone for good. k3s, Ollama and the models stay installed.
# Traefik also falls back to its default config (so *.local stops working) until `make deploy`.
# Run inside Ubuntu from the repo root:  bash infra/scripts/teardown.sh [--yes]
set -euo pipefail
export KUBECONFIG=${KUBECONFIG:-~/.kube/config}
cd "$(dirname "$0")/../.."

if [ "${1:-}" != "--yes" ]; then
  kubectl get pvc -A --no-headers 2>/dev/null | awk '$1!="kube-system" {print "  will delete volume " $1 "/" $2}'
  read -r -p "Delete all platform workloads and their data? [y/N] " ok
  [ "$ok" = "y" ] || { echo "aborted"; exit 1; }
fi

set -x
kubectl delete -R -f infra/k3s/ --ignore-not-found --wait=true
kubectl get pods,pvc -A --field-selector metadata.namespace!=kube-system
