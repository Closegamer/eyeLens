"""eyeLens - a webcam-controlled magnifying screen lens."""

from __future__ import annotations

import os

# Keep TensorFlow/MediaPipe chatter out of the user's console. This has to be
# configured before any submodule imports mediapipe.
os.environ.setdefault("GLOG_minloglevel", "2")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")

__version__ = "0.1.0"
__app_name__ = "eyeLens"

