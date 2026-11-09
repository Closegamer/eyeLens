# MediaPipe model

`face_landmarker.task` is the MediaPipe Face Landmarker model (float16,
478 landmarks including irises).

- Source: https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task
- MediaPipe: https://developers.google.com/mediapipe/solutions/vision/face_landmarker
- License: Apache License 2.0

The model is bundled here so eyeLens works offline after checkout. If the file
is missing, eyeLens downloads it automatically on first launch (see
`eyelens/config.py`), or you can run:

```bash
python scripts/download_model.py
```
