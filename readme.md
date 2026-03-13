# AI Reverse Engineering

Cyberpunk-styled reverse engineering workspace powered by:

- `Ghidraaas` as the Ghidra analysis backend
- `Ollama` on the host machine as the OpenAI-compatible LLM backend
- a Flask-based `webui` for uploads, job management, and chat-driven analysis

## Stack

- `Ghidraaas/`
  Cisco Talos Ghidra-as-a-Service backend, adapted to build cleanly on a modern Docker base.
- `webui/`
  Flask frontend and assistant orchestration layer.
- `docker-compose.yml`
  Local orchestration for `ghidraaas` and `webui`.

## Run

1. Build `ghidraaas`:

```powershell
cd Ghidraaas
docker build -t ghidraaas .
```

2. Start the full stack from the repository root:

```powershell
docker compose up --build
```

3. Open the UI:

```text
http://localhost:5000
```

## Requirements

- Docker Desktop
- Ollama running on the host
- model available locally:

```text
qwen3-coder-next:latest
```

## Shared AI Configuration

The project now keeps a small shared AI config in [`ai-config.json`](C:/Users/jcarl/Documents/repos/ai-reverse-engineering/ai-config.json).

Current defaults:

- provider: `ollama`
- API base: `http://host.docker.internal:11434/v1`
- model: `qwen3-coder-next:latest`

This same configuration is mounted into:

- `webui` at `/app/config/ai-config.json`
- the optional Windows sandbox through the shared desktop folder at `%USERPROFILE%\Desktop\shared\config\ai-config.json`

The main assistant still reads its active runtime values from environment variables, but this file is now the project-wide source of truth you can update when changing models.

## Notes

- Ghidra projects and output are stored in Docker volumes so analysis history survives container recreation.
- The web UI stores a lightweight local cache of jobs and the active selection in the browser for smoother reload behavior.
- Uploaded filenames are also persisted by the web service so historical jobs can be shown with human-readable names.

## Analysis Playbooks

The current UI and assistant are tuned around article-inspired reverse engineering workflows:

- `Static Triage`
  Start with capability mapping, likely purpose, and suspicious function clusters.
- `PE / API Behavior`
  Use imported libraries and APIs to infer filesystem, process, registry, service, crypto, and installer behavior.
- `Network Clues`
  Infer likely update, telemetry, or remote communication paths from static evidence.

The stack remains intentionally static-analysis-first:

- `Ghidraaas` now exposes cached import-table extraction in addition to function lists and decompilation.
- `Ghidraaas` now exposes cached import-table extraction and string extraction in addition to function lists and decompilation.
- The assistant is instructed to distinguish confirmed static evidence from higher-level inference.
- Dynamic-only claims are intentionally framed as hypotheses unless supported by imported APIs or decompiled code.

## Auto Triage Reports

Each sample can now generate a cached triage report per `job_id`.

Endpoints:

```text
GET /triage/<job_id>
```

Generated artifacts:

- JSON: `/app/data/triage_reports/<job_id>.json`
- Markdown: `/app/data/triage_reports/<job_id>.md`

Behavior:

- reports are queued automatically after upload
- reports are regenerated after new dynamic evidence is posted
- if Ghidra is still preparing artifacts such as the function index, the endpoint returns `202` with a processing state

By default, triage reports are generated deterministically from structured artifacts for speed and reliability. If you explicitly want LLM-authored triage prose, set:

```text
TRIAGE_USE_LLM=1
```

and keep the shared Ollama configuration aligned with [`ai-config.json`](C:/Users/jcarl/Documents/repos/ai-reverse-engineering/ai-config.json).

## Dynamic Evidence Lane

This project does not execute unknown binaries autonomously. Instead, it supports a safer dynamic-evidence workflow:

- upload or record sandbox-derived artifacts for a known `job_id`
- keep static and dynamic evidence side by side
- let the assistant correlate imports, strings, functions, decompilation, and uploaded telemetry

