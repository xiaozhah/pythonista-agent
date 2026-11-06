---
name: process-capabilities
description: "Use when something needs a second process, a shell, a compiled/native package, real parallelism, or native speed: what the Pythonista process can and cannot do, and the right in-process tool for each."
---

The process has a near-complete Darwin/UNIX userland and the whole Apple framework stack. The OS forbids exactly two things. Don't re-test them: the second one kills the app.

## The two walls

1. **No second process.** `fork`, `posix_spawn` and `exec` fail with EPERM, and `NSTask` is blocked. So no `subprocess`, shell, `os.system` or pty, and `multiprocessing`'s process pools don't work.
2. **No unsigned native code.** The moment the CPU runs a page without Apple's signature, the process dies; `MAP_JIT` needs an entitlement the app lacks. So no externally compiled `.dylib`, which is why compiled packages can't be installed. Only Apple-signed code runs, including Apple's own JITs.

## Picking a path

| Need | Use |
| --- | --- |
| Array maths at speed | `accelerate-maths`, threads for what releases the GIL |
| Big parallel work on the GPU | `metal-compute`, or MPS / `MPSGraph` |
| Any compiled language, or isolated parallel workers | `webassembly-in-javascriptcore` |
| A C program as it is | `run-c-code` |
| OCR, labels, language, Core ML | `vision-and-language` |
| Threads talking, sockets, mmap, system information | `posix-in-process` |
| Another app on the device | `cooperating-apps` |

Threads give real parallelism only for work that releases the GIL: numpy, `hashlib`, `ssl`, Accelerate, JavaScriptCore. `dispatch_apply` from GCD (via `ctypes.CDLL(None)`) adds no throughput over threads; use it only to sit on framework callbacks.

## Reachable through `ctypes` and `objc_util`

- Compute and ML: Accelerate, Metal, MPSGraph, CoreML, Vision, NaturalLanguage, Speech, SoundAnalysis.
- Media: AVFoundation, CoreImage, CoreAudio, ImageIO, CoreGraphics.
- System: Network, CFNetwork, SystemConfiguration, CoreMotion, CoreLocation, Contacts, EventKit, Photos, LocalAuthentication, CoreBluetooth, CoreNFC.

A crash in `ctypes` or `objc_util`, or running out of memory, takes the whole process down: there is no child to isolate it.
