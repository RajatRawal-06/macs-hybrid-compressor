"""
text_compressor.py — Lane A: Text / Code compression (Lossless).

Primary algorithm: LSTM byte-prediction + Arithmetic Coding (constriction).
Fallback  algorithm: zlib deflate (if TensorFlow / constriction not installed).

The LSTM model is loaded lazily on first use so the Flask server starts even
without the model weights — it will simply use zlib for text files.

Compress  → returns (macs_payload_bytes, model_version_byte_used)
Decompress → returns original_bytes

.macs file structure for text:
  [72-byte header] [payload]

Payload = arithmetic-coded bitstream (primary)
        | zlib-deflated bytes          (fallback, model_version=0x00)
"""

import io
import os
import zlib
import hashlib
import numpy as np

# ── Model version constants ───────────────────────────────────────────────────
MODEL_VERSION_ZLIB = 0x00   # legacy fallback
MODEL_VERSION_V1   = 0x01   # lstm_text_v1.h5
MODEL_VERSION_ZSTD = 0x02   # high-speed lossless (zstandard)

# max file size enforced by the route, but double-check here too
MAX_TEXT_SIZE_BYTES = 700 * 1024 * 1024   # 700 MB

# ── Lazy model loader ─────────────────────────────────────────────────────────

_lstm_model  = None
_lstm_loaded = False
_MODEL_PATH  = os.path.join(os.path.dirname(__file__), '..', 'models', 'lstm_text_v1.h5')


def _try_load_lstm():
    """Attempt to load the LSTM model once; silently fall back to zlib."""
    global _lstm_model, _lstm_loaded
    if _lstm_loaded:
        return _lstm_model
    _lstm_loaded = True
    model_path = os.path.abspath(_MODEL_PATH)
    if not os.path.exists(model_path):
        return None
    try:
        from tensorflow.keras.models import load_model  # type: ignore
        _lstm_model = load_model(model_path, compile=False)
        print(f"[text_compressor] LSTM v1 loaded from {model_path}")
    except Exception as exc:
        print(f"[text_compressor] LSTM load failed ({exc}); using zlib fallback")
        _lstm_model = None
    return _lstm_model


# ── Arithmetic-coding helpers (constriction) ──────────────────────────────────

def _lstm_predict_probabilities(model, context_bytes: bytes, seq_len: int = 64) -> np.ndarray:
    """
    Run a single LSTM forward pass and return the per-byte probability
    distribution (256-dimensional softmax) for the next byte.

    Parameters
    ----------
    context_bytes : the bytes seen so far (up to the last `seq_len`)
    seq_len       : context window length
    """
    # Pad or truncate context to seq_len
    ctx = list(context_bytes[-seq_len:])
    pad = [0] * (seq_len - len(ctx))
    inp = np.array([pad + ctx], dtype=np.float32) / 255.0  # shape (1, seq_len)
    inp = inp[:, :, np.newaxis]                              # shape (1, seq_len, 1)
    probs = model.predict(inp, verbose=0)[0]                 # shape (256,)
    probs = np.clip(probs, 1e-9, 1.0)
    probs /= probs.sum()
    return probs.astype(np.float64)


def _compress_with_lstm(data: bytes, model) -> bytes:
    """
    Compress `data` using LSTM per-byte predictions + arithmetic coding
    (constriction library).  Returns the compressed bitstream as bytes.
    """
    import constriction  # type: ignore

    codec = constriction.stream.stack.AnsCoder()
    symbols = list(data)
    # Encode in reverse order (ANS is LIFO)
    for i in range(len(symbols) - 1, -1, -1):
        probs = _lstm_predict_probabilities(model, data[:i])
        model_dist = constriction.stream.model.Categorical(probs)
        codec.encode_symbol(symbols[i], model_dist)
    return codec.get_compressed().tobytes()


def _decompress_with_lstm(payload: bytes, original_length: int, model) -> bytes:
    """
    Decompress an arithmetic-coded payload using the LSTM model.
    """
    import constriction  # type: ignore

    codec = constriction.stream.stack.AnsCoder.from_compressed(
        np.frombuffer(payload, dtype=np.uint32)
    )
    result = []
    for i in range(original_length):
        probs   = _lstm_predict_probabilities(model, bytes(result))
        model_d = constriction.stream.model.Categorical(probs)
        symbol  = codec.decode_symbol(model_d)
        result.append(symbol)
    return bytes(result)


# ── Public API ────────────────────────────────────────────────────────────────

def compress(file_bytes: bytes) -> tuple[bytes, int]:
    """
    Compress text/code bytes.

    Returns
    -------
    (payload_bytes, model_version_used)
      payload_bytes  : the compressed bitstream (stored after the .macs header)
      model_version  : MODEL_VERSION_V1 (LSTM) or MODEL_VERSION_ZLIB (fallback)
    """
    model = _try_load_lstm()

    if model is not None:
        try:
            payload = _compress_with_lstm(file_bytes, model)
            return payload, MODEL_VERSION_V1
        except Exception as exc:
            print(f"[text_compressor] LSTM compress failed ({exc}); falling back to zlib")

    # ── Primary Lossless: Zstandard (zstd) ───────────────────────────────────
    try:
        import zstandard as _zstd
        cctx = _zstd.ZstdCompressor(level=3, threads=-1)
        payload = cctx.compress(file_bytes)
        return payload, MODEL_VERSION_ZSTD
    except ImportError:
        # Final fallback: zlib — always available in standard library
        payload = zlib.compress(file_bytes, level=9)
        return payload, MODEL_VERSION_ZLIB
    except Exception as exc:
        print(f"[text_compressor] zstd compress failed ({exc}); falling back to zlib")
        payload = zlib.compress(file_bytes, level=9)
        return payload, MODEL_VERSION_ZLIB


def decompress(payload: bytes, original_length: int, model_version: int) -> bytes:
    """
    Decompress a Lane A payload.

    Parameters
    ----------
    payload         : the bytes after the 72-byte .macs header
    original_length : original file size stored in the header (for ANS decoding)
    model_version   : read from header byte 7
    """
    if model_version == MODEL_VERSION_ZLIB:
        return zlib.decompress(payload)

    if model_version == MODEL_VERSION_V1:
        model = _try_load_lstm()
        if model is None:
            raise RuntimeError(
                "MODEL_VERSION_MISMATCH: .macs file requires lstm_text_v1.h5 "
                "but the model is not installed on this server."
            )
        return _decompress_with_lstm(payload, original_length, model)

    if model_version == MODEL_VERSION_ZSTD:
        import zstandard as _zstd
        dctx = _zstd.ZstdDecompressor()
        return dctx.decompress(payload, max_output_size=original_length)

    raise ValueError(
        f"MODEL_VERSION_MISMATCH: unknown model version 0x{model_version:02x}. "
        f"Supported: 0x00 (zlib), 0x01 (lstm_v1), 0x02 (zstd)."
    )