If you operate an external sandbox runner yourself, the stack now exposes a shared uploads volume:

- `webui` stores uploaded samples in `/app/data/uploads`
- that path is backed by the named volume `sandbox_bin`
- optional sandbox profiles can mount the same volume and pick samples up by `<job_id>.bin`
- the bundled `sandbox_runner` service receives `POST /run` notifications from `webui` and records a safe execution queue for external sandboxes

Dynamic evidence endpoint:

```text
POST /evidence/<job_id>
GET  /evidence/<job_id>
```

Example payload:

```json
{
  "artifacts": [
    {
      "type": "procmon",
      "source": "manual-sandbox",
      "highlights": [
        "Writes to %ProgramData%\\\\Vendor\\\\config.json",
        "Creates child process updater.exe"
      ],
      "events": [
        {
          "timestamp": "2026-03-12T18:00:00Z",
          "operation": "WriteFile",
          "path": "C:\\\\ProgramData\\\\Vendor\\\\config.json"
        }
      ]
    }
  ]
}
```

## Optional Sandbox Profile

The repository includes an optional `windows-sandbox` profile in `docker-compose.yml` that mounts the shared uploads volume and sets:

```text
VERSION=11l
```

for `dockurr/windows`.

This profile is intentionally not required by the main stack and depends on host-side support outside the default Linux container flow.

The current profile is configured for stable local access in `bridge` mode:

- noVNC console on `http://127.0.0.1:8006`
- RDP on `127.0.0.1:3389`
- SSH on `127.0.0.1:2222`
- shared samples exposed inside the guest through the `shared` folder on the desktop

Windows guest credentials are pinned explicitly in the compose profile:

- username: `Docker`
- password: `admin`

Host-side SSH helper:

- [`sandbox/host-tools/Invoke-WindowsSandboxSSH.ps1`](C:/Users/jcarl/Documents/repos/ai-reverse-engineering/sandbox/host-tools/Invoke-WindowsSandboxSSH.ps1)
- resolves the current host key automatically through `ssh-keyscan` and calls `plink`
- example:

```powershell
powershell -ExecutionPolicy Bypass -File .\sandbox\host-tools\Invoke-WindowsSandboxSSH.ps1 -Command "whoami"
```

PowerShell example:

```powershell
powershell -ExecutionPolicy Bypass -File .\sandbox\host-tools\Invoke-WindowsSandboxSSH.ps1 -PowerShell -Command "Get-Service sshd | Select-Object Status, StartType"
```

Convenience wrappers:

- [`sandbox/host-tools/Invoke-WindowsSandboxPS.ps1`](C:/Users/jcarl/Documents/repos/ai-reverse-engineering/sandbox/host-tools/Invoke-WindowsSandboxPS.ps1)
- [`sandbox/host-tools/Copy-ToWindowsSandbox.ps1`](C:/Users/jcarl/Documents/repos/ai-reverse-engineering/sandbox/host-tools/Copy-ToWindowsSandbox.ps1)
- [`sandbox/host-tools/Copy-FromWindowsSandbox.ps1`](C:/Users/jcarl/Documents/repos/ai-reverse-engineering/sandbox/host-tools/Copy-FromWindowsSandbox.ps1)

Examples:

```powershell
powershell -ExecutionPolicy Bypass -File .\sandbox\host-tools\Invoke-WindowsSandboxPS.ps1 -Command "Get-ChildItem C:\OEM\logs"
```

```powershell
powershell -ExecutionPolicy Bypass -File .\sandbox\host-tools\Copy-ToWindowsSandbox.ps1 -SourcePath .\sample.exe -DestinationPath C:/Users/Docker/Desktop/sample.exe
```

```powershell
powershell -ExecutionPolicy Bypass -File .\sandbox\host-tools\Copy-FromWindowsSandbox.ps1 -SourcePath C:/Users/Docker/Desktop/report.txt -DestinationPath .\artifacts\report.txt
```

