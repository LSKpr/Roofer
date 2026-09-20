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
from sklearn.metrics import average_precision_score, confusion_matrix, precision_recall_fscore_support, roc_auc_score
from torch import nn
from torch.utils.data import DataLoader, Subset

from .data import RoofDataset, TrainingBatchSampler, audit_dataset, metadata_groups, stratified_group_split, stratified_split, training_mean_std
from .model import CLASS_NAMES, INPUT_SHAPE, MEAN, STD, AsbestosCNN


def select_device(name: str) -> torch.device:
    if name == "auto":
        name = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
    if name == "cuda" and not torch.cuda.is_available():
        raise ValueError("CUDA nie jest dostępne")
    if name == "mps" and not torch.backends.mps.is_available():
        raise ValueError("MPS nie jest dostępne")
    return torch.device(name)


def write_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")
    os.replace(temporary, path)


def classification_metrics(labels, probabilities) -> dict:
    labels = np.asarray(labels, dtype=np.int64)
    probabilities = np.asarray(probabilities, dtype=np.float64)
    if labels.ndim != 1 or labels.size == 0 or labels.shape != probabilities.shape:
        raise ValueError("Metryki wymagają niepustych, równych wektorów etykiet i prawdopodobieństw")
    if not np.isin(labels, [0, 1]).all() or not np.isfinite(probabilities).all() or np.any((probabilities < 0) | (probabilities > 1)):
        raise ValueError("Nieprawidłowe etykiety lub prawdopodobieństwa")
    predictions = (probabilities > 0.5).astype(np.int64)
    precision, recall, f1, support = precision_recall_fscore_support(labels, predictions, labels=[0, 1], zero_division=0)
    both_classes = bool(np.all(support > 0))
    return {
        "accuracy": float(np.mean(labels == predictions)),
        "balanced_accuracy": float(np.mean(recall)) if both_classes else None,
        "confusion_matrix": confusion_matrix(labels, predictions, labels=[0, 1]).tolist(),
        "roc_auc": float(roc_auc_score(labels, probabilities)) if both_classes else None,
        "average_precision": float(average_precision_score(labels, probabilities)) if both_classes else None,
        "brier_score": float(np.mean((probabilities - labels) ** 2)),
        "threshold": 0.5,
        "threshold_rule": "asbestos_probability > threshold",
        **{
            name: {"precision": float(precision[label]), "recall": float(recall[label]), "f1": float(f1[label]), "support": int(support[label])}
            for label, name in enumerate(CLASS_NAMES)
        },
    }


def run_epoch(model: nn.Module, loader: DataLoader, device: torch.device, optimizer=None, *, return_predictions: bool = False) -> dict:
    model.train(optimizer is not None)
    criterion = nn.CrossEntropyLoss()
    loss_sum = torch.zeros((), device=device)
    all_labels = []
    all_probabilities = []
    count = 0
    with torch.set_grad_enabled(optimizer is not None):
        for step, (inputs, labels) in enumerate(loader, start=1):
            inputs, labels = inputs.to(device), labels.to(device)
            if optimizer is not None:
                optimizer.zero_grad(set_to_none=True)
            logits = model(inputs)
            loss = criterion(logits, labels)
            if not torch.isfinite(loss).item():
                raise ValueError("Nieskończony lub NaN loss; trening został przerwany")
            if optimizer is not None:
                loss.backward()
                optimizer.step()
            loss_sum += loss.detach() * labels.size(0)
            all_labels.append(labels.detach().cpu())
            all_probabilities.append(logits.detach().softmax(dim=1)[:, 1].cpu())
            count += labels.size(0)
            if optimizer is not None and step % 10 == 0:
                print(f"  train batch {step}/{len(loader)}: loss={loss_sum.item() / count:.6f}", flush=True)
    if count == 0:
        raise ValueError("Pusty podzbiór danych")
    labels = torch.cat(all_labels).numpy()
    probabilities = torch.cat(all_probabilities).numpy()
    metrics = {"loss": loss_sum.item() / count, **classification_metrics(labels, probabilities)}
    if return_predictions:
        metrics["predictions"] = [
            {"label": int(label), "asbestos_probability": float(probability), "prediction": int(probability > 0.5)}
            for label, probability in zip(labels, probabilities)
        ]
    return metrics


