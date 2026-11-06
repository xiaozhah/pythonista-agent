"""Accelerate's array maths against numpy, natively where Accelerate exists and through the fallback."""

from __future__ import annotations

from typing import Any

import pytest

np = pytest.importorskip('numpy')

from pycoder.host import accelerate as acc  # noqa: E402
from pycoder.state.workspace import Workspace  # noqa: E402
from pycoder.tools.python_runner import run_code  # noqa: E402


@pytest.fixture(params=['native', 'numpy'])
def mode(request: Any, monkeypatch: pytest.MonkeyPatch) -> str:
    if request.param == 'native' and not acc.available():
        pytest.skip('no Accelerate here')
    if request.param == 'numpy':
        monkeypatch.setattr(acc, '_lib', False)  # as on Linux
    return str(request.param)


rng = np.random.default_rng(0)


def close(a: Any, b: Any, tol: float = 1e-9) -> bool:
    return bool(np.allclose(a, b, rtol=tol, atol=tol))


def test_matmul_and_dot(mode: str) -> None:
    a, b = rng.standard_normal((30, 20)), rng.standard_normal((20, 10))
    assert close(acc.matmul(a, b), a @ b)
    assert close(acc.matmul(a.T, a), a.T @ a)  # a transposed (non-contiguous) operand
    assert close(acc.matmul(a[0], b), a[0] @ b)
    assert close(acc.matmul(a, b[:, 0]), a @ b[:, 0])
    assert close(acc.matmul(a[0], a[0]), a[0] @ a[0])
    assert acc.matmul(a.astype(np.float32), b.astype(np.float32)).dtype == np.float32
    assert close(acc.matmul(np.arange(6).reshape(2, 3), np.ones((3, 2))), [[3, 3], [12, 12]])
    complex_ = np.ones((2, 2)) * (1 + 1j)
    assert close(acc.matmul(complex_, complex_), complex_ @ complex_)  # numpy's job
    with pytest.raises(ValueError, match='mismatch'):
        acc.matmul(a, a)
    x, y = rng.standard_normal(100), rng.standard_normal(100)
    assert close(acc.dot(x, y), x @ y)
    assert close(acc.dot(a, b), a @ b)


def test_solve_and_eigen(mode: str) -> None:
    a = rng.standard_normal((40, 40))
    b = rng.standard_normal((40, 3))
    assert close(acc.solve(a, b), np.linalg.solve(a, b))
    assert close(acc.solve(a, b[:, 0]), np.linalg.solve(a, b[:, 0]))
    with pytest.raises(np.linalg.LinAlgError):
        acc.solve(np.zeros((3, 3)), np.ones(3))

    s = a + a.T
    w, v = acc.eigh(s)
    assert close(w, np.linalg.eigvalsh(s))
    assert close(s @ v, v * w)

    w, v = acc.eig(a)  # a random matrix has complex pairs
    assert w.dtype == np.complex128
    assert close(np.sort_complex(w), np.sort_complex(np.linalg.eigvals(a)))
    assert close(a @ v, v * w)
    assert close(np.linalg.norm(v, axis=0), 1)
    w, v = acc.eig(s)
    assert w.dtype == np.float64
    assert close(s @ v, v * w)


@pytest.mark.parametrize('n', [8, 24, 1024, 7])  # 7: a length vDSP lacks, done by numpy
def test_fft(mode: str, n: int) -> None:
    x = rng.standard_normal((3, n)) + 1j * rng.standard_normal((3, n))
    assert close(acc.fft(x), np.fft.fft(x))
    assert close(acc.ifft(x), np.fft.ifft(x))
    assert close(acc.fft(x.real), np.fft.fft(x.real))
    assert close(acc.ifft(acc.fft(x)), x)


def test_vector_ops(mode: str) -> None:
    x = rng.random((10, 100)) + 0.1
    assert close(acc.sum(x), x.sum())
    assert close(acc.scale(x, 2.5), 2.5 * x)
    for name in ('sin', 'cos', 'exp', 'log', 'sqrt'):
        result = getattr(acc, name)(x)
        assert result.shape == x.shape
        assert close(result, getattr(np, name)(x))
        assert getattr(acc, name)(x.astype(np.float32)).dtype == np.float32
    assert close(acc.sin(np.array([], dtype=np.float64)), [])


def test_user_code_imports_it_from_run_python(tmp_path: Any) -> None:
    """run_python runs in pycoder's process, where the package is already imported: no path setup."""
    code = 'from pycoder.host import accelerate as acc\nprint(acc.matmul([[1, 2]], [[3], [4]]))'
    assert '[[11.]]' in run_code(Workspace(str(tmp_path)), code=code)
