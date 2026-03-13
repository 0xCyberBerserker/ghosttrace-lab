<div align="center">
  <h1>👻 GhostTrace</h1>
  <p><strong>Reverse engineering with operator-grade workflows, debugger context, sandbox trails, and less tab graveyard energy.</strong></p>
  <p><strong>Reverse engineering con flujos de operador de verdad, contexto de depuración, rastro de sandbox y menos vibra de cementerio de pestañas.</strong></p>
  <p>
    <a href="https://0xcyberberserker.github.io/ghosttrace-lab/"><img alt="site" src="https://img.shields.io/badge/site-ghosttrace--lab-0a1324?style=for-the-badge&logo=githubpages&logoColor=46f3ff&labelColor=07111d"></a>
    <img alt="ollama" src="https://img.shields.io/badge/ollama-local-0a1324?style=for-the-badge&logo=ollama&logoColor=ffffff&labelColor=07111d">
    <img alt="model" src="https://img.shields.io/badge/model-qwen3.5--abliterated%3A4b-0a1324?style=for-the-badge&logo=openai&logoColor=ff4fd8&labelColor=07111d">
  </p>
  <p>
    <img alt="backend" src="https://img.shields.io/badge/backend-ghidraaas-0a1324?style=for-the-badge&logo=gnuprivacyguard&logoColor=46f3ff&labelColor=07111d">
    <img alt="sandbox" src="https://img.shields.io/badge/lab-windows%20sandbox-0a1324?style=for-the-badge&logo=windows11&logoColor=46f3ff&labelColor=07111d">
    <img alt="debugger" src="https://img.shields.io/badge/debugger-x64dbg%20bridge-0a1324?style=for-the-badge&logo=gnubash&logoColor=a6ff47&labelColor=07111d">
  </p>
  <p>
    Made with 🖤 in Barcelona City
    <img alt="Flag of Spain" src="./docs/assets/spain-flag.svg" height="16">
  </p>
</div>

