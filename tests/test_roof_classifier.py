from __future__ import annotations

import argparse
import csv
import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import torch
from PIL import Image
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

from Data import build_roof_dataset as builder
from roof_classifier.benchmark import timing
from roof_classifier.data import RoofDataset, TrainingBatchSampler, audit_dataset, metadata_groups, preprocess, stratified_group_split, stratified_split, training_mean_std
from roof_classifier.evaluate import bootstrap_intervals, detailed_metrics, select_validation_threshold
from roof_classifier.export import export_onnx
from roof_classifier.model import CLASS_NAMES, INPUT_SHAPE, MEAN, STD, AsbestosCNN, InceptionBlock
from roof_classifier.train import classification_metrics, fit, run_epoch


class PreprocessingTests(unittest.TestCase):
    def test_rgb_scaling_and_normalization(self):
        image = Image.new("RGB", (128, 128), (255, 128, 0))
        tensor = preprocess(image)
        expected = (torch.tensor([1.0, 128 / 255, 0.0]) - torch.tensor(MEAN)) / torch.tensor(STD)
        self.assertEqual(tuple(tensor.shape), INPUT_SHAPE)
        self.assertEqual(tensor.dtype, torch.float32)
        torch.testing.assert_close(tensor[:, 64, 64], expected)
        self.assertTrue(tensor.is_contiguous())

    def test_convert_to_rgb_but_do_not_resize(self):
        self.assertEqual(preprocess(Image.new("L", (128, 128))).shape[0], 3)
        with self.assertRaisesRegex(ValueError, "128"):
            preprocess(Image.new("RGB", (256, 256)))

    def test_fixed_class_order_and_ignore_preview(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in CLASS_NAMES:
                (root / name).mkdir()
                Image.new("RGB", (128, 128)).save(root / name / "roof.png")
            Image.new("RGB", (128, 128)).save(root / "preview.jpg")
            dataset = RoofDataset(root)
            self.assertEqual(len(dataset), 2)
            self.assertEqual(dataset.labels, [0, 1])
            self.assertEqual(dataset.samples[0][0].parent.name, "non_asbestos")
            self.assertEqual(dataset[1][1], 1)

    def test_training_normalization_uses_only_selected_indices(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            values = {"non_asbestos": [(0, 10, 20), (255, 255, 255)], "asbestos": [(100, 120, 140), (255, 0, 255)]}
            for class_name, colors in values.items():
                (root / class_name).mkdir()
                for index, color in enumerate(colors):
                    Image.new("RGB", (128, 128), color).save(root / class_name / f"{index}.png")
            dataset = RoofDataset(root)
            mean, std = training_mean_std(dataset, [0, 2])
            expected = np.asarray([(0, 10, 20), (100, 120, 140)], dtype=np.float64) / 255
            np.testing.assert_allclose(mean, expected.mean(axis=0), rtol=1e-12)
            np.testing.assert_allclose(std, expected.std(axis=0), rtol=1e-12)
            dataset.set_normalization(mean, std)
            tensor, _ = dataset[0]
            np.testing.assert_allclose(tensor[:, 0, 0].numpy(), (expected[0] - expected.mean(axis=0)) / expected.std(axis=0), rtol=1e-6)

    def test_building_center_crop_uses_nine_tiles(self):
        candidate = builder.Candidate("roof", 0, 0, 40, 50, 50, 0, 0)
        args = argparse.Namespace(zoom=20, crop_size=128, request_timeout=20, request_attempts=4)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(builder, "world_pixel", return_value=(10 * 256 + 7, 20 * 256 + 250)):
                with patch.object(builder, "load_tile", side_effect=lambda x, y, *args: Image.new("RGB", (256, 256), (x, y, 128))) as load, patch.object(builder, "assess_image_quality", return_value=({}, [])):
                    _, path = builder.render_candidate(candidate, "asbestos", root, root, args)
            self.assertEqual(load.call_count, 9)
            self.assertTrue(all(call.args[2] == 20 for call in load.call_args_list))
            with Image.open(path) as image:
                self.assertEqual(image.size, (128, 128))
                self.assertEqual(image.getpixel((0, 0)), (9, 20, 128))
                self.assertEqual(image.getpixel((127, 0)), (10, 20, 128))
                self.assertEqual(image.getpixel((0, 127)), (9, 21, 128))
                self.assertEqual(image.getpixel((64, 64)), (10, 20, 128))


class CandidateSelectionTests(unittest.TestCase):
    def args(self):
        with patch("sys.argv", ["build_roof_dataset.py"]):
            return builder.parse_args()

    def feature(self, width_px, height_px):
        longitude, latitude = 20.0, 52.0
        pixel_degrees = 360 / (256 * 2**20)
        right = longitude + width_px * pixel_degrees
        top = latitude + height_px * pixel_degrees * math.cos(math.radians(latitude))
        return {
            "type": "Feature", "id": "large-roof",
            "geometry": {"type": "Polygon", "coordinates": [[
                [longitude, latitude], [right, latitude], [right, top],
                [longitude, top], [longitude, latitude],
            ]]},
        }

    def test_accept_roofs_touching_old_margin_or_larger_than_crop(self):
        for width in (126, 256, 1024):
            with self.subTest(width=width):
                candidate = builder.candidate_from_feature(self.feature(width, 80), self.args())
                self.assertIsNotNone(candidate)
                self.assertAlmostEqual(candidate.width_px, width, places=4)

    def test_minimum_area_and_side_filters_are_preserved(self):
        for width, height in ((40, 40), (10, 1024)):
            with self.subTest(width=width, height=height):
                self.assertIsNone(builder.candidate_from_feature(self.feature(width, height), self.args()))

    def test_configuration_records_no_full_roof_requirement(self):
        args = self.args()
        self.assertFalse(hasattr(args, "crop_margin_px"))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            builder.write_outputs([], [], root, args, {})
            config = json.loads((root / "config.json").read_text())
        self.assertNotIn("crop_margin_px", config["selection"])
        self.assertFalse(config["selection"]["require_full_roof_in_crop"])
        self.assertEqual(config["imagery"]["crop_size"], [128, 128])


class SplitTests(unittest.TestCase):
    def test_stratified_reproducible_disjoint_70_15_15(self):
        labels = [0] * 20 + [1] * 20
        splits = stratified_split(labels, seed=2022)
        self.assertEqual(splits, stratified_split(labels, seed=2022))
        self.assertNotEqual(splits, stratified_split(labels, seed=2023))
        self.assertEqual([len(splits[name]) for name in ("train", "val", "test")], [28, 6, 6])
        all_indices = [index for indices in splits.values() for index in indices]
        self.assertEqual(sorted(all_indices), list(range(40)))
        for name, count in (("train", 14), ("val", 3), ("test", 3)):
            self.assertEqual(sum(labels[index] == 0 for index in splits[name]), count)
            self.assertEqual(sum(labels[index] == 1 for index in splits[name]), count)

    def test_imbalanced_split_rounding(self):
        labels = [0] * 101 + [1] * 23
        splits = stratified_split(labels, seed=1)
        for name, fraction in (("train", 0.7), ("val", 0.15), ("test", 0.15)):
            for label, total in ((0, 101), (1, 23)):
                count = sum(labels[index] == label for index in splits[name])
                self.assertLessEqual(abs(count - total * fraction), 1)

    def test_grouped_split_keeps_sources_together_and_stratified(self):
        labels = [0, 1] * 30
        groups = [f"sheet-{index // 2}" for index in range(60)]
        splits = stratified_group_split(labels, groups, seed=2022)
        membership = {index: name for name, indices in splits.items() for index in indices}
        for group in set(groups):
            self.assertEqual(len({membership[index] for index, value in enumerate(groups) if value == group}), 1)
        self.assertEqual(sorted(index for indices in splits.values() for index in indices), list(range(60)))
        for name, expected in (("train", 42), ("val", 10), ("test", 8)):
            self.assertLessEqual(abs(len(splits[name]) - expected), 2)
            self.assertEqual(sum(labels[index] == 0 for index in splits[name]), sum(labels[index] == 1 for index in splits[name]))
        self.assertEqual(splits, stratified_group_split(labels, groups, seed=2022))

    def test_metadata_groups_reads_ortho_sheet(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in CLASS_NAMES:
                (root / name).mkdir()
                Image.new("RGB", (128, 128)).save(root / name / "roof.png")
            dataset = RoofDataset(root)
            with (root / "metadata.csv").open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=["image_path", "ortho_feature_id"])
                writer.writeheader()
                for path, _ in dataset.samples:
                    writer.writerow({"image_path": str(path.relative_to(dataset.root)), "ortho_feature_id": "same-sheet"})
            self.assertEqual(metadata_groups(dataset), ["same-sheet", "same-sheet"])

    def test_spatial_grouping_merges_neighboring_sheets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in CLASS_NAMES:
                (root / name).mkdir()
                Image.new("RGB", (128, 128)).save(root / name / "roof.png")
            dataset = RoofDataset(root)
            with (root / "metadata.csv").open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=["image_path", "ortho_feature_id", "longitude", "latitude"])
                writer.writeheader()
                for index, (path, _) in enumerate(dataset.samples):
                    writer.writerow({"image_path": str(path.relative_to(dataset.root)), "ortho_feature_id": f"sheet-{index}", "longitude": 20 + index * 0.00001, "latitude": 52})
            groups = metadata_groups(dataset, proximity_m=50)
            self.assertEqual(groups[0], groups[1])

    def test_reject_missing_class_or_too_small_dataset(self):
        for labels in ([0] * 20, [0] * 20 + [1] * 2, [0] * 20 + [2] * 20):
            with self.subTest(labels=labels):
                with self.assertRaises(ValueError):
                    stratified_split(labels, seed=1)

    def test_no_singleton_training_batches_or_dropped_samples(self):
        for count in (2, 28, 32, 33, 64, 65, 97):
            with self.subTest(count=count):
                sampler = TrainingBatchSampler(count, batch_size=32, generator=torch.Generator().manual_seed(1))
                batches = list(sampler)
                self.assertEqual(len(batches), len(sampler))
                self.assertEqual(sorted(index for batch in batches for index in batch), list(range(count)))
                self.assertTrue(all(2 <= len(batch) <= 32 for batch in batches))


class AuditTests(unittest.TestCase):
    def make_dataset(self, root):
        for label, name in enumerate(CLASS_NAMES):
            (root / name).mkdir()
            for index in range(7):
                Image.new("RGB", (128, 128), (label * 100 + index, 20, 30)).save(root / name / f"roof_{index}.png")
        return RoofDataset(root)

    def test_audit_counts_and_fingerprint(self):
        with tempfile.TemporaryDirectory() as temporary:
            dataset = self.make_dataset(Path(temporary))
            splits = stratified_split(dataset.labels, 2022)
            audit = audit_dataset(dataset, splits)
            self.assertEqual(audit["counts"], {"non_asbestos": 7, "asbestos": 7})
            self.assertEqual(audit["split_counts"]["train"], {"non_asbestos": 5, "asbestos": 5})
            self.assertEqual(audit["duplicate_image_groups"], [])
            self.assertEqual(len(audit["fingerprint"]), 64)
            self.assertEqual(audit["fingerprint"], audit_dataset(dataset, splits)["fingerprint"])
            self.assertFalse(audit["metadata_verified"])

    def test_reject_duplicate_images_across_splits(self):
        with tempfile.TemporaryDirectory() as temporary:
            dataset = self.make_dataset(Path(temporary))
            splits = stratified_split(dataset.labels, 2022)
            source = splits["train"][0]
            destination = splits["test"][0]
            with Image.open(dataset.samples[source][0]) as image:
                image.save(dataset.samples[destination][0])
            with self.assertRaisesRegex(ValueError, "duplikat|etykiet"):
                audit_dataset(dataset, splits)

    def test_reject_inconsistent_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dataset = self.make_dataset(root)
            with (root / "metadata.csv").open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=["image_path", "label", "class", "source_id", "longitude", "latitude"])
                writer.writeheader()
                for index, (path, label) in enumerate(dataset.samples):
                    writer.writerow({"image_path": str(path.relative_to(dataset.root)), "label": 1 - label, "class": CLASS_NAMES[label], "source_id": str(index), "longitude": 20, "latitude": 52})
            with self.assertRaisesRegex(ValueError, "metadata"):
                audit_dataset(dataset, stratified_split(dataset.labels, 2022))

    def test_reject_invalid_split(self):
        with tempfile.TemporaryDirectory() as temporary:
            dataset = self.make_dataset(Path(temporary))
            splits = stratified_split(dataset.labels, 2022)
            splits["test"].append(splits["train"][0])
            with self.assertRaisesRegex(ValueError, "podział"):
                audit_dataset(dataset, splits)


