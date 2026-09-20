from __future__ import annotations

import csv
import hashlib
import math
import random
from collections import defaultdict
from pathlib import Path
from typing import Iterator, Sequence

import numpy as np
import torch
from PIL import Image
from torch.utils.data import Dataset, Sampler

from .model import CLASS_NAMES, INPUT_SHAPE, MEAN, STD


def preprocess(image: Image.Image, mean: Sequence[float] = MEAN, std: Sequence[float] = STD) -> torch.Tensor:
    if image.size != (128, 128):
        raise ValueError(f"Oczekiwano obrazu 128×128, otrzymano {image.size}; skalowanie jest wyłączone")
    pixels = np.array(image.convert("RGB"), dtype=np.float32, copy=True)
    tensor = torch.from_numpy(pixels).permute(2, 0, 1).contiguous().div_(255.0)
    mean_tensor, std_tensor = torch.tensor(mean, dtype=torch.float32), torch.tensor(std, dtype=torch.float32)
    if mean_tensor.shape != (3,) or std_tensor.shape != (3,) or not torch.isfinite(mean_tensor).all() or not torch.isfinite(std_tensor).all() or (std_tensor <= 0).any():
        raise ValueError("mean/std muszą zawierać po 3 skończone wartości, a std musi być dodatnie")
    return tensor.sub_(mean_tensor[:, None, None]).div_(std_tensor[:, None, None])


class RoofDataset(Dataset):
    def __init__(self, root: Path, mean: Sequence[float] = MEAN, std: Sequence[float] = STD):
        self.root = root.expanduser().resolve()
        self.set_normalization(mean, std)
        self.samples: list[tuple[Path, int]] = []
        for label, class_name in enumerate(CLASS_NAMES):
            directory = self.root / class_name
            images = sorted(path for path in directory.glob("*") if path.suffix.lower() in {".png", ".jpg", ".jpeg"} and path.is_file())
            if not images:
                raise ValueError(f"Brak zdjęć klasy {class_name} w {directory}")
            for path in images:
                with Image.open(path) as image:
                    if image.size != INPUT_SHAPE[1:]:
                        raise ValueError(f"{path}: oczekiwano 128×128, otrzymano {image.size}")
                    image.verify()
                self.samples.append((path, label))
        self.labels = [label for _, label in self.samples]

    def set_normalization(self, mean: Sequence[float], std: Sequence[float]) -> None:
        if len(mean) != 3 or len(std) != 3 or any(not math.isfinite(value) for value in (*mean, *std)) or any(value <= 0 for value in std):
            raise ValueError("Nieprawidłowe mean/std")
        self.mean, self.std = tuple(float(value) for value in mean), tuple(float(value) for value in std)

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, index: int) -> tuple[torch.Tensor, int]:
        path, label = self.samples[index]
        with Image.open(path) as image:
            return preprocess(image, self.mean, self.std), label


def training_mean_std(dataset: RoofDataset, indices: Sequence[int]) -> tuple[tuple[float, ...], tuple[float, ...]]:
    if not indices:
        raise ValueError("Nie można policzyć normalizacji z pustego treningu")
    channel_sum = np.zeros(3, dtype=np.float64)
    channel_squared_sum = np.zeros(3, dtype=np.float64)
    pixels = 0
    for index in indices:
        path, _ = dataset.samples[index]
        with Image.open(path) as image:
            values = np.asarray(image.convert("RGB"), dtype=np.float64) / 255.0
        channel_sum += values.sum(axis=(0, 1))
        channel_squared_sum += np.square(values).sum(axis=(0, 1))
        pixels += values.shape[0] * values.shape[1]
    mean = channel_sum / pixels
    variance = np.maximum(channel_squared_sum / pixels - np.square(mean), 0)
    std = np.sqrt(variance)
    if not np.isfinite(mean).all() or not np.isfinite(std).all() or np.any(std <= 0):
        raise ValueError("Nieprawidłowa normalizacja obliczona ze zbioru treningowego")
    return tuple(mean.tolist()), tuple(std.tolist())


def stratified_split(labels: Sequence[int], seed: int) -> dict[str, list[int]]:
    if set(labels) != {0, 1}:
        raise ValueError("Wymagane są obie klasy: 0 = non_asbestos, 1 = asbestos")
    rng = random.Random(seed)
    splits = {"train": [], "val": [], "test": []}
    for label in (0, 1):
        indices = [index for index, value in enumerate(labels) if value == label]
        if len(indices) < 7:
            raise ValueError(f"Klasa {CLASS_NAMES[label]} wymaga co najmniej 7 zdjęć do podziału 70/15/15")
        rng.shuffle(indices)
        targets = [len(indices) * fraction for fraction in (0.7, 0.15, 0.15)]
        counts = [math.floor(target) for target in targets]
        remaining = len(indices) - sum(counts)
        for position in sorted(range(3), key=lambda index: targets[index] - counts[index], reverse=True)[:remaining]:
            counts[position] += 1
        start = 0
        for name, count in zip(splits, counts):
            splits[name].extend(indices[start : start + count])
            start += count
    for indices in splits.values():
        rng.shuffle(indices)
    return splits


