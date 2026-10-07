#!/bin/bash
# Install or update ArgoCD and the platform Application (README §7), then switch on the gitops
# profile so it runs. Run inside Ubuntu from the repo root:  bash infra/argocd/install.sh
# (or `make argocd`). ArgoCD then deploys every commit on development within ~3 minutes.
set -euo pipefail
export KUBECONFIG=${KUBECONFIG:-$([ "$EUID" -eq 0 ] && echo /etc/rancher/k3s/k3s.yaml || echo ~/.kube/config)}
cd "$(dirname "$0")/../.."

# CRDs first: the Application in the same kustomization needs them to exist
kubectl apply -k infra/argocd 2>&1 | grep -v -E "unchanged$" || true
kubectl wait --for=condition=Established crd/applications.argoproj.io --timeout=60s >/dev/null
kubectl apply -k infra/argocd 2>&1 | grep -v -E "unchanged$" || true

active=$(kubectl -n kube-system get configmap platform-profiles -o jsonpath='{.data.active}' 2>/dev/null || true)
case ",$active," in
  *,gitops,*) ;;
  *) bash infra/scripts/profiles.sh set "${active:+$active,}gitops" ;;
esac
for w in deploy/argocd-server deploy/argocd-repo-server deploy/argocd-redis statefulset/argocd-application-controller; do
  kubectl -n argocd rollout status "$w" --timeout=5m
done

echo
echo "ArgoCD: https://argocd.ai.local  (user admin, password: make argocd-password)"
kubectl -n argocd get application platform -o jsonpath='platform: sync {.status.sync.status}, health {.status.health.status}{"\n"}' 2>/dev/null || true
