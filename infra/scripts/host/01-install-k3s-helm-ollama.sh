#!/bin/bash
# README §6.2: base packages, k3s, kubeconfig, Helm, Ollama. Safe to re-run.
# Run as root inside Ubuntu:  wsl -d Ubuntu-26.04 -u root -- bash infra/scripts/host/01-install-k3s-helm-ollama.sh
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
USER_NAME=${USER_NAME:-$(id -un 1000)} # WSL default user (first account created)

echo "== base packages"
apt-get update -qq
apt-get install -y -qq curl git ca-certificates zstd >/dev/null # zstd: needed by the Ollama installer

echo "== k3s"
if ! command -v k3s >/dev/null; then
  curl -sfL https://get.k3s.io | sh -
fi
systemctl is-active k3s

echo "== kubeconfig for $USER_NAME"
install -d -o "$USER_NAME" -g "$USER_NAME" "/home/$USER_NAME/.kube"
install -m 600 -o "$USER_NAME" -g "$USER_NAME" /etc/rancher/k3s/k3s.yaml "/home/$USER_NAME/.kube/config"
grep -q 'KUBECONFIG=' "/home/$USER_NAME/.bashrc" || echo 'export KUBECONFIG=~/.kube/config' >> "/home/$USER_NAME/.bashrc"

echo "== helm"
if ! command -v helm >/dev/null; then
  curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
fi
helm version --short

echo "== ollama"
if ! command -v ollama >/dev/null; then
  curl -fsSL https://ollama.com/install.sh | sh
fi
systemctl is-active ollama
