# PSScriptAnalyzer over every .ps1 in the repo (CI job "lint"; also runnable locally with pwsh)
$ErrorActionPreference = 'Stop'
if (-not (Get-Module -ListAvailable PSScriptAnalyzer)) {
    Set-PSRepository PSGallery -InstallationPolicy Trusted
    Install-Module PSScriptAnalyzer -Scope CurrentUser -Force
}
$findings = Invoke-ScriptAnalyzer -Path . -Recurse -Settings ./PSScriptAnalyzerSettings.psd1
if ($findings) {
    $findings | Format-Table RuleName, Severity, ScriptName, Line, Message -AutoSize -Wrap | Out-String -Width 220
    exit 1
}
'PSScriptAnalyzer: no findings'
