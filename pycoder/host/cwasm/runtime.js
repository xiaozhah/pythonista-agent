// The host side of C compiled to wasm by ppci: its C library, memory and calls. Pure JS, synchronous.
// Undefined C functions are imports from module "js"; a variadic one gets a pointer to its packed
// arguments as its last parameter. include/*.h declares exactly what `libc` below implements.
var __cw = (function () {
  var HEAP_LIMIT = 256 * 1024 * 1024;  // malloc returns NULL past this: iOS kills apps that use too much
  var OUT_HEAD = 20000, OUT_TAIL = 20000;  // characters of stdout kept from the start and the end
  var inst = null, mem = null, heapEnd = 0, stage = new ArrayBuffer(1 << 16), spGlobal = null;
  var freeLists = {}, deadline = Infinity, limitMs = 10000, started = Date.now(), seed = 1;
  var head = '', tail = [], tailLen = 0, dropped = 0;
  function ExitSignal(code) { this.code = code; }
  function u8() { return new Uint8Array(mem.buffer); }
  function dv() { return new DataView(mem.buffer); }
  function cstr(p) { var b = u8(), s = ''; while (b[p]) s += String.fromCharCode(b[p++]); return s; }
  function putstr(p, s, n) {  // write s (and a NUL) at p, at most n bytes in all
    var b = u8(), k = Math.min(s.length, n - 1);
    for (var i = 0; i < k; i++) b[p + i] = s.charCodeAt(i) & 255;
    if (n > 0) b[p + k] = 0;
  }
  function ensure(end) {
    var have = mem.buffer.byteLength;
    if (end > have) mem.grow(Math.ceil((end - have) / 65536));
  }
  function malloc(n) {
    n = n >>> 0;
    var size = 16; while (size < n + 8) size *= 2;  // power-of-two size classes, 8-byte header
    var fl = freeLists[size];
    if (fl && fl.length) return fl.pop();
    if (heapEnd + size > HEAP_LIMIT) return 0;
    var p = heapEnd; heapEnd += size; ensure(heapEnd);
    dv().setUint32(p, size, true);
    return p + 8;
  }
  function free(p) {
    if (!p) return;
    var size = dv().getUint32(p - 8, true);
    (freeLists[size] = freeLists[size] || []).push(p);
  }
  function realloc(p, n) {
    if (!p) return malloc(n);
    var size = dv().getUint32(p - 8, true);
    if (n + 8 <= size) return p;
    var q = malloc(n); if (!q) return 0;
    u8().copyWithin(q, p, p + size - 8); free(p); return q;
  }
  // printf: %d %i %u %x %X %o %c %s %f %e %g %p %%, flags -0+ space, width, .precision, l/ll/h/z
  // ppci packs variadic arguments without alignment padding
  function format(fmt, va) {
    var d = dv(), s = '', i = 0;
    function arg(size) {
      var v = size === 8 ? d.getFloat64(va, true) : d.getInt32(va, true);
      va += size; return v;
    }
    function argI64(unsigned) {
      var v = unsigned ? d.getBigUint64(va, true) : d.getBigInt64(va, true); va += 8; return v;
    }
    while (i < fmt.length) {
      var ch = fmt[i++];
      if (ch !== '%') { s += ch; continue; }
      var m = /^([-+ 0#]*)(\d*)(?:\.(\d+))?(hh|h|ll|l|z)?([diuxXocsfeEgGp%])/.exec(fmt.slice(i));
      if (!m) { s += '%'; continue; }
      i += m[0].length;
      var flags = m[1], width = +m[2] || 0, prec = m[3] === undefined ? -1 : +m[3], len = m[4] || '', c = m[5], v, t;
      if (c === '%') { s += '%'; continue; }
      if ('diuxXoc'.indexOf(c) >= 0) {
        if (len === 'll') { v = argI64(c !== 'd' && c !== 'i'); }
        else { v = arg(4); if (c !== 'd' && c !== 'i' && c !== 'c') v = v >>> 0; }
        if (c === 'c') t = String.fromCharCode(v & 255);
        else if (c === 'x') t = v.toString(16); else if (c === 'X') t = v.toString(16).toUpperCase();
        else if (c === 'o') t = v.toString(8); else t = v.toString();
      } else if (c === 's') { t = cstr(arg(4)); if (prec >= 0) t = t.slice(0, prec); }
      else if (c === 'p') { t = '0x' + (arg(4) >>> 0).toString(16); }
      else {
        v = arg(8); var p = prec < 0 ? 6 : prec;
        if (!isFinite(v)) t = isNaN(v) ? 'nan' : v < 0 ? '-inf' : 'inf';
        else if (c === 'f') t = v.toFixed(p);
        else if (c === 'e' || c === 'E') { t = v.toExponential(p).replace(/e([+-])(\d)$/, 'e$10$2'); }
        else {  // %g: %e if the exponent is < -4 or >= the precision, else %f; no trailing zeros
          var P = p || 1, ex = v.toExponential(P - 1), X = +ex.slice(ex.indexOf('e') + 1);
          if (X < -4 || X >= P) t = ex.replace(/\.?0+e/, 'e').replace(/e([+-])(\d)$/, 'e$10$2');
          else { t = v.toFixed(P - 1 - X); if (t.indexOf('.') >= 0) t = t.replace(/\.?0+$/, ''); }
        }
        if (c === 'E' || c === 'G') t = t.toUpperCase();
      }
      if (flags.indexOf('+') >= 0 && t[0] !== '-' && 'difeEgG'.indexOf(c) >= 0) t = '+' + t;
      else if (flags.indexOf(' ') >= 0 && t[0] !== '-' && 'difeEgG'.indexOf(c) >= 0) t = ' ' + t;
      while (t.length < width) t = flags.indexOf('-') >= 0 ? t + ' ' : (flags.indexOf('0') >= 0 && 'sc'.indexOf(c) < 0 ? (/^[-+ ]/.test(t) ? t[0] + '0' + t.slice(1) : '0' + t) : ' ' + t);
      s += t;
    }
    return s;
  }
  function trimTail() {
    var all = tail.join(''), cut = Math.max(0, all.length - OUT_TAIL);
    dropped += cut; tail = [all.slice(cut)]; tailLen = all.length - cut;
  }
  function emit(s) {
    if (head.length < OUT_HEAD) { var k = OUT_HEAD - head.length; head += s.slice(0, k); s = s.slice(k); }
    if (!s) return;
    tail.push(s); tailLen += s.length;
    if (tailLen > 4 * OUT_TAIL || tail.length > 4096) trimTail();
  }
  function isspace(c) { return c === 32 || (c >= 9 && c <= 13) ? 1 : 0; }
  function isdigit(c) { return c >= 48 && c <= 57 ? 1 : 0; }
  function isupper(c) { return c >= 65 && c <= 90 ? 1 : 0; }
  function islower(c) { return c >= 97 && c <= 122 ? 1 : 0; }
  var libc = {
    __fuel_out: function () {  // called every 2**20 loop iterations
      if (Date.now() > deadline) throw new Error('time limit exceeded (' + limitMs / 1000 + ' s)');
      return 1 << 20;
    },
    // stdio.h
    printf: function (fmt, va) { var s = format(cstr(fmt), va); emit(s); return s.length; },
    sprintf: function (buf, fmt, va) { var s = format(cstr(fmt), va); putstr(buf, s, s.length + 1); return s.length; },
    snprintf: function (buf, n, fmt, va) { var s = format(cstr(fmt), va); putstr(buf, s, n >>> 0); return s.length; },
    puts: function (p) { emit(cstr(p) + '\n'); return 0; },
    putchar: function (c) { emit(String.fromCharCode(c & 255)); return c; },
    // stdlib.h
    malloc: malloc, free: free, realloc: realloc,
    calloc: function (n, m) { var p = malloc(n * m); if (p) u8().fill(0, p, p + n * m); return p; },
    abs: Math.abs,
    atoi: function (p) { return parseInt(cstr(p), 10) | 0; },
    atof: function (p) { return parseFloat(cstr(p)); },
    rand: function () { seed = (Math.imul(seed, 1103515245) + 12345) >>> 0; return (seed >>> 1) & 0x7fffffff; },
    srand: function (s) { seed = s >>> 0; },
    exit: function (code) { throw new ExitSignal(code); },
    abort: function () { throw new Error('abort() called'); },
    __assert_fail: function (expr, line) { throw new Error('assertion failed: ' + cstr(expr) + ' (line ' + line + ')'); },
    // string.h
    memcpy: function (d, s, n) { u8().copyWithin(d, s, s + n); return d; },
    memmove: function (d, s, n) { u8().copyWithin(d, s, s + n); return d; },
    memset: function (d, c, n) { u8().fill(c, d, d + n); return d; },
    memcmp: function (a, b, n) { var m = u8(); for (var i = 0; i < n; i++) if (m[a + i] !== m[b + i]) return m[a + i] - m[b + i]; return 0; },
    strlen: function (p) { var m = u8(), q = p; while (m[q]) q++; return q - p; },
    strcmp: function (a, b) { var m = u8(); while (m[a] && m[a] === m[b]) { a++; b++; } return m[a] - m[b]; },
    strncmp: function (a, b, n) { var m = u8(); for (; n > 0; n--, a++, b++) { if (m[a] !== m[b] || !m[a]) return m[a] - m[b]; } return 0; },
    strcpy: function (d, s) { var m = u8(), i = 0; do { m[d + i] = m[s + i]; } while (m[s + i++]); return d; },
    strncpy: function (d, s, n) { var m = u8(), i = 0; for (; i < n && m[s + i]; i++) m[d + i] = m[s + i]; for (; i < n; i++) m[d + i] = 0; return d; },
    strcat: function (d, s) { var m = u8(), e = d; while (m[e]) e++; var i = 0; do { m[e + i] = m[s + i]; } while (m[s + i++]); return d; },
    strchr: function (p, c) { var m = u8(); c &= 255; for (;; p++) { if (m[p] === c) return p; if (!m[p]) return 0; } },
    // ctype.h
    isspace: isspace, isdigit: isdigit, isupper: isupper, islower: islower,
    isalpha: function (c) { return isupper(c) || islower(c); },
    isalnum: function (c) { return isupper(c) || islower(c) || isdigit(c); },
    toupper: function (c) { return islower(c) ? c - 32 : c; },
    tolower: function (c) { return isupper(c) ? c + 32 : c; },
    // math.h
    sqrt: Math.sqrt, sin: Math.sin, cos: Math.cos, tan: Math.tan, asin: Math.asin, acos: Math.acos,
    atan: Math.atan, atan2: Math.atan2, sinh: Math.sinh, cosh: Math.cosh, tanh: Math.tanh,
    exp: Math.exp, log: Math.log, log2: Math.log2, log10: Math.log10, pow: Math.pow, cbrt: Math.cbrt,
    hypot: Math.hypot, fabs: Math.abs, floor: Math.floor, ceil: Math.ceil, trunc: Math.trunc,
    round: function (x) { return x < 0 ? -Math.round(-x) : Math.round(x); },  // halves away from zero
    fmod: function (x, y) { return x % y; }, fmin: Math.min, fmax: Math.max,
    // time.h
    clock: function () { return (Date.now() - started) * 1000; }
  };
  return {
    stage: function (n) { if (stage.byteLength < n) stage = new ArrayBuffer(Math.max(n, stage.byteLength * 2)); return stage; },
    load: function (n, heapBase) {
      var mod = new WebAssembly.Module(new Uint8Array(stage, 0, n).slice());
      var imports = { js: {} }, missing = [];
      WebAssembly.Module.imports(mod).forEach(function (im) {
        var v = libc[im.name];
        if (im.module !== 'js' || im.kind !== 'function' || !v) {
          missing.push(im.name);
          v = function () { throw new Error('unresolved import ' + im.name); };
        }
        (imports[im.module] = imports[im.module] || {})[im.name] = v;
      });
      inst = new WebAssembly.Instance(mod, imports);
      mem = inst.exports.memory;
      spGlobal = inst.exports.__stack_pointer || null;
      heapEnd = (heapBase + 15) & ~15;
      return JSON.stringify({ exports: WebAssembly.Module.exports(mod).map(function (e) { return e.name; }), missing: missing });
    },
    setLimit: function (seconds) { limitMs = seconds * 1000; },
    call: function (name, args) {
      var sp0 = spGlobal ? spGlobal.value : 0;
      deadline = Date.now() + limitMs;
      if (inst.exports.__fuel) inst.exports.__fuel.value = 1 << 20;  // a trap can leave it at 0
      try {
        var r = inst.exports[name].apply(null, args);
      } catch (e) {
        if (spGlobal) spGlobal.value = sp0;  // a trap leaves the C stack pointer mid-frame
        if (e instanceof ExitSignal) return e.code;
        throw e;
      } finally { deadline = Infinity; }
      return r === undefined ? 0 : r;
    },
    malloc: malloc, free: free,
    // copies between the staging buffer and wasm memory (both directions are native memcpy)
    toMem: function (ptr, n) { ensure(ptr + n); u8().set(new Uint8Array(stage, 0, n), ptr); },
    fromMem: function (ptr, n) { new Uint8Array(stage, 0, n).set(new Uint8Array(mem.buffer, ptr, n)); },
    stdout: function () {
      trimTail();
      var s = head + (dropped ? '\n... [' + dropped + ' characters of output left out] ...\n' : '') + tail.join('');
      head = ''; tail = []; tailLen = 0; dropped = 0;
      return s;
    }
  };
})();
