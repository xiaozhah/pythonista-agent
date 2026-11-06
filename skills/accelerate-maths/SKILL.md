---
name: accelerate-maths
description: "Use when array maths is slow in Pythonista: matrix products, solving, eigenvalues, FFT, element-wise functions; its numpy has no BLAS or LAPACK."
---

`@`, `np.dot` and `np.linalg` run plain loops here. `pycoder.host.accelerate` does the same with Apple's Accelerate on numpy arrays, and falls back to numpy where it is missing, so the same code runs anywhere.

```python
import numpy as np
from pycoder.host import accelerate as acc

c = acc.matmul(a, b)  # a @ b
x = acc.solve(a, b)  # a @ x = b
w, v = acc.eigh(s)  # symmetric: eigenvalues ascending, eigenvectors in columns
w, v = acc.eig(a)  # general: complex when needed, as numpy.linalg.eig
f = acc.fft(x)  # along the last axis; acc.ifft(f) inverts it
acc.dot(x, y), acc.sum(x), acc.scale(x, 2.0)
acc.sin(x), acc.cos(x), acc.exp(x), acc.log(x), acc.sqrt(x)
```

- Results match numpy's. float32 stays float32 where there is a single-precision routine (matmul, dot, sum, scale, element-wise); everything else is float64.
- Complex input, more than two dimensions and FFT lengths other than f·2**k (f = 1, 3, 5, 15) go to numpy.
- Call it once per array, never once per element. Use numpy for indexing, reshaping and reductions.
- A script started from the editor while pycoder isn't running first needs `sys.path.append` of the folder holding the repository.

Other Accelerate functions are a ctypes call away; set `argtypes` and `restype`, and pass addresses:

```python
lib = ctypes.CDLL('/System/Library/Frameworks/Accelerate.framework/Accelerate')
lib.vDSP_maxvD.argtypes = [ctypes.c_void_p, ctypes.c_long, ctypes.c_void_p, ctypes.c_ulong]
out = np.zeros(1)
lib.vDSP_maxvD(x.ctypes.data, 1, out.ctypes.data, x.size)  # x: contiguous float64
```