Generic SSH/copy helpers:

- [`sandbox/host-tools/Invoke-SandboxSSH.ps1`](C:/Users/jcarl/Documents/repos/ai-reverse-engineering/sandbox/host-tools/Invoke-SandboxSSH.ps1)
- [`sandbox/host-tools/Copy-ToSandbox.ps1`](C:/Users/jcarl/Documents/repos/ai-reverse-engineering/sandbox/host-tools/Copy-ToSandbox.ps1)
- [`sandbox/host-tools/Copy-FromSandbox.ps1`](C:/Users/jcarl/Documents/repos/ai-reverse-engineering/sandbox/host-tools/Copy-FromSandbox.ps1)

Linux-ready wrappers:

- [`sandbox/host-tools/Invoke-LinuxSandboxSSH.ps1`](C:/Users/jcarl/Documents/repos/ai-reverse-engineering/sandbox/host-tools/Invoke-LinuxSandboxSSH.ps1)
- [`sandbox/host-tools/Copy-ToLinuxSandbox.ps1`](C:/Users/jcarl/Documents/repos/ai-reverse-engineering/sandbox/host-tools/Copy-ToLinuxSandbox.ps1)
- [`sandbox/host-tools/Copy-FromLinuxSandbox.ps1`](C:/Users/jcarl/Documents/repos/ai-reverse-engineering/sandbox/host-tools/Copy-FromLinuxSandbox.ps1)

Linux examples:

```powershell
powershell -ExecutionPolicy Bypass -File .\sandbox\host-tools\Invoke-LinuxSandboxSSH.ps1 -HostName 127.0.0.1 -Port 2223 -UserName root -Password admin -Command "uname -a"
```

```powershell
powershell -ExecutionPolicy Bypass -File .\sandbox\host-tools\Copy-ToLinuxSandbox.ps1 -HostName 127.0.0.1 -Port 2223 -UserName root -Password admin -SourcePath .\triage.json -DestinationPath /root/triage.json
```

### First-Boot Full Lab Provisioning

The optional Windows sandbox now mounts [`sandbox/oem`](C:/Users/jcarl/Documents/repos/ai-reverse-engineering/sandbox/oem/README.md) into `dockurr/windows` as `/oem`.

On the initial Windows installation, `dockurr/windows` copies that folder into `C:\OEM` and runs `install.bat`. That bootstrap creates a one-shot scheduled task which installs a curated full reverse-engineering lab on the guest after first boot.

The lab definition is declarative:

- [`tool-manifest.json`](C:/Users/jcarl/Documents/repos/ai-reverse-engineering/sandbox/oem/tool-manifest.json) defines packages and desktop shortcuts
- [`install_full_lab.ps1`](C:/Users/jcarl/Documents/repos/ai-reverse-engineering/sandbox/oem/install_full_lab.ps1) is the generic installer that executes that manifest

Installed lab payload:

- Sysinternals Suite
  Procmon, Process Explorer, Autoruns, TCPView, ProcDump, Strings, Sigcheck
- Wireshark
- x64dbg
- x64dbg MCP plugin bundle
- Detect It Easy
- Dependencies
- Cutter
- Rizin
- radare2
- radare2 MCP
- r2ai
- decai
- PE-bear
- VC++ redistributable prerequisites

Manual-only tool:

- Binary Ninja Free
  kept outside the automated bootstrap because the free edition is useful for manual inspection but does not provide the plugin/API surface needed for MCP integration

Guest-side paths:

- tools root: `C:\Tools\ReverseLab`
- bootstrap logs: `C:\OEM\logs`
- install manifest: `C:\ProgramData\AIReverseLab\full-lab-manifest.json`
- shared folder: `%USERPROFILE%\Desktop\shared`

Guest-side PowerShell policy:

