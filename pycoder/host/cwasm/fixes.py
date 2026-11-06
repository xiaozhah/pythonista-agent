"""Run-time fixes for ppci 0.5.8's C -> wasm path (applied by compiler.py; ppci itself is untouched).

1. Nested loops: graph/relooper.StructureDetector only knew break/continue of the innermost loop.
   A jump from an inner loop to an outer loop's header or exit (every nested `for`) was dropped, so
   outer loops ran once or not at all. Jumps are resolved against the whole loop stack and emitted
   as multi-level `br`.
2. C99 `for (int j = 0; ...)` ran its initializer once, before the enclosing statement, instead of
   each time the loop starts; and `continue` in a for-loop skipped the `i++` (an endless loop).
3. mem2reg leaves 'undefined' phi inputs for variables declared inside loops, which the wasm
   backend cannot emit (NotImplementedError: UNDI32); they are emitted as zero constants.
4. Not a bug fix: loop fuel. Every loop iteration decrements a wasm global; at zero it calls the
   import js.__fuel_out(), which throws past the deadline (else refills). JavaScriptCore's time
   limit stops JavaScript but not wasm loops, so without this a `while (1);` would hang Pythonista.
   The stack pointer global is exported so the host can reset it after a trap.
5. Integer types: `unsigned int` lived in 64-bit registers, so it never wrapped at 2**32. u32 now
   lives in i32 with the unsigned div/rem/shr/compare forms; every int->int cast wraps/extends and
   then narrows (ppci treated narrowing casts as no-ops); float->int casts truncate ((int)3.99 was 4).
6. Float literals: `1.5f` and `1e-10` (an exponent without a point) were syntax errors.
7. Global initializers holding addresses (`char *names[] = {"a", "b"}`, `int *p = &x`, function
   pointers) crashed the backend; they are laid out with the right addresses.
8. Struct copies (`a = b`, returning a struct) were unimplemented; emitted as word-by-word copies.
   Passing a struct BY VALUE as a parameter is still unsupported (compiler.py says so).
9. Speed, not correctness: a peephole pass drops redundant local copies and fuses
   `local.set X; local.get X` into `local.tee X`. JSC interprets wasm on iOS (no JIT), so
   instruction count matters.
"""

from __future__ import annotations

from typing import Any

_applied = False
FUEL = 1 << 20  # loop iterations between deadline checks


