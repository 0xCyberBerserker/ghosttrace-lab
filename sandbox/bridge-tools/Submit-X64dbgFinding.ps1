param(
    [Parameter(Mandatory = $true)][string] $JobId,
    [Parameter(Mandatory = $true)][string] $Type,
    [Parameter(Mandatory = $true)][string] $Summary,
    [string] $Address,
    [string] $Evidence,
    [string] $LocalRoot = "C:\ProgramData\AIReverseLab\x64dbg-bridge"
)

$ErrorActionPreference = "Stop"

function Ensure-Directory {
    param([string] $Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -ItemType Directory -Path $Path -Force | Out-Null
    }
}

$outDir = Join-Path $LocalRoot "outbox\$JobId\findings"
Ensure-Directory -Path $outDir

$payload = [pscustomobject]@{
    findings = @(
        [pscustomobject]@{
            type = $Type
            summary = $Summary
            address = $Address
            evidence = $Evidence
        }
    )
}

$fileName = "finding-" + (Get-Date -Format "yyyyMMdd-HHmmssfff") + ".json"
$payload | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $outDir $fileName) -Encoding UTF8
Write-Host "Queued x64dbg finding payload for $JobId"
