# Start/stop the whole platform from Windows (PowerShell, Git Bash via `powershell -File`, VS Code).
#
#   .\infra\scripts\platform.ps1 up [-Docker]     start Ollama + k3s (+ Docker), wait for pods
#   .\infra\scripts\platform.ps1 down [-KeepWsl]  stop everything, then shut Ubuntu down to free its RAM
#   .\infra\scripts\platform.ps1 status
#   .\infra\scripts\platform.ps1 restart [-Docker]
#
# `down` without -KeepWsl closes any open Ubuntu terminals too.
param(
    [Parameter(Mandatory, Position = 0)][ValidateSet('up', 'down', 'status', 'restart')][string]$Action,
    [switch]$Docker,
    [switch]$KeepWsl
)
$ErrorActionPreference = 'Stop'
$distro = 'Ubuntu-26.04'

# E:\Github\local-ai-platform\infra\scripts -> /mnt/e/Github/local-ai-platform/infra/scripts
$drive = $PSScriptRoot.Substring(0, 1).ToLower()
$here = "/mnt/$drive" + ($PSScriptRoot.Substring(2) -replace '\\', '/')

function Invoke-Platform([string[]]$ArgList) {
    wsl -d $distro -u root -- bash "$here/platform.sh" @ArgList
    if ($LASTEXITCODE -ne 0) { throw "platform.sh $($ArgList -join ' ') failed ($LASTEXITCODE)" }
}

$extra = @(); if ($Docker) { $extra += '--docker' }

switch ($Action) {
    'up' { Invoke-Platform (@('up') + $extra) }
    'restart' { Invoke-Platform (@('restart') + $extra) }
    'status' { wsl -d $distro -- bash "$here/status.sh" }
    'down' {
        Invoke-Platform @('down')
        if (-not $KeepWsl) {
            wsl --terminate $distro | Out-Null
            "Ubuntu stopped; its memory is released."
        }
    }
}
