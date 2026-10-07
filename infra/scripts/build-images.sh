#!/bin/bash
# Build the platform's own images with Docker and load them into k3s (no registry needed;
# GHCR comes with CI in Week 7). Then restart the deployments that use them.
# Run inside Ubuntu from the repo root:  bash infra/scripts/build-images.sh [name ...]
#   names: mcp-filesystem mcp-rag mcp-triage agent agent-ui mlflow pipelines serving (default: all)
# Needs root for `k3s ctr`; re-runs itself with sudo when started as a normal user.
set -euo pipefail
[ "$EUID" -eq 0 ] || exec sudo -E bash "$0" "$@"
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
cd "$(dirname "$0")/../.."

# image name -> build folder, namespace/deployment
declare -A DIR=([mcp-filesystem]=mcp-servers/filesystem [mcp-rag]=mcp-servers/rag [mcp-triage]=mcp-servers/triage [serving]=serving [agent]=agent [agent-ui]=ui [mlflow]=mlops/mlflow [pipelines]=pipelines)
declare -A DEPLOY=([mcp-filesystem]=agent/mcp-filesystem [mcp-rag]=agent/mcp-rag [mcp-triage]=agent/mcp-triage [serving]=mlops/triage [agent]=agent/agent [agent-ui]=ui/agent-ui [mlflow]=mlops/mlflow [pipelines]=mlops/dagster-webserver,dagster-daemon)

names=("$@")
[ ${#names[@]} -gt 0 ] || names=(mcp-filesystem mcp-rag mcp-triage agent agent-ui mlflow pipelines serving)

systemctl start docker
for n in "${names[@]}"; do
  [ -n "${DIR[$n]:-}" ] || { echo "unknown image: $n" >&2; exit 1; }
  img=local-ai/$n:dev
  echo "== $img"
  docker build -t "$img" "${DIR[$n]}"
  docker save "$img" | k3s ctr images import -
  ns=${DEPLOY[$n]%/*}
  # Restart only if already deployed; `make deploy` creates it otherwise. One image can back
  # several deployments (pipelines: webserver,daemon).
  deploys=${DEPLOY[$n]#*/}
  for d in ${deploys//,/ }; do
    if kubectl -n "$ns" get deploy "$d" >/dev/null 2>&1; then
      kubectl -n "$ns" rollout restart deploy "$d"
    fi
  done
done
docker image prune -f >/dev/null
