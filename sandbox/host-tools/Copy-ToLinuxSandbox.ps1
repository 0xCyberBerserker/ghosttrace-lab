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

$params = @{
    SourcePath = $SourcePath
    DestinationPath = $DestinationPath
    HostName = $HostName
    Port = $Port
    UserName = $UserName
    Password = $Password
}

if ($PscpPath) {
    $params.PscpPath = $PscpPath
}

if ($Recurse) {
    $params.Recurse = $true
}

& "$PSScriptRoot\Copy-ToSandbox.ps1" @params