def metadata_groups(dataset: RoofDataset, field: str = "ortho_feature_id", proximity_m: float = 0) -> list[str] | None:
    path = dataset.root / "metadata.csv"
    if not path.is_file():
        return None
    with path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if not rows or field not in rows[0]:
        return None
    records = {row["image_path"]: row for row in rows}
    paths = [str(path.relative_to(dataset.root)) for path, _ in dataset.samples]
    if len(records) != len(rows) or set(records) != set(paths) or any(not records[path].get(field) for path in paths):
        raise ValueError(f"metadata.csv nie zawiera kompletnego grupowania {field}")
    groups = [records[path][field] for path in paths]
    if proximity_m <= 0:
        return groups
    if any(not records[path].get("longitude") or not records[path].get("latitude") for path in paths):
        raise ValueError("metadata.csv nie zawiera współrzędnych do grupowania przestrzennego")
    unique = {group: index for index, group in enumerate(sorted(set(groups)))}
    parent = list(range(len(unique)))

    def root(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(first, second):
        first, second = root(first), root(second)
        if first != second:
            parent[max(first, second)] = min(first, second)

    coordinates = [[math.radians(float(records[path]["latitude"])), math.radians(float(records[path]["longitude"]))] for path in paths]
    from sklearn.neighbors import BallTree

    neighbors = BallTree(coordinates, metric="haversine").query_radius(coordinates, r=proximity_m / 6_371_000)
    for first, indices in enumerate(neighbors):
        for second in indices:
            if second > first and groups[first] != groups[second]:
                union(unique[groups[first]], unique[groups[second]])
    return [f"spatial-component-{root(unique[group])}" for group in groups]


def stratified_group_split(labels: Sequence[int], groups: Sequence[str], seed: int) -> dict[str, list[int]]:
    if len(labels) != len(groups) or set(labels) != {0, 1}:
        raise ValueError("Grupy i etykiety muszą mieć równą długość oraz obie klasy")
    grouped = defaultdict(list)
    for index, group in enumerate(groups):
        grouped[str(group)].append(index)
    if len(grouped) < 7:
        raise ValueError("Podział grupowy 70/15/15 wymaga co najmniej 7 grup")
    rng = random.Random(seed)
    items = list(grouped.items())
    rng.shuffle(items)
    items.sort(key=lambda item: len(item[1]), reverse=True)
    names = ("train", "val", "test")
    fractions = {"train": 0.7, "val": 0.15, "test": 0.15}
    totals = {label: sum(value == label for value in labels) for label in (0, 1)}
    targets = {name: {label: totals[label] * fractions[name] for label in (0, 1)} for name in names}
    targets_total = {name: len(labels) * fractions[name] for name in names}
    splits = {name: [] for name in names}
    counts = {name: {0: 0, 1: 0} for name in names}
    for _, indices in items:
        group_counts = {label: sum(labels[index] == label for index in indices) for label in (0, 1)}
        def score(candidate):
            total = 0.0
            for name in names:
                for label in (0, 1):
                    value = counts[name][label] + (group_counts[label] if name == candidate else 0)
                    total += ((value - targets[name][label]) / max(targets[name][label], 1)) ** 2
                value = len(splits[name]) + (len(indices) if name == candidate else 0)
                total += ((value - targets_total[name]) / max(targets_total[name], 1)) ** 2
            return total, names.index(candidate)
        selected = min(names, key=score)
        splits[selected].extend(indices)
        for label in (0, 1):
            counts[selected][label] += group_counts[label]
    if any(not splits[name] or {labels[index] for index in splits[name]} != {0, 1} for name in names):
        raise ValueError("Nie udało się utworzyć grupowego podziału zawierającego obie klasy")
    for indices in splits.values():
        rng.shuffle(indices)
    return splits


def audit_dataset(dataset: RoofDataset, splits: dict[str, list[int]]) -> dict:
    all_indices = [index for indices in splits.values() for index in indices]
    if set(splits) != {"train", "val", "test"} or sorted(all_indices) != list(range(len(dataset))):
        raise ValueError("Nieprawidłowy podział: każdy obraz musi wystąpić dokładnie raz")
    membership = {index: name for name, indices in splits.items() for index in indices}
    fingerprint = hashlib.sha256()
    image_groups = defaultdict(list)
    low_contrast = []
    for index, (path, label) in enumerate(dataset.samples):
        relative = str(path.relative_to(dataset.root))
        with Image.open(path) as image:
            pixels = np.array(image.convert("RGB"))
        digest = hashlib.sha256(pixels.tobytes()).hexdigest()
        image_groups[digest].append(index)
        fingerprint.update(f"{relative}\0{label}\0{digest}\n".encode())
        if float(pixels.std(axis=(0, 1)).max()) < 2:
            low_contrast.append(relative)
    duplicate_groups = []
    for indices in image_groups.values():
        if len(indices) < 2:
            continue
        paths = [str(dataset.samples[index][0].relative_to(dataset.root)) for index in indices]
        if len({dataset.labels[index] for index in indices}) > 1:
            raise ValueError(f"Sprzeczne etykiety dla identycznego obrazu: {paths}")
        if len({membership[index] for index in indices}) > 1:
            raise ValueError(f"Wyciek danych: duplikat obrazu między podzbiorami: {paths}")
        duplicate_groups.append(paths)
    result = {
        "counts": {name: dataset.labels.count(label) for label, name in enumerate(CLASS_NAMES)},
        "split_counts": {
            name: {class_name: sum(dataset.labels[index] == label for index in indices) for label, class_name in enumerate(CLASS_NAMES)}
            for name, indices in splits.items()
        },
        "fingerprint": fingerprint.hexdigest(),
        "duplicate_image_groups": duplicate_groups,
        "low_contrast_images": low_contrast,
        "metadata_verified": False,
        "cross_split_pairs_within_50m": None,
    }
    metadata_path = dataset.root / "metadata.csv"
    if not metadata_path.is_file():
        return result
    with metadata_path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    records = {row["image_path"]: row for row in rows}
    expected_paths = {str(path.relative_to(dataset.root)) for path, _ in dataset.samples}
    if len(records) != len(rows) or set(records) != expected_paths:
        raise ValueError("metadata.csv nie odpowiada dokładnie plikom obrazów")
    coordinates = []
    identities = defaultdict(list)
    centers = defaultdict(list)
    for index, (path, label) in enumerate(dataset.samples):
        relative = str(path.relative_to(dataset.root))
        row = records[relative]
        if int(row["label"]) != label or row["class"] != CLASS_NAMES[label]:
            raise ValueError(f"Sprzeczna etykieta w metadata.csv: {relative}")
        longitude, latitude = float(row["longitude"]), float(row["latitude"])
        if not math.isfinite(longitude) or not math.isfinite(latitude) or not (-180 <= longitude <= 180 and -85.05112878 <= latitude <= 85.05112878):
            raise ValueError(f"Nieprawidłowe współrzędne w metadata.csv: {relative}")
        coordinates.append([math.radians(latitude), math.radians(longitude)])
        identities[(row["class"], row["source_id"])].append(index)
        centers[(round(longitude, 7), round(latitude, 7))].append(index)
    for indices in list(identities.values()) + list(centers.values()):
        if len(indices) > 1 and (len({membership[index] for index in indices}) > 1 or len({dataset.labels[index] for index in indices}) > 1):
            raise ValueError("metadata.csv: ten sam budynek ma sprzeczne etykiety lub występuje w różnych podzbiorach")
    from sklearn.neighbors import BallTree

    earth_radius = 6_371_000
    neighbors, distances = BallTree(coordinates, metric="haversine").query_radius(
        coordinates, r=50 / earth_radius, return_distance=True, sort_results=True,
    )
    nearby_pairs = []
    for first, (indices, radii) in enumerate(zip(neighbors, distances)):
        for second, radius in zip(indices, radii):
            if second > first and membership[first] != membership[second]:
                nearby_pairs.append({
                    "first": str(dataset.samples[first][0].relative_to(dataset.root)),
                    "second": str(dataset.samples[second][0].relative_to(dataset.root)),
                    "splits": [membership[first], membership[second]],
                    "distance_m": float(radius * earth_radius),
                })
    result["metadata_verified"] = True
    result["cross_split_pairs_within_50m"] = len(nearby_pairs)
    result["closest_cross_split_pairs"] = sorted(nearby_pairs, key=lambda pair: pair["distance_m"])[:20]
    return result


class TrainingBatchSampler(Sampler[list[int]]):
    def __init__(self, count: int, batch_size: int, generator: torch.Generator):
        if count < 2 or batch_size < 3:
            raise ValueError("BatchNorm wymaga co najmniej 2 próbek; batch_size musi wynosić co najmniej 3")
        self.count = count
        self.batch_size = batch_size
        self.generator = generator

    def __iter__(self) -> Iterator[list[int]]:
        indices = torch.randperm(self.count, generator=self.generator).tolist()
        batches = [indices[start : start + self.batch_size] for start in range(0, self.count, self.batch_size)]
        if len(batches[-1]) == 1:
            batches[-1].insert(0, batches[-2].pop())
        yield from batches

    def __len__(self) -> int:
        return math.ceil(self.count / self.batch_size)
