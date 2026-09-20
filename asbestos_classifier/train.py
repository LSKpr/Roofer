import argparse
import json
import random
from pathlib import Path

import numpy as np
import tensorflow as tf

try:
    from .asbestos_model import build_model, compile_model, load_trained_model, training_callbacks
    from .data import adapted_normalization, class_weights, make_dataset, prepare_splits, save_split_manifest
except ImportError:
    from asbestos_model import build_model, compile_model, load_trained_model, training_callbacks
    from data import adapted_normalization, class_weights, make_dataset, prepare_splits, save_split_manifest


def parse_args():
    parser = argparse.ArgumentParser(description="Trenuje klasyfikator dachów azbestowych dla obrazów RGB 48x48.")
    parser.add_argument("--asbestos-dir", required=True)
    parser.add_argument("--non-asbestos-dir", required=True)
    parser.add_argument("--output-dir", default="asbestos_classifier/artifacts/asbestos-inception")
    parser.add_argument("--epochs", type=int, default=128)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--validation-fraction", type=float, default=0.184)
    parser.add_argument("--test-fraction", type=float, default=0.184)
    parser.add_argument("--seed", type=int, default=2022)
    parser.add_argument("--augment", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def prepare_output(directory, overwrite):
    directory = Path(directory).expanduser().resolve()
    if directory.exists() and any(directory.iterdir()) and not overwrite:
        raise ValueError(f"Folder wynikowy nie jest pusty: {directory}. Użyj --overwrite.")
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def count_classes(values):
    return {
        "non_asbestos": sum(label == 0 for _, label in values),
        "asbestos": sum(label == 1 for _, label in values),
    }


def main():
    args = parse_args()
    random.seed(args.seed)
    np.random.seed(args.seed)
    tf.keras.utils.set_random_seed(args.seed)
    tf.config.experimental.enable_op_determinism()

    output_dir = prepare_output(args.output_dir, args.overwrite)
    splits = prepare_splits(
        args.asbestos_dir,
        args.non_asbestos_dir,
        validation_fraction=args.validation_fraction,
        test_fraction=args.test_fraction,
        seed=args.seed,
    )
    if not splits["validation"]:
        raise ValueError("Zbiór walidacyjny nie może być pusty")

    save_split_manifest(splits, output_dir / "splits.json")
    config = {
        "image_size": [48, 48],
        "classes": {"non_asbestos": 0, "asbestos": 1},
        "epochs": args.epochs,
        "batch_size": args.batch_size,
        "validation_fraction": args.validation_fraction,
        "test_fraction": args.test_fraction,
        "seed": args.seed,
        "augmentation": args.augment,
        "split_counts": {name: count_classes(values) for name, values in splits.items()},
    }
    (output_dir / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")

    normalization_dataset = make_dataset(splits["train"], args.batch_size, training=False)
    normalization = adapted_normalization(normalization_dataset)
    train_dataset = make_dataset(
        splits["train"],
        args.batch_size,
        training=True,
        augment=args.augment,
        seed=args.seed,
    )
    validation_dataset = make_dataset(splits["validation"], args.batch_size)
    test_dataset = make_dataset(splits["test"], args.batch_size) if splits["test"] else None

    model = compile_model(build_model(normalization))
    model.summary()
    history = model.fit(
        train_dataset,
        validation_data=validation_dataset,
        epochs=args.epochs,
        class_weight=class_weights(splits["train"]),
        callbacks=training_callbacks(output_dir),
    )
    model.save(output_dir / "final.keras")
    (output_dir / "history.json").write_text(json.dumps(history.history, indent=2), encoding="utf-8")

    best_model = compile_model(load_trained_model(output_dir / "best.keras"))
    metrics = {"validation": best_model.evaluate(validation_dataset, return_dict=True, verbose=0)}
    if test_dataset is not None:
        metrics["test"] = best_model.evaluate(test_dataset, return_dict=True, verbose=0)
    (output_dir / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
