#!/bin/bash
# Build the platform's own images locally and run them in k3s, to try a change before pushing.
# CI builds the real ones (GHCR, pinned by digest in the manifests, deployed by ArgoCD); this
# script imports local-ai/<name>:dev into k3s and points the deployments at it. ArgoCD doesn't
# self-heal, so the local image stays until the next commit that touches that manifest (or
# `kubectl apply -f` of it) brings the GHCR image back.
# Run inside Ubuntu from the repo root:  bash infra/scripts/build-images.sh [name ...]
#   names: mcp-filesystem mcp-rag mcp-triage mcp-memory mcp-calendar mcp-web agent agent-ui mlflow pipelines serving voice (default: all)
# Needs root for `k3s ctr`; re-runs itself with sudo when started as a normal user.
set -euo pipefail
[ "$EUID" -eq 0 ] || exec sudo -E bash "$0" "$@"
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
cd "$(dirname "$0")/../.."

# image name -> build folder, namespace/deployment
declare -A DIR=([mcp-filesystem]=mcp-servers/filesystem [mcp-rag]=mcp-servers/rag [mcp-triage]=mcp-servers/triage [mcp-memory]=mcp-servers/memory [mcp-calendar]=mcp-servers/calendar [mcp-web]=mcp-servers/web [serving]=serving [agent]=agent [agent-ui]=ui [mlflow]=mlops/mlflow [pipelines]=pipelines [voice]=voice)
# shellcheck disable=SC2054  # the comma joins two deployments of one image, by design
declare -A DEPLOY=([mcp-filesystem]=agent/mcp-filesystem [mcp-rag]=agent/mcp-rag [mcp-triage]=agent/mcp-triage [mcp-memory]=agent/mcp-memory [mcp-calendar]=agent/mcp-calendar [mcp-web]=agent/mcp-web [serving]=mlops/triage [agent]=agent/agent [agent-ui]=ui/agent-ui [mlflow]=mlops/mlflow [pipelines]=mlops/dagster-webserver,dagster-daemon [voice]=voice/voice)

names=("$@")
[ ${#names[@]} -gt 0 ] || names=(mcp-filesystem mcp-rag mcp-triage mcp-memory mcp-calendar mcp-web agent agent-ui mlflow pipelines serving voice)

systemctl start docker
# mlflow, pipelines and serving build FROM local-ai/ml-base (shared layers); build it first
for n in "${names[@]}"; do
  case "$n" in mlflow|pipelines|serving)
    echo "== local-ai/ml-base:dev"; docker build -t local-ai/ml-base:dev images/ml-base; break ;;
  esac
done
for n in "${names[@]}"; do
  [ -n "${DIR[$n]:-}" ] || { echo "unknown image: $n" >&2; exit 1; }
  img=local-ai/$n:dev
  echo "== $img"
  docker build -t "$img" "${DIR[$n]}"
  docker save "$img" | k3s ctr images import -
  ns=${DEPLOY[$n]%/*}
  # Point the deployments at the local image (if deployed). One image can back several
  # deployments (pipelines: webserver,daemon).
  deploys=${DEPLOY[$n]#*/}
  for d in ${deploys//,/ }; do
    if kubectl -n "$ns" get deploy "$d" >/dev/null 2>&1; then
      kubectl -n "$ns" set image deploy "$d" "*=docker.io/$img" >/dev/null
      kubectl -n "$ns" rollout restart deploy "$d"
    fi
  done
done
docker image prune -f >/dev/null
