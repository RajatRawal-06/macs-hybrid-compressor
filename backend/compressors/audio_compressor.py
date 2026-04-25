"""
audio_compressor.py — Lane C: Audio compression (MP3 + int32 zstd residual).

Pipeline:
  Compress:
    1. Load with pydub → raw PCM samples X (int32)
    2. Classify audio (speech / music / mixed) via FFT
    3. Encode as MP3 at adaptive bitrate → X̂_bytes
    4. Decode MP3 back → X̂_samples (int32), trimmed/padded to match len(X)
    5. R = X − X̂_samples  (int32 residual, no overflow risk)
    6. Compress R with zstd → residual payload

  Reconstruct (perfect):
    Decode MP3 → X̂, decompress R, X = X̂ + R → WAV

  Reconstruct (approximate):
    Decode MP3 → WAV (no residual)

Key correctness fix: MP3 encoder/decoder delay causes sample count mismatch.
We always trim or zero-pad X̂_samples to exactly len(X_samples) before subtraction.
Stored frame_count in residual header allows correct trimming at decode time.
"""

import io
import numpy as np

try:
    from pydub import AudioSegment  # type: ignore
    _PYDUB_AVAILABLE = True
except ImportError:
    _PYDUB_AVAILABLE = False

from utils.residual import compress_residual, decompress_residual

# ── Bitrate selection ─────────────────────────────────────────────────────────
BITRATE_SPEECH = '64k'
BITRATE_MIXED  = '128k'
BITRATE_MUSIC  = '192k'


