"""
residual.py — zstd-based residual compress / decompress helpers.

Used by Lanes B (images, int16), C (audio, int32), and D (video, int16).
"""

import numpy as np
import zstandard as zstd


_ZSTD_LEVEL = 3   # level 3: fast compression, good ratio, fast decompression


def compress_residual(array: np.ndarray) -> bytes:
    """
    Compress a NumPy residual array to bytes using zstd level 3.
    The array is serialised in its native dtype (int16 or int32) — no casting.
    """
    cctx = zstd.ZstdCompressor(level=_ZSTD_LEVEL)
    return cctx.compress(array.tobytes())


def decompress_residual(data: bytes, dtype: np.dtype, shape: tuple) -> np.ndarray:
    """
    Decompress zstd bytes back to a NumPy array with the given dtype and shape.

    Parameters
    ----------
    data  : raw zstd-compressed bytes (the payload only, no header)
    dtype : e.g. np.int16 (images/video) or np.int32 (audio)
    shape : tuple e.g. (H, W, C) for images, (N,) for audio samples
    """
    dctx = zstd.ZstdDecompressor()
    raw  = dctx.decompress(data)
    return np.frombuffer(raw, dtype=dtype).reshape(shape)


def compute_image_residual(original_arr: np.ndarray, lossy_arr: np.ndarray) -> np.ndarray:
    """
    Compute per-pixel residual as int16.

    Both inputs are uint8 (H×W×C).  Cast to int16 BEFORE subtraction to
    prevent silent uint8 wraparound (e.g. 10 - 20 would become 246 as uint8).
    Returns int16 array of shape (H, W, C).
    """
    return original_arr.astype(np.int16) - lossy_arr.astype(np.int16)


def reconstruct_from_image_residual(
    lossy_arr: np.ndarray, residual_arr: np.ndarray
) -> np.ndarray:
    """
    Reconstruct original uint8 image from lossy preview + int16 residual.
    Clips to valid [0, 255] range and casts back to uint8.
    """
    return np.clip(lossy_arr.astype(np.int16) + residual_arr, 0, 255).astype(np.uint8)


def compute_audio_residual(original_samples: np.ndarray, lossy_samples: np.ndarray) -> np.ndarray:
    """
    Compute waveform residual as int32.

    Both inputs should be int32 arrays of the same length.
    The MP3 encoder/decoder introduces delay, so the caller must trim/pad
    lossy_samples to exactly match len(original_samples) BEFORE calling this.
    """
    return original_samples.astype(np.int32) - lossy_samples.astype(np.int32)


def reconstruct_from_audio_residual(
    lossy_samples: np.ndarray, residual_arr: np.ndarray
) -> np.ndarray:
    """Reconstruct original audio samples from lossy + int32 residual."""
    return (lossy_samples.astype(np.int32) + residual_arr).astype(np.int32)
