"""
generate_samples.py — Creates all four sample files for testing MACS Compressor.
Run this ONCE from the repo root after installing dependencies:
  python generate_samples.py

Produces:
  samples/sample.txt   ← already exists, skip
  samples/sample.jpg   ← synthetic 800x600 colour photo (Pillow)
  samples/sample.wav   ← 5-second 44.1 kHz stereo tone (numpy + wave)
  samples/sample.py    ← Python source file
  samples/sample.json  ← structured JSON data
"""

import os
import wave
import struct
import math
import random

SAMPLES_DIR = os.path.join(os.path.dirname(__file__), 'samples')
os.makedirs(SAMPLES_DIR, exist_ok=True)

# ── sample.jpg ────────────────────────────────────────────────────────────────
def make_sample_jpg():
    path = os.path.join(SAMPLES_DIR, 'sample.jpg')
    if os.path.exists(path):
        print(f"  [skip] {path} already exists")
        return
    try:
        import numpy as np
        from PIL import Image

        rng = random.Random(42)
        W, H = 800, 600
        img_array = np.zeros((H, W, 3), dtype=np.uint8)

        # Sky gradient
        for y in range(H // 2):
            r = int(10 + (y / (H // 2)) * 40)
            g = int(20 + (y / (H // 2)) * 80)
            b = int(80 + (y / (H // 2)) * 120)
            img_array[y, :] = [r, g, b]

        # Ground gradient
        for y in range(H // 2, H):
            t = (y - H // 2) / (H // 2)
            img_array[y, :] = [int(30 + t * 60), int(80 + t * 30), int(20 + t * 10)]

        # Sun
        cx, cy, sr = 600, 80, 60
        Y, X = np.ogrid[:H, :W]
        mask = (X - cx) ** 2 + (Y - cy) ** 2 <= sr ** 2
        img_array[mask] = [255, 230, 100]

        # Add noise for JPEG complexity testing
        noise = np.random.RandomState(0).randint(-20, 20, (H, W, 3))
        img_array = np.clip(img_array.astype(np.int16) + noise, 0, 255).astype(np.uint8)

        Image.fromarray(img_array).save(path, 'JPEG', quality=95)
        size_kb = os.path.getsize(path) // 1024
        print(f"  [ok] {path}  ({size_kb} KB)")
    except ImportError as e:
        print(f"  [warn] Could not create sample.jpg: {e}")

# ── sample.wav ────────────────────────────────────────────────────────────────
def make_sample_wav():
    path = os.path.join(SAMPLES_DIR, 'sample.wav')
    if os.path.exists(path):
        print(f"  [skip] {path} already exists")
        return
    try:
        sample_rate  = 44100
        duration_sec = 5
        n_samples    = sample_rate * duration_sec
        channels     = 2
        sample_width = 2   # 16-bit

        # Mix of tones: 440 Hz + 880 Hz + some noise (music-like)
        import numpy as np
        t = np.linspace(0, duration_sec, n_samples, endpoint=False)
        left  = (np.sin(2 * np.pi * 440 * t) * 0.4
                 + np.sin(2 * np.pi * 880 * t) * 0.2
                 + np.sin(2 * np.pi * 1320 * t) * 0.15
                 + np.random.RandomState(1).randn(n_samples) * 0.05)
        right = (np.sin(2 * np.pi * 440 * t + 0.5) * 0.4
                 + np.sin(2 * np.pi * 660 * t) * 0.2
                 + np.random.RandomState(2).randn(n_samples) * 0.05)
        left  = np.clip(left,  -1, 1)
        right = np.clip(right, -1, 1)
        interleaved = np.empty(n_samples * 2, dtype=np.float64)
        interleaved[0::2] = left
        interleaved[1::2] = right
        pcm16 = (interleaved * 32767).astype(np.int16)

        with wave.open(path, 'wb') as wf:
            wf.setnchannels(channels)
            wf.setsampwidth(sample_width)
            wf.setframerate(sample_rate)
            wf.writeframes(pcm16.tobytes())

        size_kb = os.path.getsize(path) // 1024
        print(f"  [ok] {path}  ({size_kb} KB)")
    except ImportError as e:
        print(f"  [warn] Could not create sample.wav: {e}")

# ── sample.py ─────────────────────────────────────────────────────────────────
def make_sample_py():
    path = os.path.join(SAMPLES_DIR, 'sample.py')
    if os.path.exists(path):
        print(f"  [skip] {path} already exists")
        return
    code = '''"""
sample.py — Sample Python file for MACS Compressor Lane A (text/code) testing.
This file exercises typical code patterns: functions, classes, comprehensions, docstrings.
"""

import os
import sys
import math
from typing import List, Optional, Dict, Tuple


class CompressionMetrics:
    """Holds quality metrics for a compression result."""

    def __init__(self, original_bytes: int, compressed_bytes: int,
                 residual_bytes: int = 0):
        self.original_bytes   = original_bytes
        self.compressed_bytes = compressed_bytes
        self.residual_bytes   = residual_bytes

    @property
    def lossy_ratio(self) -> float:
        return self.original_bytes / max(self.compressed_bytes, 1)

    @property
    def total_ratio(self) -> float:
        total = self.compressed_bytes + self.residual_bytes
        return self.original_bytes / max(total, 1)

    @property
    def space_savings_pct(self) -> float:
        return ((self.original_bytes - self.compressed_bytes) /
                max(self.original_bytes, 1)) * 100

    def __repr__(self) -> str:
        return (f"CompressionMetrics(original={self.original_bytes}B, "
                f"compressed={self.compressed_bytes}B, "
                f"ratio={self.lossy_ratio:.2f}x, "
                f"savings={self.space_savings_pct:.1f}%)")


def fibonacci(n: int) -> int:
    """Return the nth Fibonacci number (0-indexed)."""
    if n <= 1:
        return n
    a, b = 0, 1
    for _ in range(2, n + 1):
        a, b = b, a + b
    return b


def psnr(original: List[float], lossy: List[float]) -> float:
    """Compute Peak Signal-to-Noise Ratio in dB."""
    mse = sum((o - l) ** 2 for o, l in zip(original, lossy)) / len(original)
    if mse == 0:
        return float("inf")
    return 10 * math.log10(255 ** 2 / mse)


def sha256_hex(data: bytes) -> str:
    import hashlib
    return hashlib.sha256(data).hexdigest()


if __name__ == "__main__":
    m = CompressionMetrics(2_400_000, 184_320, 92_160)
    print(m)
    print(f"Fibonacci(20) = {fibonacci(20)}")
    print(f"SHA-256 of 'hello' = {sha256_hex(b'hello')}")
    print(f"Fibonacci sequence: {[fibonacci(i) for i in range(10)]}")
'''
    with open(path, 'w', encoding='utf-8') as f:
        f.write(code)
    size_kb = os.path.getsize(path) // 1024
    print(f"  [ok] {path}  ({max(size_kb,1)} KB)")

# ── sample.json ───────────────────────────────────────────────────────────────
def make_sample_json():
    import json
    path = os.path.join(SAMPLES_DIR, 'sample.json')
    if os.path.exists(path):
        print(f"  [skip] {path} already exists")
        return
    data = {
        "project": "MACS Compressor",
        "version": "2.0",
        "algorithms": [
            {"lane": "A", "type": "text", "method": "LSTM + Arithmetic Coding", "lossless": True},
            {"lane": "B", "type": "image", "method": "JPEG + zstd residual",   "lossless": False},
            {"lane": "C", "type": "audio", "method": "MP3 + zstd residual",    "lossless": False},
            {"lane": "D", "type": "video", "method": "FFmpeg H.264 CRF 23",    "lossless": False},
        ],
        "benchmarks": [
            {"file": "sample.txt", "original_kb": 1200, "compressed_kb": 360, "ratio": 3.3},
            {"file": "sample.jpg", "original_kb": 2400, "compressed_kb": 180, "ratio": 13.3},
            {"file": "sample.wav", "original_kb": 5000, "compressed_kb": 380, "ratio": 13.2},
            {"file": "sample.mp4", "original_kb": 15000, "compressed_kb": 6000, "ratio": 2.5},
        ],
        "guarantee": "SHA-256 byte-perfect reconstruction via residual coding",
        "residual_equation": "X = X_hat + R  where  R = X - X_hat (decoded domain)",
    }
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)
    size_kb = os.path.getsize(path) // 1024
    print(f"  [ok] {path}  ({max(size_kb,1)} KB)")

# ── main ──────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    print("Generating sample files...")
    make_sample_jpg()
    make_sample_wav()
    make_sample_py()
    make_sample_json()
    print("\nDone. All sample files are in samples/")
    print("Note: sample.mp4 must be provided manually (requires FFmpeg + video source).")
