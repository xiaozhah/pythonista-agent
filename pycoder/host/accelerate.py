"""Native-speed array maths for numpy arrays, through Apple's Accelerate framework (BLAS, LAPACK,
vDSP, vForce), reached with ctypes. For user code as well as pycoder:

    from pycoder.host import accelerate as acc

    acc.matmul(a, b)        a @ b (BLAS gemm); 1-D operands work as in numpy
    acc.solve(a, b)         x with a @ x = b (LAPACK gesv)
    acc.eigh(a)             (w, v) of a symmetric matrix, w ascending (LAPACK syevd)
    acc.eig(a)              (w, v) of a general matrix, complex when needed (LAPACK geev)
    acc.fft(x), acc.ifft(x) along the last axis (vDSP; lengths f * 2**k, f in 1, 3, 5, 15)
    acc.dot(x, y), acc.sum(x), acc.scale(x, alpha)
    acc.sin, cos, exp, log, sqrt   element-wise (vForce)

Pythonista's numpy has no BLAS or LAPACK, so its `@`, `np.dot` and `np.linalg` run plain loops;
Accelerate's are 50-100x faster there. Results match numpy's: float32 stays float32 where
Accelerate has a single-precision routine (matmul, dot, sum, scale, the element-wise functions),
everything else is computed in float64. Whatever Accelerate can't do (complex input, more than two
dimensions, an FFT length vDSP lacks) and every call on a system without Accelerate (Linux) goes to
numpy instead, so code using this module runs anywhere.
"""

from __future__ import annotations

import ctypes
from ctypes import byref, c_double, c_float, c_int, c_long, c_ulong, c_void_p
from typing import Any

import numpy as np

FRAMEWORK = '/System/Library/Frameworks/Accelerate.framework/Accelerate'
_ROW_MAJOR, _NO_TRANS = 101, 111  # CBLAS enums

_P = c_void_p
_SIGNATURES: dict[str, tuple[Any, list[Any]]] = {
    'cblas_dgemm': (None, [c_int] * 6 + [c_double, _P, c_int, _P, c_int, c_double, _P, c_int]),
    'cblas_sgemm': (None, [c_int] * 6 + [c_float, _P, c_int, _P, c_int, c_float, _P, c_int]),
    'cblas_ddot': (c_double, [c_int, _P, c_int, _P, c_int]),
    'cblas_sdot': (c_float, [c_int, _P, c_int, _P, c_int]),
    'vDSP_sveD': (None, [_P, c_long, _P, c_ulong]),
    'vDSP_sve': (None, [_P, c_long, _P, c_ulong]),
    'vDSP_vsmulD': (None, [_P, c_long, _P, _P, c_long, c_ulong]),
    'vDSP_vsmul': (None, [_P, c_long, _P, _P, c_long, c_ulong]),
    'vDSP_DFT_zop_CreateSetupD': (_P, [_P, c_ulong, c_int]),
    'vDSP_DFT_ExecuteD': (None, [_P, _P, _P, _P, _P]),
    'dgesv_': (c_int, [_P] * 8),
    'dsyevd_': (c_int, [_P] * 11),
    'dgeev_': (c_int, [_P] * 14),
}
_UNARY = ('sin', 'cos', 'exp', 'log', 'sqrt')  # vvsin / vvsinf, ...
for _name in _UNARY:
    _SIGNATURES['vv' + _name] = _SIGNATURES['vv' + _name + 'f'] = (None, [_P, _P, _P])

_lib: Any = None
_dft_setups: dict[tuple[int, int], int] = {}


def _accelerate() -> Any:
    """The framework with its signatures set, or None where there is no Accelerate."""
    global _lib
    if _lib is None:
        try:
            library: Any = ctypes.CDLL(FRAMEWORK)
            for name, (result, args) in _SIGNATURES.items():
                function = getattr(library, name)
                function.restype, function.argtypes = result, args
        except (OSError, AttributeError):
            library = False
        _lib = library
    return _lib or None


