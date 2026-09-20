from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import torch
from torch.utils.data import DataLoader

from .data import RoofDataset
from .evaluate import (
    bootstrap_intervals,
    detailed_metrics,
    load_metadata,
    plot_calibration,
    plot_confusion,
    plot_curves,
    plot_histogram,
    save_csv,
)
from .model import load_checkpoint
from .train import run_epoch, write_json


def main() -> None:
    parser = argparse.ArgumentParser(description="Ewaluacja checkpointu na niezależnym zewnętrznym datasecie")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--selected-threshold", type=float)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--bootstrap", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=2022)
    args = parser.parse_args()
    if args.selected_threshold is not None and not 0 < args.selected_threshold < 1:
        parser.error("--selected-threshold musi mieścić się w (0,1)")
    output = args.output_dir.expanduser().resolve()
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise SystemExit(f"Folder ewaluacji nie jest pusty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(args.threads)
    model, checkpoint = load_checkpoint(args.checkpoint)
    dataset = RoofDataset(args.data_dir, checkpoint["mean"], checkpoint["std"])
    result = run_epoch(model, DataLoader(dataset, batch_size=32), torch.device("cpu"), return_predictions=True)
    predictions = result.pop("predictions")
    metadata = load_metadata(dataset)
    rows = []
    for (path, _), prediction in zip(dataset.samples, predictions, strict=True):
        relative = str(path.relative_to(dataset.root))
        row = {"image_path": relative, **prediction, **metadata.get(relative, {})}
        row["prediction_threshold_0_5"] = int(float(row["asbestos_probability"]) > 0.5)
        if args.selected_threshold is not None:
            row["prediction_source_validation_threshold"] = int(float(row["asbestos_probability"]) > args.selected_threshold)
        rows.append(row)
    save_csv(output / "predictions.csv", rows)
    labels = np.asarray([int(row["label"]) for row in rows])
    probabilities = np.asarray([float(row["asbestos_probability"]) for row in rows])
    default = detailed_metrics(labels, probabilities, 0.5)
    selected = detailed_metrics(labels, probabilities, args.selected_threshold) if args.selected_threshold is not None else None
    roc_rows, pr_rows = plot_curves(labels, probabilities, output)
    save_csv(output / "roc_curve.csv", roc_rows)
    save_csv(output / "precision_recall_curve.csv", pr_rows)
    save_csv(output / "calibration.csv", plot_calibration(labels, probabilities, output))
    plot_histogram(labels, probabilities, output)
    plot_confusion(default["confusion_matrix"], output / "confusion_matrix_counts.png", False)
    plot_confusion(default["confusion_matrix"], output / "confusion_matrix_normalized.png", True)
    false_positives = sorted((row for row in rows if int(row["label"]) == 0 and float(row["asbestos_probability"]) > 0.5), key=lambda row: float(row["asbestos_probability"]), reverse=True)
    false_negatives = sorted((row for row in rows if int(row["label"]) == 1 and float(row["asbestos_probability"]) <= 0.5), key=lambda row: float(row["asbestos_probability"]))
    save_csv(output / "false_positives.csv", false_positives)
    save_csv(output / "false_negatives.csv", false_negatives)
    summary = {
        "evaluation_type": "external_dataset",
        "data_dir": str(dataset.root),
        "samples": len(dataset),
        "checkpoint_epoch": checkpoint.get("epoch"),
        "checkpoint_validation_loss": checkpoint.get("val_loss"),
        "threshold_0_5": default,
        "source_validation_selected_threshold": selected,
        "bootstrap_95_ci_threshold_0_5": bootstrap_intervals(labels, probabilities, 0.5, args.bootstrap, args.seed),
        "bootstrap_95_ci_source_validation_threshold": bootstrap_intervals(labels, probabilities, args.selected_threshold, args.bootstrap, args.seed + 1) if args.selected_threshold is not None else None,
        "false_positive_count_threshold_0_5": len(false_positives),
        "false_negative_count_threshold_0_5": len(false_negatives),
        "notes": [
            "No threshold or model parameter was selected using this external dataset.",
            "Source-id overlap with the original training dataset must be checked separately and reported.",
            "Scores are not proof of asbestos and negative labels are based on absence from GeoAzbest.",
        ],
    }
    write_json(output / "summary.json", summary)
    selected_section = ""
    if selected is not None:
        selected_section = f"""\n## Source-validation threshold {args.selected_threshold:.2f}\n\n- Accuracy: {selected['accuracy']:.4f}\n- Balanced accuracy: {selected['balanced_accuracy']:.4f}\n- Asbestos precision: {selected['precision_ppv']:.4f}\n- Asbestos recall: {selected['sensitivity_recall']:.4f}\n- Asbestos F1: {selected['asbestos']['f1']:.4f}\n- Confusion matrix: `{selected['confusion_matrix']}`\n"""
    report = f"""# External model evaluation\n\nDataset: `{dataset.root}`  \nSamples: **{len(dataset)}**  \nCheckpoint epoch: **{checkpoint.get('epoch')}**  \n\n## Threshold 0.5\n\n- Accuracy: {default['accuracy']:.4f}\n- Balanced accuracy: {default['balanced_accuracy']:.4f}\n- Asbestos precision: {default['precision_ppv']:.4f}\n- Asbestos recall/sensitivity: {default['sensitivity_recall']:.4f}\n- Specificity: {default['specificity']:.4f}\n- Asbestos F1: {default['asbestos']['f1']:.4f}\n- ROC AUC: {default['roc_auc']:.4f}\n- Average precision / PR AUC: {default['average_precision_pr_auc']:.4f}\n- MCC: {default['matthews_correlation_coefficient']:.4f}\n- Cohen's kappa: {default['cohen_kappa']:.4f}\n- Brier score: {default['brier_score']:.4f}\n- Log loss: {default['log_loss']:.4f}\n- Confusion matrix [[TN, FP], [FN, TP]]: `{default['confusion_matrix']}`\n{selected_section}\nThis is an external evaluation. The model and thresholds were not tuned on this dataset. Model scores are not confirmation of asbestos.\n"""
    (output / "REPORT.md").write_text(report, encoding="utf-8")
    figure, axis = plt.subplots(figsize=(7, 5))
    axis.scatter([float(row.get("sharpness", 0) or 0) for row in rows], probabilities, s=8, alpha=0.35)
    axis.set(xlabel="Image sharpness", ylabel="Asbestos probability", title="Probability vs image sharpness")
    figure.tight_layout()
    figure.savefig(output / "probability_vs_sharpness.png", dpi=160)
    plt.close(figure)
    print(json.dumps({"threshold_0_5": default, "source_validation_selected_threshold": selected}, indent=2), flush=True)


if __name__ == "__main__":
    main()
