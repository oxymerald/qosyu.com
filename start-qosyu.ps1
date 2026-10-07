$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
docker info --format '{{.ServerVersion}}' 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw 'Start Docker Desktop, wait until it is ready, then run this file again.'
}
docker compose up -d --build
if ($LASTEXITCODE -ne 0) { throw 'QOSYU startup failed. See the message above.' }
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    try {
        $mapping = docker compose port backend 8000
        $port = ($mapping.Trim() -split ':')[-1]
        $response = Invoke-RestMethod -Uri "http://localhost:$port/health" -TimeoutSec 2
        if ($response.status -eq 'ok') {
            Write-Host "QOSYU is ready: http://localhost:$port"
            exit 0
        }
    } catch { }
    Start-Sleep -Seconds 2
}
throw 'QOSYU did not become ready. Run: docker compose logs backend'
