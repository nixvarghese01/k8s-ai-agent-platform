#!/bin/bash
# Start/stop the platform's host services inside Ubuntu. Workloads themselves come from
# manifests (deploy.sh now, ArgoCD later); this script never deploys anything.
#
#   platform.sh up [--docker]   start Ollama + k3s (and Docker), wait until every pod is Ready
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
  local services="ollama k3s"
  [ "${1:-}" = "--docker" ] && services="$services docker"
  echo "== starting: $services"
  systemctl start $services

  echo "== waiting for the k3s node"
  until kubectl get nodes >/dev/null 2>&1; do sleep 2; done
  kubectl wait --for=condition=Ready node --all --timeout=180s

  echo "== waiting for pods"
  # Completed one-shot pods (e.g. helm-install-traefik) never become Ready, so skip them
  kubectl wait --for=condition=Ready pod -A --field-selector=status.phase!=Succeeded --timeout=600s
  kubectl get pods -A --no-headers | awk '{printf "  %-12s %-45s %s\n", $1, $2, $4}'

  echo
  echo "Platform is up (URLs need the hosts-file entries from README §6.7):"
  echo "  Ollama API   http://localhost:11434"
  kubectl get ingress -A --no-headers -o custom-columns='NS:.metadata.namespace,HOST:.spec.rules[*].host' |
    awk '{printf "  %-12s http://%s\n", $1, $2}'
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

case "${1:-}" in
  up) up "${2:-}" ;;
  down) down ;;
  restart) down; up "${2:-}" ;;
  status) exec sudo -u "$USER_NAME" env KUBECONFIG="/home/$USER_NAME/.kube/config" bash "$HERE/status.sh" ;;
  *) echo "usage: $0 {up [--docker]|down|restart|status}" >&2; exit 2 ;;
esac
