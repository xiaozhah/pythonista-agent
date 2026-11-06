---
name: posix-in-process
description: "Use when a program needs threads talking to each other, sockets, mmap, file tricks, system information or Darwin notifications inside Pythonista's process."
---

Everything POSIX works in-process, except what needs a second process.

- **Files:** read the visible filesystem, read and write the app's container; symlinks, hardlinks, `chmod`, `statvfs`, `mmap`, `sendfile`, `/dev/{null,zero,random,urandom}`.
- **Between threads:** `os.pipe`, `os.mkfifo`, `socket.socketpair`, `AF_UNIX` sockets (bind a short path: the container's overflows `sun_path`), anonymous `mmap`, `select`/`poll`, `fcntl.flock`. No SysV or POSIX shared memory.
- **Network:** TCP, UDP, IPv6, loopback, LAN (bind `0.0.0.0`), DNS, TLS through `ssl`. Raw sockets are denied.
- **libc:** `ctypes.CDLL(None)` gives `sysctlbyname`, clocks, `getrlimit`, `uname` and the rest of libSystem.
- **Darwin notify:** `notify_post`, `notify_register_check`, `notify_check`, `notify_get_state`: signals through `notifyd`, plus state daemons publish (`com.apple.system.powersources.timeremaining`, timezone, clock). Let a post settle before `notify_check`.
- **Mach telemetry:** `mach_host_self`, `mach_task_self`, `host_statistics` (VM and CPU), `task_info` (this process's memory), `host_info`.
- **Data:** `sqlite3`, `zlib`, `bz2`, `gzip`, `hashlib`, `hmac`, `secrets`.

## Traps

- `signal.signal` works only on the console's main thread, a CPython rule. Worker threads can't call it.
- Missing from the standard library: `lzma`, `readline`, `curses`, `pty`.
- `sandbox_check()` says "denied" for much that works: try the operation instead.
- Don't reach daemons at the raw layer: `xpc_connection_send_message_*` crashes the process. Use the frameworks (NSUserDefaults, UIPasteboard, SCNetworkReachability).