def fit(model, train_loader, val_loader, device, checkpoint_path: Path, max_epochs: int = 128, run_metadata: dict | None = None, mean=MEAN, std=STD) -> dict:
    if not 1 <= max_epochs <= 128:
        raise ValueError("Liczba epok musi mieścić się w zakresie 1–128")
    optimizer = torch.optim.Adam(model.parameters(), lr=0.001)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode="min", factor=0.5, patience=3)
    best_loss = math.inf
    best_epoch = 0
    stale_epochs = 0
    history = []
    for epoch in range(1, max_epochs + 1):
        started = time.monotonic()
        print(f"Epoka {epoch:03d}/{max_epochs}: trening", flush=True)
        train_metrics = run_epoch(model, train_loader, device, optimizer)
        val_metrics = run_epoch(model, val_loader, device)
        if not math.isfinite(train_metrics["loss"]) or not math.isfinite(val_metrics["loss"]):
            raise ValueError("Nieskończony lub NaN loss; trening został przerwany")
        lr = optimizer.param_groups[0]["lr"]
        scheduler.step(val_metrics["loss"])
        improved = val_metrics["loss"] < best_loss
        if improved:
            best_loss = val_metrics["loss"]
            best_epoch = epoch
            stale_epochs = 0
            temporary = checkpoint_path.with_suffix(".pt.tmp")
            torch.save({
                "state_dict": {name: tensor.detach().cpu() for name, tensor in model.state_dict().items()},
                "input_shape": INPUT_SHAPE,
                "mean": list(mean),
                "std": list(std),
                "class_names": list(CLASS_NAMES),
                "epoch": epoch,
                "val_loss": best_loss,
                "training": run_metadata or {},
            }, temporary)
            os.replace(temporary, checkpoint_path)
        else:
            stale_epochs += 1
        history.append({"epoch": epoch, "lr": lr, "seconds": time.monotonic() - started, "train": train_metrics, "val": val_metrics})
        result = {"best_epoch": best_epoch, "best_val_loss": best_loss, "history": history}
        write_json(checkpoint_path.parent / "history.json", result)
        asbestos = val_metrics.get("asbestos", {})
        print(
            f"Epoka {epoch:03d}/{max_epochs}: train_loss={train_metrics['loss']:.6f} "
            f"val_loss={val_metrics['loss']:.6f} val_acc={val_metrics['accuracy']:.3f} "
            f"val_recall={asbestos.get('recall', 0):.3f} val_f1={asbestos.get('f1', 0):.3f} "
            f"lr={lr:.6g}" + (" — zapisano najlepszy model" if improved else ""),
            flush=True,
        )
        if stale_epochs >= 10:
            print("Early stopping: 10 epok bez poprawy validation loss", flush=True)
            break
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Trening CNN dachów: 0 = brak azbestu, 1 = azbest; eksport najlepszego modelu do ONNX")
    parser.add_argument("--data-dir", type=Path, required=True, help="Folder zawierający non_asbestos/ i asbestos/")
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/roof_classifier"))
    parser.add_argument("--epochs", type=int, default=128)
    parser.add_argument("--seed", type=int, default=2022)
    parser.add_argument("--workers", type=int, default=0)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--device", choices=("auto", "cpu", "mps", "cuda"), default="auto")
    args = parser.parse_args()
    if not 1 <= args.epochs <= 128:
        parser.error("--epochs musi mieścić się w zakresie 1–128")
    if args.workers < 0 or args.threads < 1:
        parser.error("--workers musi być >= 0, --threads musi być >= 1")
    return args