def apply() -> None:
    global _applied
    if _applied:
        return
    from ppci.graph import relooper
    from ppci.graph.relooper import BasicShape, BreakShape, ContinueShape, IfShape, LoopShape, SequenceShape
    from ppci.wasm import components
    from ppci.wasm.ppci2wasm import IrToWasmCompiler

    # ppci is not a pycoder module, so it stays imported (and patched) while this module is dropped and
    # reimported between runs — re-running the bridge, say. _applied resets with the reimport; the mark
    # on ppci itself does not. Without it, each compile would wrap the already-wrapped methods again and
    # stack duplicate fuel imports and globals into every module, which then fails to run.
    if getattr(IrToWasmCompiler, '_pycoder_fixed', False):
        _applied = True
        return

    class StructureDetector(relooper.StructureDetector):  # type: ignore[misc]
        def _jump(self, node: Any) -> Any:
            """A jump to an enclosing loop's header or follow block: continue/break at that level."""
            for level, (loop, follow) in enumerate(reversed(self.loop_stack[1:])):
                if node is loop.header:
                    return ContinueShape(level)
                if follow is not None and node is follow:
                    return BreakShape(level)
            return None

        def test(self, node: Any) -> Any:
            if node in self.marked:
                return self._jump(node)
            return self.make_shape(node)

        def make_shape(self, entry: Any) -> Any:
            if entry is self.cfg.exit_node:
                return None
            if self.is_inactive_header(entry):
                loop = self.loop_headers[entry]
                follow_up = self.follows_loop(loop)
                self.loop_stack.append((loop, follow_up))
                self.marked.add(entry)
                self.marked.add(follow_up)
                s1 = self.make_shape(entry)
                self.loop_stack.pop(-1)
                shape = LoopShape(s1)
                if follow_up:
                    s3 = self._jump(follow_up) or self.make_shape(follow_up)
                    shape = SequenceShape([shape, s3])
                return shape
            if len(entry.successors) == 1:
                (follow_up,) = entry.successors
                shape = BasicShape(entry)
                s2 = self.test(follow_up)
                return SequenceShape([shape, s2]) if s2 else shape
            if len(entry.successors) == 2:
                try:
                    merger = self.cfg.get_immediate_post_dominator(entry)
                except KeyError:  # no path to the exit (a `for (;;)` without break)
                    merger = None
                if merger in self.loop_stack[-1][0].rest:
                    follow_up = merger
                    self.marked.add(follow_up)
                else:
                    follow_up = None
                yes_shape = self.test(entry.yes)
                no_shape = self.test(entry.no)
                shape = IfShape(entry, yes_shape, no_shape)
                if follow_up:
                    shape = SequenceShape([shape, self.make_shape(follow_up)])
                return shape
            raise NotImplementedError(str(entry))

    relooper.StructureDetector = StructureDetector

    orig = IrToWasmCompiler.do_tree

    def do_tree(self: Any, tree: Any) -> Any:
        if tree.name.startswith('UND'):
            key = 'CONST' + tree.name[3:]
            self.emit(self.const_opcodes[key], 0.0 if 'F' in key else 0)
            self.stack += 1
            return
        return orig(self, tree)

    IrToWasmCompiler.do_tree = do_tree

    orig_shape = IrToWasmCompiler.do_shape

    def do_shape(self: Any, shape: Any) -> Any:
        # multi-level break/continue: each 'loop' entry is two wasm labels (loop, then block)
        if isinstance(shape, (BreakShape, ContinueShape)):
            depth, seen = 0, -1
            for kind in reversed(self._block_stack):
                if kind == 'loop':
                    seen += 1
                    if seen == shape.level:
                        break
                    depth += 2
                else:
                    depth += 1
            else:
                raise NotImplementedError('jump to loop level %d outside any loop' % shape.level)
            label = depth + (1 if isinstance(shape, BreakShape) else 0)
            self.emit('br', components.Ref('label', index=label))
            return
        if isinstance(shape, LoopShape) and getattr(self, 'fuel_ref', None) is not None:
            self.push_block('loop')
            self.emit('block', 'emptyblock')
            self.emit('loop', 'emptyblock')
            self.emit('global.get', self.fuel_ref)
            self.emit('i32.const', 1)
            self.emit('i32.sub')
            self.emit('global.set', self.fuel_ref)  # ppci's encoder has no global.tee
            self.emit('global.get', self.fuel_ref)
            self.emit('i32.eqz')
            self.emit('if', 'emptyblock')
            self.emit('call', self.fuel_func)
            self.emit('global.set', self.fuel_ref)
            self.emit('end')
            self.do_shape(shape.body)
            self.emit('end')
            self.emit('end')
            self.pop_block('loop')
            return
        return orig_shape(self, shape)

    IrToWasmCompiler.do_shape = do_shape

    from ppci import ir

    orig_compile = IrToWasmCompiler.compile

    def compile(self: Any, ir_module: Any) -> Any:
        # Global initializers holding addresses ((ptr, name) tuples) crashed the backend
        # ("data must be bytes"). Lay variables out exactly as ppci will, write addresses of
        # variables now and of functions (table indices) after the functions are known.
        addr, var_addr, fixups = self.global_memory, {}, []
        for v in ir_module.variables:
            var_addr[v.name] = addr
            addr += v.amount
        for v in ir_module.variables:
            if not v.value:
                continue
            parts, off = [], 0
            for item in v.value:
                if isinstance(item, tuple):
                    name = item[1]
                    if name in var_addr:
                        item = var_addr[name].to_bytes(4, 'little')
                    else:
                        fixups.append((var_addr[v.name] + off, name))
                        item = bytes(4)
                parts.append(item)
                off += len(item)
            v.value = parts
        if getattr(self, 'use_fuel', False):
            # import first, so it takes function index 0 before externals and functions
            type_ref = self.get_type_id((), (ir.i32,))
            self.fuel_func = components.Ref('func', index=len(self.function_refs), name='$__fuel_out')
            self.function_refs['__fuel_out'] = self.fuel_func
            self.add_definition(components.Import('js', '__fuel_out', 'func', self.fuel_func, (type_ref,)))
            self.fuel_ref = components.Ref('global', index=1)
            self.add_definition(
                components.Global(1, 'i32', True, [components.Instruction('i32.const', FUEL)])
            )
            # table slot 0 is taken by a placeholder so a NULL function pointer is not a real function
            self.pointed_functions.append(self.fuel_func)
        result = orig_compile(self, ir_module)
        for at, name in fixups:
            if name not in self.global_labels:
                self.global_labels[name] = len(self.pointed_functions)
                self.pointed_functions.append(self.function_refs[name])
            index = self.global_labels[name].to_bytes(4, 'little')
            for k, (memid, base, data) in enumerate(self.initial_memory):
                if base <= at < base + len(data):
                    o = at - base
                    self.initial_memory[k] = (memid, base, data[:o] + index + data[o + 4 :])
                    break
        return result

    IrToWasmCompiler.compile = compile

    _fix_integer_types(ir, components, IrToWasmCompiler)
    _fix_float_literals()

    orig_do_function = IrToWasmCompiler.do_function

    def do_function(self: Any, ir_function: Any, wasm_func: Any) -> Any:
        orig_do_function(self, ir_function, wasm_func)
        wasm_func.instructions = peephole(wasm_func.instructions, components)

    IrToWasmCompiler.do_function = do_function

    from ppci.lang.c.codegenerator import CCodeGenerator
    from ppci.lang.c.nodes import statements
    from ppci.lang.c.parser import CParser

    def parse_for_statement(self: Any) -> Any:
        location = self.consume('for').loc
        self.semantics.enter_scope()
        self.consume('(')
        if self.peek == ';':
            initial = None
            self.consume(';')
        elif self.is_declaration_statement():
            self.semantics.compounds.append([])  # collect the DeclarationStatements here
            try:
                self.parse_declarations()  # consumes the ';'
            finally:
                initial = statements.Compound(self.semantics.compounds.pop(), location)
        else:
            initial = self.parse_expression()
            self.consume(';')
        condition = None if self.peek == ';' else self.parse_expression()
        self.consume(';')
        post = None if self.peek == ')' else self.parse_expression()
        self.consume(')')
        body = self.parse_statement()
        self.semantics.leave_scope()
        return self.semantics.on_for(initial, condition, post, body, location)

    CParser.parse_for_statement = parse_for_statement

    def gen_for(self: Any, stmt: Any) -> Any:
        # as ppci's, plus: declarations in init, and `continue` goes to the post expression
        if isinstance(stmt.init, statements.Compound):
            self.gen_compound_statement(stmt.init)
        elif stmt.init is not None:
            self.gen_expr(stmt.init, rvalue=True)
        condition_block = self.builder.new_block()
        body_block = self.builder.new_block()
        post_block = self.builder.new_block()
        final_block = self.builder.new_block()
        self.break_block_stack.append(final_block)
        self.continue_block_stack.append(post_block)
        self.builder.emit_jump(condition_block)
        self.builder.set_block(condition_block)
        if stmt.condition:
            self.gen_condition(stmt.condition, body_block, final_block)
        else:
            self.builder.emit_jump(body_block)
        self.builder.set_block(body_block)
        self.gen_stmt(stmt.body)
        self.builder.emit_jump(post_block)
        self.builder.set_block(post_block)
        if stmt.post:
            self.gen_expr(stmt.post, rvalue=True)
        self.builder.emit_jump(condition_block)
        self.builder.set_block(final_block)
        self.break_block_stack.pop(-1)
        self.continue_block_stack.pop(-1)

    CCodeGenerator.gen_for = gen_for
    IrToWasmCompiler._pycoder_fixed = True
    _applied = True


