---
name: scenekit-models
description: "Use when a program should show real 3D objects with SceneKit through objc_util: meshes, lights, reflective floors, cameras, or a model following the device's attitude."
---

An `SCNView` inside a `ui.View`. WebGL isn't an option in `ui.WebView`.

```python
import ctypes
from objc_util import ObjCClass, ObjCInstance, load_framework, on_main_thread

load_framework('SceneKit')


class Vector3(ctypes.Structure):
    _fields_ = [('x', ctypes.c_float), ('y', ctypes.c_float), ('z', ctypes.c_float)]


def place(node, x, y, z):
    node.setPosition_(Vector3(x, y, z), argtypes=[Vector3], restype=None)


@on_main_thread
def build(host, w, h):
    view = ObjCClass('SCNView').alloc().initWithFrame_(((0, 0), (w, h)))
    world = ObjCClass('SCNScene').scene()
    box = ObjCClass('SCNBox').boxWithWidth_height_length_chamferRadius_(1.0, 0.4, 2.0, 0.1)
    box.firstMaterial().diffuse().setContents_(ObjCClass('UIColor').systemTealColor())
    node = ObjCClass('SCNNode').nodeWithGeometry_(box)
    world.rootNode().addChildNode_(node)
    camera = ObjCClass('SCNNode').node()
    camera.setCamera_(ObjCClass('SCNCamera').camera())
    place(camera, 0, 1.5, 4)
    camera.setEulerAngles_(Vector3(-0.35, 0, 0), argtypes=[Vector3], restype=None)
    world.rootNode().addChildNode_(camera)
    view.setScene_(world)
    view.setPointOfView_(camera)
    view.setAutoenablesDefaultLighting_(True)
    ObjCInstance(host).addSubview_(view)
    return view, node
```

- Vectors are structs: pass them with `argtypes=[Vector3], restype=None`. Without that the call crashes or does nothing.
- All of it on the main thread. Keep references to `view` and `node` for as long as they are shown.
- `SCNFloor.floor()` gives a reflective floor. `SCNAction.rotateByX_y_z_duration_` with `repeatActionForever_` spins a node with no Python per frame.
- Follow the device: `node.setEulerAngles_(Vector3(pitch, yaw, roll), argtypes=[Vector3], restype=None)`.
- `view.setAllowsCameraControl_(True)` gives real fingers orbit and pinch, which nothing here can test: say so.

## Checking it

`look_at_screen` sees it. `view.snapshot()` gives a `UIImage` of SceneKit alone, for a test: `UIImagePNGRepresentation` (see `pythonista-objc-recipes`), then read the pixels with PIL. `use_screen` can't see into an `SCNView`: lay a transparent `ui.View` subclass with touch methods over it, and `drag` reaches that.
