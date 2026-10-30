"""Descriptores SIFT 128D, codebook propio y ResNet-18 ImageNet 512D real."""
import io
import os
from collections import Counter
from pathlib import Path
import numpy as np
from PIL import Image, ImageOps
from .paged import FixedArray
from .vector import nearest, kmeans, normalized


def decode_image(data):
    with Image.open(io.BytesIO(data)) as source:
        if source.width*source.height > 25_000_000:
            raise ValueError("La imagen supera 25 megapíxeles")
        source.load()
        return ImageOps.exif_transpose(source).convert("RGB")


def sift(data):
    import cv2
    image = np.asarray(decode_image(data).resize((224, 224)))
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    _, descriptors = cv2.SIFT_create(nfeatures=100).detectAndCompute(gray, None)
    return descriptors if descriptors is not None else np.empty((0, 128), dtype=np.float32)


class VisualWords:
    def __init__(self, path, counter=None):
        self.file = FixedArray(path, "<I128f", counter)
        self.centers = np.asarray([row[1:] for row in self.file.rows()], dtype=np.float32)
        if not len(self.centers):
            raise ValueError("Codebook vacío")

    @classmethod
    def train(cls, path, descriptors, words=128, counter=None):
        descriptors = np.asarray(descriptors, dtype=np.float32)
        centers = kmeans(descriptors, words, iterations=20)
        file = FixedArray(path, "<I128f", counter)
        try:
            file.write_all((i, *center) for i, center in enumerate(centers))
        finally:
            file.close()
        return cls(path, counter)

    def encode(self, descriptors):
        if not len(descriptors):
            return Counter()
        return Counter(f"v{int(label):04d}" for label in nearest(descriptors, self.centers))

    def close(self):
        self.file.close()


class ResNetEncoder:
    def __init__(self, cache=None, threads=4):
        import torch
        from torchvision.models import resnet18, ResNet18_Weights
        root = Path(__file__).resolve().parents[3]
        os.environ.setdefault("TORCH_HOME", str(cache or root / ".cache/torch"))
        torch.set_num_threads(threads)
        self.torch = torch
        weights = ResNet18_Weights.IMAGENET1K_V1
        self.transform = weights.transforms()
        self.model = resnet18(weights=weights).eval()
        self.model.fc = torch.nn.Identity()

    def encode(self, images):
        batch = self.torch.stack([self.transform(decode_image(data)) for data in images])
        with self.torch.inference_mode():
            return normalized(self.model(batch).cpu().numpy())