def _fix_integer_types(ir: Any, components: Any, IrToWasmCompiler: Any) -> None:
    import re

    from ppci.arch.arch_info import ArchInfo, TypeInfo
    from ppci.arch.registers import RegisterClass
    from ppci.wasm import arch as wasm_arch

    rc = wasm_arch.register_classes
    wasm_arch.register_classes = [
        RegisterClass(
            'i32', [ir.i8, ir.u8, ir.i16, ir.u16, ir.i32, ir.u32, ir.ptr], wasm_arch.I32Register, None
        ),
        RegisterClass('i64', [ir.i64, ir.u64], wasm_arch.I64Register, None),
    ] + [c for c in rc if c.name in ('f32', 'f64')]

    def arch_init(self: Any) -> Any:
        wasm_arch.VirtualMachineArchitecture.__init__(self)
        self.info = ArchInfo(
            type_infos={
                ir.i8: TypeInfo(1, 1),
                ir.u8: TypeInfo(1, 1),
                ir.i16: TypeInfo(2, 1),
                ir.u16: TypeInfo(2, 1),
                ir.i32: TypeInfo(4, 1),
                ir.u32: TypeInfo(4, 1),
                ir.i64: TypeInfo(8, 1),
                ir.u64: TypeInfo(8, 1),
                ir.f32: TypeInfo(4, 1),
                ir.f64: TypeInfo(8, 1),
                'int': ir.i32,
                'long': ir.i32,
                'ptr': ir.i32,
            },
            register_classes=wasm_arch.register_classes,
        )
        self.fp_location = wasm_arch.FramePointerLocation.BOTTOM  # frames are [sp, sp + size)

    wasm_arch.WasmArchitecture.__init__ = arch_init

    C = IrToWasmCompiler
    for op, w in (
        ('ADD', 'add'),
        ('SUB', 'sub'),
        ('MUL', 'mul'),
        ('DIV', 'div_u'),
        ('REM', 'rem_u'),
        ('AND', 'and'),
        ('OR', 'or'),
        ('XOR', 'xor'),
        ('SHR', 'shr_u'),
        ('SHL', 'shl'),
    ):
        C.binop_map[op + 'U32'] = 'i32.' + w
    C.store_opcodes['STRU32'] = 'i32.store'
    C.load_opcodes['LDRU32'] = 'i32.load'
    C.const_opcodes['CONSTU32'] = 'i32.const'
    for name in list(C.cast_operators2):
        ops = C.cast_operators2[name]
        if ops and ops[0].endswith('.nearest'):  # C float->int conversion truncates
            C.cast_operators2[name] = ops[1:]
    C.cast_operators2['F32TOU32'] = ['i32.trunc_f32_u']
    C.cast_operators2['F64TOU32'] = ['i32.trunc_f64_u']
    C.cast_operators2['U32TOF64'] = ['f64.convert_i32_u']
    C.cast_operators2['U32TOF32'] = ['f32.convert_i32_u']

    orig_get_ty = C.get_ty

    def get_ty(self: Any, ir_ty: Any) -> Any:
        return 'i32' if ir_ty is ir.u32 else orig_get_ty(self, ir_ty)

    C.get_ty = get_ty

    int_cast = re.compile(r'^([IU])(8|16|32|64)TO([IU])(8|16|32|64)$')
    orig_do_tree = C.do_tree

    def do_tree(self: Any, tree: Any) -> Any:
        m = int_cast.match(tree.name)
        if m:
            src_signed, src_bits = m.group(1) == 'I', int(m.group(2))
            dst_signed, dst_bits = m.group(3) == 'I', int(m.group(4))
            self.do_tree(tree[0])
            if src_bits == 64 and dst_bits < 64:
                self.emit('i32.wrap_i64')
            elif src_bits < 64 and dst_bits == 64:
                self.emit('i64.extend_i32_s' if src_signed else 'i64.extend_i32_u')
            if dst_bits < 32:
                if dst_signed:
                    self.emit('i32.const', 32 - dst_bits)
                    self.emit('i32.shl')
                    self.emit('i32.const', 32 - dst_bits)
                    self.emit('i32.shr_s')
                else:
                    self.emit('i32.const', (1 << dst_bits) - 1)
                    self.emit('i32.and')
            return
        if tree.name.startswith('MOVB'):
            # block copy (struct assignment / struct return): MOVB[n](dst_addr, src_addr)
            size = tree.value
            for off, width in [(k, 4) for k in range(0, size - size % 4, 4)] + [
                (k, 1) for k in range(size - size % 4, size)
            ]:
                self.do_tree(tree[0])
                self.emit('i32.const', off)
                self.emit('i32.add')
                self.do_tree(tree[1])
                self.emit('i32.const', off)
                self.emit('i32.add')
                self.emit('i32.load' if width == 4 else 'i32.load8_u', 0, 0)
                self.emit('i32.store' if width == 4 else 'i32.store8', 0, 0)
                self.stack -= 2
            return
        if tree.name == 'CONSTU32':
            v = tree.value & 0xFFFFFFFF
            self.emit('i32.const', v - (1 << 32) if v >= 1 << 31 else v)
            self.stack += 1
            return
        return orig_do_tree(self, tree)

    C.do_tree = do_tree


