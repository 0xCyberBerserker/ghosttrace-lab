$ErrorActionPreference = "Stop"

$stateRoot = "C:\ProgramData\AIReverseLab"
$toolsRoot = "C:\Tools\ReverseLab"
$downloadRoot = Join-Path $stateRoot "downloads"
$logRoot = "C:\OEM\logs"
$markerPath = Join-Path $stateRoot "full-lab-installed.json"
$manifestPath = Join-Path $stateRoot "full-lab-manifest.json"
$failurePath = Join-Path $stateRoot "full-lab-failed.json"
$notesPath = Join-Path $toolsRoot "README.txt"
$desktopPath = [Environment]::GetFolderPath("Desktop")
$startupPath = [Environment]::GetFolderPath("CommonStartup")
$taskName = "AIReverseLabFullLab"
$toolManifestPath = "C:\OEM\tool-manifest.json"
$bridgeBootstrapPath = Join-Path $stateRoot "Start-X64dbgBridge-Autostart.ps1"
$bridgeLauncherPath = Join-Path $startupPath "Start-X64dbgBridge.cmd"
$results = [System.Collections.Generic.List[object]]::new()

function Ensure-Directory {
    param([string] $Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -ItemType Directory -Path $Path -Force | Out-Null
    }
}

function Write-Log {
    param([string] $Message)

    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Write-Host "[$timestamp] $Message"
}

function Add-Result {
    param(
        [string] $Tool,
        [string] $Status,
        [string] $InstallPath,
        [string] $Source,
        [string] $Details
    )

    $results.Add([pscustomobject]@{
        tool = $Tool
        status = $Status
        install_path = $InstallPath
        source = $Source
        details = $Details
    })
}

function Wait-ForInternet {
    param([int] $MaxAttempts = 24)

    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        try {
            Invoke-WebRequest -UseBasicParsing -Uri "https://www.microsoft.com" -TimeoutSec 15 | Out-Null
            Write-Log "Internet connectivity confirmed."
            return
        } catch {
            Write-Log "Waiting for network ($attempt/$MaxAttempts)..."
            Start-Sleep -Seconds 10
        }
    }

    throw "Network did not become available in time."
}

function Set-UnrestrictedExecutionPolicy {
    Write-Log "Setting PowerShell execution policy to Unrestricted at LocalMachine scope."
    try {
        Set-ExecutionPolicy -ExecutionPolicy Unrestricted -Scope LocalMachine -Force -ErrorAction Stop
        Add-Result -Tool "powershell execution policy" -Status "configured" -InstallPath "LocalMachine" -Source "bootstrap" -Details "Set to Unrestricted for the sandbox lab."
    } catch {
        $message = $_.Exception.Message
        $effectivePolicy = $null
        try {
            $effectivePolicy = (Get-ExecutionPolicy).ToString()
        } catch {
            $effectivePolicy = "unknown"
        }

        Write-Log "Execution policy update raised an exception; continuing because the bootstrap already runs with Bypass. Effective policy: $effectivePolicy"
        Add-Result -Tool "powershell execution policy" -Status "warning" -InstallPath "LocalMachine" -Source "bootstrap" -Details ($message + " | Effective policy: " + $effectivePolicy)
    }
}

