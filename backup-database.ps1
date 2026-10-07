$ErrorActionPreference = 'Stop'
Push-Location -LiteralPath $PSScriptRoot
try {
    $backupDir = Join-Path $PSScriptRoot 'backups'
    New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
    $containerPath = "/tmp/qosyu-$stamp.dump"
    $destination = Join-Path $backupDir "qosyu-$stamp.dump"
    $ready = $false
    for ($attempt = 0; $attempt -lt 10; $attempt++) {
        docker compose exec -T db sh -c 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' *> $null
        if ($LASTEXITCODE -eq 0) { $ready = $true; break }
        Start-Sleep -Seconds 2
    }
    if (-not $ready) { throw 'Database is not ready. Start QOSYU and try again.' }
    docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f "$1"' -- $containerPath
    if ($LASTEXITCODE -ne 0) { throw 'Database backup failed.' }
    docker compose exec -T db pg_restore --list $containerPath | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Backup archive could not be read.' }
    docker compose cp "db:$containerPath" $destination
    if ($LASTEXITCODE -ne 0) { throw 'Could not save backup to the laptop.' }
    docker compose exec -T db rm -- $containerPath
    Write-Output "Database backup saved: $destination"
    Write-Output 'Keep this file private. API keys remain in your separate local .env file.'
} finally { Pop-Location }
