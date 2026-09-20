from __future__ import annotations

import csv
import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from Data import build_roof_dataset as builder


def arguments():
    with patch("sys.argv", ["build_roof_dataset.py"]):
        return builder.parse_args()


def roof_image():
    y, x = np.indices((128, 128))
    pixels = np.full((128, 128, 3), (45, 90, 35), dtype=np.uint8)
    roof = 110 + ((x // 4 + y // 16) % 2) * 50
    pixels[16:112, 16:112] = roof[16:112, 16:112, None]
    mask = Image.new("L", (128, 128))
    ImageDraw.Draw(mask).rectangle((16, 16, 111, 111), fill=255)
    return Image.fromarray(pixels), mask


class ImageQualityTests(unittest.TestCase):
    def test_accept_sharp_roof_with_green_surroundings(self):
        image, mask = roof_image()
        metrics, reasons = builder.assess_image_quality(image, mask, arguments())
        self.assertEqual(reasons, [])
        self.assertGreater(metrics["green_fraction"], 0.4)
        self.assertEqual(metrics["roof_green_fraction"], 0)
        self.assertGreater(metrics["roof_fraction"], 0.5)
        self.assertEqual(metrics["region_source"], "footprint")

    def test_reject_blur_in_roof_even_with_sharp_background(self):
        image, mask = roof_image()
        blurred = image.filter(ImageFilter.GaussianBlur(5))
        rng = np.random.default_rng(42)
        background = Image.fromarray(rng.integers(0, 256, (128, 128, 3), dtype=np.uint8))
        background.paste(blurred, (0, 0), mask)
        metrics, reasons = builder.assess_image_quality(background, mask, arguments())
        self.assertLess(metrics["sharpness"], arguments().min_sharpness)
        self.assertIn("low_sharpness", reasons)

    def test_reject_textured_grass(self):
        rng = np.random.default_rng(42)
        noise = rng.integers(-20, 21, (128, 128, 1))
        image = Image.fromarray(np.clip(np.array([45, 110, 35]) + noise, 0, 255).astype(np.uint8))
        mask = Image.new("L", (128, 128), 255)
        metrics, reasons = builder.assess_image_quality(image, mask, arguments())
        self.assertGreater(metrics["sharpness"], arguments().min_sharpness)
        self.assertIn("too_much_green", reasons)
        self.assertIn("green_over_roof", reasons)

    def test_reject_blank_imagery(self):
        _, reasons = builder.assess_image_quality(Image.new("RGB", (128, 128), "gray"), Image.new("L", (128, 128), 255), arguments())
        self.assertIn("low_contrast", reasons)
        self.assertIn("low_sharpness", reasons)
        self.assertIn("few_edges", reasons)

    def test_reject_missing_or_tiny_footprint(self):
        image, _ = roof_image()
        for size in (0, 8):
            mask = Image.new("L", (128, 128))
            if size:
                ImageDraw.Draw(mask).rectangle((60, 60, 60 + size, 60 + size), fill=255)
            with self.subTest(size=size):
                _, reasons = builder.assess_image_quality(image, mask, arguments())
                self.assertIn("insufficient_roof_coverage", reasons)

    def test_large_roof_can_cover_entire_crop(self):
        y, x = np.indices((128, 128))
        gray = (100 + ((x // 4 + y // 16) % 2) * 60).astype(np.uint8)
        image = Image.fromarray(gray).convert("RGB")
        metrics, reasons = builder.assess_image_quality(image, Image.new("L", (128, 128), 255), arguments())
        self.assertEqual(reasons, [])
        self.assertEqual(metrics["roof_fraction"], 1)

    def test_old_images_without_footprints_use_explicit_center_fallback(self):
        image, _ = roof_image()
        metrics, reasons = builder.assess_image_quality(image, None, arguments())
        self.assertEqual(reasons, [])
        self.assertEqual(metrics["region_source"], "center_fallback")
        self.assertIsNone(metrics["roof_fraction"])

    def test_invalid_thresholds_are_rejected(self):
        for option, value in (("--max-green-fraction", "1.2"), ("--min-sharpness", "-1"), ("--min-contrast", "nan")):
            with self.subTest(option=option), patch("sys.argv", ["builder", option, value]), patch("sys.stderr"):
                with self.assertRaises(SystemExit):
                    builder.parse_args()


class RoofCenterTests(unittest.TestCase):
    def test_concave_roof_centroid_outside_is_recentered_inside(self):
        polygon = [[[0, 0], [6, 0], [6, 6], [4, 6], [4, 2], [2, 2], [2, 6], [0, 6], [0, 0]]]
        self.assertFalse(builder.point_in_polygon(builder.geometry_centroid([polygon]), polygon))
        center, selected, method = builder.roof_center([polygon])
        self.assertTrue(builder.point_in_polygon(center, selected))
        self.assertEqual(method, "interior_point")

    def test_courtyard_is_not_selected_as_roof(self):
        polygon = [
            [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]],
            [[2, 2], [8, 2], [8, 8], [2, 8], [2, 2]],
        ]
        center, selected, _ = builder.roof_center([polygon])
        self.assertTrue(builder.point_in_polygon(center, selected))
        self.assertFalse(builder.point_in_ring(center, polygon[1]))

    def test_multipolygon_uses_largest_roof_not_gap_between_roofs(self):
        small = [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]
        large = [[[10, 0], [14, 0], [14, 4], [10, 4], [10, 0]]]
        center, selected, method = builder.roof_center([small, large])
        self.assertEqual(selected, large)
        self.assertEqual(center, (12, 2))
        self.assertEqual(method, "centroid")

    def test_polygon_mask_preserves_holes_and_clips_without_resizing(self):
        polygon = [[[-20, -20], [150, -20], [150, 150], [-20, 150]], [[50, 50], [78, 50], [78, 78], [50, 78]]]
        mask = builder.polygon_mask(polygon, (128, 128))
        self.assertEqual(mask.size, (128, 128))
        self.assertEqual(mask.getpixel((0, 0)), 255)
        self.assertEqual(mask.getpixel((64, 64)), 0)


class CollectionQualityTests(unittest.TestCase):
    def test_render_projects_roof_mask_without_resizing(self):
        args = arguments()
        scale = 256 * 2**20
        center_x, center_y = builder.world_pixel(20, 52, 20)
        ring = [
            [(center_x + dx) / scale * 360 - 180, math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (center_y + dy) / scale))))]
            for dx, dy in ((-48, -48), (48, -48), (48, 48), (-48, 48), (-48, -48))
        ]
        candidate = builder.candidate_from_feature({"id": "roof", "geometry": {"type": "Polygon", "coordinates": [ring]}}, args)
        y, x = np.indices((256, 256))
        tile = Image.fromarray((100 + ((x // 4 + y // 16) % 2) * 60).astype(np.uint8)).convert("RGB")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(builder, "load_tile", return_value=tile) as load:
                rendered, path = builder.render_candidate(candidate, "asbestos", root, root, args)
            self.assertEqual(load.call_count, 9)
            self.assertTrue(path.is_file())
            self.assertEqual(rendered.quality["region_source"], "footprint")
            self.assertGreater(rendered.quality["roof_fraction"], 0.55)
            self.assertLess(rendered.quality["roof_fraction"], 0.60)
            xs = [point[0] for point in rendered.crop_polygon[0]]
            self.assertAlmostEqual(max(xs) - min(xs), 96, places=4)
            self.assertLess(abs(min(xs) - 16), 1)
            with Image.open(path) as image:
                metrics, reasons = builder.assess_image_quality(image, builder.polygon_mask(rendered.crop_polygon, image.size), args)
            self.assertEqual(reasons, [])
            self.assertEqual(metrics, rendered.quality)

    def test_rejected_crop_is_not_saved_to_training_class(self):
        args = arguments()
        candidate = builder.Candidate("roof", 20, 52, 100, 100, 100, 0, 0)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(builder, "load_tile", return_value=Image.new("RGB", (256, 256), (40, 90, 30))):
                with self.assertRaises(builder.QualityRejected):
                    builder.render_candidate(candidate, "asbestos", root, root, args)
            self.assertEqual(list(root.glob("*.png")), [])

    def test_rejection_refills_target_and_is_reported_separately(self):
        args = arguments()
        args.workers = 1
        bad = builder.Candidate("bad", 20, 52, 100, 100, 100, 0, 0)
        good = builder.Candidate("good", 21, 52, 100, 100, 100, 0, 0)
        image, mask = roof_image()
        metrics, _ = builder.assess_image_quality(image, mask, args)
        good.quality = metrics

        def render(candidate, class_name, destination, cache_dir, args):
            if candidate.source_id == "bad":
                raise builder.QualityRejected(["too_much_green"], metrics, image)
            path = destination / "good.png"
            image.save(path)
            return candidate, path

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(builder, "render_candidate", side_effect=render), patch("builtins.print"):
                records, failures, rejections = builder.download_class([bad, good], "asbestos", 1, 1, root, root, args)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["source_id"], "good")
            self.assertEqual(failures, [])
            self.assertEqual(len(rejections), 1)
            self.assertEqual(rejections[0]["reasons"], "too_much_green")
            self.assertTrue((root / "quality_rejections_asbestos.csv").is_file())
            self.assertEqual([path.name for path in (root / "asbestos").glob("*.png")], ["good.png"])

    def test_audit_does_not_modify_source_images(self):
        args = arguments()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "asbestos").mkdir()
            path = source / "asbestos" / "grass.png"
            Image.new("RGB", (128, 128), (45, 100, 30)).save(path)
            before = path.read_bytes()
            with (source / "metadata.csv").open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=["image_path", "class", "label"])
                writer.writeheader()
                writer.writerow({"image_path": "asbestos/grass.png", "class": "asbestos", "label": 1})
            destination = root / "audit"
            destination.mkdir()
            with patch("builtins.print"):
                builder.audit_existing_dataset(source, destination, args)
            report = json.loads((destination / "quality_summary.json").read_text())
            self.assertEqual(report["rejected"], 1)
            self.assertEqual(report["accepted"], 0)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(len(list((source / "asbestos").glob("*.png"))), 1)


if __name__ == "__main__":
    unittest.main()
