---
name: cooperating-apps
description: "Use when Pythonista should exchange data with another app on the same device: what crosses the sandbox, and what doesn't."
---

Apps can't read each other's containers (EPERM both ways), list other processes, or share a writable folder without an app group. Three channels do cross, between apps that both cooperate:

- **Loopback TCP.** One app connects to a port the other bound on `127.0.0.1`, so each can offer what its own sandbox has through a small server.
- **The system clipboard.** `UIPasteboard`, kept by the system, so it survives either app going to the background.
- **Darwin notify.** Signals only: see `posix-in-process`.

iOS suspends a backgrounded app, and its server stops answering. For live traffic both must be in front, as with Split View on an iPad.
