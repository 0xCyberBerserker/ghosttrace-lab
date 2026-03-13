param(
    [string] $LocalRoot = "C:\ProgramData\AIReverseLab\x64dbg-bridge",
    [string] $SharedRoot = "",
    [int] $PollSeconds = 3
)

$ErrorActionPreference = "Stop"

function Ensure-Directory {
    param([string] $Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -ItemType Directory -Path $Path -Force | Out-Null
    }
}

function Resolve-SharedRoot {
    param([string] $RequestedPath)

    if ($RequestedPath) {
        return $RequestedPath
    }

    $candidates = @(
        (Join-Path $env:USERPROFILE "Desktop\shared\bridge"),
        "Z:\bridge"
    )

    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            return $candidate
        }
    }

    return $candidates[0]
}

function Sync-OutboxKind {
    param(
        [string] $LocalRoot,
        [string] $SharedRoot,
        [string] $JobId,
        [string] $Kind
    )

    $sourceDir = Join-Path $LocalRoot "outbox\$JobId\$Kind"
    if (-not (Test-Path -LiteralPath $sourceDir)) {
        return
    }

    $targetDir = Join-Path $SharedRoot "$JobId\incoming\$Kind"
    $processedDir = Join-Path $LocalRoot "processed\$JobId\$Kind"
    Ensure-Directory -Path $targetDir
    Ensure-Directory -Path $processedDir

    Get-ChildItem -LiteralPath $sourceDir -Filter *.json -File -ErrorAction SilentlyContinue | ForEach-Object {
        $destination = Join-Path $targetDir $_.Name
        Copy-Item -LiteralPath $_.FullName -Destination $destination -Force
        Move-Item -LiteralPath $_.FullName -Destination (Join-Path $processedDir $_.Name) -Force
    }
}

function Sync-RequestsInbox {
    param(
        [string] $LocalRoot,
        [string] $SharedRoot,
        [string] $JobId
    )

    $sharedPath = Join-Path $SharedRoot "$JobId\requests.pending.json"
    if (-not (Test-Path -LiteralPath $sharedPath)) {
        return
    }

    $inboxDir = Join-Path $LocalRoot "inbox\$JobId"
    Ensure-Directory -Path $inboxDir
    Copy-Item -LiteralPath $sharedPath -Destination (Join-Path $inboxDir "requests.pending.json") -Force
}

function Publish-BridgeHeartbeat {
    param(
        [string] $LocalRoot,
        [string] $JobId
    )

    $stateDir = Join-Path $LocalRoot "outbox\$JobId\state"
    Ensure-Directory -Path $stateDir

    $markerPath = Join-Path $stateDir ".bridge-online"
    if (Test-Path -LiteralPath $markerPath) {
        return
    }

    $payload = [pscustomobject]@{
        status = "bridge-online"
        transport = "mcp"
        notes = @("Guest bridge loop is running and mirroring requests.")
    }

    $fileName = "bridge-online-" + (Get-Date -Format "yyyyMMdd-HHmmssfff") + ".json"
    $payload | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $stateDir $fileName) -Encoding UTF8
    Set-Content -LiteralPath $markerPath -Value "published" -Encoding ASCII
}

Ensure-Directory -Path $LocalRoot
Ensure-Directory -Path (Join-Path $LocalRoot "outbox")
Ensure-Directory -Path (Join-Path $LocalRoot "processed")
Ensure-Directory -Path (Join-Path $LocalRoot "inbox")
$SharedRoot = Resolve-SharedRoot -RequestedPath $SharedRoot
Ensure-Directory -Path $SharedRoot

Write-Host "x64dbg bridge loop started. LocalRoot=$LocalRoot SharedRoot=$SharedRoot"

while ($true) {
    try {
        $outboxRoot = Join-Path $LocalRoot "outbox"
        if (Test-Path -LiteralPath $outboxRoot) {
            Get-ChildItem -LiteralPath $outboxRoot -Directory -ErrorAction SilentlyContinue | ForEach-Object {
                $jobId = $_.Name
                Sync-OutboxKind -LocalRoot $LocalRoot -SharedRoot $SharedRoot -JobId $jobId -Kind "state"
                Sync-OutboxKind -LocalRoot $LocalRoot -SharedRoot $SharedRoot -JobId $jobId -Kind "findings"
                Sync-RequestsInbox -LocalRoot $LocalRoot -SharedRoot $SharedRoot -JobId $jobId
            }
        }

        if (Test-Path -LiteralPath $SharedRoot) {
            Get-ChildItem -LiteralPath $SharedRoot -Directory -ErrorAction SilentlyContinue | ForEach-Object {
                $jobId = $_.Name
                $requestsSnapshot = Join-Path $_.FullName "requests.pending.json"
                if (Test-Path -LiteralPath $requestsSnapshot) {
                    Sync-RequestsInbox -LocalRoot $LocalRoot -SharedRoot $SharedRoot -JobId $jobId
                    Publish-BridgeHeartbeat -LocalRoot $LocalRoot -JobId $jobId
                    Sync-OutboxKind -LocalRoot $LocalRoot -SharedRoot $SharedRoot -JobId $jobId -Kind "state"
                }
            }
        }
    } catch {
        Write-Warning $_.Exception.Message
    }

    Start-Sleep -Seconds $PollSeconds
}
