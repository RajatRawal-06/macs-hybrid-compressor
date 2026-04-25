"""
file_detector.py — Route incoming files to the correct compression lane.

Priority:
  1. Magic bytes (first 16 bytes of file) for reliable type detection.
  2. File extension as fallback (for text formats with no magic signature).

Returns one of: 'text' | 'image' | 'audio' | 'video'
Raises ValueError for unsupported types.
"""

import os

# ── Extension whitelists ──────────────────────────────────────────────────────

TEXT_EXTENSIONS  = {'.txt', '.csv', '.py', '.js', '.ts', '.json',
                    '.html', '.css', '.xml', '.md'}
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.bmp'}
AUDIO_EXTENSIONS = {'.wav', '.mp3', '.aac', '.flac'}
VIDEO_EXTENSIONS = {'.mp4', '.mov', '.avi', '.mkv'}

ALL_SUPPORTED = TEXT_EXTENSIONS | IMAGE_EXTENSIONS | AUDIO_EXTENSIONS | VIDEO_EXTENSIONS

# ── Magic byte signatures ─────────────────────────────────────────────────────
# Each entry: (byte_offset, bytes_to_match, file_type)
_MAGIC_SIGNATURES = [
    # Images
    (0, b'\xff\xd8\xff',              'image'),   # JPEG
    (0, b'\x89PNG\r\n\x1a\n',        'image'),   # PNG
    (0, b'RIFF',                      None),      # WAV handled separately (RIFF+WAVE)
    (0, b'BM',                        'image'),   # BMP
    (0, b'WEBP',                      'image'),   # WebP (at offset 8 actually; see below)
    # Audio
    (0, b'ID3',                       'audio'),   # MP3 (ID3 tag)
    (0, b'\xff\xfb',                  'audio'),   # MP3 (raw frame)
    (0, b'\xff\xf3',                  'audio'),   # MP3
    (0, b'\xff\xf2',                  'audio'),   # MP3
    (0, b'fLaC',                      'audio'),   # FLAC
    # Video
    (4, b'ftyp',                      'video'),   # MP4/MOV
    (0, b'\x1aE\xdf\xa3',            'video'),   # MKV/WebM
    (0, b'RIFF',                      None),      # also AVI — checked below
]


def detect_file_type(filename: str, file_bytes: bytes) -> str:
    """
    Detect the compression lane for a file.

    Parameters
    ----------
    filename   : original filename (used for extension fallback)
    file_bytes : first 16+ bytes of the file content

    Returns
    -------
    'text' | 'image' | 'audio' | 'video'

    Raises
    ------
    ValueError : if the type cannot be determined or is not supported
    """
    header = file_bytes[:16] if len(file_bytes) >= 16 else file_bytes

    # ── Magic byte detection ──────────────────────────────────────────────────
    # RIFF disambiguation (WAV vs AVI)
    if header[:4] == b'RIFF':
        chunk_type = header[8:12]
        if chunk_type == b'WAVE':
            return 'audio'
        elif chunk_type == b'AVI ':
            return 'video'
        # Unknown RIFF — fall through to extension

    # WebP (RIFF....WEBP)
    if header[:4] == b'RIFF' and header[8:12] == b'WEBP':
        return 'image'

    # JPEG
    if header[:3] == b'\xff\xd8\xff':
        return 'image'

    # PNG
    if header[:8] == b'\x89PNG\r\n\x1a\n':
        return 'image'

    # BMP
    if header[:2] == b'BM':
        return 'image'

    # MP3 variants
    if header[:3] == b'ID3' or header[:2] in (b'\xff\xfb', b'\xff\xf3', b'\xff\xf2'):
        return 'audio'

    # FLAC
    if header[:4] == b'fLaC':
        return 'audio'

    # AAC (ADTS frame sync)
    if header[:2] == b'\xff\xf1' or header[:2] == b'\xff\xf9':
        return 'audio'

    # MP4/MOV (ftyp box at offset 4)
    if len(file_bytes) >= 8 and file_bytes[4:8] == b'ftyp':
        return 'video'

    # MKV / WebM
    if header[:4] == b'\x1aE\xdf\xa3':
        return 'video'

    # AVI
    if header[:4] == b'RIFF' and len(file_bytes) >= 12 and file_bytes[8:12] == b'AVI ':
        return 'video'

    # ── Extension fallback ────────────────────────────────────────────────────
    ext = os.path.splitext(filename)[1].lower()

    if ext in TEXT_EXTENSIONS:
        return 'text'
    if ext in IMAGE_EXTENSIONS:
        return 'image'
    if ext in AUDIO_EXTENSIONS:
        return 'audio'
    if ext in VIDEO_EXTENSIONS:
        return 'video'

    raise ValueError(
        f"File type '{ext}' is not supported. "
        f"Supported extensions: "
        + ", ".join(sorted(ALL_SUPPORTED))
    )


def supported_extensions_list() -> str:
    """Human-readable comma-separated list of supported extensions."""
    return ", ".join(sorted(ALL_SUPPORTED))
