"""
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
