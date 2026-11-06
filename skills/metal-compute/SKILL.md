---
name: metal-compute
description: "Use when code should run on the GPU, or be much faster than numpy can make it: Metal compute kernels (MSL) compiled at run time, large parallel arrays, simulations, fractals, training a network by hand."
---

iOS loads no CPU libraries you build, but Metal compiles kernel source at run time. `pycoder.host.metal` wraps it.

```python
import struct
import numpy as np
from pycoder.host.metal import GPU

gpu = GPU()
gpu.compile("""
#include <metal_stdlib>
using namespace metal;
kernel void scale(device const float *a [[buffer(0)]], device float *out [[buffer(1)]],
                  constant float &k [[buffer(2)]], uint i [[thread_position_in_grid]]) {
    out[i] = a[i] * k;
}
""")
a_buf, _ = gpu.buffer(np.arange(1000, dtype=np.float32))
out_buf, out = gpu.buffer(np.zeros(1000, dtype=np.float32))
seconds = gpu.run('scale', [a_buf, out_buf, struct.pack('f', 2.0)], (1000,))
```

- `gpu.buffer(array)` returns (MTLBuffer, numpy view of its memory). Keep the buffer as long as the view. The view shows the result once `run` returns.
- A buffer argument is an MTLBuffer, or bytes for a constant. A grid has up to 3 sizes.
- `gpu.run_all([(kernel, buffers, grid), ...])` runs several steps in one go, and returns the GPU's seconds.

## Traps

- A device's `new...` method (`newTextureWithDescriptor_`, `newBufferWithLength_options_`) hands over one reference more than `ObjCInstance` gives back, so the memory is never freed and each run costs more until iOS closes the app. Wrap the result: `owned(device.newTexture...)`, from `pycoder.host.metal`. `GPU` already does this for its own.
- A compute encoder freed without `endEncoding` aborts the whole app, later, when the garbage collector reaches it: after any exception halfway through. Make your own with `with encoding(command) as e:`, from `pycoder.host.metal`.
- `float32` and `int32` only: MSL has no `double`, and numpy's default float64 reads as garbage.
- A compile error raises `MetalError` with the compiler's message and line.
- A kernel out of bounds corrupts memory or returns wrong numbers rather than failing: compare with numpy on a small input first.
- The GPU isn't available in the background: expect an error from `run` once the app has left the screen.

## When it pays

Every `run` has a fixed cost to commit and wait, so the work has to be big and parallel.

- Wins: each element independent, as in fractals, image filters, particles, big matrix products.
- Loses: small arrays and many small `run` calls. Put the steps of one round in one `run_all`.
- Dense linear algebra: try `accelerate-maths` first.

Measure both on the real size before settling on it.