def _classify_audio(samples: np.ndarray, sample_rate: int) -> str:
    """
    Classify audio as 'speech', 'music', or 'mixed' using FFT-based
    spectral analysis of the first second.
    """
    try:
        window = samples[:sample_rate]
        fft_mag = np.abs(np.fft.rfft(window))
        n = len(fft_mag)
        nyq = sample_rate // 2

        # Frequency band indices
        speech_hi_hz = 3400
        speech_mask  = slice(int(300 * n // nyq), int(speech_hi_hz * n // nyq))
        music_mask   = slice(int(speech_hi_hz * n // nyq), None)

        speech_band = np.mean(fft_mag[speech_mask]) if speech_mask.start < len(fft_mag) else 1.0
        music_band  = np.mean(fft_mag[music_mask])  if music_mask.start  < len(fft_mag) else 1.0

        ratio = speech_band / (music_band + 1e-9)
        if ratio > 3.0:
            return 'speech'
        if ratio < 0.5:
            return 'music'
        return 'mixed'
    except Exception:
        return 'mixed'


def _bitrate_for_class(audio_class: str) -> str:
    return {'speech': BITRATE_SPEECH, 'music': BITRATE_MUSIC}.get(audio_class, BITRATE_MIXED)


# ── Internal encode / decode ──────────────────────────────────────────────────

def _encode_mp3(audio_seg: 'AudioSegment', bitrate: str) -> bytes:
    buf = io.BytesIO()
    audio_seg.export(buf, format='mp3', bitrate=bitrate)
    return buf.getvalue()


def _decode_mp3(mp3_bytes: bytes) -> 'AudioSegment':
    return AudioSegment.from_mp3(io.BytesIO(mp3_bytes))


def _seg_to_samples(audio_seg: 'AudioSegment') -> np.ndarray:
    return np.array(audio_seg.get_array_of_samples(), dtype=np.int32)


def _align_samples(decoded_samples: np.ndarray, target_len: int) -> np.ndarray:
    """Trim or zero-pad decoded samples to exactly target_len (handles MP3 delay)."""
    n = len(decoded_samples)
    if n > target_len:
        return decoded_samples[:target_len]
    if n < target_len:
        return np.pad(decoded_samples, (0, target_len - n))
    return decoded_samples


# ── Public compress ───────────────────────────────────────────────────────────

def compress(file_bytes: bytes, original_filename: str) -> dict:
    """
    Compress audio.

    Returns
    -------
    dict:
      'mp3_payload'      : bytes  — MP3 bitstream
      'residual_payload' : bytes  — zstd int32 residual
      'audio_class'      : str    — 'speech' | 'music' | 'mixed'
      'bitrate'          : str    — e.g. '128k'
      'sample_rate'      : int
      'channels'         : int
      'sample_width'     : int    — bytes per sample (1 or 2)
      'frame_count'      : int    — number of samples per channel in original
      'compressed_size'  : int
      'residual_size'    : int
    """
    if not _PYDUB_AVAILABLE:
        raise RuntimeError("pydub is not installed. Install it with: pip install pydub")

    ext = original_filename.rsplit('.', 1)[-1].lower()
    fmt_map = {'mp3': 'mp3', 'aac': 'aac', 'flac': 'flac', 'wav': 'wav'}
    fmt = fmt_map.get(ext, 'wav')

    # Load audio
    audio = AudioSegment.from_file(io.BytesIO(file_bytes), format=fmt)
    # Normalise to WAV in memory for stable raw sample access
    audio_wav_buf = io.BytesIO()
    audio.export(audio_wav_buf, format='wav')
    audio_wav_buf.seek(0)
    audio = AudioSegment.from_wav(audio_wav_buf)

    sample_rate  = audio.frame_rate
    channels     = audio.channels
    sample_width = audio.sample_width

    X_samples = _seg_to_samples(audio)
    frame_count = len(X_samples)

    # Classify → select bitrate
    mono_samples = X_samples[::channels] if channels > 1 else X_samples
    audio_class  = _classify_audio(mono_samples, sample_rate)
    bitrate      = _bitrate_for_class(audio_class)

    # Encode MP3
    mp3_bytes = _encode_mp3(audio, bitrate)

    # Decode MP3 back (handles encoder delay)
    X_hat_audio   = _decode_mp3(mp3_bytes)
    X_hat_samples = _seg_to_samples(X_hat_audio)
    X_hat_samples = _align_samples(X_hat_samples, frame_count)

    # Residual (int32, safe from overflow)
    R = X_samples.astype(np.int32) - X_hat_samples.astype(np.int32)
    residual_compressed = compress_residual(R)

    return {
        'mp3_payload':      mp3_bytes,
        'residual_payload': residual_compressed,
        'audio_class':      audio_class,
        'bitrate':          bitrate,
        'sample_rate':      sample_rate,
        'channels':         channels,
        'sample_width':     sample_width,
        'frame_count':      frame_count,
        'compressed_size':  len(mp3_bytes),
        'residual_size':    len(residual_compressed),
    }


# ── Public decompress ─────────────────────────────────────────────────────────

def decompress_perfect(
    mp3_payload: bytes,
    residual_payload: bytes,
    frame_count: int,
    sample_rate: int,
    channels: int,
    sample_width: int,
) -> bytes:
    """
    Perfect reconstruction: MP3 + residual → original WAV bytes.
    frame_count allows us to truncate the decoded samples to the exact original length.
    """
    if not _PYDUB_AVAILABLE:
        raise RuntimeError("pydub is not installed.")

    X_hat_audio   = _decode_mp3(mp3_payload)
    X_hat_samples = _seg_to_samples(X_hat_audio)
    X_hat_samples = _align_samples(X_hat_samples, frame_count)

    R = decompress_residual(residual_payload, np.int32, (frame_count,))
    X_reconstructed = reconstruct_samples = (X_hat_samples + R).astype(np.int32)

    # Rebuild AudioSegment from raw samples
    raw_bytes = X_reconstructed.astype(
        np.int16 if sample_width == 2 else np.int8
    ).tobytes()
    audio_out = AudioSegment(
        data=raw_bytes,
        sample_width=sample_width,
        frame_rate=sample_rate,
        channels=channels,
    )
    buf = io.BytesIO()
    audio_out.export(buf, format='wav')
    return buf.getvalue()


def decompress_approximate(mp3_payload: bytes) -> bytes:
    """Approximate reconstruction: decode MP3 → WAV (no residual)."""
    if not _PYDUB_AVAILABLE:
        raise RuntimeError("pydub is not installed.")
    audio = _decode_mp3(mp3_payload)
    buf = io.BytesIO()
    audio.export(buf, format='wav')
    return buf.getvalue()
