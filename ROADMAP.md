# GhostTrace Roadmap

GhostTrace already works as a usable reverse engineering workbench. This roadmap is about where the next sharp edges should go, not about pretending every idea deserves code today.

## Guiding idea

Keep the core tight:

- static triage first
- dynamic evidence where it earns its keep
- debugger context without losing the plot
- one trail of evidence instead of five disconnected tools

## Now

### 1. Benchmark corpus for real-world validation

GhostTrace needs a stable bench of public samples and PoCs so the workflow can be exercised end to end instead of only on ad-hoc uploads.

Targets:

- public Windows driver and userland PoCs
- installers and large binaries
- samples with clear imports / strings / function-map behavior
- samples that benefit from debugger context

Initial references:

- `alfarom256/HPHardwareDiagnostics-PoC`
- `alfarom256/LogMeInPoCHandleDup`
- additional Windows PoCs from `alfarom256`

Deliverables:

- [`samples/benchmarks.md`](./samples/benchmarks.md)
- repeatable validation checklist per sample
- notes about where GhostTrace is strong or still clumsy

### 2. Better sample typing in triage

The current triage is useful, but it should start classifying what kind of binary it is looking at.

Proposed `sample_type` values:

- `driver`
- `userland`
- `dotnet`
- `installer`
- `firmware`
- `java`
- `unknown`

Immediate payoff:

- better triage prompts
- better next-step recommendations
- better debugger guidance

### 3. Windows PoC triage heuristics

GhostTrace should get better at recognizing common Windows PoC patterns:

- vulnerable driver abuse
- handle duplication
- arbitrary read / write
- privilege escalation indicators
- direct `Nt*` / syscall-heavy behavior
- service / registry / process manipulation

## Next

### 4. Windows syscall tracing lane

This is the most compelling next feature.

Goal:

- ingest `NTAPI -> syscall` telemetry from the Windows lab
- correlate it with imports, strings, functions, and debugger activity
- expose it as dynamic evidence, not as a disconnected side channel

Primary references:

- `paranoidninja/PI-Tracker`
- `paranoidninja/Process-Instrumentation-Syscall-Hook`

Why it matters:

- catches behavior that static triage only hints at
- gives the operator something more meaningful than “the binary looked suspicious”
- fits the existing `Dynamic Evidence` lane naturally

### 5. .NET tracing lane

Goal:

- recognize `.NET`-heavy samples early
- pull useful runtime evidence into the same workspace
- stop treating managed binaries like second-class citizens

Primary reference:

- `paranoidninja/DotNetTracer`

### 6. IPC / named pipe telemetry

Goal:

- collect named pipe / IPC activity from the sandbox
- feed it into triage, evidence, and debugger-aware workflows

Primary reference:

- `alfarom256/smokescreen`

## Later

### 7. Firmware / UEFI lane

GhostTrace could eventually grow a more specialized firmware path.

Primary reference:

- `REhints/efiXplorer`

This is not core for the first expansion wave, but it is one of the clearest long-range directions if the project keeps growing.

### 8. Java / JDWP lane

Goal:

- better support for JVM targets
- debugger-aware workflows for Java processes
- bridge-style operations for managed runtimes

Primary reference:

- `alfarom256/jditinker`

### 9. Dynamic evidence packs

GhostTrace already ingests dynamic evidence. The next jump is to make that ingestion more opinionated and more useful.

Candidate packs:

- Sysmon evidence
- ETW evidence
- process tree evidence
- file / registry / network evidence
- VirusTotal or reputation lookups

Primary inspiration:

- `paranoidninja/Threat-Hunting`

## What should not happen

Things that would make GhostTrace worse:

- bolting in offensive PoCs directly as product dependencies
- turning the workbench into a generic “AI wrapper” over every tool in sight
- adding five new analysis lanes before the current Windows workflow feels boringly reliable
- letting dynamic evidence become a second product with its own UX and memory model

## Practical next slice

If time is limited, the best next slice is:

1. build the benchmark corpus
2. add `sample_type` to triage
3. prototype syscall tracing ingestion

That would move GhostTrace forward without bloating it.
