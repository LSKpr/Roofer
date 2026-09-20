from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import torch
from sklearn.calibration import calibration_curve
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    balanced_accuracy_score,
    brier_score_loss,
    cohen_kappa_score,
    confusion_matrix,
    f1_score,
    log_loss,
    matthews_corrcoef,
    precision_recall_curve,
    precision_recall_fscore_support,
    roc_auc_score,
    roc_curve,
)
from torch.utils.data import DataLoader, Subset

from .data import RoofDataset
from .model import CLASS_NAMES, load_checkpoint
from .train import run_epoch, write_json


def safe_ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def expected_calibration_error(labels: np.ndarray, probabilities: np.ndarray, bins: int = 10) -> float:
    edges = np.linspace(0, 1, bins + 1)
    total = len(labels)
    result = 0.0
    for lower, upper in zip(edges[:-1], edges[1:]):
        selected = (probabilities >= lower) & (probabilities < upper if upper < 1 else probabilities <= upper)
        if selected.any():
            result += selected.mean() * abs(probabilities[selected].mean() - labels[selected].mean())
    return float(result)


def detailed_metrics(labels, probabilities, threshold: float) -> dict:
    labels = np.asarray(labels, dtype=np.int64)
    probabilities = np.asarray(probabilities, dtype=np.float64)
    predictions = (probabilities > threshold).astype(np.int64)
    matrix = confusion_matrix(labels, predictions, labels=[0, 1])
    tn, fp, fn, tp = matrix.ravel()
    precision, recall, f1, support = precision_recall_fscore_support(labels, predictions, labels=[0, 1], zero_division=0)
    both = len(np.unique(labels)) == 2
    return {
        "threshold": float(threshold),
        "threshold_rule": "asbestos_probability > threshold",
        "samples": int(len(labels)),
        "confusion_matrix": matrix.tolist(),
        "confusion_matrix_normalized_true": np.divide(matrix, matrix.sum(axis=1, keepdims=True), out=np.zeros_like(matrix, dtype=float), where=matrix.sum(axis=1, keepdims=True) != 0).tolist(),
        "accuracy": float(accuracy_score(labels, predictions)),
        "balanced_accuracy": float(balanced_accuracy_score(labels, predictions)) if both else None,
        "sensitivity_recall": safe_ratio(tp, tp + fn),
        "specificity": safe_ratio(tn, tn + fp),
        "precision_ppv": safe_ratio(tp, tp + fp),
        "negative_predictive_value": safe_ratio(tn, tn + fn),
        "false_positive_rate": safe_ratio(fp, fp + tn),
        "false_negative_rate": safe_ratio(fn, fn + tp),
        "matthews_correlation_coefficient": float(matthews_corrcoef(labels, predictions)) if both else None,
        "cohen_kappa": float(cohen_kappa_score(labels, predictions)) if both else None,
        "f1_macro": float(f1_score(labels, predictions, average="macro", zero_division=0)),
        "f1_weighted": float(f1_score(labels, predictions, average="weighted", zero_division=0)),
        "roc_auc": float(roc_auc_score(labels, probabilities)) if both else None,
        "average_precision_pr_auc": float(average_precision_score(labels, probabilities)) if both else None,
        "brier_score": float(brier_score_loss(labels, probabilities)),
        "log_loss": float(log_loss(labels, np.column_stack((1 - probabilities, probabilities)), labels=[0, 1])),
        "expected_calibration_error_10_bins": expected_calibration_error(labels, probabilities),
        "non_asbestos": {"precision": float(precision[0]), "recall": float(recall[0]), "f1": float(f1[0]), "support": int(support[0])},
        "asbestos": {"precision": float(precision[1]), "recall": float(recall[1]), "f1": float(f1[1]), "support": int(support[1])},
    }


