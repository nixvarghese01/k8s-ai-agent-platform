# Capture the platform's web UIs into docs/screenshots/ for the README and issue evidence.
# Run from Windows with the platform up:  .\infra\scripts\screenshots.ps1 [-Only agent,qdrant]
#
# Drives headless Chrome (or Edge) over the DevTools protocol, so it waits until each page has
# really rendered (Streamlit fills its page over a websocket after load). The agent page asks a
# document question and opens the retrieved passages (5-20 s on CPU).
# Every UI is behind single sign-on (README section 6.14): the script captures the sign-in page, then
# signs in once with your platform login (asked for, or $env:LOCAL_AI_USER / LOCAL_AI_PASSWORD).
# Every app then opens signed in, with its data; Argo CD's "Log in via Authelia" is clicked.
# A full run (no -Only) into docs/screenshots replaces every image there.
#   -Out <folder>  write somewhere else, e.g. to check every UI without touching the repo's images
#   -Edge          use Microsoft Edge instead of Chrome
#
# Signing in yourself instead (the password never reaches the script):
#   -Open    opens a visible browser window (its own profile, your normal one is untouched) with
#            every UI in a tab; sign in once at auth.ai.local in it
#   -Attach  then captures every UI from that signed-in window, and leaves it open
param([string[]]$Only, [string]$Out, [switch]$Edge, [switch]$Open, [switch]$Attach)
$ErrorActionPreference = 'Stop'
if (-not ($Open -or $Attach)) {
    $user = if ($env:LOCAL_AI_USER) { $env:LOCAL_AI_USER } else { Read-Host 'Platform username' }
    $password = if ($env:LOCAL_AI_PASSWORD) { $env:LOCAL_AI_PASSWORD } else {
        [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR((Read-Host 'Password' -AsSecureString)))
    }
}
$repo = Resolve-Path "$PSScriptRoot\..\.."
$out = if ($Out) { $Out } else { "$repo\docs\screenshots" }
New-Item -ItemType Directory -Force $out | Out-Null
if (-not $Only -and -not $Open) { Get-ChildItem $out -Filter *.png | Remove-Item }  # a full run starts clean

$chrome = "$env:ProgramFiles\Google\Chrome\Application\chrome.exe"
$msedge = "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe"
$browser = @($(if ($Edge) { $msedge } else { $chrome }), $msedge) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $browser) { throw 'Chrome or Edge not found' }
"browser: $browser"

$question = 'What was decided in the meeting on 2026-10-01?'
$chatQuestion = 'In two sentences: what is retrieval-augmented generation?'
# name = url, JavaScript that is true once the page has rendered, seconds to wait for it,
#        then optionally: JavaScript to run (a click), what is true after it, and the page height
$text = 'document.body.innerText'
$pages = [ordered]@{
    auth     = @('https://auth.ai.local/', "!!document.querySelector('#password-textfield, #authenticated-view')", 30)  # first: signs in
    chat     = @('https://chat.ai.local/', "!!document.querySelector('#chat-input, textarea') && $text.includes('chat-default')", 90)
    agent    = @('https://agent.ai.local/', "!!document.querySelector('[data-testid=stChatInput] textarea') && $text.includes('Tools:')", 60)
    models   = @('https://agent.ai.local/models', "$text.includes('Model for each use case') && $text.includes('History')", 90, $null, $null, 1700)
    litellm  = @('https://llm.ai.local/', "!!document.querySelector('.swagger-ui .info')", 30)
    qdrant   = @('https://qdrant.ai.local/dashboard', "$text.includes('Collections') && $text.includes('docs')", 30)
    headlamp = @('https://headlamp.ai.local/c/local-ai/workloads', "$text.includes('Workloads') && document.querySelectorAll('table tbody tr').length > 3", 60)
    mlflow   = @('https://mlflow.ai.local/#/models/message-triage', "$text.includes('champion')", 60)
    dagster  = @('https://dagster.ai.local/assets/triage_model', "$text.includes('test_f1')", 60)
    s3       = @('https://s3.ai.local/', "/dashboard|buckets/i.test($text) && !document.querySelector('input[type=password]')", 30)
    triage   = @('https://triage.ai.local/', "$text.includes('classify')", 60)
    # Phoenix: open the agent project's trace list (its id comes from Phoenix's own API)
    phoenix  = @('https://phoenix.ai.local/projects', "$text.includes('agent') && $text.includes('litellm')", 60,
        "fetch('/v1/projects').then(r => r.json()).then(d => location.assign('/projects/' + d.data.find(p => p.name === 'agent').id))",
        "location.pathname.split('/').length > 2 && document.querySelectorAll('tbody tr').length > 3")
    grafana  = @('https://grafana.ai.local/d/platform-overview?orgId=1&kiosk', "$text.includes('Memory by namespace') && !$text.includes('Loading') && !$text.includes('Cancel') && document.querySelectorAll('canvas').length >= 6", 90)
    n8n      = @('https://n8n.ai.local/home/workflows', "$text.includes('Email triage') && $text.includes('Daily briefing')", 60)
    # Argo CD: "Log in via Authelia" goes straight through with the platform session
    argocd   = @('https://argocd.ai.local/applications/argocd/platform', "/log in via authelia/i.test($text) || $text.includes('Synced')", 60,
        "[...document.querySelectorAll('button, a')].find(b => /log in via authelia/i.test(b.innerText))?.click()",
        "/app health\s+healthy/i.test($text) && $text.includes('Synced')")
    actions  = @('https://github.com/nixvarghese01/k8s-ai-agent-platform/actions', "$text.includes('build')", 60)
}