class MetricTests(unittest.TestCase):
    def test_minority_metrics_and_majority_baseline(self):
        result = classification_metrics([0, 0, 0, 0, 1, 1], [0.1] * 6)
        self.assertAlmostEqual(result["accuracy"], 2 / 3)
        self.assertEqual(result["balanced_accuracy"], 0.5)
        self.assertEqual(result["asbestos"]["recall"], 0)
        self.assertEqual(result["asbestos"]["f1"], 0)
        self.assertEqual(result["roc_auc"], 0.5)
        self.assertAlmostEqual(result["average_precision"], 1 / 3)
        self.assertEqual(result["confusion_matrix"], [[4, 0], [2, 0]])

    def test_known_predictions(self):
        result = classification_metrics([0, 0, 1, 1], [0.1, 0.7, 0.4, 0.8])
        self.assertEqual(result["confusion_matrix"], [[1, 1], [1, 1]])
        self.assertEqual(result["asbestos"]["precision"], 0.5)
        self.assertEqual(result["asbestos"]["recall"], 0.5)
        self.assertEqual(result["asbestos"]["f1"], 0.5)
        self.assertEqual(result["roc_auc"], 0.75)

    def test_ties_match_argmax_and_missing_classes_are_safe(self):
        result = classification_metrics([0, 0], [0.5, 0.5])
        self.assertEqual(result["accuracy"], 1)
        self.assertIsNone(result["roc_auc"])
        self.assertIsNone(result["average_precision"])
        json.dumps(result, allow_nan=False)


