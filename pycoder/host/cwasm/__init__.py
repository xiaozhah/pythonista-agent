"""C programs in Pythonista: compiled to WebAssembly by ppci and run by JavaScriptCore, in-process.

Pythonista cannot load machine code it didn't ship with (iOS code signing), so C can't be
compiled to native code here. What is possible: ppci, a C compiler written in pure Python, turns
C into WebAssembly, and JavaScriptCore (an Apple framework, reached through its C API with
ctypes) runs that. The result runs a few times faster than the same algorithm in CPython.

    compiler.py   C -> wasm with ppci; fixes.py patches ppci's miscompilations at run time
    jsc.py        JavaScriptCore's C API: synchronous calls, no Objective-C blocks
    runtime.py    loads a module and calls it; runtime.js is the C library it gets (printf, malloc, …)
    include/      the headers C code can include, matching what runtime.js provides

ppci is installed on first use (`PPCI`); it is pure Python, so it works on iOS.
"""

PPCI = 'ppci==0.5.8'  # fixes.py patches this exact version's internals