function Install-OpenSSHServer {
    Write-Log "Installing and enabling OpenSSH Server."

    $capability = Get-WindowsCapability -Online | Where-Object { $_.Name -like "OpenSSH.Server*" } | Select-Object -First 1
    if (-not $capability) {
        throw "Could not locate the OpenSSH.Server Windows capability."
    }

    if ($capability.State -ne "Installed") {
        Add-WindowsCapability -Online -Name $capability.Name | Out-Null
        Write-Log "OpenSSH Server capability installed."
    } else {
        Write-Log "OpenSSH Server capability already installed."
    }

    $service = Get-Service -Name sshd -ErrorAction SilentlyContinue
    if (-not $service) {
        throw "OpenSSH Server service 'sshd' is not available after capability installation."
    }

    Set-Service -Name sshd -StartupType Automatic
    if ($service.Status -ne "Running") {
        Start-Service -Name sshd
    }

    $agentService = Get-Service -Name ssh-agent -ErrorAction SilentlyContinue
    if ($agentService) {
        Set-Service -Name ssh-agent -StartupType Manual
    }

    $firewallRule = Get-NetFirewallRule -Name "OpenSSH-Server-In-TCP" -ErrorAction SilentlyContinue
    if (-not $firewallRule) {
        New-NetFirewallRule -Name "OpenSSH-Server-In-TCP" -DisplayName "OpenSSH Server (sshd)" -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22 | Out-Null
    } else {
        Enable-NetFirewallRule -Name "OpenSSH-Server-In-TCP" | Out-Null
    }

    $sshdConfigPath = "C:\ProgramData\ssh\sshd_config"
    if (Test-Path -LiteralPath $sshdConfigPath) {
        $sshdConfig = Get-Content -LiteralPath $sshdConfigPath -Raw
        if ($sshdConfig -notmatch "(?m)^\s*PasswordAuthentication\s+yes\s*$") {
            $updatedConfig = if ($sshdConfig -match "(?m)^\s*#?\s*PasswordAuthentication\s+\w+\s*$") {
                [regex]::Replace($sshdConfig, "(?m)^\s*#?\s*PasswordAuthentication\s+\w+\s*$", "PasswordAuthentication yes")
            } else {
                $sshdConfig.TrimEnd() + "`r`nPasswordAuthentication yes`r`n"
            }
            Set-Content -LiteralPath $sshdConfigPath -Value $updatedConfig -Encoding ASCII
            Restart-Service -Name sshd -Force
        }
    }

    Add-Result -Tool "OpenSSH Server" -Status "installed" -InstallPath "C:\Windows\System32\OpenSSH" -Source "bootstrap" -Details "Enabled sshd on port 22 with automatic startup and inbound firewall rule."
}

function Invoke-DownloadFile {
    param(
        [Parameter(Mandatory = $true)][string] $Url,
        [Parameter(Mandatory = $true)][string] $Destination,
        [int] $MaxAttempts = 4
    )

    Ensure-Directory -Path (Split-Path -Parent $Destination)
    $isZip = [System.IO.Path]::GetExtension($Destination).Equals(".zip", [System.StringComparison]::OrdinalIgnoreCase)

    if (Test-Path -LiteralPath $Destination) {
        $existingFile = Get-Item -LiteralPath $Destination -ErrorAction SilentlyContinue
        if ($existingFile -and $existingFile.Length -gt 0) {
            if ($isZip -and -not (Test-ZipArchive -Path $Destination)) {
                Write-Log "Discarding invalid cached archive $Destination."
                Remove-Item -LiteralPath $Destination -Force -ErrorAction SilentlyContinue
            } else {
                Write-Log "Reusing cached download $Destination ($($existingFile.Length) bytes)."
                return
            }
        }

        if (Test-Path -LiteralPath $Destination) {
            Remove-Item -LiteralPath $Destination -Force -ErrorAction SilentlyContinue
        }
    }

    $tempDestination = "$Destination.part"
    Remove-Item -LiteralPath $tempDestination -Force -ErrorAction SilentlyContinue

    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        try {
            Write-Log "Downloading $Url (attempt $attempt/$MaxAttempts)"

            if (Get-Command curl.exe -ErrorAction SilentlyContinue) {
                & curl.exe --fail --location --retry 2 --retry-all-errors --connect-timeout 20 --output $tempDestination $Url
                if ($LASTEXITCODE -ne 0) {
                    throw "curl.exe exited with code $LASTEXITCODE"
                }
            } else {
                Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $tempDestination -TimeoutSec 900
            }

            $downloadedFile = Get-Item -LiteralPath $tempDestination -ErrorAction SilentlyContinue
            if (-not $downloadedFile -or $downloadedFile.Length -le 0) {
                throw "Download completed without producing a non-empty file."
            }

            if ($isZip -and -not (Test-ZipArchive -Path $tempDestination)) {
                throw "Downloaded archive failed ZIP validation."
            }

            Move-Item -LiteralPath $tempDestination -Destination $Destination -Force
            return
        } catch {
            $message = $_.Exception.Message
            Write-Log "Download attempt $attempt failed for ${Url}: $message"
            Remove-Item -LiteralPath $tempDestination -Force -ErrorAction SilentlyContinue

            if ($attempt -eq $MaxAttempts) {
                throw
            }

            Start-Sleep -Seconds ([Math]::Min(10 * $attempt, 30))
        }
    }
}

