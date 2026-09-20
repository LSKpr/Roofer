from __future__ import annotations

from pathlib import Path

import torch
from torch import nn

INPUT_SHAPE = (3, 128, 128)
MEAN = (0.3616, 0.3497, 0.3882)
STD = (0.2406, 0.2315, 0.2276)
CLASS_NAMES = ("non_asbestos", "asbestos")


class InceptionBlock(nn.Module):
    def __init__(self, in_channels: int):
        super().__init__()
        self.branch3 = nn.Sequential(
            nn.Conv2d(in_channels, 32, kernel_size=1),
            nn.ReLU(inplace=True),
            nn.Conv2d(32, 64, kernel_size=3, padding=1),
            nn.ReLU(inplace=True),
            nn.BatchNorm2d(64),
        )
        self.branch5 = nn.Sequential(
            nn.Conv2d(in_channels, 32, kernel_size=1),
            nn.ReLU(inplace=True),
            nn.Conv2d(32, 64, kernel_size=5, padding=2),
            nn.ReLU(inplace=True),
            nn.BatchNorm2d(64),
        )
        self.branch_pool = nn.Sequential(
            nn.MaxPool2d(kernel_size=3, stride=1, padding=1),
            nn.Conv2d(in_channels, 64, kernel_size=5, padding=2),
            nn.ReLU(inplace=True),
            nn.BatchNorm2d(64),
        )

    def forward(self, inputs: torch.Tensor) -> torch.Tensor:
        return torch.cat((self.branch3(inputs), self.branch5(inputs), self.branch_pool(inputs)), dim=1)


class AsbestosCNN(nn.Module):
    def __init__(self):
        super().__init__()
        layers = [
            nn.Conv2d(3, 64, kernel_size=3, padding=1, bias=False),
            nn.ReLU(inplace=True),
            nn.BatchNorm2d(64),
        ]
        for in_channels in (64, 192, 192):
            layers.extend([
                InceptionBlock(in_channels),
                nn.Dropout2d(0.55),
                nn.MaxPool2d(kernel_size=3, stride=2, padding=1),
            ])
        layers.extend([
            nn.MaxPool2d(kernel_size=3, stride=1, padding=1),
            nn.Dropout2d(0.55),
        ])
        self.features = nn.Sequential(*layers)
        self.classifier = nn.Sequential(
            nn.Flatten(),
            nn.Linear(192 * 16 * 16, 1024, bias=False),
            nn.BatchNorm1d(1024),
            nn.ReLU(inplace=True),
            nn.Dropout(0.5),
            nn.Linear(1024, 1024, bias=False),
            nn.BatchNorm1d(1024),
            nn.ReLU(inplace=True),
            nn.Dropout(0.5),
            nn.Linear(1024, 2),
        )

    def forward(self, inputs: torch.Tensor) -> torch.Tensor:
        return self.classifier(self.features(inputs))


def load_checkpoint(path: Path) -> tuple[AsbestosCNN, dict]:
    checkpoint = torch.load(path, map_location="cpu", weights_only=True)
    expected = {"input_shape": INPUT_SHAPE, "class_names": CLASS_NAMES}
    for name, value in expected.items():
        if tuple(checkpoint.get(name, ())) != value:
            raise ValueError(f"Nieprawidłowe {name} w checkpoincie: {checkpoint.get(name)}")
    mean, std = checkpoint.get("mean"), checkpoint.get("std")
    if not isinstance(mean, (list, tuple)) or not isinstance(std, (list, tuple)) or len(mean) != 3 or len(std) != 3:
        raise ValueError("Checkpoint nie zawiera poprawnego mean/std")
    if not all(isinstance(value, (int, float)) and torch.isfinite(torch.tensor(value)).item() for value in (*mean, *std)) or any(value <= 0 for value in std):
        raise ValueError("Checkpoint zawiera nieprawidłowe mean/std")
    model = AsbestosCNN()
    model.load_state_dict(checkpoint["state_dict"], strict=True)
    return model.eval(), checkpoint
