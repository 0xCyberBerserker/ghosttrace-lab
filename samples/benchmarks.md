# GhostTrace Benchmark Bench

This file tracks public samples and proof-of-concepts that are useful for validating GhostTrace as a workbench, not just as a demo.

The point is simple:

- feed real binaries through the workflow
- see where triage is sharp
- see where debugger context helps
- keep a repeatable paper trail instead of hand-wavy “it worked on my sample”

## Validation checklist

Use this for every sample:

- upload succeeds
- `job_id` resolves cleanly
- status transitions are sane
- strings are extracted
- imports are extracted
- functions list becomes available
- triage report is generated
- triage suggestions feel relevant
- chat can reason over the sample
- x64dbg lane can attach or at least provide meaningful follow-up
- dynamic evidence can be added without breaking the job

## Sample types

Use one of these when adding new samples:

- `driver`
- `userland`
- `dotnet`
- `installer`
- `firmware`
- `java`
- `unknown`

## Priority samples

### 1. HPHardwareDiagnostics-PoC

- Source: [alfarom256/HPHardwareDiagnostics-PoC](https://github.com/alfarom256/HPHardwareDiagnostics-PoC)
- Type: `driver`
- Why it matters:
  - vulnerable driver PoC
  - good for imports, strings, and privilege-escalation style triage
  - useful debugger target for Windows-focused analysis

### 2. LogMeInPoCHandleDup

- Source: [alfarom256/LogMeInPoCHandleDup](https://github.com/alfarom256/LogMeInPoCHandleDup)
- Type: `userland`
- Why it matters:
  - handle duplication behavior
  - good fit for imports, process logic, and debugger follow-up

### 3. Archetype Petrucci X Installer

- Local benchmark already used in this repo
- Type: `installer`
- Why it matters:
  - large binary
  - stresses upload, analysis time, cache behavior, and triage generation
  - good for installer-path reasoning

## Future benchmark lanes

### Java

- Reference source: [alfarom256/jditinker](https://github.com/alfarom256/jditinker)
- Why:
  - future `java` / JDWP lane
  - useful when GhostTrace grows beyond native Windows binaries

### Firmware / UEFI

- Reference source: [REhints/efiXplorer](https://github.com/REhints/efiXplorer)
- Why:
  - future `firmware` lane
  - helps frame what “specialized GhostTrace” could become later

### Syscall / telemetry-heavy Windows samples

- Reference sources:
  - [paranoidninja/PI-Tracker](https://github.com/paranoidninja/PI-Tracker)
  - [paranoidninja/Process-Instrumentation-Syscall-Hook](https://github.com/paranoidninja/Process-Instrumentation-Syscall-Hook)
- Why:
  - future dynamic evidence lane for syscall tracing
  - useful when validating `Dynamic Evidence` and debugger-aware workflows

### .NET

- Reference source: [paranoidninja/DotNetTracer](https://github.com/paranoidninja/DotNetTracer)
- Why:
  - future managed-code lane
  - useful when validating `.NET`-aware triage

### IPC / named pipes

- Reference source: [alfarom256/smokescreen](https://github.com/alfarom256/smokescreen)
- Why:
  - future IPC telemetry lane
  - useful for pipe-heavy Windows tooling

## Notes

This bench is intentionally pragmatic.

It is not a malware zoo, not a “cool PoC” scrapbook, and not an excuse to hoard binaries.

If a sample does not teach GhostTrace something, it does not belong here.
