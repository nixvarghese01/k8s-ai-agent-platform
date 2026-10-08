# PSScriptAnalyzer settings for CI (.github/workflows/ci.yml) and local runs:
#   Invoke-ScriptAnalyzer -Path . -Recurse -Settings ./PSScriptAnalyzerSettings.psd1
@{
    Severity     = @('Error', 'Warning')
    ExcludeRules = @(
        'PSUseSingularNouns'  # Get-Pages-style helpers in scripts, not a published module
    )
}