- first-boot provisioning now sets `Set-ExecutionPolicy -ExecutionPolicy Unrestricted -Scope LocalMachine -Force`
- existing Windows installs do not retroactively receive that change unless you reprovision the VM or run the command manually once inside the guest

Guest-side remote access:

- first-boot provisioning now installs and enables OpenSSH Server
- the compose profile maps guest port `22` to host port `2222`
- existing Windows installs do not retroactively receive that change unless you reprovision the VM or install OpenSSH manually once inside the guest

Important caveat:

- this provisioning is triggered on a fresh Windows install
- if the Windows disk in `sandbox_storage` already exists, changing the OEM scripts will not retroactively rerun the first-boot setup
- to replay the full bootstrap automatically, recreate the Windows storage volume and let the guest reinstall from scratch

### Clean Reinstall Workflow

To force a clean Windows reinstall and rerun the first-boot full lab bootstrap:

```powershell
docker compose --profile windows-sandbox down windows_sandbox
docker volume rm ai-reverse-engineering_sandbox_storage
docker compose --profile windows-sandbox up -d windows_sandbox
```

That rebuilds the guest disk from scratch, reimports `C:\OEM`, and reruns the scheduled first-boot installer.

## Sandbox Runner Bridge

The Linux-side `sandbox_runner` service is included by default and provides a thin coordination layer:

- `POST /run`
  Queue a sample by `job_id` after upload.
- `GET /jobs/<job_id>`
  Inspect queued sample metadata and whether the shared `.bin` file is visible.
- `POST /jobs/<job_id>/evidence`
  Forward already-captured sandbox artifacts into `webui` at `/evidence/<job_id>`.

This bridge does not execute binaries itself. It only coordinates shared-volume pickup and evidence forwarding.

## x64dbg MCP Bridge

The platform now includes a first bridge layer for `x64dbg MCP`-driven debugging context.

Current capabilities:

- persist the current x64dbg session state for a `job_id`
- store debugger findings captured from x64dbg MCP
- queue analyst or assistant requests for debugger actions
- expose that state back into the assistant as structured tools

Proxy endpoints exposed by `webui`:

```text
GET  /debug/x64dbg/<job_id>
POST /debug/x64dbg/<job_id>
GET  /debug/x64dbg/<job_id>/findings
POST /debug/x64dbg/<job_id>/findings
GET  /debug/x64dbg/<job_id>/requests
POST /debug/x64dbg/<job_id>/requests
```

Typical use:

- the sandbox-side bridge posts session metadata such as `status`, `pid`, `target_module`, and transport details
- x64dbg MCP findings such as breakpoint hits, memory observations, or API traces are posted to `/findings`
- the assistant can queue requests such as `set_breakpoint` or `inspect_address` to `/requests`

This is intentionally a coordination and evidence layer. It does not make the web stack execute debugger actions by itself; the actual x64dbg MCP runtime still lives in the sandbox.

### Automatic Sandbox Bridge

The repository now also includes a shared-mailbox bridge for the Windows sandbox:

- Linux side:
  - `sandbox_runner` watches `sandbox_bridge`
  - ingests x64dbg state payloads and findings automatically
  - writes `requests.pending.json` snapshots back into the shared bridge
- Windows side:
  - [`bridge-tools`](C:/Users/jcarl/Documents/repos/ai-reverse-engineering/sandbox/bridge-tools/README.md) is exposed inside the guest through `%USERPROFILE%\Desktop\shared\bridge-tools`
  - the shared mailbox is exposed at `%USERPROFILE%\Desktop\shared\bridge`
  - `Start-X64dbgBridge.ps1` mirrors local outbox payloads into that mailbox and syncs pending requests back into the guest inbox
  - first-boot provisioning installs an automatic launcher in the Windows Startup folder so the bridge starts on login without copy/paste

This means the sandbox can now publish debugger findings automatically without posting JSON directly to the web API, as long as the guest-side bridge loop is running.