def available() -> bool:
    """Whether calls run natively here (False: they fall back to numpy)."""
    return _accelerate() is not None


def _real(x: Any) -> np.ndarray[Any, Any] | None:
    """x as a contiguous float32 or float64 array, or None for what Accelerate can't take."""
    a = np.asarray(x)
    if a.dtype == np.float32:
        return np.ascontiguousarray(a)
    if a.dtype.kind in 'biuf':
        return np.ascontiguousarray(a, dtype=np.float64)
    return None


def _ptr(a: np.ndarray[Any, Any]) -> int:
    return int(a.ctypes.data)


# ---- BLAS


def matmul(a: Any, b: Any) -> np.ndarray[Any, Any]:
    """a @ b with BLAS gemm, for 1-D and 2-D real operands."""
    lib, x, y = _accelerate(), _real(a), _real(b)
    if lib is None or x is None or y is None or not (1 <= x.ndim <= 2 and 1 <= y.ndim <= 2):
        return np.asarray(np.matmul(a, b))
    x2 = x.reshape(1, -1) if x.ndim == 1 else x
    y2 = y.reshape(-1, 1) if y.ndim == 1 else y
    (m, k), (k2, n) = x2.shape, y2.shape
    if k != k2 or 0 in (m, n, k):
        return np.asarray(np.matmul(a, b))  # numpy's error, or an empty/zero result
    single = x.dtype == y.dtype == np.float32
    dtype = np.float32 if single else np.float64
    x2, y2 = np.ascontiguousarray(x2, dtype=dtype), np.ascontiguousarray(y2, dtype=dtype)
    c = np.empty((m, n), dtype=dtype)
    gemm, scalar = (lib.cblas_sgemm, c_float) if single else (lib.cblas_dgemm, c_double)
    gemm(
        _ROW_MAJOR,
        _NO_TRANS,
        _NO_TRANS,
        m,
        n,
        k,
        scalar(1.0),
        _ptr(x2),
        k,
        _ptr(y2),
        n,
        scalar(0.0),
        _ptr(c),
        n,
    )
    if x.ndim == 1 and y.ndim == 1:
        return c.reshape(())
    if x.ndim == 1:
        return c.reshape(n)
    if y.ndim == 1:
        return c.reshape(m)
    return c


def dot(x: Any, y: Any) -> Any:
    """The dot product of two vectors (BLAS dot); 2-D operands are multiplied as matrices."""
    lib, a, b = _accelerate(), _real(x), _real(y)
    if lib is None or a is None or b is None or not (1 <= a.ndim <= 2 and 1 <= b.ndim <= 2):
        return np.dot(x, y)
    if a.ndim == 2 or b.ndim == 2 or a.size != b.size:
        return matmul(a, b)
    if a.dtype == b.dtype == np.float32:
        return np.float32(lib.cblas_sdot(a.size, _ptr(a), 1, _ptr(b), 1))
    a, b = a.astype(np.float64, copy=False), b.astype(np.float64, copy=False)
    return np.float64(lib.cblas_ddot(a.size, _ptr(a), 1, _ptr(b), 1))


# ---- vDSP and vForce


def sum(x: Any) -> Any:
    """The sum of all elements (vDSP)."""
    lib, a = _accelerate(), _real(x)
    if lib is None or a is None or a.size == 0:
        return np.sum(x)
    out = np.zeros(1, dtype=a.dtype)
    (lib.vDSP_sve if a.dtype == np.float32 else lib.vDSP_sveD)(_ptr(a), 1, _ptr(out), a.size)
    return out[0]


def scale(x: Any, alpha: float) -> np.ndarray[Any, Any]:
    """alpha * x as a new array (vDSP)."""
    lib, a = _accelerate(), _real(x)
    if lib is None or a is None or a.size == 0:
        return np.asarray(np.multiply(x, alpha))
    out = np.empty_like(a)
    factor = np.array([alpha], dtype=a.dtype)
    (lib.vDSP_vsmul if a.dtype == np.float32 else lib.vDSP_vsmulD)(
        _ptr(a), 1, _ptr(factor), _ptr(out), 1, a.size
    )
    return out


