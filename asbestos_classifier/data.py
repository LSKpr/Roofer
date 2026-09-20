import hashlib
import json
import random
from pathlib import Path

import tensorflow as tf
from tensorflow.keras import layers

try:
    from .asbestos_model import IMAGE_SIZE
except ImportError:
    from asbestos_model import IMAGE_SIZE

SUPPORTED_EXTENSIONS = {".bmp", ".jpeg", ".jpg", ".png"}


def discover_images(directory):
    directory = Path(directory).expanduser().resolve()
    if not directory.is_dir():
        raise ValueError(f"Folder nie istnieje: {directory}")
    images = sorted(path for path in directory.rglob("*") if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS)
    if not images:
        raise ValueError(f"Brak obsługiwanych obrazów w: {directory}")
    return images


def reject_duplicate_files(labeled_paths):
    hashes = {}
    for path, label in labeled_paths:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest in hashes:
            previous_path, previous_label = hashes[digest]
            relation = "sprzeczne klasy" if previous_label != label else "duplikat"
            raise ValueError(f"Wykryto {relation}: {previous_path} oraz {path}")
        hashes[digest] = (path, label)


def split_one_class(paths, validation_fraction, test_fraction, random_generator):
    paths = list(paths)
    random_generator.shuffle(paths)
    validation_count = round(len(paths) * validation_fraction)
    test_count = round(len(paths) * test_fraction)
    train_count = len(paths) - validation_count - test_count
    if train_count < 2:
        raise ValueError("Za mało obrazów w klasie po podziale danych")
    test = paths[:test_count]
    validation = paths[test_count : test_count + validation_count]
    train = paths[test_count + validation_count :]
    return train, validation, test


def prepare_splits(asbestos_dir, non_asbestos_dir, validation_fraction=0.184, test_fraction=0.184, seed=2022):
    if validation_fraction < 0 or test_fraction < 0 or validation_fraction + test_fraction >= 0.8:
        raise ValueError("Nieprawidłowe proporcje validation/test")

    asbestos = discover_images(asbestos_dir)
    non_asbestos = discover_images(non_asbestos_dir)
    all_images = [(path, 1) for path in asbestos] + [(path, 0) for path in non_asbestos]
    reject_duplicate_files(all_images)

    random_generator = random.Random(seed)
    asbestos_split = split_one_class(asbestos, validation_fraction, test_fraction, random_generator)
    non_asbestos_split = split_one_class(non_asbestos, validation_fraction, test_fraction, random_generator)
    names = ("train", "validation", "test")
    splits = {}

    for index, name in enumerate(names):
        labeled = [(path, 1) for path in asbestos_split[index]] + [
            (path, 0) for path in non_asbestos_split[index]
        ]
        random_generator.shuffle(labeled)
        splits[name] = labeled

    return splits


def decode_image(path, label):
    encoded = tf.io.read_file(path)
    image = tf.io.decode_image(encoded, channels=3, expand_animations=False)
    image = tf.cast(tf.ensure_shape(image, (*IMAGE_SIZE, 3)), tf.float32)
    label = tf.one_hot(label, depth=2, dtype=tf.float32)
    return image, label


def augment_image(image, label):
    rotations = tf.random.uniform((), minval=0, maxval=4, dtype=tf.int32)
    image = tf.image.rot90(image, rotations)
    image = tf.image.random_flip_left_right(image)
    image = tf.image.random_flip_up_down(image)
    return image, label


def make_dataset(labeled_paths, batch_size, training=False, augment=False, seed=2022):
    paths = [str(path) for path, _ in labeled_paths]
    labels = [label for _, label in labeled_paths]
    dataset = tf.data.Dataset.from_tensor_slices((paths, labels))
    if training:
        dataset = dataset.shuffle(max(len(paths), 1), seed=seed, reshuffle_each_iteration=True)
    dataset = dataset.map(decode_image, num_parallel_calls=tf.data.AUTOTUNE, deterministic=True)
    if training and augment:
        dataset = dataset.map(augment_image, num_parallel_calls=tf.data.AUTOTUNE, deterministic=True)
    dataset = dataset.batch(batch_size, drop_remainder=False)
    return dataset.prefetch(tf.data.AUTOTUNE)


def adapted_normalization(train_dataset):
    normalization = layers.Normalization(axis=-1, name="featurewise_standardization")
    normalization.adapt(train_dataset.map(lambda images, labels: images))
    return normalization


def class_weights(train_paths):
    counts = {0: 0, 1: 0}
    for _, label in train_paths:
        counts[label] += 1
    total = counts[0] + counts[1]
    return {label: total / (2 * count) for label, count in counts.items()}


def save_split_manifest(splits, path):
    payload = {
        name: [
            {"path": str(image_path), "class": "asbestos" if label == 1 else "non_asbestos"}
            for image_path, label in values
        ]
        for name, values in splits.items()
    }
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
