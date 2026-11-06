---
name: webassembly-in-javascriptcore
description: "Use when compiled code (Rust, C, Go, Zig) should run on the device, or CPU work needs parallel workers isolated from each other: WebAssembly in JavaScriptCore and a pool of VMs."
---

JavaScriptCore is an Apple-signed JIT, so it runs WebAssembly at near-native speed. iOS can't run the toolchain, but it runs the output: compile any wasm32 language off the device, ship the `.wasm` bytes, and `new WebAssembly.Instance(new WebAssembly.Module(bytes), imports)` in a `JSContext`.

- An i64 comes back as a JS `BigInt`. SIMD (v128) works. Imports are plain JS functions the module calls.
- `run_c` is the on-device case: see `run-c-code`.

## A pool of workers

The closest thing to `multiprocessing`: N threads, each with its own VM running the same module.

```python
vm = ObjCClass('JSVirtualMachine').alloc().init()
context = ObjCClass('JSContext').alloc().initWithVirtualMachine_(vm)
```

- **One VM per thread.** Contexts sharing a group, which is what `jsc.Context` gives, serialize and even contend: slower than one thread.
- Hand out tasks and collect results over `queue.Queue`. Pass data as copied buffers: each VM has its own linear memory.
- A trap (division by zero, `unreachable`) arrives as a `RuntimeError`, and the worker survives.
- An infinite loop hangs its worker with no way to stop it from Python: set `JSContextGroupSetExecutionTimeLimit`, and compile with loop fuel, as `run_c` does.
- Only the WASM is isolated: a native crash in `ctypes` or `objc_util` still ends the process.