def _fix_float_literals() -> None:
    from ppci.lang.c import utils
    from ppci.lang.c.lexer import CLexer

    def exponent_and_suffix(self: Any) -> Any:
        self.accept('+-')
        self.accept_run(self.numbers)
        self.accept('fFlL')
        self.emit('NUMBER')
        return self.lex_c

    def lex_float(self: Any) -> Any:
        self.accept_run(self.numbers)
        if self.accept('eEpP'):
            return exponent_and_suffix(self)
        self.accept('fFlL')
        self.emit('NUMBER')
        return self.lex_c

    def lex_number(self: Any) -> Any:
        digits = self.numbers
        if self.accept('0'):
            digits = (
                self.hex_numbers
                if self.accept('xX')
                else self.binary_numbers
                if self.accept('bB')
                else digits
            )
        self.accept_run(digits)
        if self.accept('.'):
            return self.lex_float()
        if digits is self.numbers and self.accept('eE'):  # 1e-10: a float without a point
            return exponent_and_suffix(self)
        for _ in range(3):
            self.accept('LlUu')
        self.emit('NUMBER')
        return self.lex_c

    CLexer.lex_float = lex_float
    CLexer.lex_number = lex_number
    orig_cnum = utils.cnum

    def cnum(txt: Any) -> Any:
        low = txt.lower()
        if not low.startswith('0x') and ('.' in low or 'e' in low):
            suffix = low[-1] if low[-1] in 'fl' else ''
            return float(low[:-1] if suffix else low), ['float'] if suffix == 'f' else ['double']
        return orig_cnum(txt)

    utils.cnum = cnum