# --- minimal DevTools protocol client (System.Net.WebSockets, works in Windows PowerShell 5.1)
$script:ws = $null; $script:msgId = 0
function Send-Cdp([string]$method, [hashtable]$params = @{}) {
    $script:msgId++
    $json = @{ id = $script:msgId; method = $method; params = $params } | ConvertTo-Json -Depth 10 -Compress
    $bytes = [Text.Encoding]::UTF8.GetBytes($json)
    $script:ws.SendAsync([ArraySegment[byte]]$bytes, 'Text', $true, [Threading.CancellationToken]::None).Wait()
    $buf = New-Object byte[] 1048576
    while ($true) {  # read messages until the reply to this id (events are skipped)
        $ms = New-Object IO.MemoryStream
        do {
            $r = $script:ws.ReceiveAsync([ArraySegment[byte]]$buf, [Threading.CancellationToken]::None).Result
            $ms.Write($buf, 0, $r.Count)
        } until ($r.EndOfMessage)
        $msg = [Text.Encoding]::UTF8.GetString($ms.ToArray()) | ConvertFrom-Json
        if ($msg.id -eq $script:msgId) {
            if ($msg.error) { throw "$method failed: $($msg.error.message)" }
            return $msg.result
        }
    }
}
function Test-Js([string]$expr) {
    $r = Send-Cdp 'Runtime.evaluate' @{ expression = "(() => { try { return !!($expr) } catch (e) { return false } })()"; returnByValue = $true }
    return [bool]$r.result.value
}
function Wait-Js([string]$expr, [int]$seconds) {
    $end = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $end) { if (Test-Js $expr) { return $true }; Start-Sleep -Milliseconds 500 }
    return $false
}

