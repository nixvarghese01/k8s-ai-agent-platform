# README §6.14: make Windows (and so Chrome and Edge) trust the platform's local CA, so the
# *.ai.local sites open with a normal padlock. Run in PowerShell from the repo folder, after
# 06-local-tls.sh. No admin needed: it goes into YOUR user's trusted roots, and Windows asks
# you to confirm once. Firefox keeps its own store; import the same file there if you use it.
# Undo: run again with -Remove
param([switch]$Remove)
$ErrorActionPreference = 'Stop'
$distro = 'Ubuntu-26.04'
$file = Join-Path $env:TEMP 'local-ai-platform-ca.crt'

wsl -d $distro -u root -- cat /var/lib/local-ai-ca/ca.crt | Set-Content -Path $file -Encoding ascii
if ($LASTEXITCODE -ne 0) { throw 'CA not found: run infra/scripts/host/06-local-tls.sh first' }
$ca = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2 $file

$existing = Get-ChildItem Cert:\CurrentUser\Root | Where-Object Thumbprint -eq $ca.Thumbprint
if ($Remove) {
    $existing | Remove-Item
    "Removed $($ca.Subject) from your trusted roots."
} elseif ($existing) {
    "Already trusted: $($ca.Subject) (expires $($ca.NotAfter.ToString('yyyy-MM-dd')))"
} else {
    Import-Certificate -FilePath $file -CertStoreLocation Cert:\CurrentUser\Root | Out-Null
    "Trusted: $($ca.Subject) (expires $($ca.NotAfter.ToString('yyyy-MM-dd'))). Restart the browser if it was open."
}
Remove-Item $file