def _unary(name: str, x: Any) -> np.ndarray[Any, Any]:
    lib, a = _accelerate(), _real(x)
    if lib is None or a is None or a.size == 0 or a.size >= 2**31:
        return np.asarray(getattr(np, name)(x))
    out = np.empty_like(a)
    function = getattr(lib, 'vv' + name + ('f' if a.dtype == np.float32 else ''))
    function(_ptr(out), _ptr(a), byref(c_int(a.size)))
    return out


def sin(x: Any) -> np.ndarray[Any, Any]:
    return _unary('sin', x)


def cos(x: Any) -> np.ndarray[Any, Any]:
    return _unary('cos', x)


def exp(x: Any) -> np.ndarray[Any, Any]:
    return _unary('exp', x)


def log(x: Any) -> np.ndarray[Any, Any]:
    return _unary('log', x)


def sqrt(x: Any) -> np.ndarray[Any, Any]:
    return _unary('sqrt', x)


# ---- FFT (vDSP's DFT: complex to complex, out of place, unnormalised in both directions)


def _dft_setup(lib: Any, n: int, direction: int) -> int:
    """A cached vDSP DFT setup for length n; 0 if vDSP can't do that length."""
    key = (n, direction)
    if key not in _dft_setups:
        _dft_setups[key] = int(lib.vDSP_DFT_zop_CreateSetupD(None, n, direction) or 0)
    return _dft_setups[key]


def _dft(x: Any, direction: int) -> np.ndarray[Any, Any] | None:
    lib = _accelerate()
    a = np.asarray(x)
    if lib is None or a.ndim == 0 or a.dtype.kind not in 'biufc' or a.shape[-1] == 0:
        return None
    n = a.shape[-1]
    setup = _dft_setup(lib, n, direction)
    if not setup:
        return None
    rows = a.reshape(-1, n)
    real = np.ascontiguousarray(rows.real, dtype=np.float64)
    imag = np.ascontiguousarray(rows.imag, dtype=np.float64) if a.dtype.kind == 'c' else np.zeros_like(real)
    out_real, out_imag = np.empty_like(real), np.empty_like(real)
    step = n * 8
    for r in range(rows.shape[0]):
        offset = r * step
        lib.vDSP_DFT_ExecuteD(
            setup,
            _ptr(real) + offset,
            _ptr(imag) + offset,
            _ptr(out_real) + offset,
            _ptr(out_imag) + offset,
        )
    result = np.empty(rows.shape, dtype=np.complex128)
    result.real, result.imag = out_real, out_imag
    return result.reshape(a.shape)


def fft(x: Any) -> np.ndarray[Any, Any]:
    """The discrete Fourier transform along the last axis, as numpy.fft.fft."""
    result = _dft(x, 1)
    return np.fft.fft(x) if result is None else result


def ifft(x: Any) -> np.ndarray[Any, Any]:
    """The inverse transform along the last axis, as numpy.fft.ifft (divided by n)."""
    result = _dft(x, -1)
    if result is None:
        return np.fft.ifft(x)
    result /= result.shape[-1]
    return result


# ---- LAPACK (column-major: matrices go in as Fortran-ordered copies, which LAPACK overwrites)


def _square(a: Any) -> np.ndarray[Any, Any] | None:
    m = np.asarray(a)
    if m.ndim != 2 or m.shape[0] != m.shape[1] or m.shape[0] == 0 or m.dtype.kind not in 'biuf':
        return None
    return np.array(m, dtype=np.float64, order='F')