class DetailedMetricTests(unittest.TestCase):
    def test_detailed_metrics_known_confusion_matrix(self):
        result = detailed_metrics([0, 0, 0, 1, 1, 1], [0.1, 0.8, 0.2, 0.9, 0.4, 0.7], 0.5)
        self.assertEqual(result["confusion_matrix"], [[2, 1], [1, 2]])
        self.assertAlmostEqual(result["sensitivity_recall"], 2 / 3)
        self.assertAlmostEqual(result["specificity"], 2 / 3)
        self.assertAlmostEqual(result["precision_ppv"], 2 / 3)
        self.assertAlmostEqual(result["negative_predictive_value"], 2 / 3)
        self.assertAlmostEqual(result["accuracy"], 2 / 3)
        self.assertTrue(-1 <= result["matthews_correlation_coefficient"] <= 1)
        json.dumps(result, allow_nan=False)

    def test_threshold_is_selected_only_from_passed_validation_values(self):
        threshold, sweep = select_validation_threshold([0, 0, 1, 1], [0.1, 0.4, 0.45, 0.9])
        self.assertGreater(threshold, 0.4)
        self.assertLess(threshold, 0.45)
        self.assertEqual(max(row["asbestos_f1"] for row in sweep), 1)

    def test_bootstrap_is_reproducible_and_finite(self):
        first = bootstrap_intervals([0, 0, 0, 1, 1, 1], [0.1, 0.2, 0.6, 0.4, 0.8, 0.9], 0.5, 20, 7)
        second = bootstrap_intervals([0, 0, 0, 1, 1, 1], [0.1, 0.2, 0.6, 0.4, 0.8, 0.9], 0.5, 20, 7)
        self.assertEqual(first, second)
        for interval in first.values():
            self.assertLessEqual(interval["lower_95"], interval["median"])
            self.assertLessEqual(interval["median"], interval["upper_95"])
        json.dumps(first, allow_nan=False)


