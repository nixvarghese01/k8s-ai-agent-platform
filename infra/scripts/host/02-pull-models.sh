#!/bin/bash
# README §6.3: pull the chat and embedding models (~2.3 GB). Safe to re-run.
# Run as your user inside Ubuntu:  bash infra/scripts/host/02-pull-models.sh [extra models...]
#   e.g. ... 02-pull-models.sh qwen3:4b   (then switch to it: model.sh use qwen3:4b, §6.9)
set -euo pipefail
for m in qwen2.5:3b nomic-embed-text "$@"; do
  echo "\$ ollama pull $m"
  ollama pull "$m"
done
ollama list
