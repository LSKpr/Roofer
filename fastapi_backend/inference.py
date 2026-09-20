from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import onnxruntime as ort
from PIL import Image


class RoofModel:
    def __init__(self, path: Path, threads: int):
        with path.open("rb") as stream:
            self.model_id = hashlib.file_digest(stream, "sha256").hexdigest()
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(str(path), sess_options=options, providers=["CPUExecutionProvider"])
        inputs, outputs = self.session.get_inputs(), self.session.get_outputs()
        if len(inputs) != 1 or inputs[0].name != "images" or inputs[0].shape != ["batch", 3, 128, 128] or inputs[0].type != "tensor(float)":
            raise ValueError("Model must accept float32 images with shape N×3×128×128")
        if len(outputs) != 1 or outputs[0].name != "logits" or outputs[0].shape != ["batch", 2]:
            raise ValueError("Model must return N×2 logits")
        metadata = self.session.get_modelmeta().custom_metadata_map
        if json.loads(metadata["class_names"]) != ["non_asbestos", "asbestos"]:
            raise ValueError("Unexpected model class order")
        mean, std = (np.asarray(json.loads(metadata[key]), dtype=np.float32) for key in ("mean", "std"))
        if mean.shape != (3,) or std.shape != (3,) or not np.isfinite(mean).all() or not np.isfinite(std).all() or np.any(std <= 0):
            raise ValueError("Invalid model normalization metadata")
        self.mean, self.std = mean.reshape(1, 3, 1, 1), std.reshape(1, 3, 1, 1)

    def predict(self, images: list[Image.Image]) -> list[float]:
        if not images:
            return []
        if any(image.size != (128, 128) for image in images):
            raise ValueError("Images must be 128×128; resizing is disabled")
        inputs = np.stack([np.asarray(image.convert("RGB"), dtype=np.float32) for image in images]).transpose(0, 3, 1, 2)
        inputs = np.ascontiguousarray((inputs / 255.0 - self.mean) / self.std, dtype=np.float32)
        logits = self.session.run(["logits"], {"images": inputs})[0]
        if logits.shape != (len(images), 2) or not np.isfinite(logits).all():
            raise ValueError("Model returned invalid logits")
        scores = np.exp(logits - logits.max(axis=1, keepdims=True))
        return (scores[:, 1] / scores.sum(axis=1)).tolist()