class BenchmarkTests(unittest.TestCase):
    def test_timing_summary(self):
        result = timing([0.01, 0.02, 0.03, 0.04], batch=8)
        self.assertEqual(result["batch_size"], 8)
        self.assertEqual(result["repetitions"], 4)
        self.assertAlmostEqual(result["mean_ms"], 25)
        self.assertAlmostEqual(result["median_ms"], 25)
        self.assertAlmostEqual(result["images_per_second"], 320)
        self.assertLessEqual(result["p90_ms"], result["max_ms"])
        json.dumps(result, allow_nan=False)


class ArchitectureTests(unittest.TestCase):
    def test_exact_shapes_and_layers(self):
        with torch.device("meta"):
            model = AsbestosCNN()
            inputs = torch.empty(2, *INPUT_SHAPE)
            features = model.features(inputs)
            logits = model(inputs)
        self.assertEqual(tuple(features.shape), (2, 192, 16, 16))
        self.assertEqual(tuple(logits.shape), (2, 2))
        self.assertIsNone(model.features[0].bias)
        self.assertIsInstance(model.features[1], nn.ReLU)
        self.assertIsInstance(model.features[2], nn.BatchNorm2d)
        blocks = [layer for layer in model.features if isinstance(layer, InceptionBlock)]
        self.assertEqual(len(blocks), 3)
        for block, channels in zip(blocks, (64, 192, 192)):
            self.assertEqual(block.branch3[0].in_channels, channels)
            self.assertEqual(block.branch3[0].out_channels, 32)
            self.assertEqual(block.branch3[2].kernel_size, (3, 3))
            self.assertEqual(block.branch5[2].kernel_size, (5, 5))
            self.assertEqual(block.branch_pool[1].kernel_size, (5, 5))
            self.assertEqual(block.branch_pool[1].in_channels, channels)
            self.assertIsInstance(block.branch_pool[0], nn.MaxPool2d)
        self.assertEqual([layer.p for layer in model.modules() if isinstance(layer, nn.Dropout2d)], [0.55] * 4)
        linear = [layer for layer in model.modules() if isinstance(layer, nn.Linear)]
        self.assertEqual([(layer.in_features, layer.out_features) for layer in linear], [(49152, 1024), (1024, 1024), (1024, 2)])
        self.assertIsNone(linear[0].bias)
        self.assertIsNone(linear[1].bias)
        self.assertIsNotNone(linear[2].bias)
        self.assertEqual(CLASS_NAMES, ("non_asbestos", "asbestos"))


