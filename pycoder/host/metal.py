"""Metal compute kernels compiled at run time: how to run your own native-speed code on iOS."""

from __future__ import annotations

import ctypes
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import numpy as np


class MTLSize(ctypes.Structure):
    _fields_ = [('width', ctypes.c_ulong), ('height', ctypes.c_ulong), ('depth', ctypes.c_ulong)]


class MetalError(Exception):
    pass


def owned(instance: Any) -> Any:
    """What a `new...` method returns: it hands over a reference on top of the one ObjCInstance keeps,
    so without this the object, however large, is never freed."""
    instance.release()
    return instance


@contextmanager
def encoding(command: Any) -> Iterator[Any]:
    """A compute encoder that always gets ended: Metal aborts the whole app when an unended one is
    freed, which is what an exception halfway through would otherwise lead to, whenever the garbage
    collector gets to it."""
    encoder = command.computeCommandEncoder()
    try:
        yield encoder
    finally:
        encoder.endEncoding()


class GPU:
    def __init__(self) -> None:
        from objc_util import ObjCInstance

        metal = ctypes.CDLL('/System/Library/Frameworks/Metal.framework/Metal')
        metal.MTLCreateSystemDefaultDevice.restype = ctypes.c_void_p
        self.device = ObjCInstance(metal.MTLCreateSystemDefaultDevice())
        self.queue = owned(self.device.newCommandQueue())
        self.kernels: dict[str, Any] = {}

    def compile(self, source: str) -> None:
        """Compile Metal Shading Language: its kernels can then be run by name."""
        from objc_util import ns

        err = ctypes.c_void_p(0)
        library = self.device.newLibraryWithSource_options_error_(ns(source), None, ctypes.byref(err))
        if library is None:
            raise MetalError(_why(err, 'compile'))
        owned(library)
        for name in library.functionNames():
            function = owned(library.newFunctionWithName_(name))
            pipeline = self.device.newComputePipelineStateWithFunction_error_(function, ctypes.byref(err))
            if pipeline is None:
                raise MetalError(_why(err, f'pipeline {name}'))
            self.kernels[str(name)] = owned(pipeline)

    def buffer(self, array: Any) -> tuple[Any, Any]:
        """A copy of the array in memory the GPU shares: (MTLBuffer, numpy view of that memory).
        Keep the buffer as long as the view, which goes wrong without it."""
        array = np.ascontiguousarray(array)
        buffer = owned(
            self.device.newBufferWithBytes_length_options_(
                ctypes.c_void_p(array.ctypes.data), array.nbytes, 0
            )
        )
        pointer = buffer.contents()
        raw = (ctypes.c_char * array.nbytes).from_address(getattr(pointer, 'value', pointer))
        return buffer, np.frombuffer(raw, dtype=array.dtype).reshape(array.shape)

    def run_all(self, steps: list[tuple[str, list[Any], tuple[int, ...]]]) -> float:
        """Run (kernel name, buffers, grid) steps in order and wait; the GPU's seconds. A buffer is an
        MTLBuffer, or bytes for a constant argument. A grid has up to 3 sizes."""
        command = self.queue.commandBuffer()
        with encoding(command) as encoder:
            for kernel, buffers, grid in steps:
                pipeline = self.kernels[kernel]
                encoder.setComputePipelineState_(pipeline)
                for i, b in enumerate(buffers):
                    if isinstance(b, bytes):
                        encoder.setBytes_length_atIndex_(ctypes.c_char_p(b), len(b), i)
                    else:
                        encoder.setBuffer_offset_atIndex_(b, 0, i)
                sizes = tuple(grid) + (1,) * (3 - len(grid))
                group = (min(pipeline.threadExecutionWidth(), sizes[0]), 1, 1)
                encoder.dispatchThreads_threadsPerThreadgroup_(
                    MTLSize(*sizes), MTLSize(*group), argtypes=[MTLSize, MTLSize], restype=None
                )
        command.commit()
        command.waitUntilCompleted()
        if command.error():
            raise MetalError(str(command.error()))
        return float(command.GPUEndTime() - command.GPUStartTime())

    def run(self, kernel: str, buffers: list[Any], grid: tuple[int, ...]) -> float:
        return self.run_all([(kernel, buffers, grid)])


def _why(err: ctypes.c_void_p, what: str) -> str:
    from objc_util import ObjCInstance

    return f'{what}: {ObjCInstance(err.value).localizedDescription()}' if err.value else what
