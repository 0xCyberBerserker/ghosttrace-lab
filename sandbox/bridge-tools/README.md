# x64dbg Sandbox Bridge Tools

This folder is mounted into the Windows sandbox at:

- `%USERPROFILE%\Desktop\shared\bridge-tools`

Shared bridge mailbox:

- `%USERPROFILE%\Desktop\shared\bridge`

Local working directory inside Windows:

- `C:\ProgramData\AIReverseLab\x64dbg-bridge`

## Purpose

These scripts provide a lightweight agent loop inside the Windows sandbox:

- publish x64dbg session state into the shared bridge
- publish debugger findings into the shared bridge
- mirror pending debugger requests from the platform back into the guest

The Linux-side `sandbox_runner` automatically ingests files dropped into:

- `%USERPROFILE%\Desktop\shared\bridge\<job_id>\incoming\state`
- `%USERPROFILE%\Desktop\shared\bridge\<job_id>\incoming\findings`

and writes pending requests to:

- `%USERPROFILE%\Desktop\shared\bridge\<job_id>\requests.pending.json`

## Recommended usage inside the guest

The preferred setup is automatic startup at user logon. First-boot provisioning installs a launcher in the Windows Startup folder that waits for `%USERPROFILE%\Desktop\shared\bridge-tools\Start-X64dbgBridge.ps1` and starts it automatically.

`Start-X64dbgBridge.ps1` now resolves the shared mailbox automatically. It prefers `%USERPROFILE%\Desktop\shared\bridge` and only falls back to `Z:\bridge` for compatibility with older guests.

Use the command below only as a manual fallback:

1. Start the bridge loop:

```powershell
powershell -ExecutionPolicy Bypass -File "$env:USERPROFILE\Desktop\shared\bridge-tools\Start-X64dbgBridge.ps1"
```

2. Publish state snapshots:

```powershell
powershell -ExecutionPolicy Bypass -File "$env:USERPROFILE\Desktop\shared\bridge-tools\Submit-X64dbgState.ps1" -JobId <job_id> -Status attached -Pid 4242 -TargetModule notepad.exe -Notes "x64dbg MCP connected"
```

3. Publish findings:

```powershell
powershell -ExecutionPolicy Bypass -File "$env:USERPROFILE\Desktop\shared\bridge-tools\Submit-X64dbgFinding.ps1" -JobId <job_id> -Type breakpoint-hit -Summary "Breakpoint hit at process entry" -Address 0x401000 -Evidence "Initial loader breakpoint observed via x64dbg MCP"
```

4. Read mirrored requests from the local inbox:

```text
C:\ProgramData\AIReverseLab\x64dbg-bridge\inbox\<job_id>\requests.pending.json
```

## Notes

- This bridge does not execute the debugger by itself.
- It only synchronizes structured debugger state and findings.
- The actual x64dbg MCP runtime remains under analyst control inside the sandbox.