class ExportTests(unittest.TestCase):
    def test_valid_export_has_dynamic_batch_and_metadata(self):
        import onnx

        model = nn.Sequential(nn.Flatten(), nn.Linear(49152, 2)).eval()
        checkpoint = {"mean": list(MEAN), "std": list(STD), "class_names": list(CLASS_NAMES)}
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "model.onnx"
            with patch("roof_classifier.export.load_checkpoint", return_value=(model, checkpoint)), patch("builtins.print"):
                export_onnx(Path("unused.pt"), destination)
            graph = onnx.load(str(destination))
            self.assertEqual(graph.graph.input[0].type.tensor_type.shape.dim[0].dim_param, "batch")
            properties = {item.key: item.value for item in graph.metadata_props}
            self.assertEqual(json.loads(properties["class_names"]), list(CLASS_NAMES))
            self.assertEqual(json.loads(properties["mean"]), list(MEAN))
            self.assertEqual(list(destination.parent.iterdir()), [destination])

    def test_failed_export_does_not_publish_artifact(self):
        model = nn.Sequential(nn.Flatten(), nn.Linear(49152, 2)).eval()
        checkpoint = {"mean": list(MEAN), "std": list(STD), "class_names": list(CLASS_NAMES)}
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "model.onnx"
            with patch("roof_classifier.export.load_checkpoint", return_value=(model, checkpoint)):
                with patch("roof_classifier.export.np.testing.assert_allclose", side_effect=AssertionError("parity failed")):
                    with self.assertRaisesRegex(AssertionError, "parity failed"):
                        export_onnx(Path("unused.pt"), destination)
            self.assertFalse(destination.exists())
            self.assertEqual(list(destination.parent.iterdir()), [])

    def test_existing_export_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "model.onnx"
            destination.write_bytes(b"existing")
            with self.assertRaises(FileExistsError):
                export_onnx(Path("unused.pt"), destination)
            self.assertEqual(destination.read_bytes(), b"existing")


