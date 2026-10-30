"""
model_base.py — Abstract base class for all stream-mgr model plugins.

Every plugin must:
  1. Live in /app/plugins/<name>.py
  2. Define a class called Model(BaseModel)
  3. Implement load() and infer()

The worker will call:
  model = Model()
  model.load(config)
  for frame in stream:
      results = model.infer(frame)
      for r in results:
          print(r)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ModelConfig:
    """
    Passed to Model.load() — contains everything the CLI registered.
    Add extra kwargs via --plugin-args key=value at activation time.
    """
    model_path: str          # path to weights / model file
    conf:       float = 0.45
    classes:    list  = field(default_factory=list)   # empty = all classes
    half:       bool  = True                          # FP16 if supported
    device:     str   = "cuda"                        # cuda | cpu
    extra:      dict  = field(default_factory=dict)   # any --plugin-args


@dataclass
class Detection:
    """
    Standard output container. Fill in whichever fields make sense.
    Unused fields can be left as None — the worker prints only non-None ones.
    """
    label:      str
    confidence: float        = None
    bbox:       list  = None  # [x1, y1, x2, y2] pixels
    mask:       Any   = None  # segmentation mask (numpy array or RLE)
    keypoints:  Any   = None  # pose keypoints
    extra:      dict  = field(default_factory=dict)  # arbitrary extra data

    def __str__(self):
        parts = [self.label]
        if self.confidence is not None:
            parts.append(f"{self.confidence:.2f}")
        if self.bbox is not None:
            b = self.bbox
            parts.append(f"[{b[0]:.0f},{b[1]:.0f},{b[2]:.0f},{b[3]:.0f}]")
        if self.extra:
            parts.append(str(self.extra))
        return "  ".join(parts)


class BaseModel(ABC):
    """
    Inherit from this and implement load() + infer().

    Minimal plugin skeleton:

        from model_base import BaseModel, ModelConfig, Detection

        class Model(BaseModel):
            def load(self, config: ModelConfig):
                self.model = ...load your model here...

            def infer(self, frame) -> list[Detection]:
                # frame: numpy array, BGR uint8, shape (H, W, 3)
                results = self.model(frame)
                return [Detection(label="thing", confidence=0.9)]
    """

    @abstractmethod
    def load(self, config: ModelConfig):
        """
        Load model weights and prepare for inference.
        Called once before the stream loop starts.
        """

    @abstractmethod
    def infer(self, frame) -> list[Detection]:
        """
        Run inference on a single BGR frame (numpy uint8 HxWx3).
        Return a list of Detection objects (can be empty).
        """

    def warmup(self, width: int = 640, height: int = 640):
        """
        Optional: run a dummy inference to warm up GPU/TRT engine.
        Called once after load() if the worker requests it.
        """
        import numpy as np
        dummy = np.zeros((height, width, 3), dtype="uint8")
        self.infer(dummy)