function Test-ZipArchive {
    param([Parameter(Mandatory = $true)][string] $Path)

    try {
        Add-Type -AssemblyName System.IO.Compression.FileSystem -ErrorAction SilentlyContinue
        $archive = [System.IO.Compression.ZipFile]::OpenRead($Path)
        $archive.Dispose()
        return $true
    } catch {
        return $false
    }
}

function Expand-ZipFresh {
    param(
        [Parameter(Mandatory = $true)][string] $ZipPath,
        [Parameter(Mandatory = $true)][string] $Destination
    )

    if (Test-Path -LiteralPath $Destination) {
        Remove-Item -LiteralPath $Destination -Recurse -Force
    }

    Ensure-Directory -Path $Destination
    Expand-Archive -LiteralPath $ZipPath -DestinationPath $Destination -Force
}

function Invoke-Installer {
    param(
        [Parameter(Mandatory = $true)][string] $FilePath,
        [string] $Arguments,
        [string] $Name = (Split-Path -Leaf $FilePath),
        [int[]] $AllowedExitCodes = @(0, 3010)
    )

    $process = Start-Process -FilePath $FilePath -ArgumentList $Arguments -Wait -PassThru -NoNewWindow
    if ($AllowedExitCodes -notcontains $process.ExitCode) {
        throw "$Name failed with exit code $($process.ExitCode)."
    }

    Write-Log "$Name completed with exit code $($process.ExitCode)."
}

function Get-GitHubAssetUrl {
    param(
        [Parameter(Mandatory = $true)][string] $Repo,
        [Parameter(Mandatory = $true)][string] $Pattern
    )

    $headers = @{
        "User-Agent" = "ai-reverse-lab-bootstrap"
        "Accept" = "application/vnd.github+json"
    }
    $release = Invoke-RestMethod -Headers $headers -Uri "https://api.github.com/repos/$Repo/releases/latest"
    $asset = $release.assets | Where-Object { $_.name -match $Pattern } | Select-Object -First 1

    if (-not $asset) {
        throw "No release asset matching '$Pattern' found for $Repo."
    }

    return $asset.browser_download_url
}

function New-DesktopShortcut {
    param(
        [Parameter(Mandatory = $true)][string] $TargetPath,
        [Parameter(Mandatory = $true)][string] $ShortcutName,
        [string] $WorkingDirectory = (Split-Path -Parent $TargetPath)
    )

    if (-not (Test-Path -LiteralPath $TargetPath)) {
        $resolvedTargetPath = Resolve-PathHint -PathHint $TargetPath
        if (-not $resolvedTargetPath) {
            return
        }
        $TargetPath = $resolvedTargetPath
        if (-not $WorkingDirectory) {
            $WorkingDirectory = Split-Path -Parent $TargetPath
        }
    }

    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut((Join-Path $desktopPath "$ShortcutName.lnk"))
    $shortcut.TargetPath = $TargetPath
    $shortcut.WorkingDirectory = $WorkingDirectory
    $shortcut.Save()
}