class TrainingTests(unittest.TestCase):
    def test_prediction_rows_preserve_order_and_class_probability(self):
        inputs = torch.tensor([[3.0, 1.0], [1.0, 4.0], [2.0, 2.0]])
        labels = torch.tensor([0, 1, 0])
        loader = DataLoader(TensorDataset(inputs, labels), batch_size=2)
        result = run_epoch(nn.Identity(), loader, torch.device("cpu"), return_predictions=True)
        self.assertEqual([row["label"] for row in result["predictions"]], labels.tolist())
        self.assertEqual([row["prediction"] for row in result["predictions"]], [0, 1, 0])
        for row, expected in zip(result["predictions"], inputs.softmax(dim=1)[:, 1]):
            self.assertAlmostEqual(row["asbestos_probability"], expected.item(), places=6)
        self.assertEqual(result["accuracy"], 1)

    def test_eval_loss_is_weighted_by_samples_and_does_not_update_weights(self):
        model = nn.Linear(3, 2)
        inputs = torch.randn(5, 3)
        labels = torch.tensor([0, 0, 1, 1, 1])
        expected = nn.functional.cross_entropy(model(inputs), labels).item()
        before = model.weight.detach().clone()
        metrics = run_epoch(model, DataLoader(TensorDataset(inputs, labels), batch_size=3), torch.device("cpu"))
        self.assertAlmostEqual(metrics["loss"], expected, places=6)
        self.assertEqual(sum(sum(row) for row in metrics["confusion_matrix"]), 5)
        self.assertFalse(model.training)
        self.assertIsNone(model.weight.grad)
        torch.testing.assert_close(model.weight, before)

    def test_backward_updates_weights(self):
        model = nn.Linear(3, 2)
        before = model.weight.detach().clone()
        loader = DataLoader(TensorDataset(torch.randn(4, 3), torch.tensor([0, 1, 0, 1])), batch_size=4)
        run_epoch(model, loader, torch.device("cpu"), torch.optim.Adam(model.parameters(), lr=0.001))
        self.assertTrue(model.training)
        self.assertFalse(torch.equal(before, model.weight))

    def test_best_checkpoint_scheduler_and_early_stopping(self):
        model = nn.Linear(3, 2)
        validation_losses = iter([0.6, 0.4] + [0.5] * 10)
        epoch = 0

        def fake_epoch(model, loader, device, optimizer=None):
            nonlocal epoch
            if optimizer is not None:
                epoch += 1
                with torch.no_grad():
                    model.weight.fill_(epoch)
                loss = 0.7
            else:
                loss = next(validation_losses)
            return {"loss": loss, "accuracy": 0.5, "confusion_matrix": [[1, 1], [1, 1]]}

        with tempfile.TemporaryDirectory() as temporary:
            checkpoint_path = Path(temporary) / "best.pt"
            with patch("roof_classifier.train.run_epoch", side_effect=fake_epoch), patch("builtins.print"):
                result = fit(model, [], [], torch.device("cpu"), checkpoint_path, max_epochs=128)
            checkpoint = torch.load(checkpoint_path, weights_only=True)
            self.assertEqual(result["best_epoch"], 2)
            self.assertEqual(len(result["history"]), 12)
            self.assertEqual(checkpoint["epoch"], 2)
            self.assertEqual(checkpoint["input_shape"], INPUT_SHAPE)
            self.assertEqual(checkpoint["mean"], list(MEAN))
            self.assertEqual(checkpoint["std"], list(STD))
            self.assertEqual(checkpoint["class_names"], list(CLASS_NAMES))
            self.assertTrue(torch.all(checkpoint["state_dict"]["weight"] == 2))
            self.assertLess(result["history"][-1]["lr"], 0.001)
            history = json.loads((checkpoint_path.parent / "history.json").read_text())
            self.assertEqual(history["best_epoch"], 2)
            self.assertEqual(len(history["history"]), 12)

    def test_nonfinite_validation_loss_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch("roof_classifier.train.run_epoch", return_value={"loss": float("nan"), "accuracy": 0}):
                with self.assertRaisesRegex(ValueError, "loss"):
                    fit(nn.Linear(3, 2), [], [], torch.device("cpu"), Path(temporary) / "best.pt", max_epochs=1)


if __name__ == "__main__":
    unittest.main()
