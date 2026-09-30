#!/bin/bash
# README §6.5: apply every manifest under infra/k3s and wait for the Week 1 workloads.
# Run inside Ubuntu from the repo root:  bash infra/scripts/deploy.sh
set -euxo pipefail
export KUBECONFIG=${KUBECONFIG:-~/.kube/config}
cd "$(dirname "$0")/../.."

kubectl apply -f infra/k3s/namespaces.yaml
kubectl apply -R -f infra/k3s/
kubectl -n llm rollout status deploy/litellm --timeout=10m
kubectl -n storage rollout status deploy/qdrant --timeout=10m
kubectl -n ui rollout status deploy/open-webui --timeout=15m
kubectl get pods,pvc,ingress -A --field-selector metadata.namespace!=kube-system
