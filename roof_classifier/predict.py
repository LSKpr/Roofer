from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch
from PIL import Image

from .data import preprocess
from .model import CLASS_NAMES, load_checkpoint
from .train import select_device


def predict(checkpoint_path: Path, image_path: Path, device_name: str = "cpu") -> dict:
    device = select_device(device_name)
    model, checkpoint = load_checkpoint(checkpoint_path)
    model.to(device)
    with Image.open(image_path) as image:
        inputs = preprocess(image, checkpoint["mean"], checkpoint["std"]).unsqueeze(0).to(device)
    with torch.inference_mode():
        logits = model(inputs)
        probabilities = torch.softmax(logits, dim=1)[0]
    return {
        "class_names": list(CLASS_NAMES),
        "logits": logits[0].cpu().tolist(),
        "asbestos_probability": probabilities[1].item(),
        "predicted_class": CLASS_NAMES[probabilities.argmax().item()],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Klasyfikacja zdjęcia dachu RGB 128×128; softmax(logits)[1] = prawdopodobieństwo azbestu")
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--device", choices=("auto", "cpu", "mps", "cuda"), default="auto")
    args = parser.parse_args()
    torch.set_num_threads(4)
    print(json.dumps(predict(args.checkpoint.expanduser(), args.image.expanduser(), args.device), indent=2))


if __name__ == "__main__":
    main()
