---
name: vision-and-language
description: "Use when code reads images or text on the device: OCR, image labels, faces, barcodes, the language of a text, word vectors, or a Core ML model."
---

All offline. Use synchronous APIs only (see `pythonista-objc-recipes`). For OCR by itself there is the `recognize_text` tool.

## Vision

```python
from objc_util import ObjCClass, ns, nsurl


def vision(path, *requests):
    handler = ObjCClass('VNImageRequestHandler').alloc().initWithURL_options_(nsurl(path), ns({}))
    return handler.performRequests_error_(ns(list(requests)), None)


text = ObjCClass('VNRecognizeTextRequest').alloc().init()
text.setRecognitionLevel_(0)  # accurate
text.setAutomaticallyDetectsLanguage_(True)  # without it Vision reads English only
labels = ObjCClass('VNClassifyImageRequest').alloc().init()
faces = ObjCClass('VNDetectFaceRectanglesRequest').alloc().init()
vision('photo.png', text, labels, faces)
lines = [str(o.topCandidates_(1)[0].string()) for o in text.results() or []]
top = sorted(((float(o.confidence()), str(o.identifier())) for o in labels.results()), reverse=True)[:5]
face_count = len(faces.results() or [])
```

The first request loads the model and is slower. Images come from a file path: save a PIL or `ui.Image` to a temporary PNG first. `VNDetectBarcodesRequest` and `VNDetectHumanRectanglesRequest` work the same way.

## NaturalLanguage

```python
ObjCClass('NLLanguageRecognizer').dominantLanguageForString_('今天天气不错')  # 'zh-Hans'
embedding = ObjCClass('NLEmbedding').wordEmbeddingForLanguage_('en')
[str(w) for w in embedding.neighborsForString_maximumCount_distanceType_('python', 5, 0)]
```

Sentiment (`NLTagger` with the SentimentScore scheme) may return no score: check for numbers before relying on it.

## Core ML

The only door to the Neural Engine: give it a model, and it decides where each layer runs. Models come from elsewhere (Apple's gallery, coremltools or Create ML on a Mac): Core ML runs them, and can't train them. Steps are in `pythonista-objc-recipes`. It is new ground in pycoder: test step by step, and say so.
