# OEM First-Boot Provisioning

This folder is mounted into the optional `dockurr/windows` sandbox at `/oem`.

`dockurr/windows` copies the contents of this directory into `C:\OEM` during the initial Windows installation. The included `install.bat` creates a one-shot scheduled task that runs `install_full_lab.ps1` on first boot to provision a reverse-engineering lab.
For extra reliability, `install.bat` now registers both an `ONSTART` and an `ONLOGON` scheduled task and writes a marker file to `C:\OEM\logs\install-bat-ran.txt`.

The bootstrap is now manifest-driven through `tool-manifest.json`, so adding or removing packages is a data change instead of a PowerShell rewrite.

Current lab payload:

- Sysinternals Suite
- Wireshark
- x64dbg
- x64dbg MCP plugin
- Detect It Easy
- Dependencies
- Cutter
- Rizin
- radare2
- radare2 MCP
- r2ai
- decai
- PE-bear
- VC++ runtime prerequisites

Manual-only addition:

- Binary Ninja Free can be added by the analyst for manual use, but it is intentionally not part of the automated bootstrap because the free edition does not expose the API/plugin surface needed for MCP-style integration.

Artifacts created inside Windows:

- logs: `C:\OEM\logs`
- install.bat marker: `C:\OEM\logs\install-bat-ran.txt`
- manifest: `C:\ProgramData\AIReverseLab\full-lab-manifest.json`
- marker: `C:\ProgramData\AIReverseLab\full-lab-installed.json`
- failure record: `C:\ProgramData\AIReverseLab\full-lab-failed.json`
- tools root: `C:\Tools\ReverseLab`

PowerShell policy:

- first-boot provisioning sets `Set-ExecutionPolicy -ExecutionPolicy Unrestricted -Scope LocalMachine -Force`
- if Windows reports an override or any security-related exception while changing the policy, the bootstrap now logs that condition and continues instead of aborting
- this applies automatically only on a fresh guest install or when the bootstrap is rerun manually

Bootstrap state handling:

- the installed marker is now written only on successful completion
- failed runs write `C:\ProgramData\AIReverseLab\full-lab-failed.json` instead, so reruns are not blocked by a partial failure

Shared AI configuration:

- the project-wide LLM settings are exposed inside the guest through `%USERPROFILE%\Desktop\shared\config\ai-config.json`
- environment variables also expose the same Compose-side Ollama target:
  - `OLLAMA_HOST=ollama`
  - `OLLAMA_BASE_URL=http://ollama:11434`
  - `OLLAMA_MODEL=Godmoded/llama3-lexi-uncensored`

The provisioning is idempotent inside the guest. To force a clean first-boot reinstall, recreate the Windows storage volume so the OS is installed from scratch again.