def main() -> None:
    args = parse_args()
    output_dir = args.output_dir.expanduser().resolve()
    if output_dir.exists() and (not output_dir.is_dir() or any(output_dir.iterdir())):
        raise SystemExit(f"Folder wyjściowy nie jest pusty: {output_dir}")
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.set_num_threads(args.threads)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(args.seed)
        torch.backends.cudnn.benchmark = False
        torch.backends.cudnn.deterministic = True
    device = select_device(args.device)
    dataset = RoofDataset(args.data_dir)
    groups = metadata_groups(dataset, proximity_m=50)
    splits = stratified_group_split(dataset.labels, groups, args.seed) if groups else stratified_split(dataset.labels, args.seed)
    split_strategy = "stratified_group_by_ortho_sheet_plus_50m_components" if groups else "stratified_random"
    audit = audit_dataset(dataset, splits)
    mean, std = training_mean_std(dataset, splits["train"])
    dataset.set_normalization(mean, std)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "data_audit.json", audit)
    manifest = {
        name: [{"image_path": str(dataset.samples[index][0].relative_to(dataset.root)), "label": dataset.labels[index]} for index in indices]
        for name, indices in splits.items()
    }
    write_json(output_dir / "splits.json", {"seed": args.seed, "data_dir": str(dataset.root), "fingerprint": audit["fingerprint"], "splits": manifest})
    config = {
        "seed": args.seed, "batch_size": 32, "max_epochs": args.epochs,
        "optimizer": "Adam", "lr": 0.001, "loss": "CrossEntropyLoss",
        "scheduler": {"name": "ReduceLROnPlateau", "mode": "min", "factor": 0.5, "patience": 3},
        "early_stopping_patience": 10, "device": str(device),
        "input_shape": INPUT_SHAPE, "mean": mean, "std": std, "normalization_source": "training_split_only",
        "data_dir": str(dataset.root), "dataset_fingerprint": audit["fingerprint"],
        "split_counts": audit["split_counts"], "torch_version": str(torch.__version__),
        "augmentation": False, "class_weights": None, "split_strategy": split_strategy,
    }
    write_json(output_dir / "run_config.json", config)
    generator = torch.Generator().manual_seed(args.seed)
    train_loader = DataLoader(
        Subset(dataset, splits["train"]),
        batch_sampler=TrainingBatchSampler(len(splits["train"]), 32, generator),
        num_workers=args.workers,
        pin_memory=device.type == "cuda",
    )
    val_loader = DataLoader(Subset(dataset, splits["val"]), batch_size=32, num_workers=args.workers)
    test_loader = DataLoader(Subset(dataset, splits["test"]), batch_size=32, num_workers=args.workers)
    print(f"Urządzenie: {device}; podział: {split_strategy}; liczby zdjęć: " + ", ".join(f"{name}={len(indices)}" for name, indices in splits.items()), flush=True)
    print(f"Normalizacja policzona wyłącznie na train: mean={mean}, std={std}", flush=True)
    print(f"Audyt: {audit['counts']}; metadata_verified={audit['metadata_verified']}; bliskie pary między podzbiorami (<50m): {audit['cross_split_pairs_within_50m']}", flush=True)
    if audit["cross_split_pairs_within_50m"]:
        print("UWAGA: podział losowy nie jest walidacją geograficzną — sąsiednie dachy mogą współdzielić cechy okolicy.", flush=True)
    if len(dataset) < 1000:
        print("UWAGA: mały zbiór — wyniki nie stanowią wiarygodnej oceny modelu produkcyjnego.", flush=True)
    print("Etykieta non_asbestos oparta na braku wpisu GeoAzbest nie potwierdza braku azbestu.", flush=True)
    model = AsbestosCNN().to(device)
    checkpoint_path = output_dir / "best.pt"
    result = fit(model, train_loader, val_loader, device, checkpoint_path, args.epochs, config, mean, std)
    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
    model.load_state_dict(checkpoint["state_dict"])
    del checkpoint
    result["val"] = run_epoch(model, val_loader, device)
    result["test"] = run_epoch(model, test_loader, device, return_predictions=True)
    predictions = result["test"].pop("predictions")
    with (output_dir / "test_predictions.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["image_path", "label", "asbestos_probability", "prediction"])
        writer.writeheader()
        for sample, prediction in zip(manifest["test"], predictions, strict=True):
            writer.writerow({"image_path": sample["image_path"], **prediction})
    train_labels = [dataset.labels[index] for index in splits["train"]]
    majority_class = int(np.bincount(train_labels, minlength=2).argmax())
    test_labels = [dataset.labels[index] for index in splits["test"]]
    result["majority_baseline"] = classification_metrics(test_labels, [float(majority_class)] * len(test_labels))
    result["class_names"] = list(CLASS_NAMES)
    result["config"] = config
    write_json(output_dir / "metrics.json", result)
    print(f"Test najlepszego modelu (epoka {result['best_epoch']}): {json.dumps(result['test'])}", flush=True)
    model.cpu()
    del model
    if device.type == "mps":
        torch.mps.empty_cache()
    elif device.type == "cuda":
        torch.cuda.empty_cache()
    from .export import export_onnx

    export_onnx(checkpoint_path, output_dir / "model.onnx")
    print(f"Zapisano checkpoint, audyt, podział, metryki, predykcje i ONNX w {output_dir}", flush=True)


if __name__ == "__main__":
    main()
