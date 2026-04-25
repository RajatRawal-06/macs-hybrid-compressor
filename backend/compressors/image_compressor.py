"""
image_compressor.py — Lane B: Image compression (Lossy JPEG + int16 zstd residual).

Pipeline:
  Compress:
    1. Load image → uint8 NumPy array X  (H×W×C)
    2. Detect complexity → choose JPEG quality (60 / 75 / 85)
    3. JPEG-encode X → X̂_bytes  (lossy bitstream)
    4. Decode X̂_bytes → X̂_pixels (int16)
    5. R = X.astype(int16) − X̂_pixels  (int16 residual)
    6. Compress R with zstd → residual payload
    7. Return (jpeg_payload, residual_payload, quality_metrics, (H,W,C))

  Decompress (perfect):
    1. Decode JPEG → X̂_pixels (int16)
    2. Decompress residual zstd → R (int16, reshape to H×W×C)
    3. X = clip(X̂_pixels + R, 0, 255).astype(uint8)

  Decompress (approximate / no residual):
    1. Decode JPEG → uint8 image → return
"""

import io
import hashlib
import numpy as np
from PIL import Image

from utils.residual import (
    compress_residual,
    decompress_residual,
    compute_image_residual,
    reconstruct_from_image_residual,
)
from utils.metrics import psnr, mse_value, ssim_score


def _canonical_png_bytes(arr: np.ndarray) -> bytes:
    """Return the PNG encoding of a uint8 RGB array — reproducible across platforms."""
    buf = io.BytesIO()
    Image.fromarray(arr.astype(np.uint8)).save(buf, format='PNG')
    return buf.getvalue()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ── Quality / complexity thresholds ──────────────────────────────────────────
QUALITY_HIGH   = 85   # complex / detailed images
QUALITY_MED    = 75   # default
QUALITY_LOW    = 60   # flat / simple images (diagrams, logos)

HIGH_THRESHOLD = 8.0
LOW_THRESHOLD  = 2.0


def _image_complexity(img_array: np.ndarray) -> float:
    """
    No-reference complexity score.
    Combines Sobel edge strength with colour variance (std).
    Higher values → complex / detailed image → use higher JPEG quality.
    """
    try:
        from skimage.filters import sobel
        gray = img_array.mean(axis=2) if img_array.ndim == 3 else img_array
        edge_strength  = float(np.mean(sobel(gray)))
        color_variance = float(np.std(img_array))
        return edge_strength * color_variance
    except ImportError:
        # skimage not available → return mid-range score → default quality
        return (HIGH_THRESHOLD + LOW_THRESHOLD) / 2.0


def _choose_quality(img_array: np.ndarray) -> int:
    score = _image_complexity(img_array)
    if score > HIGH_THRESHOLD:
        return QUALITY_HIGH
    if score < LOW_THRESHOLD:
        return QUALITY_LOW
    return QUALITY_MED


# ── JPEG helpers ──────────────────────────────────────────────────────────────

def _jpeg_encode(img_array: np.ndarray, quality: int) -> bytes:
    """Encode a uint8 NumPy array as a JPEG byte string."""
    img = Image.fromarray(img_array.astype(np.uint8))
    buf = io.BytesIO()
    # Always save as RGB so we can compute residuals cleanly
    img = img.convert('RGB')
    img.save(buf, format='JPEG', quality=quality, optimize=True)
    return buf.getvalue()


def _jpeg_decode(jpeg_bytes: bytes) -> np.ndarray:
    """Decode a JPEG byte string to an int16 H×W×3 NumPy array."""
    img = Image.open(io.BytesIO(jpeg_bytes)).convert('RGB')
    return np.array(img, dtype=np.int16)


# ── Public compress ───────────────────────────────────────────────────────────

