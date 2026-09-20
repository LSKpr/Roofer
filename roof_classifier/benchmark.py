from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path

import numpy as np
import onnxruntime as ort
import torch
from PIL import Image

from .data import RoofDataset
from .model import INPUT_SHAPE, load_checkpoint
from .train import write_json


def timing(values: list[float], batch: int) -> dict:
    array = np.asarray(values, dtype=np.float64) * 1000
    mean = float(array.mean())
    return {
        "batch_size": batch,
        "repetitions": len(values),
        "mean_ms": mean,
        "median_ms": float(np.median(array)),
        "p90_ms": float(np.quantile(array, 0.90)),
        "p95_ms": float(np.quantile(array, 0.95)),
        "min_ms": float(array.min()),
        "max_ms": float(array.max()),
        "images_per_second": float(batch / (mean / 1000)),
    }


def measure(function, synchronize, warmup: int, repetitions: int, batch: int) -> dict:
    for _ in range(warmup):
        function()
    synchronize()
    values = []
    for _ in range(repetitions):
        synchronize()
        started = time.perf_counter()
        function()
        synchronize()
        values.append(time.perf_counter() - started)
    return timing(values, batch)


def load_comparison(values: list[str]) -> dict:
    result = {}
    for value in values:
        if "=" not in value:
            raise ValueError("--compare wymaga NAME=PATH")
        name, path = value.split("=", 1)
        document = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
        test = document.get("test", {}).get("threshold_0_5") or document.get("test") or document.get("threshold_0_5")
        if not test:
            raise ValueError(f"Brak metryk testowych w {path}")
        result[name] = {
            "source": str(Path(path).expanduser().resolve()),
            "accuracy": test.get("accuracy"), "balanced_accuracy": test.get("balanced_accuracy"),
            "asbestos_precision": test.get("precision_ppv", test.get("asbestos", {}).get("precision")),
            "asbestos_recall": test.get("sensitivity_recall", test.get("asbestos", {}).get("recall")),
            "asbestos_f1": test.get("asbestos", {}).get("f1"), "roc_auc": test.get("roc_auc"),
            "pr_auc": test.get("average_precision_pr_auc", test.get("average_precision")),
            "warning": "Datasets and splits differ; this is not a controlled head-to-head experiment.",
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark PyTorch CPU/MPS i ONNX Runtime CPU")
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--onnx", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument("--repetitions", type=int, default=50)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--compare", action="append", default=[])
    args = parser.parse_args()
    if args.warmup < 1 or args.repetitions < 50 or args.threads < 1:
        parser.error("Wymagany warmup >=1, repetitions >=50 i threads >=1")
    output = args.output_dir.expanduser().resolve()
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise SystemExit(f"Folder benchmarku nie jest pusty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(args.threads)
    cpu_model, checkpoint = load_checkpoint(args.checkpoint)
    dataset = RoofDataset(args.data_dir, checkpoint["mean"], checkpoint["std"])
    tensors = torch.stack([dataset[index][0] for index in range(32)])
    options = ort.SessionOptions()
    options.intra_op_num_threads = args.threads
    options.inter_op_num_threads = 1
    session = ort.InferenceSession(str(args.onnx), sess_options=options, providers=["CPUExecutionProvider"])
    results = []
    correctness = []
    with torch.inference_mode():
        for batch in (1, 8, 32):
            cpu_inputs = tensors[:batch]
            expected = cpu_model(cpu_inputs).numpy()
            actual = session.run(["logits"], {"images": cpu_inputs.numpy()})[0]
            error = float(np.max(np.abs(expected - actual)))
            correctness.append({"batch_size": batch, "max_absolute_logit_error": error})
            np.testing.assert_allclose(actual, expected, rtol=1e-3, atol=1e-5)
            cpu = measure(lambda: cpu_model(cpu_inputs), lambda: None, args.warmup, args.repetitions, batch)
            results.append({"engine": "pytorch_cpu", **cpu})
            onnx = measure(lambda: session.run(["logits"], {"images": cpu_inputs.numpy()}), lambda: None, args.warmup, args.repetitions, batch)
            results.append({"engine": "onnxruntime_cpu", **onnx})
    mps_available = torch.backends.mps.is_available()
    if mps_available:
        mps_model, _ = load_checkpoint(args.checkpoint)
        mps_model.to("mps")
        with torch.inference_mode():
            for batch in (1, 8, 32):
                inputs = tensors[:batch].to("mps")
                mps = measure(lambda: mps_model(inputs), torch.mps.synchronize, args.warmup, args.repetitions, batch)
                results.append({"engine": "pytorch_mps", **mps})
        mps_model.cpu()
        torch.mps.empty_cache()
    parameters = sum(parameter.numel() for parameter in cpu_model.parameters())
    summary = {
        "model": {
            "checkpoint": str(args.checkpoint.expanduser().resolve()), "onnx": str(args.onnx.expanduser().resolve()),
            "parameters": parameters, "checkpoint_bytes": args.checkpoint.stat().st_size, "onnx_bytes": args.onnx.stat().st_size,
            "input_shape": ["N", *INPUT_SHAPE], "mean": checkpoint["mean"], "std": checkpoint["std"],
        },
        "settings": {"warmup": args.warmup, "repetitions": args.repetitions, "threads": args.threads, "mps_available": mps_available},
        "onnx_correctness": correctness,
        "timings": results,
        "quality_comparison": load_comparison(args.compare),
        "comparison_warning": "Quality metrics come from different datasets/splits and are not a controlled head-to-head comparison.",
    }
    write_json(output / "benchmark.json", summary)
    with (output / "benchmark.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(results[0]))
        writer.writeheader()
        writer.writerows(results)
    report = [
        "# Inference benchmark", "", f"Parameters: **{parameters:,}**", f"Checkpoint: **{args.checkpoint.stat().st_size / 2**20:.1f} MiB**",
        f"ONNX: **{args.onnx.stat().st_size / 2**20:.1f} MiB**", "", f"Warmup: {args.warmup}; repetitions: {args.repetitions}; CPU threads: {args.threads}", "",
        "| Engine | Batch | Mean ms | Median ms | p90 ms | p95 ms | images/s |", "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in results:
        report.append(f"| {row['engine']} | {row['batch_size']} | {row['mean_ms']:.3f} | {row['median_ms']:.3f} | {row['p90_ms']:.3f} | {row['p95_ms']:.3f} | {row['images_per_second']:.2f} |")
    report.extend(["", "Quality comparison is indicative only: datasets and splits differ, so this is not a controlled head-to-head experiment."])
    (output / "REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
