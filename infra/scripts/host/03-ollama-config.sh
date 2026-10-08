#!/bin/bash
# Ollama systemd override (README §6.3 and §12). Safe to re-run.
#  - OLLAMA_HOST=0.0.0.0  so k3s pods can reach it at http://<node-hostname>:11434
#  - OLLAMA_NUM_PARALLEL=1 one request at a time (less heat, less RAM)
#  - OLLAMA_MAX_LOADED_MODELS=2  at most 2 models in RAM (a chat model + the embedding model;
#                         different models per use case swap instead of piling up, README §6.9)
#  - CPUQuota=400%        hard cap of 4 cores' worth of CPU
# Run as root inside Ubuntu:  wsl -d Ubuntu-26.04 -u root -- bash infra/scripts/host/03-ollama-config.sh
# Undo: rm /etc/systemd/system/ollama.service.d/override.conf && systemctl daemon-reload && systemctl restart ollama
set -euo pipefail
mkdir -p /etc/systemd/system/ollama.service.d
cat > /etc/systemd/system/ollama.service.d/override.conf <<'EOF'
[Service]
Environment="OLLAMA_HOST=0.0.0.0:11434"
# Thermal (README §12): one request at a time, and at most 4 cores' worth of CPU
Environment="OLLAMA_NUM_PARALLEL=1"
# RAM (README §6.9): at most two models loaded at once
Environment="OLLAMA_MAX_LOADED_MODELS=2"
CPUQuota=400%
EOF
systemctl daemon-reload
systemctl restart ollama
sleep 2
systemctl show ollama -p CPUQuotaPerSecUSec
curl -s http://127.0.0.1:11434/api/version; echo
