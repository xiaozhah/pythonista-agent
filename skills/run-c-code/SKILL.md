---
name: run-c-code
description: "Use when C code should be run or ported on the device with the run_c tool: what it supports, its limits, and when it is the wrong tool."
---

`run_c` compiles one C file with ppci (a pure-Python compiler, installed on first use) to WebAssembly and runs its `main()` in JavaScriptCore: you get what it prints, its exit code, or the compile error with its line.

It is for logic, not speed: this path is nowhere near native. For speed use `accelerate-maths` or `metal-compute`.

**Works:** C99 in one file; int, `long long`, unsigned arithmetic (wraps like C), char, short, float, double, pointers, arrays, structs (assignment and return), initialized globals, function pointers, recursion, goto. `long` and pointers are 32 bits.

**Library:** `printf`, `sprintf`, `snprintf`, `puts`, `putchar`, `malloc`, `calloc`, `realloc`, `free`, `exit`, `rand`, `srand`, `atoi`, `atof`, `assert`, `clock`, and the common string.h, ctype.h and math.h functions, limits.h, stdint.h, stdbool.h. A function outside it is reported with the full list; write it yourself in the program.

**Not supported:** passing a struct by value to a function (pass a pointer), files and stdin, threads, other libraries.

**Limits:** `timeout` (default 10 s, at most 300; infinite loops are stopped), a 1 MB stack, a 256 MB heap (`malloc` returns NULL past it), and the output keeps its first and last 20,000 characters.