def select_validation_threshold(labels, probabilities) -> tuple[float, list[dict]]:
    sweep = []
    for threshold in np.linspace(0.01, 0.99, 99):
        metrics = detailed_metrics(labels, probabilities, float(threshold))
        sweep.append({
            "threshold": float(threshold), "asbestos_f1": metrics["asbestos"]["f1"],
            "balanced_accuracy": metrics["balanced_accuracy"], "sensitivity": metrics["sensitivity_recall"],
            "specificity": metrics["specificity"], "precision": metrics["precision_ppv"],
        })
    best = max(sweep, key=lambda row: (row["asbestos_f1"], row["balanced_accuracy"], -abs(row["threshold"] - 0.5)))
    return best["threshold"], sweep


def bootstrap_intervals(labels, probabilities, threshold: float, repetitions: int, seed: int) -> dict:
    labels = np.asarray(labels)
    probabilities = np.asarray(probabilities)
    classes = [np.flatnonzero(labels == value) for value in (0, 1)]
    rng = np.random.default_rng(seed)
    keys = ("accuracy", "balanced_accuracy", "sensitivity_recall", "specificity", "precision_ppv", "negative_predictive_value", "matthews_correlation_coefficient", "roc_auc", "average_precision_pr_auc", "brier_score")
    values = {key: [] for key in keys}
    for _ in range(repetitions):
        indices = np.concatenate([rng.choice(items, len(items), replace=True) for items in classes])
        metrics = detailed_metrics(labels[indices], probabilities[indices], threshold)
        for key in keys:
            if metrics[key] is not None:
                values[key].append(metrics[key])
    return {
        key: {"lower_95": float(np.quantile(items, 0.025)), "median": float(np.median(items)), "upper_95": float(np.quantile(items, 0.975))}
        for key, items in values.items()
    }


def save_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def load_metadata(dataset: RoofDataset) -> dict[str, dict]:
    path = dataset.root / "metadata.csv"
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8", newline="") as stream:
        return {row["image_path"]: row for row in csv.DictReader(stream)}


def plot_confusion(matrix, path: Path, normalized: bool) -> None:
    values = np.asarray(matrix, dtype=float if normalized else int)
    if normalized:
        values = np.divide(values, values.sum(axis=1, keepdims=True), out=np.zeros_like(values), where=values.sum(axis=1, keepdims=True) != 0)
    figure, axis = plt.subplots(figsize=(6, 5))
    image = axis.imshow(values, cmap="Blues", vmin=0, vmax=1 if normalized else None)
    figure.colorbar(image, ax=axis)
    axis.set(xticks=[0, 1], yticks=[0, 1], xticklabels=CLASS_NAMES, yticklabels=CLASS_NAMES, xlabel="Predicted", ylabel="Actual", title="Normalized confusion matrix" if normalized else "Confusion matrix")
    for row in range(2):
        for column in range(2):
            axis.text(column, row, f"{values[row, column]:.3f}" if normalized else str(int(values[row, column])), ha="center", va="center")
    figure.tight_layout()
    figure.savefig(path, dpi=160)
    plt.close(figure)


def plot_curves(labels, probabilities, output: Path) -> tuple[list[dict], list[dict]]:
    fpr, tpr, roc_thresholds = roc_curve(labels, probabilities)
    precision, recall, pr_thresholds = precision_recall_curve(labels, probabilities)
    roc_rows = [{"false_positive_rate": float(x), "true_positive_rate": float(y), "threshold": float(t)} for x, y, t in zip(fpr, tpr, roc_thresholds)]
    pr_rows = [{"recall": float(r), "precision": float(p), "threshold": float(t) if index < len(pr_thresholds) else ""} for index, (r, p, t) in enumerate(zip(recall, precision, np.append(pr_thresholds, np.nan)))]
    figure, axes = plt.subplots(1, 2, figsize=(12, 5))
    axes[0].plot(fpr, tpr, label=f"AUC={roc_auc_score(labels, probabilities):.3f}")
    axes[0].plot([0, 1], [0, 1], "--", color="gray")
    axes[0].set(xlabel="False positive rate", ylabel="True positive rate", title="ROC curve")
    axes[0].legend()
    axes[1].plot(recall, precision, label=f"AP={average_precision_score(labels, probabilities):.3f}")
    axes[1].axhline(np.mean(labels), linestyle="--", color="gray")
    axes[1].set(xlabel="Recall", ylabel="Precision", title="Precision–Recall curve")
    axes[1].legend()
    figure.tight_layout()
    figure.savefig(output / "roc_pr_curves.png", dpi=160)
    plt.close(figure)
    return roc_rows, pr_rows