function Resolve-PathHint {
    param([string] $PathHint)

    if ([string]::IsNullOrWhiteSpace($PathHint)) {
        return $null
    }

    if (Test-Path -LiteralPath $PathHint) {
        return (Resolve-Path -LiteralPath $PathHint).Path
    }

    $command = Get-Command $PathHint -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($command -and $command.Source) {
        return $command.Source
    }

    $matches = Get-ChildItem -Path $PathHint -ErrorAction SilentlyContinue
    if ($matches) {
        return $matches | Select-Object -First 1 -ExpandProperty FullName
    }

    return $null
}

function Read-ToolManifest {
    if (-not (Test-Path -LiteralPath $toolManifestPath)) {
        throw "Missing tool manifest at $toolManifestPath"
    }

    return Get-Content -LiteralPath $toolManifestPath -Raw | ConvertFrom-Json
}

function Invoke-ManifestCommand {
    param([pscustomobject] $Package)

    $executablePath = Resolve-PathHint -PathHint $Package.executable
    if (-not $executablePath) {
        throw "Could not resolve executable '$($Package.executable)' for $($Package.name)."
    }

    $workingDirectory = $null
    if ($Package.PSObject.Properties.Name -contains "working_directory") {
        $workingDirectory = Resolve-PathHint -PathHint $Package.working_directory
    }
    if (-not $workingDirectory) {
        $workingDirectory = Split-Path -Parent $executablePath
    }

    $allowedExitCodes = @()
    if ($Package.PSObject.Properties.Name -contains "allowed_exit_codes") {
        $allowedExitCodes = @($Package.allowed_exit_codes)
    }
    if ($allowedExitCodes.Count -eq 0) {
        $allowedExitCodes = @(0, 3010)
    }

    $process = Start-Process -FilePath $executablePath -ArgumentList $Package.args -WorkingDirectory $workingDirectory -Wait -PassThru -NoNewWindow
    if ($AllowedExitCodes -notcontains $process.ExitCode) {
        throw "$($Package.name) failed with exit code $($process.ExitCode)."
    }

    Write-Log "$($Package.name) completed with exit code $($process.ExitCode)."
}

function Test-PackageInstalled {
    param([pscustomobject] $Package)

    $resolvedInstallPath = Resolve-PathHint -PathHint $Package.install_path

    switch ($Package.id) {
        "x64dbg-mcp-install" {
            return (
                (Test-Path -LiteralPath "C:\Tools\ReverseLab\x64dbg\release\x64\plugins\MCPx64dbg.dp64") -and
                (Test-Path -LiteralPath "C:\Tools\ReverseLab\x64dbg\release\x32\plugins\MCPx64dbg.dp32")
            )
        }
        "r2ai" {
            $pluginPath = Join-Path $env:USERPROFILE ".local\share\radare2\r2pm\git\r2ai"
            return (Test-Path -LiteralPath $pluginPath)
        }
        "decai" {
            $pluginPath = Join-Path $env:USERPROFILE ".local\share\radare2\r2pm\git\decai"
            return (Test-Path -LiteralPath $pluginPath)
        }
        "r2pm-sync" {
            $dbPath = Join-Path $env:USERPROFILE ".local\share\radare2\r2pm\db"
            return (Test-Path -LiteralPath $dbPath)
        }
    }

    if (-not $resolvedInstallPath) {
        return $false
    }

    if (Test-Path -LiteralPath $resolvedInstallPath -PathType Container) {
        return [bool](Get-ChildItem -LiteralPath $resolvedInstallPath -Force -ErrorAction SilentlyContinue | Select-Object -First 1)
    }

    return (Test-Path -LiteralPath $resolvedInstallPath)
}