def solve(a: Any, b: Any) -> np.ndarray[Any, Any]:
    """x such that a @ x = b, for a square a and b of shape (n,) or (n, k) (LAPACK gesv)."""
    lib, m, rhs = _accelerate(), _square(a), np.asarray(b)
    if lib is None or m is None or rhs.dtype.kind not in 'biuf' or rhs.ndim not in (1, 2):
        return np.linalg.solve(a, b)
    n = m.shape[0]
    if rhs.shape[0] != n:
        return np.linalg.solve(a, b)  # numpy's error message
    x = np.array(rhs, dtype=np.float64, order='F')
    nrhs = 1 if x.ndim == 1 else x.shape[1]
    pivots = np.empty(n, dtype=np.int32)
    info = c_int(0)
    lib.dgesv_(
        byref(c_int(n)), byref(c_int(nrhs)), _ptr(m), byref(c_int(n)), _ptr(pivots), _ptr(x),
        byref(c_int(n)), byref(info),
    )  # fmt: skip
    if info.value > 0:
        raise np.linalg.LinAlgError('Singular matrix')
    if info.value < 0:
        raise ValueError(f'dgesv: argument {-info.value} is invalid')
    return x


def eigh(a: Any) -> tuple[np.ndarray[Any, Any], np.ndarray[Any, Any]]:
    """Eigenvalues (ascending) and eigenvectors (columns) of a symmetric matrix, as numpy.linalg.eigh:
    only the lower triangle is read (LAPACK syevd)."""
    lib, m = _accelerate(), _square(a)
    if lib is None or m is None:
        return np.linalg.eigh(a)
    n = m.shape[0]
    w = np.empty(n)
    jobz, uplo, size, info = b'V', b'L', c_int(n), c_int(0)

    def call(work: np.ndarray[Any, Any], lwork: int, iwork: np.ndarray[Any, Any], liwork: int) -> None:
        lib.dsyevd_(
            jobz, uplo, byref(size), _ptr(m), byref(size), _ptr(w), _ptr(work), byref(c_int(lwork)),
            _ptr(iwork), byref(c_int(liwork)), byref(info),
        )  # fmt: skip

    work, iwork = np.empty(1), np.empty(1, dtype=np.int32)
    call(work, -1, iwork, -1)  # workspace query
    lwork, liwork = int(work[0]), int(iwork[0])
    call(np.empty(lwork), lwork, np.empty(liwork, dtype=np.int32), liwork)
    if info.value > 0:
        raise np.linalg.LinAlgError('Eigenvalues did not converge')
    return w, m


def eig(a: Any) -> tuple[np.ndarray[Any, Any], np.ndarray[Any, Any]]:
    """Eigenvalues and right eigenvectors (columns, unit length) of a square matrix, as
    numpy.linalg.eig: real arrays when every eigenvalue is real, else complex (LAPACK geev)."""
    lib, m = _accelerate(), _square(a)
    if lib is None or m is None:
        return np.linalg.eig(a)
    n = m.shape[0]
    wr, wi, vr = np.empty(n), np.empty(n), np.empty((n, n), order='F')
    size, one, info = c_int(n), c_int(1), c_int(0)
    unused = np.empty(1)

    def call(work: np.ndarray[Any, Any], lwork: int) -> None:
        lib.dgeev_(
            b'N', b'V', byref(size), _ptr(m), byref(size), _ptr(wr), _ptr(wi), _ptr(unused), byref(one),
            _ptr(vr), byref(size), _ptr(work), byref(c_int(lwork)), byref(info),
        )  # fmt: skip

    work = np.empty(1)
    call(work, -1)  # workspace query
    lwork = int(work[0])
    call(np.empty(lwork), lwork)
    if info.value > 0:
        raise np.linalg.LinAlgError('Eigenvalues did not converge')
    if not wi.any():
        return wr, vr
    w = wr + 1j * wi
    v = vr.astype(np.complex128)
    j = 0
    while j < n:  # a complex pair is stored as two columns: real part, imaginary part
        if wi[j] != 0 and j + 1 < n:
            v[:, j] = vr[:, j] + 1j * vr[:, j + 1]
            v[:, j + 1] = vr[:, j] - 1j * vr[:, j + 1]
            j += 2
        else:
            j += 1
    return w, v
