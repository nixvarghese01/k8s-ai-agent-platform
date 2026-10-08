#!/bin/bash
# Start the platform on demand instead of at every Ubuntu start (less heat, RAM and battery).
#  - k3s, ollama, docker, containerd: no longer enabled at boot; `platform.sh up` starts them
#  - docker.socket stays enabled, so the first `docker` command starts Docker by itself
#  - installs make for the repo Makefile
# Run as root inside Ubuntu:  wsl -d Ubuntu-26.04 -u root -- bash infra/scripts/host/05-on-demand-services.sh
# Undo: systemctl enable k3s ollama docker containerd
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

apt-get install -y -qq make >/dev/null
systemctl disable k3s ollama docker containerd
systemctl enable docker.socket
for s in k3s ollama docker docker.socket containerd; do
  printf "%-14s %s\n" "$s" "$(systemctl is-enabled $s)"
done
make --version | head -1
