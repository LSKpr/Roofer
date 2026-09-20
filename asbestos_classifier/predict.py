import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image

try:
    from .asbestos_model import IMAGE_SIZE, load_trained_model
except ImportError:
    from asbestos_model import IMAGE_SIZE, load_trained_model


def load_rgb_image(path):
    path = Path(path).expanduser().resolve()
    with Image.open(path) as image:
        image = image.convert("RGB")
        if image.size != IMAGE_SIZE:
            raise ValueError(f"Obraz musi mieć dokładnie 48x48 pikseli, otrzymano {image.size}")
        return np.asarray(image, dtype=np.float32)


def predict_probability(model, image_path):
    image = load_rgb_image(image_path)
    probabilities = model(np.expand_dims(image, axis=0), training=False).numpy()[0]
    return {
        "asbestos_probability": float(probabilities[1]),
        "non_asbestos_probability": float(probabilities[0]),
        "predicted_class": "asbestos" if probabilities[1] >= 0.5 else "non_asbestos",
    }


def parse_args():
    parser = argparse.ArgumentParser(description="Zwraca prawdopodobieństwo azbestowego dachu dla obrazu 48x48 RGB.")
    parser.add_argument("--model", required=True)
    parser.add_argument("--image", required=True)
    return parser.parse_args()


def main():
    args = parse_args()
    model = load_trained_model(args.model)
    print(json.dumps(predict_probability(model, args.image), indent=2))


if __name__ == "__main__":
    main()
