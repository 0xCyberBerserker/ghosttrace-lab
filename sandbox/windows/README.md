## Windows sandbox container

This directory defines a minimal Windows container that you can use as a manual sandbox for executing binaries and collecting dynamic artifacts that feed the main AI Reverse Engineering stack.

### Base image

The sandbox uses the official Windows base image from Microsoft:

- Image: `mcr.microsoft.com/windows:ltsc2019`
- Reference: `https://hub.docker.com/r/microsoft/windows`

Windows containers require a matching Windows host build and Docker configured in **Windows containers** mode (not Linux containers). You cannot run this container side by side with the existing Linux-based services (`ghidraaas`, `webui`) on the same Docker engine instance.

### Building the sandbox image

From the repository root, run:

```powershell
cd sandbox/windows
docker build -t ai-re-sandbox-windows .
```

### Running the sandbox

To start an interactive sandbox session:

```powershell
docker run --rm -it ai-re-sandbox-windows
```

This drops you into `cmd.exe` inside the container, with `C:\sandbox` as the working directory.

You can also mount a host directory containing binaries and an output directory for artifacts, for example:

```powershell
docker run --rm -it ^
  -v C:\path\to\samples:C:\sandbox\samples ^
  -v C:\path\to\artifacts:C:\sandbox\artifacts ^
  ai-re-sandbox-windows
```

Inside the container you can then:

- Copy a binary from `C:\sandbox\samples`
- Execute it under the constraints you choose (e.g., with additional tooling installed in a derived image)
- Save logs, traces, or other dynamic evidence into `C:\sandbox\artifacts`

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

