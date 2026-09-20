from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
import time
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader, Subset

from .data import RoofDataset, TrainingBatchSampler, audit_dataset
from .model import CLASS_NAMES, INPUT_SHAPE, AsbestosCNN, load_checkpoint
from .train import classification_metrics, run_epoch, select_device, write_json


def atomic_save(value, path: Path) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    torch.save(value, temporary)
    os.replace(temporary, path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Wznawia trening w istniejącym folderze")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--artifacts-dir", type=Path, required=True)
    parser.add_argument("--max-epochs", type=int, default=128)
    parser.add_argument("--workers", type=int, default=0)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--device", choices=("auto", "cpu", "mps", "cuda"), default="auto")
    parser.add_argument("--train-only", action="store_true")
    parser.add_argument("--early-stopping-patience", type=int, default=10)
    args = parser.parse_args()
    artifacts = args.artifacts_dir.expanduser().resolve()
    required = [artifacts / name for name in ("best.pt", "history.json", "splits.json", "run_config.json", "data_audit.json")]
    if not 1 <= args.max_epochs <= 128 or args.early_stopping_patience < 1 or any(not path.is_file() for path in required):
        raise SystemExit("Brak kompletnego checkpointu lub nieprawidłowa konfiguracja treningu")
    torch.set_num_threads(args.threads)
    device = select_device(args.device)
    config = json.loads((artifacts / "run_config.json").read_text(encoding="utf-8"))
    seed = int(config["seed"])
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    _, best = load_checkpoint(artifacts / "best.pt")
    mean, std = tuple(best["mean"]), tuple(best["std"])
    dataset = RoofDataset(args.data_dir, mean, std)
    lookup = {str(path.relative_to(dataset.root)): index for index, (path, _) in enumerate(dataset.samples)}
    manifest = json.loads((artifacts / "splits.json").read_text(encoding="utf-8"))["splits"]
    splits = {name: [lookup[item["image_path"]] for item in items] for name, items in manifest.items()}
    audit = audit_dataset(dataset, splits)
    if audit["fingerprint"] != config["dataset_fingerprint"]:
        raise ValueError("Dataset zmienił się; resume zabronione")
    model = AsbestosCNN().to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=0.001)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode="min", factor=0.5, patience=3)
    latest_path = artifacts / "latest.pt"
    history_document = json.loads((artifacts / "history.json").read_text(encoding="utf-8"))
    if latest_path.is_file():
        state = torch.load(latest_path, map_location=device, weights_only=True)
        model.load_state_dict(state["state_dict"])
        optimizer.load_state_dict(state["optimizer_state_dict"])
        scheduler.load_state_dict(state["scheduler_state_dict"])
        history = state["history"]
        start_epoch = int(state["epoch"]) + 1
        best_epoch, best_loss = int(state["best_epoch"]), float(state["best_val_loss"])
        stale = int(state["stale_epochs"])
        resume_kind = "latest_with_optimizer"
    else:
        model.load_state_dict(best["state_dict"])
        best_epoch, best_loss = int(best["epoch"]), float(best["val_loss"])
        history = [row for row in history_document["history"] if int(row["epoch"]) <= best_epoch]
        start_epoch, stale = best_epoch + 1, 0
        resume_kind = "best_weights_optimizer_reset"
    if start_epoch > args.max_epochs:
        raise SystemExit("Osiągnięto już maksymalną epokę")
    config.setdefault("resume_events", []).append({"utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "kind": resume_kind, "start_epoch": start_epoch})
    config["device"] = str(device)
    write_json(artifacts / "run_config.json", config)
    generator = torch.Generator().manual_seed(seed + start_epoch)
    train_loader = DataLoader(Subset(dataset, splits["train"]), batch_sampler=TrainingBatchSampler(len(splits["train"]), 32, generator), num_workers=args.workers, pin_memory=device.type == "cuda")
    val_loader = DataLoader(Subset(dataset, splits["val"]), batch_size=32, num_workers=args.workers)
    test_loader = DataLoader(Subset(dataset, splits["test"]), batch_size=32, num_workers=args.workers)
    print(f"Resume={resume_kind}; start={start_epoch}; best={best_epoch}; val_loss={best_loss:.6f}; device={device}", flush=True)
    for epoch in range(start_epoch, args.max_epochs + 1):
        started = time.monotonic()
        print(f"Epoka {epoch:03d}/{args.max_epochs}: trening po resume", flush=True)
        train_metrics = run_epoch(model, train_loader, device, optimizer)
        val_metrics = run_epoch(model, val_loader, device)
        if not math.isfinite(train_metrics["loss"]) or not math.isfinite(val_metrics["loss"]):
            raise ValueError("NaN/Inf loss")
        lr = optimizer.param_groups[0]["lr"]
        scheduler.step(val_metrics["loss"])
        improved = val_metrics["loss"] < best_loss
        if improved:
            best_loss, best_epoch, stale = val_metrics["loss"], epoch, 0
            atomic_save({"state_dict": {name: tensor.detach().cpu() for name, tensor in model.state_dict().items()}, "input_shape": INPUT_SHAPE, "mean": list(mean), "std": list(std), "class_names": list(CLASS_NAMES), "epoch": epoch, "val_loss": best_loss, "training": config}, artifacts / "best.pt")
        else:
            stale += 1
        history.append({"epoch": epoch, "lr": lr, "seconds": time.monotonic() - started, "train": train_metrics, "val": val_metrics, "resumed": True})
        write_json(artifacts / "history.json", {"best_epoch": best_epoch, "best_val_loss": best_loss, "history": history})
        atomic_save({
            "state_dict": {name: tensor.detach().cpu() for name, tensor in model.state_dict().items()},
            "optimizer_state_dict": optimizer.state_dict(), "scheduler_state_dict": scheduler.state_dict(),
            "epoch": epoch, "best_epoch": best_epoch, "best_val_loss": best_loss, "stale_epochs": stale,
            "history": history, "mean": list(mean), "std": list(std), "input_shape": INPUT_SHAPE, "class_names": list(CLASS_NAMES),
        }, latest_path)
        print(f"Epoka {epoch:03d}: train_loss={train_metrics['loss']:.6f} val_loss={val_metrics['loss']:.6f} val_acc={val_metrics['accuracy']:.3f} val_f1={val_metrics['asbestos']['f1']:.3f} lr={lr:.6g}" + (" — nowy best" if improved else ""), flush=True)
        if stale >= args.early_stopping_patience:
            print("Early stopping po resume", flush=True)
            break
    if args.train_only:
        print(f"Trening zakończony; best={best_epoch}; val_loss={best_loss:.6f}", flush=True)
        return
    best_model, checkpoint = load_checkpoint(artifacts / "best.pt")
    best_model.to(device)
    result = {"best_epoch": checkpoint["epoch"], "best_val_loss": checkpoint["val_loss"], "history": history}
    result["val"] = run_epoch(best_model, val_loader, device)
    result["test"] = run_epoch(best_model, test_loader, device, return_predictions=True)
    predictions = result["test"].pop("predictions")
    with (artifacts / "test_predictions.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["image_path", "label", "asbestos_probability", "prediction"])
        writer.writeheader()
        for sample, prediction in zip(manifest["test"], predictions, strict=True):
            writer.writerow({"image_path": sample["image_path"], **prediction})
    majority = int(np.bincount([dataset.labels[index] for index in splits["train"]], minlength=2).argmax())
    result["majority_baseline"] = classification_metrics([dataset.labels[index] for index in splits["test"]], [float(majority)] * len(splits["test"]))
    result["class_names"], result["config"] = list(CLASS_NAMES), config
    write_json(artifacts / "metrics.json", result)
    if (artifacts / "model.onnx").exists():
        raise FileExistsError("model.onnx już istnieje; nie nadpisuję")
    best_model.cpu()
    from .export import export_onnx
    export_onnx(artifacts / "best.pt", artifacts / "model.onnx")
    print(f"Resume zakończony; best={checkpoint['epoch']}; test={result['test']}", flush=True)


if __name__ == "__main__":
    main()
