# Start the platform from the repo folder (PowerShell):  .\local-up  [-Docker]
# Starts Ollama + k3s, replaces the previous run's pods with fresh ones and waits until every
# pod is Ready. Same as `.\infra\scripts\platform.ps1 up` (README §6.6).
param([switch]$Docker)
& "$PSScriptRoot\infra\scripts\platform.ps1" up -Docker:$Docker
