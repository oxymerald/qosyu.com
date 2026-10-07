param([switch]$NoRestart)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
Write-Host 'QOSYU: Google AI Studio / Gemini setup'
Write-Host 'Paste the API key below. Input is hidden and is not written to command history.'
$secretInput = Read-Host 'Gemini API key' -AsSecureString
$keyPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secretInput)
try {
    $geminiKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($keyPointer).Trim()
    if ($geminiKey -notmatch '^[A-Za-z0-9_-]{20,200}$') { throw 'The key format is invalid. Nothing was changed.' }
    $configPath = Join-Path $PSScriptRoot '.env'
    if (-not (Test-Path -LiteralPath $configPath)) { throw 'Project .env was not found. Configure the local database first.' }
    $lines = [IO.File]::ReadAllLines($configPath)
    $kept = @($lines | Where-Object { $_ -notmatch '^\s*(GEMINI_API_KEY|GEMINI_MODEL|AI_PROVIDER)\s*=' })
    $kept += 'AI_PROVIDER=gemini'
    $kept += 'GEMINI_MODEL=gemini-3.5-flash-lite'
    $kept += ('GEMINI_API_KEY=' + $geminiKey)
    [IO.File]::WriteAllLines($configPath, $kept, [Text.UTF8Encoding]::new($false))
    Write-Host 'Key saved locally. No model request was sent.'
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($keyPointer)
    $geminiKey = $null
    $secretInput.Dispose()
}
if (-not $NoRestart) {
    docker compose up -d backend
    if ($LASTEXITCODE -ne 0) { throw 'Could not restart QOSYU. Start Docker Desktop and run start-qosyu.ps1.' }
    Write-Host 'Reopen the AI assistant at http://localhost:8080. Questions may consume your Gemini quota.'
}
