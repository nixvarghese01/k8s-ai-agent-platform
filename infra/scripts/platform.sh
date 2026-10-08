#!/bin/bash
# Start/stop the platform's host services inside Ubuntu. Workloads themselves come from
# manifests (deploy.sh now, ArgoCD later); this script never deploys anything.
#
#   platform.sh up [--docker] [--profile mlops,observability]
#                               start Ollama + k3s (and Docker) with the core plus the given
#                               profiles (default: the ones active last time; profiles.sh),
#                               replace the old pods with fresh ones, wait until all are Ready
#   platform.sh profile <p1,p2|core>  switch profiles while running
#   platform.sh down            stop all pods cleanly, then k3s, Ollama and Docker
#   platform.sh status          run status.sh
#   platform.sh restart         down, then up
#
# Needs root for systemctl; re-runs itself with sudo when started as a normal user.
set -euo pipefail
[ "$EUID" -eq 0 ] || exec sudo -E bash "$0" "$@"

export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
HERE=$(cd "$(dirname "$0")" && pwd)
USER_NAME=${SUDO_USER:-$(id -un 1000)}

up() {
  local services="ollama k3s" profile=""
  while [ $# -gt 0 ]; do
    case "$1" in
      --docker) services="$services docker" ;;
      --profile) profile=${2:?--profile needs a list, e.g. mlops,observability or core}; shift ;;
    esac
    shift
  done
  echo "== starting: $services"
  systemctl start $services

  echo "== waiting for the k3s node"
  until kubectl get nodes >/dev/null 2>&1; do sleep 2; done
  kubectl wait --for=condition=Ready node --all --timeout=180s

  # Scale the optional services before replacing pods, so switched-off ones never start
  if [ -n "$profile" ]; then
    bash "$HERE/profiles.sh" set "$profile" >/dev/null
  fi
  bash "$HERE/profiles.sh" apply

  # k3s revives the previous run's pods, so RESTARTS and AGE pile up across every down/up.
  # Replace them instead: their Deployments create new pods (restarts 0). Data lives on
  # volumes and survives; completed one-shot pods (helm-install-*) are left alone.
  echo "== replacing pods from the previous run"
  kubectl delete pods -A --field-selector=status.phase!=Succeeded --grace-period=5 --wait=true

  echo "== waiting for pods"
  # Completed one-shot pods (e.g. helm-install-traefik) never become Ready, so skip them
  kubectl wait --for=condition=Ready pod -A --field-selector=status.phase!=Succeeded --timeout=600s
  kubectl get pods -A --no-headers | awk '{printf "  %-12s %-45s %s\n", $1, $2, $4}'

  echo
  echo "Platform is up. Sign in once at https://auth.ai.local (README §6.14):"
  echo "  Ollama API   http://localhost:11434"
  kubectl get ingress -A --no-headers -o custom-columns='NS:.metadata.namespace,HOST:.spec.rules[*].host' |
    awk '{printf "  %-12s https://%s\n", $1, $2}'
  echo "Optional services off? Their pages answer 503: .\\local-up -Profile mlops (or: make profile P=mlops)"
}

down() {
  echo "== stopping k3s and all pods"
  systemctl stop k3s || true
  # `systemctl stop k3s` leaves containers running; k3s-killall.sh stops them and
  # unmounts their volumes cleanly
  /usr/local/bin/k3s-killall.sh >/dev/null 2>&1 || true
  echo "== stopping ollama and docker"
  systemctl stop ollama || true
  systemctl stop docker docker.socket containerd 2>/dev/null || true
  systemctl start docker.socket # keep on-demand Docker available
  for s in k3s ollama docker; do printf "  %-7s %s\n" "$s" "$(systemctl is-active $s)"; done
}

cmd=${1:-}; shift || true
case "$cmd" in
  up) up "$@" ;;
  down) down ;;
  restart) down; up "$@" ;;
  profile) bash "$HERE/profiles.sh" set "${1:-core}" ;;
  status) exec sudo -u "$USER_NAME" env KUBECONFIG="/home/$USER_NAME/.kube/config" bash "$HERE/status.sh" ;;
  *) echo "usage: $0 {up [--docker] [--profile p1,p2|core] | profile p1,p2|core | down | restart | status}" >&2; exit 2 ;;
esac
