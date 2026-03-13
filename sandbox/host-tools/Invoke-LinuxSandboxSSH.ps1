param(
    [Parameter(Mandatory = $true)][string] $Command,
    [string] $HostName = "127.0.0.1",
    [int] $Port = 22,
    [Parameter(Mandatory = $true)][string] $UserName,
    [Parameter(Mandatory = $true)][string] $Password,
    [string] $PlinkPath = ""
)

$ErrorActionPreference = "Stop"

$params = @{
    Command = $Command
    HostName = $HostName
    Port = $Port
    UserName = $UserName
    Password = $Password
}

if ($PlinkPath) {
    $params.PlinkPath = $PlinkPath
}

& "$PSScriptRoot\Invoke-SandboxSSH.ps1" @params