def plot_calibration(labels, probabilities, output: Path) -> list[dict]:
    fraction, mean = calibration_curve(labels, probabilities, n_bins=10, strategy="uniform")
    rows = [{"mean_predicted_probability": float(x), "observed_positive_fraction": float(y)} for x, y in zip(mean, fraction)]
    figure, axis = plt.subplots(figsize=(6, 5))
    axis.plot(mean, fraction, marker="o")
    axis.plot([0, 1], [0, 1], "--", color="gray")
    axis.set(xlabel="Mean predicted probability", ylabel="Observed positive fraction", title="Calibration curve", xlim=(0, 1), ylim=(0, 1))
    figure.tight_layout()
    figure.savefig(output / "calibration_curve.png", dpi=160)
    plt.close(figure)
    return rows


def plot_histogram(labels, probabilities, output: Path) -> None:
    figure, axis = plt.subplots(figsize=(7, 5))
    bins = np.linspace(0, 1, 21)
    axis.hist(probabilities[np.asarray(labels) == 0], bins=bins, alpha=0.6, label="non_asbestos")
    axis.hist(probabilities[np.asarray(labels) == 1], bins=bins, alpha=0.6, label="asbestos")
    axis.set(xlabel="Asbestos probability", ylabel="Samples", title="Test probability distributions")
    axis.legend()
    figure.tight_layout()
    figure.savefig(output / "probability_histogram.png", dpi=160)
    plt.close(figure)


def plot_training(history: list[dict], output: Path) -> None:
    epochs = [row["epoch"] for row in history]
    figure, axes = plt.subplots(2, 2, figsize=(12, 9))
    for split in ("train", "val"):
        axes[0, 0].plot(epochs, [row[split]["loss"] for row in history], label=split)
        axes[0, 1].plot(epochs, [row[split]["accuracy"] for row in history], label=split)
        axes[1, 0].plot(epochs, [row[split]["asbestos"]["f1"] for row in history], label=split)
        axes[1, 1].plot(epochs, [row[split]["roc_auc"] for row in history], label=split)
    for axis, title, ylabel in zip(axes.ravel(), ("Loss", "Accuracy", "Asbestos F1", "ROC AUC"), ("Loss", "Accuracy", "F1", "AUC")):
        axis.set(xlabel="Epoch", ylabel=ylabel, title=title)
        axis.legend()
    figure.tight_layout()
    figure.savefig(output / "training_history.png", dpi=160)
    plt.close(figure)


