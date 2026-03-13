param(
    [Parameter(Mandatory = $true)][string] $Command,
    [string] $HostName = "127.0.0.1",
    [int] $Port = 22,
    [Parameter(Mandatory = $true)][string] $UserName,
    [Parameter(Mandatory = $true)][string] $Password,
    [string] $PlinkPath = "",
    [switch] $PowerShell
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\SandboxSshCommon.ps1"

$plink = Resolve-PlinkPath -RequestedPath $PlinkPath
$hostKey = Get-HostKeyFingerprint -HostName $HostName -Port $Port
$remoteCommand = $Command

if ($PowerShell) {
    $bootstrap = @"
`$ProgressPreference = 'SilentlyContinue'
`$InformationPreference = 'SilentlyContinue'
$Command
"@
    $encodedCommand = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($bootstrap))
    $remoteCommand = "powershell.exe -NoProfile -EncodedCommand $encodedCommand"
}

& $plink -ssh -batch -no-antispoof -hostkey $hostKey -P $Port -l $UserName -pw $Password $HostName $remoteCommand
