param([switch]$Background)

$ErrorActionPreference = 'Stop'
$repoDir = $PSScriptRoot
$pythonExe = Join-Path $repoDir '.venv\Scripts\python.exe'
$runtimeDir = Join-Path $repoDir 'data\runtime'
if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw 'Create .venv and install requirements.txt first; see README.md.'
}
New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
$env:PYTHONUTF8 = '1'
$env:ANONYMIZED_TELEMETRY = 'False'
$env:OLLAMA_HOST = '127.0.0.1:11434'

# Winget installations may not be visible in the current terminal's PATH yet.
foreach ($ocrDir in @("$env:LOCALAPPDATA\Programs\Tesseract-OCR", "$env:ProgramFiles\Tesseract-OCR")) {
    if (Test-Path -LiteralPath (Join-Path $ocrDir 'tesseract.exe')) {
        $env:PATH = "$ocrDir;$env:PATH"
        break
    }
}
$ollamaCommand = Get-Command ollama.exe -ErrorAction SilentlyContinue
$ollamaExe = if ($ollamaCommand) { $ollamaCommand.Source } else { "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" }
if (-not (Test-Path -LiteralPath $ollamaExe)) {
    throw 'Install Ollama first; see README.md.'
}

try {
    $models = Invoke-RestMethod 'http://127.0.0.1:11434/api/tags' -TimeoutSec 3
} catch {
    Start-Process -FilePath $ollamaExe -ArgumentList 'serve' -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $runtimeDir 'ollama.stdout.log') `
        -RedirectStandardError (Join-Path $runtimeDir 'ollama.stderr.log') | Out-Null
    $models = $null
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Seconds 1
        try {
            $models = Invoke-RestMethod 'http://127.0.0.1:11434/api/tags' -TimeoutSec 2
            break
        } catch { }
    }
    if ($null -eq $models) { throw 'Ollama did not start. Check data/runtime/ollama.stderr.log.' }
}
foreach ($model in @('qwen3:8b', 'nomic-embed-text:latest')) {
    if ($model -notin @($models.models.name)) {
        throw "Missing model: $model. Run: & '$ollamaExe' pull $model"
    }
}

$mockReady = $false
try { $mockReady = (Invoke-RestMethod 'http://127.0.0.1:8502/health' -TimeoutSec 2).service -eq 'iep-synthetic-platform' } catch { }
if (-not $mockReady) {
    $mockProcess = Start-Process -FilePath $pythonExe -ArgumentList @('mock_platform.py', '--port', '8502') `
        -WorkingDirectory $repoDir -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $runtimeDir 'mock-platform.stdout.log') `
        -RedirectStandardError (Join-Path $runtimeDir 'mock-platform.stderr.log')
    $mockProcess.Id | Set-Content (Join-Path $runtimeDir 'mock-platform.pid')
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        Start-Sleep -Seconds 1
        if ($mockProcess.HasExited) { throw 'Mock platform exited. Check data/runtime/mock-platform.stderr.log.' }
        try { $mockReady = (Invoke-RestMethod 'http://127.0.0.1:8502/health' -TimeoutSec 2).service -eq 'iep-synthetic-platform' } catch { }
        if ($mockReady) { break }
    }
    if (-not $mockReady) { throw 'Mock platform did not become ready.' }
}

$streamlitArgs = @('-m', 'streamlit', 'run', 'app.py', '--server.address=127.0.0.1',
    '--server.port=8501', '--server.headless=true', '--browser.gatherUsageStats=false')
$serverReady = $false
try {
    $serverReady = (Invoke-RestMethod 'http://127.0.0.1:8501/_stcore/health' -TimeoutSec 2) -eq 'ok'
} catch { }
if ($serverReady) {
    Write-Host 'A Streamlit server is already running at http://127.0.0.1:8501.'
    return
}
if ($Background) {
    $appProcess = Start-Process -FilePath $pythonExe -ArgumentList $streamlitArgs `
        -WorkingDirectory $repoDir -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $runtimeDir 'streamlit.stdout.log') `
        -RedirectStandardError (Join-Path $runtimeDir 'streamlit.stderr.log')
    $appProcess.Id | Set-Content (Join-Path $runtimeDir 'streamlit.pid')
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Seconds 1
        if ($appProcess.HasExited) { throw 'Streamlit exited. Check data/runtime/streamlit.stderr.log.' }
        try {
            $serverReady = (Invoke-RestMethod 'http://127.0.0.1:8501/_stcore/health' -TimeoutSec 2) -eq 'ok'
        } catch { }
        if ($serverReady) { break }
    }
    if (-not $serverReady) { throw 'Streamlit did not become ready. Check data/runtime/streamlit.stderr.log.' }
    Write-Host "IEP Assistant is ready at http://127.0.0.1:8501 (PID $($appProcess.Id))."
} else {
    Push-Location $repoDir
    try { & $pythonExe @streamlitArgs } finally { Pop-Location }
}
