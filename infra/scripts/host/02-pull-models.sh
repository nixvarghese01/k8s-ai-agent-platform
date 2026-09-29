#!/bin/bash
# README §6.3: pull the chat and embedding models (~2.3 GB). Safe to re-run.
# Run as your user inside Ubuntu:  bash infra/scripts/host/02-pull-models.sh
set -euo pipefail
for m in llama3.2:3b nomic-embed-text; do
  echo "\$ ollama pull $m"
  ollama pull "$m"
done
ollama list