def compress(file_bytes: bytes, original_filename: str) -> dict:
    """
    Compress an image.

    Returns
    -------
    dict with keys:
      'jpeg_payload'     : bytes  — the JPEG bitstream (stored as .macs payload)
      'residual_payload' : bytes  — zstd-compressed int16 residual
      'quality'          : int    — JPEG quality used
      'shape'            : (H, W, C) — original image dimensions
      'psnr_db'          : float
      'ssim'             : float
      'mse'              : float
      'compressed_size'  : int    — size of JPEG payload in bytes
      'residual_size'    : int    — size of residual payload in bytes
    """
    # Load original → uint8 array
    img_orig = Image.open(io.BytesIO(file_bytes)).convert('RGB')
    X = np.array(img_orig, dtype=np.uint8)
    H, W, C = X.shape

    # Adaptive quality
    quality = _choose_quality(X)

    # JPEG encode / decode (lossy round-trip)
    jpeg_bytes     = _jpeg_encode(X, quality)
    X_hat_pixels   = _jpeg_decode(jpeg_bytes)   # int16

    # Residual (int16)
    R = compute_image_residual(X, X_hat_pixels.astype(np.uint8))
    residual_compressed = compress_residual(R)

    # Quality metrics on lossy preview
    X_hat_uint8 = np.clip(X_hat_pixels, 0, 255).astype(np.uint8)
    p   = psnr(X, X_hat_uint8)
    s   = ssim_score(X, X_hat_uint8)
    m   = mse_value(X, X_hat_uint8)

    return {
        'jpeg_payload':      jpeg_bytes,
        'residual_payload':  residual_compressed,
        'quality':           quality,
        'shape':             (H, W, C),
        'psnr_db':           p,
        'ssim':              s,
        'mse':               m,
        'compressed_size':   len(jpeg_bytes),
        'residual_size':     len(residual_compressed),
        # SHA-256 of the *canonical PNG* of the pixel array — not the raw JPEG bytes.
        # Stored in .macs header so the decompressor can verify bit-exactly
        # after reconstruct_from_image_residual → re-encode as PNG.
        'sha256_canonical':  _sha256(_canonical_png_bytes(X)),
    }


# ── Public decompress ─────────────────────────────────────────────────────────

def decompress_perfect(
    jpeg_payload: bytes,
    residual_payload: bytes,
    shape: tuple,          # (H, W, C)
    original_format: str = 'PNG',
) -> bytes:
    """
    Perfect reconstruction: JPEG + residual → original image bytes.

    Parameters
    ----------
    jpeg_payload     : the JPEG bitstream from the .macs file
    residual_payload : zstd-compressed int16 residual from .macs.residual
    shape            : (H, W, C) from residual header dims
    original_format  : output format ('PNG' or 'JPEG')
    """
    H, W, C = shape

    # Decode JPEG → int16 pixel array
    X_hat_pixels = _jpeg_decode(jpeg_payload)   # int16 H×W×3

    # Decompress residual
    R = decompress_residual(residual_payload, np.int16, (H, W, C))

    # Reconstruct
    X_rec = reconstruct_from_image_residual(X_hat_pixels.astype(np.uint8), R)

    # Encode to output format
    buf = io.BytesIO()
    out_img = Image.fromarray(X_rec)
    out_fmt = original_format.upper() if original_format.upper() in ('JPEG', 'PNG', 'WEBP', 'BMP') else 'PNG'
    if out_fmt == 'JPEG':
        out_img.save(buf, format='JPEG', quality=95)
    else:
        out_img.save(buf, format=out_fmt)
    return buf.getvalue()


def decompress_approximate(jpeg_payload: bytes, original_format: str = 'PNG') -> bytes:
    """
    Approximate reconstruction: JPEG only → high-quality preview.
    No residual → no SHA-256 guarantee.
    """
    img = Image.open(io.BytesIO(jpeg_payload)).convert('RGB')
    buf = io.BytesIO()
    out_fmt = original_format.upper() if original_format.upper() in ('JPEG', 'PNG', 'WEBP', 'BMP') else 'PNG'
    if out_fmt == 'JPEG':
        img.save(buf, format='JPEG', quality=95)
    else:
        img.save(buf, format=out_fmt)
    return buf.getvalue()
