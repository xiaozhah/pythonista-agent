---
name: pythonista-objc-recipes
description: "Use when calling iOS frameworks through objc_util for images or models: CoreImage (QR codes, rectangle detection, perspective), a Core ML model with Vision, struct returns, blocks, or copying an image to the clipboard."
---

## objc_util traps
- Don't use `objc_util.autoreleasepool()`: its Python object later sends `release` to a pool that is gone, and when the garbage collector does that it crashes the app. In a loop on your own thread, pair `objc_autoreleasePoolPush` and `objc_autoreleasePoolPop` through `ctypes` (`restype` and `argtypes` `c_void_p`), in `try`/`finally`, on the same thread.
- Use synchronous APIs. Never pass an `ObjCBlock` to an API that calls it later from another thread unless you must: that can crash Pythonista outright.
- Struct returns (CGPoint, CGRect): call `objc_msgSend` yourself with `restype` set, from `cdll.LoadLibrary('/usr/lib/libobjc.A.dylib')`.
- Struct arguments: use `CIVector.vectorWithX_Y_(x, y)` where it's accepted.
- A raw int argument is converted to NSNumber: pass it through `objc_msgSend` with `c_void_p`, and wrap results in `ObjCInstance`.
- A block iOS keeps: pass `ctypes.addressof(block._as_parameter_)`, with `argtypes` given, and keep the block alive. By itself objc_util passes a copy that is gone when the call returns.
- `createCGImage:fromRect:` returns +1: call `CGImageRelease` after making the UIImage.
- None for an `NSError**` argument gives no error text when a call fails: check the result.

## QR code without packages
`CIFilter.filterWithName_('CIQRCodeGenerator')`, `setValue_forKey_(ns(text).dataUsingEncoding_(4), 'inputMessage')`, `setValue_forKey_(ns('M'), 'inputCorrectionLevel')`. `outputImage()` is None when it doesn't fit (2331 bytes at M). Then `CIContext.context().createCGImage_fromRect_(out, out.extent())` and `UIImage.imageWithCGImage_`. Scale with `Image.NEAREST`, and keep a 4-module quiet zone. Check by decoding with `CIDetector` of type `CIDetectorTypeQRCode`.

## PNG bytes and the clipboard
- `pngData` isn't there. Use `UIImagePNGRepresentation` from `ctypes.CDLL('/System/Library/Frameworks/UIKit.framework/UIKit')`.
- `clipboard.set_image(pil_image)` fails here. Use `UIPasteboard.generalPasteboard().setData_forPasteboardType_(nsdata, 'public.png')`.
- Other apps change the clipboard at any time: don't test by reading back text.

## Rectangle detection
`CIDetector.detectorOfType_context_options_('CIDetectorTypeRectangle', None, ns({'CIDetectorAccuracy': 'CIDetectorAccuracyHigh'}))`, `featuresInImage_`. CoreImage's origin is bottom-left, so flip y for overlays. Respect orientation with `ns({'kCIImageApplyOrientationProperty': True})`.

## Core ML with Vision, no blocks
1. `MLModel.compileModelAtURL_error_(nsurl(path), None)`, and copy the result as `.mlmodelc` to keep it.
2. `MLModel.modelWithContentsOfURL_error_(nsurl(dir), None)`, `VNCoreMLModel.modelForMLModel_error_(ml, None)`.
3. `VNCoreMLRequest.alloc().initWithModel_(vn)`, `VNImageRequestHandler.alloc().initWithURL_options_(nsurl(path), ns({}))`, `performRequests_error_(ns([req]), None)`; read `req.results()` by `count()` and `objectAtIndex_(i)`.
The first call takes seconds, later ones are fast. Generate test images instead of using the photo library.
