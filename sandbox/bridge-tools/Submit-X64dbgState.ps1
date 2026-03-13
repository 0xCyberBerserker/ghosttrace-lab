param(
    [Parameter(Mandatory = $true)][string] $JobId,
    [Parameter(Mandatory = $true)][string] $Status,
    [int] $Pid,
    [string] $TargetModule,
    [string[]] $Notes = @(),
    [string] $Transport = "mcp",
    [string] $LocalRoot = "C:\ProgramData\AIReverseLab\x64dbg-bridge"
)

$ErrorActionPreference = "Stop"

function Ensure-Directory {
    param([string] $Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -ItemType Directory -Path $Path -Force | Out-Null
    }
}

$outDir = Join-Path $LocalRoot "outbox\$JobId\state"
Ensure-Directory -Path $outDir

$payload = [pscustomobject]@{
    status = $Status
    pid = if ($PSBoundParameters.ContainsKey("Pid")) { $Pid } else { $null }
    target_module = $TargetModule
    transport = $Transport
    notes = @($Notes)
}

$fileName = "state-" + (Get-Date -Format "yyyyMMdd-HHmmssfff") + ".json"
$payload | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $outDir $fileName) -Encoding UTF8
Write-Host "Queued x64dbg state payload for $JobId"
