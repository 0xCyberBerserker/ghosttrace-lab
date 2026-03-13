param(
    [Parameter(Mandatory = $true)][string] $SourcePath,
    [Parameter(Mandatory = $true)][string] $DestinationPath,
    [string] $HostName = "127.0.0.1",
    [int] $Port = 22,
    [Parameter(Mandatory = $true)][string] $UserName,
    [Parameter(Mandatory = $true)][string] $Password,
    [string] $PscpPath = "",
    [switch] $Recurse
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\SandboxSshCommon.ps1"

$pscp = Resolve-PscpPath -RequestedPath $PscpPath
$hostKey = Get-HostKeyFingerprint -HostName $HostName -Port $Port
$source = (Resolve-Path -LiteralPath $SourcePath).Path
$target = "${UserName}@${HostName}:$DestinationPath"

$args = @(
    "-batch",
    "-hostkey", $hostKey,
    "-P", $Port,
    "-l", $UserName,
    "-pw", $Password
)

if ($Recurse) {
    $args += "-r"
}

$args += @($source, $target)
& $pscp @args