def _idx(ins: Any) -> Any:
    a = ins.args[0]
    return getattr(a, 'index', a)


def peephole(code: Any, components: Any) -> Any:
    """Local-copy cleanup on a flat wasm instruction list (structured control flow untouched)."""
    changed = True
    while changed:
        changed = False
        reads: dict[Any, int] = {}
        for ins in code:
            if ins.opcode == 'local.get':
                reads[_idx(ins)] = reads.get(_idx(ins), 0) + 1
        out = []
        i = 0
        while i < len(code):
            ins = code[i]
            nxt = code[i + 1] if i + 1 < len(code) else None
            op = ins.opcode
            # local.get X; local.set X  -> nothing
            if op == 'local.get' and nxt is not None and nxt.opcode == 'local.set' and _idx(nxt) == _idx(ins):
                i += 2
                changed = True
                continue
            # local.get Y; local.set X (X never read) -> nothing
            if op == 'local.get' and nxt is not None and nxt.opcode == 'local.set' and _idx(nxt) not in reads:
                i += 2
                changed = True
                continue
            # local.set X (X never read) -> drop
            if op == 'local.set' and _idx(ins) not in reads:
                out.append(components.Instruction('drop'))
                i += 1
                changed = True
                continue
            # local.tee X (X never read) -> nothing
            if op == 'local.tee' and _idx(ins) not in reads:
                i += 1
                changed = True
                continue
            # local.set X; local.get X -> local.tee X
            if op == 'local.set' and nxt is not None and nxt.opcode == 'local.get' and _idx(nxt) == _idx(ins):
                out.append(components.Instruction('local.tee', ins.args[0]))
                i += 2
                changed = True
                continue
            out.append(ins)
            i += 1
        code = out
    return code