function Install-Package {
    param([pscustomobject] $Package)

    if (Test-PackageInstalled -Package $Package) {
        Write-Log "Skipping $($Package.name); already present."
        Add-Result -Tool $Package.name -Status "installed" -InstallPath $Package.install_path -Source $Package.source -Details ($Package.notes + " | skipped on rerun")
        return
    }

    $downloadPath = $null
    if ($Package.PSObject.Properties.Name -contains "download_name" -and $Package.download_name) {
        $downloadPath = Join-Path $downloadRoot $Package.download_name
    }
    $allowedExitCodes = @()
    if ($Package.PSObject.Properties.Name -contains "allowed_exit_codes") {
        $allowedExitCodes = @($Package.allowed_exit_codes)
    }
    if ($allowedExitCodes.Count -eq 0) {
        $allowedExitCodes = @(0, 3010)
    }

    try {
        switch ($Package.kind) {
            "exe" {
                Invoke-DownloadFile -Url $Package.url -Destination $downloadPath
                Invoke-Installer -FilePath $downloadPath -Arguments $Package.args -Name $Package.name -AllowedExitCodes $allowedExitCodes
            }
            "zip" {
                Invoke-DownloadFile -Url $Package.url -Destination $downloadPath
                Expand-ZipFresh -ZipPath $downloadPath -Destination $Package.install_path
            }
            "github-zip" {
                $assetUrl = Get-GitHubAssetUrl -Repo $Package.repo -Pattern $Package.asset_pattern
                Invoke-DownloadFile -Url $assetUrl -Destination $downloadPath
                $replaceExisting = $true
                if ($Package.PSObject.Properties.Name -contains "replace_existing") {
                    $replaceExisting = [bool] $Package.replace_existing
                }
                if ($replaceExisting) {
                    Expand-ZipFresh -ZipPath $downloadPath -Destination $Package.install_path
                } else {
                    Ensure-Directory -Path $Package.install_path
                    Expand-Archive -LiteralPath $downloadPath -DestinationPath $Package.install_path -Force
                }
            }
            "github-exe" {
                $assetUrl = Get-GitHubAssetUrl -Repo $Package.repo -Pattern $Package.asset_pattern
                Invoke-DownloadFile -Url $assetUrl -Destination $downloadPath
                Invoke-Installer -FilePath $downloadPath -Arguments $Package.args -Name $Package.name -AllowedExitCodes $allowedExitCodes
            }
            "command" {
                Invoke-ManifestCommand -Package $Package
            }
            default {
                throw "Unsupported package kind '$($Package.kind)' for $($Package.name)."
            }
        }

        Add-Result -Tool $Package.name -Status "installed" -InstallPath $Package.install_path -Source $Package.source -Details $Package.notes
    } catch {
        $isOptional = ($Package.PSObject.Properties.Name -contains "optional") -and [bool]$Package.optional
        if ($isOptional) {
            Write-Log "Optional package $($Package.name) failed and will be skipped: $($_.Exception.Message)"
            Add-Result -Tool $Package.name -Status "warning" -InstallPath $Package.install_path -Source $Package.source -Details ($Package.notes + " | optional package skipped: " + $_.Exception.Message)
            return
        }

        throw
    }
}

function Write-NotesFile {
    param([pscustomobject] $ToolManifest)

    $content = @(
        "AI Reverse Lab bootstrap completed.",
        "",
        "Installed packages:"
    )

    foreach ($package in $ToolManifest.packages) {
        $content += "  - $($package.name): $($package.install_path)"
    }

    $content += ""
    $content += "Manifest: C:\ProgramData\AIReverseLab\full-lab-manifest.json"
    $content += "Logs: C:\OEM\logs"

    Set-Content -LiteralPath $notesPath -Value $content -Encoding ASCII
}

function Write-Manifest {
    param(
        [pscustomobject] $ToolManifest,
        [switch] $MarkInstalled
    )

    $manifest = [pscustomobject]@{
        installed_at = (Get-Date).ToString("o")
        tools_root = $toolsRoot
        package_manifest = $ToolManifest
        results = $results
    }

    $json = $manifest | ConvertTo-Json -Depth 8
    $json | Set-Content -LiteralPath $manifestPath -Encoding UTF8
    if ($MarkInstalled) {
        $json | Set-Content -LiteralPath $markerPath -Encoding UTF8
        if (Test-Path -LiteralPath $failurePath) {
            Remove-Item -LiteralPath $failurePath -Force -ErrorAction SilentlyContinue
        }
    }
}