- [English](#english)
- [Español](#español)

---

## English

GhostTrace ties together a cyberpunk operator UI, `Ghidraaas` for static analysis, `Ollama` for local reasoning, cached triage artifacts, and a reproducible Windows sandbox lab with SSH and debugger bridge support.

### Highlights

- Static-analysis-first workflow powered by `Ghidraaas`
- Local LLM integration via `Ollama` and `huihui_ai/qwen3.5-abliterated:4b`
- Cached imports, strings, functions, and decompilation
- Auto-generated triage reports per analysis job
- Persistent job management in the web UI
- Windows sandbox profile with `noVNC`, `RDP`, and `SSH`
- `x64dbg` bridge for debugger-aware workflows

### Responsibility Note

GhostTrace is built for legitimate reverse engineering, malware analysis, DFIR, research, and defensive engineering.

Like any serious binary-analysis stack, it can be misused. That decision belongs to the operator, not the project. If you point GhostTrace at targets, software, or environments without proper authorization, you own the legal, ethical, and operational consequences. Use it smart. Use it lawfully. Good hands. Better judgment.

### Architecture

```text
Binary Upload -> Web UI -> Ghidraaas -> Cached Artifacts -> AI Operator / Chat / Triage
                                      \-> Sandbox Queue -> Windows Lab -> x64dbg Bridge
```

Core components:

- `webui/`
  Flask application, job management, AI operator, chat, triage view, and debugger view.
- `Ghidraaas/`
  Cisco Talos Ghidra-as-a-Service backend adapted for this stack.
- `sandbox/`
  Windows sandbox provisioning, host-side SSH helpers, bridge tooling, and OEM automation.
- `docs/`
  Public landing page for GitHub Pages.

### Quick Start

1. Build `Ghidraaas`:

```powershell
cd Ghidraaas
docker build -t ghidraaas .
```

2. Start the stack from the repository root:

```powershell
docker compose up --build
```

3. Open the app:

```text
http://localhost:5000
```

### Requirements

- Docker Desktop
- Ollama running on the host
- local model available:

```text
huihui_ai/qwen3.5-abliterated:4b
```

### Shared AI Configuration

GhostTrace keeps its shared AI runtime settings in [`ai-config.json`](./ai-config.json).

Current defaults:

- provider: `ollama`
- API base: `http://host.docker.internal:11434/v1`
- model: `huihui_ai/qwen3.5-abliterated:4b`

The repo is aligned so the same Ollama model is used on both sides:

- `webui` uses `MODEL_NAME=huihui_ai/qwen3.5-abliterated:4b`
- `windows_sandbox` uses `OLLAMA_MODEL=huihui_ai/qwen3.5-abliterated:4b`

### Analysis Workflow

- `Static Triage`
  Understand likely purpose, suspicious subsystems, installer behavior, and priority code paths.
- `PE / API Behavior`
  Use imports and decompilation to reason about registry, file, service, crypto, and process behavior.
- `Network Clues`
  Surface likely telemetry, update, or remote communication paths from static evidence.
- `Dynamic Correlation`
  Bring in sandbox findings and debugger evidence without losing the static-analysis context.

### Auto Triage Reports

Endpoint:

```text
GET /triage/<job_id>
```

Artifacts:

- JSON: `/app/data/triage_reports/<job_id>.json`
- Markdown: `/app/data/triage_reports/<job_id>.md`

Behavior:

- triage is queued automatically after upload
- triage is regenerated when new dynamic evidence is added
- the endpoint returns `202` while required artifacts are still being prepared

To enable LLM-authored triage prose:

```text
TRIAGE_USE_LLM=1
```

### Dynamic Evidence Lane

GhostTrace does not autonomously execute unknown binaries as part of the default workflow. Instead, it supports structured evidence ingestion from controlled environments.

Endpoints:

```text
POST /evidence/<job_id>
GET  /evidence/<job_id>
```

This lets the platform correlate imports, strings, decompilation, sandbox artifacts, and debugger findings.

### Windows Sandbox Lab

The optional `windows-sandbox` profile provides:

- `noVNC` on `http://127.0.0.1:8006`
- `RDP` on `127.0.0.1:3389`
- `SSH` on `127.0.0.1:2222`
- shared samples through the `Shared` desktop folder

#### Default local lab credentials

- username: `Docker`
- password: `admin`

These defaults are only meant for a disposable local lab. If you expose the sandbox beyond localhost, change them immediately.

### Host-Side Helpers

Windows helpers:

- [`Invoke-WindowsSandboxSSH.ps1`](./sandbox/host-tools/Invoke-WindowsSandboxSSH.ps1)
- [`Invoke-WindowsSandboxPS.ps1`](./sandbox/host-tools/Invoke-WindowsSandboxPS.ps1)
- [`Copy-ToWindowsSandbox.ps1`](./sandbox/host-tools/Copy-ToWindowsSandbox.ps1)
- [`Copy-FromWindowsSandbox.ps1`](./sandbox/host-tools/Copy-FromWindowsSandbox.ps1)

Generic helpers:

- [`Invoke-SandboxSSH.ps1`](./sandbox/host-tools/Invoke-SandboxSSH.ps1)
- [`Copy-ToSandbox.ps1`](./sandbox/host-tools/Copy-ToSandbox.ps1)
- [`Copy-FromSandbox.ps1`](./sandbox/host-tools/Copy-FromSandbox.ps1)

### Public Site

The landing page lives in [`docs/index.html`](./docs/index.html) and is published on GitHub Pages:

- [https://0xcyberberserker.github.io/ghosttrace-lab/](https://0xcyberberserker.github.io/ghosttrace-lab/)
- English: [https://0xcyberberserker.github.io/ghosttrace-lab/en/](https://0xcyberberserker.github.io/ghosttrace-lab/en/)
- Español: [https://0xcyberberserker.github.io/ghosttrace-lab/es/](https://0xcyberberserker.github.io/ghosttrace-lab/es/)

---

## Español

GhostTrace reúne una interfaz de operador con estética cyberpunk, `Ghidraaas` para análisis estático, `Ollama` para razonamiento local, artefactos de triage en caché y un laboratorio Windows reproducible con SSH y un puente de depuración.

### Puntos fuertes

- Flujo centrado en análisis estático apoyado por `Ghidraaas`
- Integración local con `Ollama` y `huihui_ai/qwen3.5-abliterated:4b`
- Caché de imports, strings, funciones y decompilación
- Informes de triage automáticos por análisis
- Gestión persistente de trabajos en la interfaz
- Perfil de sandbox Windows con `noVNC`, `RDP` y `SSH`
- Puente de `x64dbg` para flujos de depuración asistida

### Nota de responsabilidad

GhostTrace está pensado para reverse engineering legítimo, análisis de malware, DFIR, investigación y trabajo defensivo.

Como cualquier stack serio de análisis binario, puede usarse mal. Esa decisión pertenece al operador, no al proyecto. Si apuntas GhostTrace contra objetivos, software o entornos sin la debida autorización, asumes toda la responsabilidad por las consecuencias legales, éticas y operativas. Úsalo con cabeza. Úsalo dentro de la ley. Buen pulso. Mejor criterio.

### Arquitectura

```text
Subida binaria -> Web UI -> Ghidraaas -> Artefactos cacheados -> AI Operator / Chat / Triage
                                         \-> Cola sandbox -> Laboratorio Windows -> Puente x64dbg
```

Componentes principales:

- `webui/`
  Aplicación Flask, gestión de trabajos, operador IA, chat, vista de triage y vista del depurador.
- `Ghidraaas/`
  Backend Ghidra-as-a-Service de Cisco Talos adaptado a este stack.
- `sandbox/`
  Aprovisionamiento de sandbox Windows, utilidades SSH desde el host, herramientas del puente y automatización OEM.
- `docs/`
  Landing pública para GitHub Pages.

### Puesta en marcha

1. Construye `Ghidraaas`:

```powershell
cd Ghidraaas
docker build -t ghidraaas .
```

2. Arranca el stack desde la raíz del repositorio:

```powershell
docker compose up --build
```

3. Abre la app:

```text
http://localhost:5000
```

### Requisitos

- Docker Desktop
- Ollama en ejecución en el host
- modelo disponible localmente:

```text
huihui_ai/qwen3.5-abliterated:4b
```

### Configuración compartida de IA

GhostTrace mantiene la configuración compartida en [`ai-config.json`](./ai-config.json).

Valores actuales:

- proveedor: `ollama`
- API base: `http://host.docker.internal:11434/v1`
- modelo: `huihui_ai/qwen3.5-abliterated:4b`

El repo está alineado para usar el mismo modelo en ambos lados:

- `webui` usa `MODEL_NAME=huihui_ai/qwen3.5-abliterated:4b`
- `windows_sandbox` usa `OLLAMA_MODEL=huihui_ai/qwen3.5-abliterated:4b`

### Flujo de análisis

- `Triage estático`
  Entender el propósito probable, los subsistemas sospechosos, el comportamiento del instalador y las rutas de código prioritarias.
- `Comportamiento PE / API`
  Usar imports y decompilación para razonar sobre registro, ficheros, servicios, criptografía y procesos.
- `Pistas de red`
  Sacar pistas de telemetría, actualización o comunicación remota a partir de evidencia estática.
- `Correlación dinámica`
  Mezclar hallazgos de la sandbox y del depurador sin perder el contexto del análisis estático.

### Informes automáticos de triage

Endpoint:

```text
GET /triage/<job_id>
```

Artefactos:

- JSON: `/app/data/triage_reports/<job_id>.json`
- Markdown: `/app/data/triage_reports/<job_id>.md`

Comportamiento:

- el triage se encola automáticamente tras la subida
- se regenera al añadir evidencia dinámica
- el endpoint devuelve `202` mientras falten artefactos necesarios

Para activar prosa de triage generada por LLM:

```text
TRIAGE_USE_LLM=1
```

### Canal de evidencia dinámica

GhostTrace no ejecuta binarios desconocidos automáticamente en el flujo por defecto. En su lugar, soporta ingestión estructurada de evidencia desde entornos controlados.

Endpoints:

```text
POST /evidence/<job_id>
GET  /evidence/<job_id>
```

Esto permite correlacionar imports, strings, decompilación, artefactos de sandbox y hallazgos del depurador.

### Laboratorio Windows

El perfil opcional `windows-sandbox` ofrece:

- `noVNC` en `http://127.0.0.1:8006`
- `RDP` en `127.0.0.1:3389`
- `SSH` en `127.0.0.1:2222`
- muestras compartidas a través de la carpeta `Shared`

#### Credenciales locales por defecto

- usuario: `Docker`
- contraseña: `admin`

Estas credenciales están pensadas solo para un laboratorio local desechable. Si expones la sandbox fuera de localhost, cámbialas inmediatamente.

### Utilidades desde el host

Utilidades para Windows:

- [`Invoke-WindowsSandboxSSH.ps1`](./sandbox/host-tools/Invoke-WindowsSandboxSSH.ps1)
- [`Invoke-WindowsSandboxPS.ps1`](./sandbox/host-tools/Invoke-WindowsSandboxPS.ps1)
- [`Copy-ToWindowsSandbox.ps1`](./sandbox/host-tools/Copy-ToWindowsSandbox.ps1)
- [`Copy-FromWindowsSandbox.ps1`](./sandbox/host-tools/Copy-FromWindowsSandbox.ps1)

Utilidades genéricas:

- [`Invoke-SandboxSSH.ps1`](./sandbox/host-tools/Invoke-SandboxSSH.ps1)
- [`Copy-ToSandbox.ps1`](./sandbox/host-tools/Copy-ToSandbox.ps1)
- [`Copy-FromSandbox.ps1`](./sandbox/host-tools/Copy-FromSandbox.ps1)

### Web pública

La landing vive en [`docs/index.html`](./docs/index.html) y se publica en GitHub Pages:

- [https://0xcyberberserker.github.io/ghosttrace-lab/](https://0xcyberberserker.github.io/ghosttrace-lab/)
- Inglés: [https://0xcyberberserker.github.io/ghosttrace-lab/en/](https://0xcyberberserker.github.io/ghosttrace-lab/en/)
- Español: [https://0xcyberberserker.github.io/ghosttrace-lab/es/](https://0xcyberberserker.github.io/ghosttrace-lab/es/)
