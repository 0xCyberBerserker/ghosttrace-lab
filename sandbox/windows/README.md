## Windows sandbox container

This directory defines the Windows sandbox used by the optional `windows-sandbox` Compose profile. The main stack uses `dockurr/windows`, which provides a full Windows VM with OEM provisioning, noVNC, RDP, SSH, and shared folders.

### Base image

The sandbox uses `dockurr/windows`:

- Image: `dockurr/windows:latest`
- Reference: `https://hub.docker.com/r/dockurr/windows`

The `windows-sandbox` profile requires Docker Desktop with KVM/QEMU support (typically Linux hosts or WSL2 with nested virtualization). It cannot run side by side with the Linux-based services on the same engine when using Windows containers mode; `dockurr/windows` runs as a Linux container that emulates Windows.

### Running via Docker Compose

From the repository root:

```powershell
docker compose --profile windows-sandbox up --build
```

This starts the full stack plus the Windows sandbox. Ports:

- noVNC: `http://127.0.0.1:8006`
- RDP: `127.0.0.1:3389`
- SSH: `127.0.0.1:2222`

Samples are shared via the `Shared` folder on the Windows desktop. Credentials are auto-generated and exposed in the Web UI once the sandbox has started at least once.

### Standalone build (advanced)

For a minimal standalone image without the full OEM lab:

```powershell
cd sandbox/windows
docker build -t ai-re-sandbox-windows .
```

The Compose profile uses the same Dockerfile but wires OEM, bridge tools, and shared volumes from the root context.

### Feeding dynamic artifacts back into the web UI

The main web UI exposes the following endpoint for dynamic evidence:

- `POST /evidence/<job_id>`

The payload format is:

```json
{
  "artifacts": [
    {
      "type": "procmon",
      "source": "windows-sandbox",
      "highlights": [
        "Example highlight"
      ],
      "events": [
        {
          "timestamp": "2026-03-12T18:00:00Z",
          "operation": "WriteFile",
          "path": "C:\\\\SomePath\\\\file.txt"
        }
      ]
    }
  ]
}
```

You can design your sandbox workflow so that whatever telemetry you collect in `C:\sandbox\artifacts` is transformed into this JSON structure and then sent from your host to the web UI, keeping static and dynamic evidence side by side.