def grouped_metrics(rows: list[dict], threshold: float) -> dict:
    result = {}
    for field in ("ortho_source", "ortho_year", "native_gsd_m"):
        groups = {}
        for value in sorted({row.get(field, "unknown") for row in rows}):
            selected = [row for row in rows if row.get(field, "unknown") == value]
            labels = [int(row["label"]) for row in selected]
            probabilities = [float(row["asbestos_probability"]) for row in selected]
            groups[str(value)] = detailed_metrics(labels, probabilities, threshold)
        result[field] = groups
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Rozszerzona ewaluacja najlepszego checkpointu; próg dobierany tylko na walidacji")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--artifacts-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--bootstrap", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=2022)
    args = parser.parse_args()
    artifacts = args.artifacts_dir.expanduser().resolve()
    output = (args.output_dir or artifacts / "evaluation").expanduser().resolve()
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise SystemExit(f"Folder ewaluacji nie jest pusty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(args.threads)
    model, checkpoint = load_checkpoint(artifacts / "best.pt")
    dataset = RoofDataset(args.data_dir, checkpoint["mean"], checkpoint["std"])
    path_to_index = {str(path.relative_to(dataset.root)): index for index, (path, _) in enumerate(dataset.samples)}
    split_manifest = json.loads((artifacts / "splits.json").read_text(encoding="utf-8"))["splits"]
    metadata = load_metadata(dataset)

    rows_by_split = {}
    for name in ("val", "test"):
        indices = [path_to_index[item["image_path"]] for item in split_manifest[name]]
        loader = DataLoader(Subset(dataset, indices), batch_size=32)
        result = run_epoch(model, loader, torch.device("cpu"), return_predictions=True)
        predictions = result.pop("predictions")
        rows = []
        for item, prediction in zip(split_manifest[name], predictions, strict=True):
            rows.append({"split": name, "image_path": item["image_path"], **prediction, **metadata.get(item["image_path"], {})})
        rows_by_split[name] = rows

    val_labels = np.asarray([int(row["label"]) for row in rows_by_split["val"]])
    val_probabilities = np.asarray([float(row["asbestos_probability"]) for row in rows_by_split["val"]])
    test_labels = np.asarray([int(row["label"]) for row in rows_by_split["test"]])
    test_probabilities = np.asarray([float(row["asbestos_probability"]) for row in rows_by_split["test"]])
    selected_threshold, sweep = select_validation_threshold(val_labels, val_probabilities)
    for row in rows_by_split["test"]:
        row["prediction_threshold_0_5"] = int(float(row["asbestos_probability"]) > 0.5)
        row["prediction_validation_threshold"] = int(float(row["asbestos_probability"]) > selected_threshold)
    save_csv(output / "predictions_val.csv", rows_by_split["val"])
    save_csv(output / "predictions_test.csv", rows_by_split["test"])
    save_csv(output / "threshold_sweep_validation.csv", sweep)

    val_default = detailed_metrics(val_labels, val_probabilities, 0.5)
    val_selected = detailed_metrics(val_labels, val_probabilities, selected_threshold)
    test_default = detailed_metrics(test_labels, test_probabilities, 0.5)
    test_selected = detailed_metrics(test_labels, test_probabilities, selected_threshold)
    roc_rows, pr_rows = plot_curves(test_labels, test_probabilities, output)
    save_csv(output / "roc_curve_test.csv", roc_rows)
    save_csv(output / "precision_recall_curve_test.csv", pr_rows)
    save_csv(output / "calibration_test.csv", plot_calibration(test_labels, test_probabilities, output))
    plot_histogram(test_labels, test_probabilities, output)
    plot_confusion(test_default["confusion_matrix"], output / "confusion_matrix_counts.png", False)
    plot_confusion(test_default["confusion_matrix"], output / "confusion_matrix_normalized.png", True)
    history = json.loads((artifacts / "history.json").read_text(encoding="utf-8"))["history"]
    plot_training(history, output)
    figure, axis = plt.subplots(figsize=(7, 5))
    axis.plot([row["threshold"] for row in sweep], [row["asbestos_f1"] for row in sweep], label="Asbestos F1")
    axis.plot([row["threshold"] for row in sweep], [row["balanced_accuracy"] for row in sweep], label="Balanced accuracy")
    axis.axvline(selected_threshold, linestyle="--", color="black", label=f"selected={selected_threshold:.2f}")
    axis.set(xlabel="Threshold selected on validation", ylabel="Score", title="Validation threshold sweep")
    axis.legend()
    figure.tight_layout()
    figure.savefig(output / "threshold_sweep_validation.png", dpi=160)
    plt.close(figure)

    false_positives = sorted((row for row in rows_by_split["test"] if int(row["label"]) == 0 and float(row["asbestos_probability"]) > 0.5), key=lambda row: float(row["asbestos_probability"]), reverse=True)
    false_negatives = sorted((row for row in rows_by_split["test"] if int(row["label"]) == 1 and float(row["asbestos_probability"]) <= 0.5), key=lambda row: float(row["asbestos_probability"]))
    save_csv(output / "false_positives.csv", false_positives)
    save_csv(output / "false_negatives.csv", false_negatives)
    summary = {
        "checkpoint_epoch": checkpoint.get("epoch"), "checkpoint_validation_loss": checkpoint.get("val_loss"),
        "threshold_selection": {"source": "validation_only", "objective": "max_asbestos_f1_then_balanced_accuracy", "selected": selected_threshold},
        "validation": {"threshold_0_5": val_default, "selected_threshold": val_selected},
        "test": {"threshold_0_5": test_default, "selected_validation_threshold": test_selected},
        "test_bootstrap_95_ci_threshold_0_5": bootstrap_intervals(test_labels, test_probabilities, 0.5, args.bootstrap, args.seed),
        "test_bootstrap_95_ci_selected_threshold": bootstrap_intervals(test_labels, test_probabilities, selected_threshold, args.bootstrap, args.seed + 1),
        "test_groups_threshold_0_5": grouped_metrics(rows_by_split["test"], 0.5),
        "false_positive_count_threshold_0_5": len(false_positives), "false_negative_count_threshold_0_5": len(false_negatives),
        "model_class_order": list(CLASS_NAMES), "notes": [
            "The selected threshold was optimized exclusively on validation data.",
            "Test data was not used for model or threshold selection.",
            "Scores are not proof of asbestos and may be uncalibrated.",
        ],
    }
    write_json(output / "summary.json", summary)
    report = f"""# Model evaluation\n\nBest checkpoint epoch: **{summary['checkpoint_epoch']}**  \nValidation-selected threshold: **{selected_threshold:.2f}**  \n\n## Test at threshold 0.5\n\n- Accuracy: {test_default['accuracy']:.4f}\n- Balanced accuracy: {test_default['balanced_accuracy']:.4f}\n- Asbestos precision: {test_default['precision_ppv']:.4f}\n- Asbestos recall/sensitivity: {test_default['sensitivity_recall']:.4f}\n- Specificity: {test_default['specificity']:.4f}\n- Asbestos F1: {test_default['asbestos']['f1']:.4f}\n- ROC AUC: {test_default['roc_auc']:.4f}\n- Average precision / PR AUC: {test_default['average_precision_pr_auc']:.4f}\n- MCC: {test_default['matthews_correlation_coefficient']:.4f}\n- Cohen's kappa: {test_default['cohen_kappa']:.4f}\n- Brier score: {test_default['brier_score']:.4f}\n- Log loss: {test_default['log_loss']:.4f}\n- Confusion matrix [[TN, FP], [FN, TP]]: `{test_default['confusion_matrix']}`\n\n## Test at validation-selected threshold\n\n- Accuracy: {test_selected['accuracy']:.4f}\n- Balanced accuracy: {test_selected['balanced_accuracy']:.4f}\n- Asbestos precision: {test_selected['precision_ppv']:.4f}\n- Asbestos recall: {test_selected['sensitivity_recall']:.4f}\n- Asbestos F1: {test_selected['asbestos']['f1']:.4f}\n- Confusion matrix: `{test_selected['confusion_matrix']}`\n\nThe alternative threshold was selected only on validation data. See `summary.json` for confidence intervals and grouped metrics, CSV files for raw curves/predictions, and PNG files for plots. Model scores are not confirmation of asbestos.\n"""
    (output / "REPORT.md").write_text(report, encoding="utf-8")
    print(json.dumps({"selected_threshold": selected_threshold, "test_threshold_0_5": test_default, "test_selected_threshold": test_selected}, indent=2), flush=True)


if __name__ == "__main__":
    main()
