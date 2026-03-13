param(
    [Parameter(Mandatory = $true)][string] $JobId,
    [string] $LocalRoot = "C:\ProgramData\AIReverseLab\x64dbg-bridge"
)

$ErrorActionPreference = "Stop"

$path = Join-Path $LocalRoot "inbox\$JobId\requests.pending.json"
if (-not (Test-Path -LiteralPath $path)) {
    throw "No mirrored requests file found for $JobId at $path"
}

Get-Content -LiteralPath $path -Raw
