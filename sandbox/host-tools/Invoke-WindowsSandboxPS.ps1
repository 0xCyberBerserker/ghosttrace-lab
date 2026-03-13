param(
    [Parameter(Mandatory = $true)][string] $Command,
    [string] $HostName = "127.0.0.1",
    [int] $Port = 2222,
    [string] $UserName = "Docker",
    [string] $Password = "admin",
    [string] $PlinkPath = ""
)

$ErrorActionPreference = "Stop"

$params = @{
    Command = $Command
    HostName = $HostName
    Port = $Port
    UserName = $UserName
    Password = $Password
    PowerShell = $true
}

if ($PlinkPath) {
    $params.PlinkPath = $PlinkPath
}

& "$PSScriptRoot\Invoke-SandboxSSH.ps1" @params
