Set-StrictMode -Version Latest

function Resolve-PlinkPath {
    param([string] $RequestedPath)

    if ($RequestedPath -and (Test-Path -LiteralPath $RequestedPath)) {
        return $RequestedPath
    }

    $plinkCommand = Get-Command plink -ErrorAction SilentlyContinue
    if ($plinkCommand) {
        return $plinkCommand.Source
    }

    $candidates = @(
        "C:\Program Files\PuTTY\plink.exe",
        "C:\Program Files (x86)\PuTTY\plink.exe"
    )

    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            return $candidate
        }
    }

    throw "Could not locate plink.exe. Install PuTTY or pass -PlinkPath."
}

function Resolve-PscpPath {
    param([string] $RequestedPath)

    if ($RequestedPath -and (Test-Path -LiteralPath $RequestedPath)) {
        return $RequestedPath
    }

    $pscpCommand = Get-Command pscp -ErrorAction SilentlyContinue
    if ($pscpCommand) {
        return $pscpCommand.Source
    }

    $candidates = @(
        "C:\Program Files\PuTTY\pscp.exe",
        "C:\Program Files (x86)\PuTTY\pscp.exe"
    )

    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            return $candidate
        }
    }

    throw "Could not locate pscp.exe. Install PuTTY or pass -PscpPath."
}

function Get-HostKeyFingerprint {
    param(
        [string] $HostName,
        [int] $Port
    )

    $tempFile = Join-Path ([System.IO.Path]::GetTempPath()) ("sandbox-known-hosts-" + [guid]::NewGuid().ToString("N") + ".txt")

    try {
        $keyscanOutput = cmd /c "ssh-keyscan -p $Port $HostName 2>nul"
        if (-not $keyscanOutput) {
            throw "ssh-keyscan returned no host keys for ${HostName}:$Port"
        }

        Set-Content -LiteralPath $tempFile -Value $keyscanOutput -Encoding ascii
        $fingerprints = & ssh-keygen -lf $tempFile -E sha256
        $ed25519 = $fingerprints | Where-Object { $_ -match "\(ED25519\)" } | Select-Object -First 1

        if (-not $ed25519) {
            throw "Could not determine ssh-ed25519 host key fingerprint for ${HostName}:$Port"
        }

        if ($ed25519 -match "^(?<bits>\d+)\s+(?<fingerprint>SHA256:[^\s]+)\s+") {
            return "ssh-ed25519 $($matches.bits) $($matches.fingerprint)"
        }

        throw "Could not parse host key fingerprint from: $ed25519"
    } finally {
        Remove-Item -LiteralPath $tempFile -Force -ErrorAction SilentlyContinue
    }
}
