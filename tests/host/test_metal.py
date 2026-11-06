"""Metal kernels: only where the GPU can be reached, which is inside Pythonista."""

from __future__ import annotations

import struct

import numpy as np
import pytest

from pycoder.host import env


@pytest.mark.skipif(not env.IN_PYTHONISTA, reason='needs Pythonista')
def test_a_kernel_runs_and_a_bad_one_says_why() -> None:
    from pycoder.host.metal import GPU, MetalError

    gpu = GPU()
    gpu.compile(
        """
        #include <metal_stdlib>
        using namespace metal;
        kernel void scale(device const float *a [[buffer(0)]], device float *out [[buffer(1)]],
                          constant float &k [[buffer(2)]], uint i [[thread_position_in_grid]]) {
            out[i] = a[i] * k;
        }
        """
    )
    a, _ = gpu.buffer(np.arange(10, dtype=np.float32))
    b, out = gpu.buffer(np.zeros(10, dtype=np.float32))
    gpu.run('scale', [a, b, struct.pack('f', 2.0)], (10,))
    assert out.tolist() == [float(i * 2) for i in range(10)]
    assert a.retainCount() == 1  # or its memory would never come back
    with pytest.raises(MetalError):
        gpu.compile('this is not metal')


def test_it_imports_anywhere() -> None:
    from pycoder.host import metal

    assert issubclass(metal.MetalError, Exception)