function Write-FailureRecord {
    param(
        [string] $Failure,
        [pscustomobject] $ToolManifest
    )

    $payload = [pscustomobject]@{
        failed_at = (Get-Date).ToString("o")
        tools_root = $toolsRoot
        package_manifest = $ToolManifest
        results = $results
        failure = $Failure
    }

    $json = $payload | ConvertTo-Json -Depth 8
    $json | Set-Content -LiteralPath $manifestPath -Encoding UTF8
    $json | Set-Content -LiteralPath $failurePath -Encoding UTF8
}

function Install-BridgeAutostart {
    $bridgeDesktopToolPath = Join-Path $desktopPath "shared\bridge-tools\Start-X64dbgBridge.ps1"

    $bootstrapContent = @'
$ErrorActionPreference = "SilentlyContinue"

$bridgeCandidates = @(
    (Join-Path $env:USERPROFILE "Desktop\shared\bridge-tools\Start-X64dbgBridge.ps1"),
    "Z:\bridge-tools\Start-X64dbgBridge.ps1"
)
$maxAttempts = 40

for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
    $bridgeToolPath = $bridgeCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if ($bridgeToolPath) {
        Start-Process -WindowStyle Hidden -FilePath "powershell.exe" -ArgumentList @(
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-File", $bridgeToolPath
        ) | Out-Null
        exit 0
    }

    Start-Sleep -Seconds 3
}

exit 0
'@

    $launcherContent = '@echo off' + "`r`n" +
        'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\ProgramData\AIReverseLab\Start-X64dbgBridge-Autostart.ps1"' + "`r`n"

    Set-Content -LiteralPath $bridgeBootstrapPath -Value $bootstrapContent -Encoding ASCII
    Set-Content -LiteralPath $bridgeLauncherPath -Value $launcherContent -Encoding ASCII

    Add-Result -Tool "x64dbg bridge autostart" -Status "installed" -InstallPath $bridgeLauncherPath -Source "bootstrap" -Details "Starts the x64dbg bridge automatically at user logon from the shared desktop folder."
    Write-Log "Installed x64dbg bridge autostart launcher."
}

Ensure-Directory -Path $stateRoot
Ensure-Directory -Path $downloadRoot
Ensure-Directory -Path $toolsRoot
Ensure-Directory -Path $logRoot

$transcriptPath = Join-Path $logRoot ("install-full-lab-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".log")
Start-Transcript -Path $transcriptPath -Append | Out-Null

try {
    if (Test-Path -LiteralPath $markerPath) {
        Write-Log "Full lab already provisioned. Exiting."
        exit 0
    }

    $toolManifest = Read-ToolManifest
    Wait-ForInternet
    Set-UnrestrictedExecutionPolicy
    Install-OpenSSHServer

    foreach ($package in $toolManifest.packages) {
        Install-Package -Package $package
    }

    Write-NotesFile -ToolManifest $toolManifest

    foreach ($shortcut in $toolManifest.shortcuts) {
        New-DesktopShortcut -TargetPath $shortcut.target -ShortcutName $shortcut.name
    }

    Install-BridgeAutostart
    Write-Manifest -ToolManifest $toolManifest -MarkInstalled
    Write-Log "Full reverse lab provisioning completed."

    schtasks /Delete /TN $taskName /F | Out-Null
    exit 0
} catch {
    $failure = $_.Exception.Message
    Write-Log "Bootstrap failed: $failure"
    Add-Result -Tool "bootstrap" -Status "failed" -InstallPath $toolsRoot -Source "bootstrap" -Details $failure
    $fallbackManifest = if (Test-Path -LiteralPath $toolManifestPath) { Read-ToolManifest } else { $null }
    if ($fallbackManifest) {
        Write-FailureRecord -Failure $failure -ToolManifest $fallbackManifest
    }
    exit 1
} finally {
    Stop-Transcript | Out-Null
}
