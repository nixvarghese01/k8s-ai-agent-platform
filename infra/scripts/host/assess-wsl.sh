#!/bin/bash
# Read-only facts about the WSL distro, one "key=value" per line. Called by 00-assess.ps1.
export KUBECONFIG=${KUBECONFIG:-~/.kube/config}
. /etc/os-release
echo "os=$PRETTY_NAME"
echo "kernel=$(uname -r)"
echo "init=$(ps -p 1 -o comm=)"
echo "cpus=$(nproc)"
echo "mem_gib=$(free -g | awk '/^Mem:/{print $2}')"
echo "swap_gib=$(free -g | awk '/^Swap:/{print $2}')"
echo "disk_used=$(df -h / | awk 'NR==2{print $3}')"
echo "disk_size=$(df -h / | awk 'NR==2{print $2}')"
echo "user=$(id -un)"
echo "sudo_group=$(id -nG | grep -qw sudo && echo yes || echo no)"
v() { command -v "$1" >/dev/null && "$@" 2>/dev/null | head -1 || echo missing; }
echo "tool_git=$(v git --version)"
echo "tool_curl=$(v curl --version | awk '{print $1, $2}')"
echo "tool_zstd=$(command -v zstd >/dev/null && zstd --version | grep -o 'v[0-9.]*' || echo missing)"
echo "tool_make=$(v make --version)"
echo "tool_k3s=$(v k3s --version)"
echo "tool_helm=$(v helm version --short)"
echo "tool_ollama=$(v ollama --version)"
echo "tool_docker=$(command -v docker >/dev/null && docker --version 2>/dev/null || echo missing)"
for s in k3s ollama docker; do
  echo "svc_$s=$(systemctl is-active $s 2>/dev/null) / $(systemctl is-enabled $s 2>/dev/null)"
done
echo "kubeconfig=$([ -r "${KUBECONFIG/#\~/$HOME}" ] && echo present || echo missing)"
if command -v ollama >/dev/null && curl -s -m 3 http://127.0.0.1:11434/api/version >/dev/null; then
  echo "models=$(ollama list 2>/dev/null | awk 'NR>1{printf "%s ", $1}')"
else
  echo "models=(ollama not running)"
fi
if kubectl get nodes >/dev/null 2>&1; then
  echo "node=$(kubectl get nodes --no-headers | awk '{print $1, $2, $5}')"
  echo "pods=$(kubectl get pods -A --no-headers 2>/dev/null | awk '$4=="Running"{r++} $4!="Running" && $4!="Completed"{b++} END{printf "%d running, %d not ready", r, b}')"
else
  echo "node=(k3s not running)"
fi
