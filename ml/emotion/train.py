"""Emotion model training stub.

Sprint N will implement full training pipeline using facial landmark features.
"""

import argparse
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train ARIA emotion classifier")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("models/emotion"))
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--batch-size", type=int, default=32)
    return parser.parse_args()


def train(args: argparse.Namespace) -> None:
    print(f"[stub] Training emotion model on {args.data_dir}")
    print(f"[stub] Epochs: {args.epochs}, batch size: {args.batch_size}")
    print(f"[stub] Output: {args.output_dir}")
    raise NotImplementedError("Emotion model training not yet implemented")


if __name__ == "__main__":
    args = parse_args()
    train(args)
