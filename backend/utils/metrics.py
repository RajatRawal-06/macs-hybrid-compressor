"""
metrics.py — Compression quality metrics.

  sha256_of_bytes(data)          → hex string
  sha256_of_file(filepath)       → hex string
  compression_ratio(orig, comp)  → float
  space_savings(orig, comp)      → float (0–100)
  psnr(original_arr, lossy_arr)  → float (dB)
  ssim_score(original_arr, lossy_arr) → float (0–1)
"""

import hashlib
import math
import numpy as np


# ── SHA-256 ──────────────────────────────────────────────────────────────────

def sha256_of_bytes(data: bytes) -> str:
    """SHA-256 of an in-memory byte string; returns hex digest."""
    return hashlib.sha256(data).hexdigest()


def sha256_of_file(filepath: str) -> str:
    """SHA-256 of a file on disk; streams in 64 KB chunks to handle large files."""
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


# ── Compression ratios ────────────────────────────────────────────────────────

def compression_ratio(original_bytes: int, compressed_bytes: int) -> float:
    """original / compressed.  Clamp denominator to avoid division by zero."""
    if compressed_bytes <= 0:
        return 0.0
    return round(original_bytes / compressed_bytes, 2)


def space_savings(original_bytes: int, compressed_bytes: int) -> float:
    """Percentage of original size saved (0–100)."""
    if original_bytes <= 0:
        return 0.0
    return round(((original_bytes - compressed_bytes) / original_bytes) * 100, 2)


def total_compression_ratio(original_bytes: int, compressed_bytes: int, residual_bytes: int) -> float:
    """Ratio when both compressed + residual are kept."""
    total = compressed_bytes + residual_bytes
    if total <= 0:
        return 0.0
    return round(original_bytes / total, 2)


def total_space_savings(original_bytes: int, compressed_bytes: int, residual_bytes: int) -> float:
    """Space savings when both files are kept (archival use-case)."""
    total = compressed_bytes + residual_bytes
    if original_bytes <= 0:
        return 0.0
    return round(((original_bytes - total) / original_bytes) * 100, 2)


# ── Image quality metrics (Lane B) ───────────────────────────────────────────

def psnr(original_arr: np.ndarray, lossy_arr: np.ndarray) -> float:
    """
    Peak Signal-to-Noise Ratio in dB between original and lossy preview.
    Computed on lossy preview ONLY — perfect reconstruction gives ∞ PSNR.
    Both arrays must be uint8 (0–255).
    """
    original = original_arr.astype(np.float64)
    lossy    = lossy_arr.astype(np.float64)
    mse = np.mean((original - lossy) ** 2)
    if mse == 0.0:
        return float('inf')
    return round(10.0 * math.log10(255.0 ** 2 / mse), 4)


def mse_value(original_arr: np.ndarray, lossy_arr: np.ndarray) -> float:
    """Mean squared error between original and lossy arrays."""
    return round(float(np.mean((original_arr.astype(np.float64) - lossy_arr.astype(np.float64)) ** 2)), 4)


def ssim_score(original_arr: np.ndarray, lossy_arr: np.ndarray) -> float:
    """
    Structural Similarity Index (0–1) between original and lossy preview.
    Requires scikit-image.  channel_axis=2 is required for RGB images.
    """
    try:
        from skimage.metrics import structural_similarity
        is_color = original_arr.ndim == 3 and original_arr.shape[2] >= 3
        if is_color:
            score = structural_similarity(
                original_arr,
                lossy_arr,
                channel_axis=2,
                data_range=255,
            )
        else:
            score = structural_similarity(
                original_arr.squeeze(),
                lossy_arr.squeeze(),
                data_range=255,
            )
        return round(float(score), 4)
    except ImportError:
        return 0.0


def psnr_label(psnr_db: float) -> str:
    """Human-readable quality label for a given PSNR value."""
    if psnr_db == float('inf'):
        return "Perfect (lossless)"
    if psnr_db > 40:
        return "Excellent quality"
    if psnr_db >= 35:
        return "Good quality"
    if psnr_db >= 30:
        return "Acceptable quality"
    return "Visibly degraded — consider increasing quality setting"