if ($Open -or $Attach) {
    # A visible window you sign in to; its profile is kept between -Open and -Attach
    $port = 9334
    $profileDir = Join-Path $env:TEMP 'local-ai-signin'
}
else {
    $port = 9333
    $profileDir = Join-Path $env:TEMP 'local-ai-screenshots'  # throwaway profile; your browser is untouched
}
if ($Open) {
    $urls = @($pages.Values | ForEach-Object { $_[0] } | Where-Object { $_ -notlike 'https://github.com/*' })
    Start-Process $browser -ArgumentList (@('--new-window', "--remote-debugging-port=$port", "--user-data-dir=`"$profileDir`"",
            '--no-first-run', '--no-default-browser-check') + $urls) | Out-Null
    "Opened $($urls.Count) tabs in a separate $([IO.Path]::GetFileNameWithoutExtension($browser)) window."
    'Sign in once at https://auth.ai.local in that window, then run:  .\infra\scripts\screenshots.ps1 -Attach'
    return
}
$proc = $null
if (-not $Attach) {
    # --ignore-certificate-errors: works before windows-trust-ca.ps1 too (throwaway profile only)
    $proc = Start-Process $browser -PassThru -WindowStyle Hidden -ArgumentList @('--headless=new', '--disable-gpu', '--ignore-certificate-errors',
        '--hide-scrollbars', "--remote-debugging-port=$port", "--user-data-dir=`"$profileDir`"", 'about:blank')
}
try {
    $target = $null
    for ($i = 0; $i -lt 40 -and -not $target; $i++) {
        try {
            $target = if ($Attach) {  # a tab of its own, so your tabs stay as they are
                Invoke-RestMethod -Method Put "http://127.0.0.1:$port/json/new?about:blank"
            }
            else { (Invoke-RestMethod "http://127.0.0.1:$port/json/list") | Where-Object type -eq 'page' | Select-Object -First 1 }
        }
        catch { Start-Sleep -Milliseconds 250 }
    }
    if (-not $target) { throw $(if ($Attach) { "no browser on port ${port}: run with -Open first and sign in" } else { 'browser did not start' }) }
    $script:ws = New-Object Net.WebSockets.ClientWebSocket
    $script:ws.ConnectAsync([Uri]$target.webSocketDebuggerUrl, [Threading.CancellationToken]::None).Wait()
    Send-Cdp 'Emulation.setDeviceMetricsOverride' @{ width = 1400; height = 900; deviceScaleFactor = 1; mobile = $false } | Out-Null

    foreach ($name in $pages.Keys) {
        if ($Only -and $name -notin $Only -and $name -ne 'auth') { continue }  # sign-in always runs
        $url, $ready, $wait, $action, $after, $height = $pages[$name]
        Send-Cdp 'Emulation.setDeviceMetricsOverride' @{ width = 1400; height = $(if ($height) { $height } else { 900 }); deviceScaleFactor = 1; mobile = $false } | Out-Null
        Send-Cdp 'Page.navigate' @{ url = $url } | Out-Null
        $ok = Wait-Js $ready $wait
        if ($ok -and $action -and -not (Test-Js $after)) {  # a click or a jump to the page with the data
            Send-Cdp 'Runtime.evaluate' @{ expression = $action } | Out-Null
            $ok = Wait-Js $after $wait
        }
        if (-not $ok) {
            $seen = (Send-Cdp 'Runtime.evaluate' @{ expression = "location.href + ' | ' + document.title + ' | ' + (document.body ? document.body.innerText.slice(0, 160) : '')"; returnByValue = $true }).result.value
            Write-Warning "$name did not render in $wait s: $url`n  the page shows: $seen"
            continue
        }

        if ($name -eq 'agent') {
            Send-Cdp 'Runtime.evaluate' @{ expression = "document.querySelector('[data-testid=stChatInput] textarea').focus()" } | Out-Null
            Send-Cdp 'Input.insertText' @{ text = $question } | Out-Null
            foreach ($t in 'keyDown', 'keyUp') {
                Send-Cdp 'Input.dispatchKeyEvent' @{ type = $t; key = 'Enter'; code = 'Enter'; windowsVirtualKeyCode = 13; text = "`r" } | Out-Null
            }
            # Done when the answer's "<n> s" caption shows; then open the first tool call
            $answered = Wait-Js "document.querySelectorAll('[data-testid=stChatMessage]').length >= 2 && /\d+(\.\d+)? s/.test(document.querySelectorAll('[data-testid=stChatMessage]')[1].innerText)" 300
            if (-not $answered) { Write-Warning 'agent did not answer in 300 s' }
            Send-Cdp 'Runtime.evaluate' @{ expression = "document.querySelector('[data-testid=stExpander] summary')?.click()" } | Out-Null
        }
        if ($name -eq 'chat') {
            # A short conversation, so the picture shows the local model answering
            Send-Cdp 'Runtime.evaluate' @{ expression = "document.querySelector('#chat-input, textarea').focus()" } | Out-Null
            Send-Cdp 'Input.insertText' @{ text = $chatQuestion } | Out-Null
            foreach ($t in 'keyDown', 'keyUp') {
                Send-Cdp 'Input.dispatchKeyEvent' @{ type = $t; key = 'Enter'; code = 'Enter'; windowsVirtualKeyCode = 13; text = "`r" } | Out-Null
            }
            # Done when Open WebUI shows the finished answer's buttons (Regenerate)
            if (-not (Wait-Js "!!document.querySelector('button[aria-label=Regenerate]')" 240)) { Write-Warning 'chat did not answer in 240 s' }
        }
        Start-Sleep -Seconds 2  # let animations settle
        if (-not $Only -or $name -in $Only) {
            $shot = Send-Cdp 'Page.captureScreenshot' @{ format = 'png' }
            [IO.File]::WriteAllBytes("$out\$name.png", [Convert]::FromBase64String($shot.data))
            "{0,-9} {1} ({2:N0} KB)" -f $name, $url, ((Get-Item "$out\$name.png").Length / 1KB)
        }

        if ($name -eq 'auth' -and -not $Attach) {
            # Sign in once; the session cookie on ai.local then opens every other page
            foreach ($f in @(@('username-textfield', $user), @('password-textfield', $password))) {
                Send-Cdp 'Runtime.evaluate' @{ expression = "document.getElementById('$($f[0])').focus()" } | Out-Null
                Send-Cdp 'Input.insertText' @{ text = $f[1] } | Out-Null
            }
            Send-Cdp 'Runtime.evaluate' @{ expression = "document.getElementById('sign-in-button').click()" } | Out-Null
            # Signed in: Authelia either shows its "authenticated" view or moves on to its default
            # page (chat.ai.local)
            if (-not (Wait-Js "location.host !== 'auth.ai.local' || !!document.getElementById('authenticated-view')" 20)) {
                $seen = (Send-Cdp 'Runtime.evaluate' @{ returnByValue = $true; expression = "location.href + ' | user field: ' + (document.getElementById('username-textfield')||{}).tagName + '/' + ((document.getElementById('username-textfield')||{}).value||'').length + ' chars, password: ' + ((document.getElementById('password-textfield')||{}).value||'').length + ' chars | ' + document.body.innerText.slice(0, 200)" }).result.value
                throw "sign-in failed (wrong username/password, or locked out after 5 tries: wait 10 min). Page: $seen"
            }
            "signed in as $user"
        }
    }
}
finally {
    if ($script:ws) { $script:ws.Dispose() }
    if ($Attach) {  # leave your window open; close only the tab used for the captures
        if ($target) { try { Invoke-RestMethod "http://127.0.0.1:$port/json/close/$($target.id)" | Out-Null } catch { $null = $_ } }
    }
    else {
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        Get-CimInstance Win32_Process -Filter "Name like '%chrome%' or Name like '%msedge%'" |
            Where-Object CommandLine -like "*local-ai-screenshots*" | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        Start-Sleep -Milliseconds 500
        Remove-Item -Recurse -Force $profileDir -ErrorAction SilentlyContinue
    }
}
