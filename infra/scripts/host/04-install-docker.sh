#!/bin/bash
# Docker Engine + Compose + Buildx from Docker's apt repo (docs.docker.com/engine/install/ubuntu).
# Docker is for building images and docker-compose dev; k3s keeps its own containerd.
# Run as root inside Ubuntu:  wsl -d Ubuntu-26.04 -u root -- bash infra/scripts/host/04-install-docker.sh
set -euxo pipefail
export DEBIAN_FRONTEND=noninteractive
USER_NAME=${USER_NAME:-$(id -un 1000)} # WSL default user (first account created)

apt-get update
apt-get install -y ca-certificates curl
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $VERSION_CODENAME stable" > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
usermod -aG docker "$USER_NAME" # takes effect in new shells
systemctl enable --now docker
docker run --rm hello-world | head -3
