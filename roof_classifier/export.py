from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

import numpy as np
import onnx
import onnxruntime as ort
import torch

from .model import INPUT_SHAPE, load_checkpoint


def export_onnx(checkpoint_path: Path, destination: Path) -> Path:
    if destination.exists():
        raise FileExistsError(f"Plik docelowy już istnieje: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".onnx-export-", dir=destination.parent) as temporary:
        temporary_path = Path(temporary) / destination.name
        _export_and_verify(checkpoint_path, temporary_path)
        os.replace(temporary_path, destination)
    return destination


def _export_and_verify(checkpoint_path: Path, destination: Path) -> Path:
    model, checkpoint = load_checkpoint(checkpoint_path)
    example = torch.zeros(1, *INPUT_SHAPE)
    with torch.inference_mode():
        torch.onnx.export(
            model,
            example,
            str(destination),
            input_names=["images"],
            output_names=["logits"],
            dynamic_axes={"images": {0: "batch"}, "logits": {0: "batch"}},
            opset_version=17,
            dynamo=False,
        )
    graph = onnx.load(str(destination))
    onnx.helper.set_model_props(graph, {
        "input_shape": json.dumps(["N", *INPUT_SHAPE]),
        "mean": json.dumps(checkpoint["mean"]),
        "std": json.dumps(checkpoint["std"]),
        "class_names": json.dumps(checkpoint["class_names"]),
        "preprocessing": "RGB float32 NCHW; (pixels / 255 - mean) / std; normalization is external",
        "output": "raw logits; asbestos_probability = softmax(logits, axis=1)[:, 1]",
    })
    onnx.checker.check_model(graph, full_check=True)
    onnx.save(graph, str(destination))
    del graph, checkpoint
    options = ort.SessionOptions()
    options.intra_op_num_threads = min(torch.get_num_threads(), 4)
    session = ort.InferenceSession(str(destination), sess_options=options, providers=["CPUExecutionProvider"])
    if session.get_inputs()[0].shape != ["batch", *INPUT_SHAPE] or session.get_outputs()[0].shape != ["batch", 2]:
        raise ValueError("Nieprawidłowy kształt wejścia lub wyjścia ONNX")
    generator = torch.Generator().manual_seed(2022)
    with torch.inference_mode():
        for batch in (1, 2, 8, 32):
            inputs = torch.randn(batch, *INPUT_SHAPE, generator=generator)
            expected = model(inputs).numpy()
            actual = session.run(["logits"], {"images": inputs.numpy()})[0]
            if not np.isfinite(expected).all() or not np.isfinite(actual).all():
                raise ValueError("Nieskończone lub NaN logity podczas weryfikacji ONNX")
            np.testing.assert_allclose(actual, expected, rtol=1e-3, atol=1e-5)
            print(f"ONNX batch={batch}: zgodność z PyTorch, max_abs_error={np.max(np.abs(actual - expected)):.8g}", flush=True)
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description="Eksport najlepszego checkpointu do ONNX z dynamicznym batchem; wejście już znormalizowane")
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    torch.set_num_threads(4)
    export_onnx(args.checkpoint.expanduser(), args.output.expanduser())


if __name__ == "__main__":
    main()
