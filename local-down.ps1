# Stop the platform from the repo folder (PowerShell):  .\local-down  [-KeepWsl]
# Stops all pods, k3s, Ollama and Docker, then shuts Ubuntu down to free its RAM (skip that
# with -KeepWsl). Same as `.\infra\scripts\platform.ps1 down` (README §6.6).
param([switch]$KeepWsl)
& "$PSScriptRoot\infra\scripts\platform.ps1" down -KeepWsl:$KeepWsl
