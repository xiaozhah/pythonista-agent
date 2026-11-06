"""C through ppci and JavaScriptCore: programs must print what clang-compiled ones print.

c_programs/*.out were made by the Mac's clang (`clang -O1 -ffp-contract=off`, so floating point
rounds the same way as wasm). Runs where JavaScriptCore and ppci are available (macOS, Pythonista).
"""

from __future__ import annotations

import glob
import os
import time

import pytest

from pycoder.host.cwasm import jsc

if not jsc.available():
    pytest.skip('no JavaScriptCore here', allow_module_level=True)
pytest.importorskip('ppci')

from pycoder.host.cwasm.compiler import CompileError, compile_c
from pycoder.host.cwasm.runtime import JSError, WasmModule

PROGRAMS = sorted(glob.glob(os.path.join(os.path.dirname(__file__), 'c_programs', '*.c')))


def load(source: str, opt_level: int = 2, time_limit: float = 5.0) -> WasmModule:
    compiled = compile_c(source, opt_level=opt_level)
    return WasmModule(compiled.wasm, compiled.heap_base, time_limit=time_limit)


@pytest.mark.parametrize('path', PROGRAMS, ids=os.path.basename)
def test_programs_print_what_clang_builds_print(path: str) -> None:
    with open(path, encoding='utf-8') as f:
        module = load(f.read())
    with open(path[:-2] + '.out', encoding='utf-8') as f:
        want = f.read()
    try:
        assert module.missing == []
        code = module.call('main')
        assert module.stdout() == want
        assert code == (3 if path.endswith('12_libc.c') else 0)  # it ends with exit(3)
    finally:
        module.close()


# loops that ppci 0.5.8 got wrong before fixes.py (each: function, argument, expected result)
CONTROL_FLOW = """
int nested(int n){int c=0; for(int i=0;i<n;i++) for(int j=0;j<n;j++) c++; return c;}
int triple(int n){int c=0; for(int i=0;i<n;i++) for(int j=0;j<n;j++) for(int k=0;k<n;k++) c+=i+j*k; return c;}
int flagbreak(int n){int c=0; for(int i=2;i<n;i++){int p=1;
    for(int j=2;j*j<=i;j++){ if(i%j==0){p=0;break;}} c+=p;} return c;}
int nested_while(int n){int c=0,i=0,j; while(i<n){ j=0; while(j<n){c++; j++;} i++;} return c;}
int nested_do(int n){int c=0,i=0,j; do{ j=0; do{c++; j++;}while(j<n); i++;}while(i<n); return c;}
int cont(int n){int c=0; for(int i=0;i<n;i++){
    for(int j=0;j<n;j++){ if(j%2) continue; c++;} if(i==2) continue; c+=100;} return c;}
int retinner(int n){for(int i=0;i<n;i++) for(int j=0;j<n;j++) if(i*j==12) return i*10+j; return -1;}
int loop_in_if(int n){int c=0; if(n>3){ for(int i=0;i<n;i++) c+=i; } else { c=-1; }
    for(int k=0;k<2;k++) c++; return c;}
int jump(int n){int i=0; again: i++; if(i<n) goto again; return i;}
unsigned int fnv(int n){unsigned int h=2166136261u; for(int i=0;i<n;i++) h=(h^(i&255))*16777619u; return h;}
"""
EXPECTED = [
    ('nested', 5, 25),
    ('triple', 4, 240),
    ('flagbreak', 10000, 1229),
    ('nested_while', 5, 25),
    ('nested_do', 5, 25),
    ('cont', 5, 415),
    ('retinner', 10, 26),
    ('loop_in_if', 5, 12),
    ('jump', 7, 7),
]


@pytest.mark.parametrize('opt_level', [0, 2])
def test_control_flow(opt_level: int) -> None:
    module = load(CONTROL_FLOW, opt_level)
    try:
        for name, arg, want in EXPECTED:
            assert module.call(name, arg) == want, name
        h = 2166136261
        for i in range(1000):
            h = ((h ^ (i & 255)) * 16777619) & 0xFFFFFFFF
        assert int(module.call('fnv', 1000)) & 0xFFFFFFFF == h  # unsigned arithmetic wraps at 2**32
    finally:
        module.close()


@pytest.mark.parametrize(
    'source',
    [
        'int f(int n){ int c=0; while(n) c++; return c; }',
        'int f(int n){ for(;;){ for(int i=0;i<n;i++) {} if (!n) break; } return 0; }',
        'int g(int n); int f(int n){ return g(n); } int g(int n){ int c=0; if (n) c = f(n); return c+1; }',
    ],
    ids=['while', 'nested-for', 'recursion'],
)
def test_runaway_code_is_stopped_and_the_module_stays_usable(source: str) -> None:
    module = load(source, time_limit=0.3)
    try:
        started = time.time()
        with pytest.raises(JSError):
            module.call('f', 1)
        assert time.time() - started < 3
        assert module.call('f', 0) in (0, 1)
    finally:
        module.close()


def test_compile_errors_point_at_the_line() -> None:
    with pytest.raises(CompileError) as e:
        compile_c('int main(void) {\n  int x = 1\n  return x;\n}\n')
    message = str(e.value)
    assert message.startswith('main.c:3:')
    assert 'return x;' in message
    assert '^' in message


def test_unsupported_struct_by_value_says_what_to_do() -> None:
    source = 'typedef struct { int a, b; } P;\nint sum(P p) { return p.a + p.b; }\n'
    source += 'int main(void) { P q = {1, 2}; return sum(q); }\n'
    with pytest.raises(CompileError, match='pass a pointer'):
        compile_c(source)


def test_limits_on_memory_and_output() -> None:
    source = """
    #include <stdio.h>
    #include <stdlib.h>
    int big(void) { return malloc(300000000) == NULL; }
    int chatty(void) { for (int i = 0; i < 100000; i++) printf("line %d\\n", i); return 0; }
    """
    module = load(source)
    try:
        assert module.call('big') == 1  # past the heap limit: NULL, not an app killed by iOS
        module.call('chatty')
        out = module.stdout()
        assert out.startswith('line 0\n')
        assert out.endswith('line 99999\n')
        assert 'characters of output left out' in out
        assert len(out) < 50000
    finally:
        module.close()


def test_fixes_do_not_stack_when_pycoder_is_reimported() -> None:
    """The bridge drops and reimports pycoder between runs while ppci stays loaded (and patched).
    Applying the fixes again must not wrap the already-patched ppci a second time; it used to, and
    each compile then stacked another js.__fuel_out import until the module no longer ran."""
    import importlib
    import sys

    source = 'int main(void) { return 0; }'
    from pycoder.host.cwasm import compiler

    assert compiler.compile_c(source).wasm.count(b'__fuel_out') == 1
    for name in [n for n in list(sys.modules) if n.startswith('pycoder.host.cwasm')]:
        del sys.modules[name]  # as a fresh run would, leaving ppci as it is
    again = importlib.import_module('pycoder.host.cwasm.compiler')
    assert again.compile_c(source).wasm.count(b'__fuel_out') == 1
