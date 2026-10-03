#!/bin/bash
# Run the RAG indexer now instead of waiting for the 15-minute CronJob (README §6.12).
# Run inside Ubuntu from the repo root:  bash infra/scripts/rag-index.sh [--rebuild]
#   --rebuild  drop the Qdrant collection and embed everything again (after changing the
#              embedding model, its prefixes or the chunk size)
set -euo pipefail
export KUBECONFIG=${KUBECONFIG:-~/.kube/config}

job=rag-index-manual-$(date +%Y%m%d-%H%M%S)
spec=$(kubectl -n agent create job "$job" --from=cronjob/rag-index --dry-run=client -o yaml)
if [ "${1:-}" = "--rebuild" ]; then
  spec=$(sed 's/^\( *\)- rag_index.py$/&\n\1- --rebuild/' <<<"$spec")
fi
kubectl apply -f - <<<"$spec"

# Wait for the pod, then stream its log until the job ends
kubectl -n agent wait --for=condition=Ready pod -l job-name="$job" --timeout=120s >/dev/null 2>&1 || true
kubectl -n agent logs -f "job/$job" || true
kubectl -n agent wait --for=condition=Complete "job/$job" --timeout=60m
