# Start the platform from the repo folder (PowerShell):  .\local-up  [-Docker] [-Profile mlops,observability]
# Starts Ollama + k3s, replaces the previous run's pods with fresh ones and waits until every
# pod is Ready. -Profile picks the optional services (default: last time's; `core` = none).
# Same as `.\infra\scripts\platform.ps1 up` (README §6.6).
param([switch]$Docker, [string]$Profile)
& "$PSScriptRoot\infra\scripts\platform.ps1" up -Docker:$Docker -Profile $Profile
