"""
header.py — .macs and .macs.residual file format pack/unpack.

.macs header: 72 bytes fixed
  Offset  Len  Field
  0       4    Magic b'MACS'
  4       1    Version 0x02
  5       1    File Type (0x01=text, 0x02=image, 0x03=audio, 0x04=video)
  6       1    Has Residual (0x01/0x00)
  7       1    Model Version (LSTM version for Lane A; 0x00 for others)
  8       8    Original Size uint64 little-endian
  16      32   SHA-256 raw bytes of original file
  48      24   Original Name UTF-8, null-padded to 24 bytes

.macs.residual header: 32 bytes fixed
  Offset  Len  Field
  0       4    Magic b'MACR'
  4       4    Parent SHA-256 truncated (first 4 bytes)
  8       8    Residual data length uint64
  16      4    Dim1 (H for images, frame_count for video, sample_count for audio)
  20      4    Dim2 (W for images/video, channels for audio)
  24      4    Dim3 (C channels for images/video, sample_width_bytes for audio)
  28      4    Reserved 0x00000000
"""

import struct

MACS_MAGIC           = b'MACS'
MACR_MAGIC           = b'MACR'
HEADER_SIZE          = 72
RESIDUAL_HEADER_SIZE = 32

FILE_TYPE_TEXT  = 0x01
FILE_TYPE_IMAGE = 0x02
FILE_TYPE_AUDIO = 0x03
FILE_TYPE_VIDEO = 0x04

FILE_TYPE_NAMES = {
    FILE_TYPE_TEXT:  'text',
    FILE_TYPE_IMAGE: 'image',
    FILE_TYPE_AUDIO: 'audio',
    FILE_TYPE_VIDEO: 'video',
}


def pack_header(
    file_type: int,
    has_residual: bool,
    model_version: int,
    original_size: int,
    sha256_bytes: bytes,
    original_name: str,
) -> bytes:
    """Pack a 72-byte .macs file header."""
    name_bytes = original_name.encode('utf-8')[:23].ljust(24, b'\x00')
    return struct.pack(
        '<4sBBBBQ32s24s',
        MACS_MAGIC,
        0x02,                           # format version
        file_type,
        0x01 if has_residual else 0x00,
        model_version,
        original_size,
        sha256_bytes,
        name_bytes,
    )


def unpack_header(data: bytes) -> dict:
    """Unpack a 72-byte .macs file header.  Raises ValueError on bad magic."""
    if len(data) < HEADER_SIZE:
        raise ValueError("Data too short to contain a valid .macs header")
    if data[:4] != MACS_MAGIC:
        raise ValueError(f"Invalid .macs file: bad magic bytes {data[:4]!r}")
    (
        _magic,
        version,
        file_type,
        has_residual,
        model_version,
        original_size,
        sha256_bytes,
        name_bytes,
    ) = struct.unpack('<4sBBBBQ32s24s', data[:HEADER_SIZE])
    return {
        'version':       version,
        'file_type':     file_type,
        'file_type_name': FILE_TYPE_NAMES.get(file_type, 'unknown'),
        'has_residual':  bool(has_residual),
        'model_version': model_version,
        'original_size': original_size,
        'sha256':        sha256_bytes.hex(),
        'sha256_bytes':  sha256_bytes,
        'original_name': name_bytes.rstrip(b'\x00').decode('utf-8', errors='replace'),
    }


def pack_residual_header(
    parent_sha256_bytes: bytes,
    data_length: int,
    dim1: int,
    dim2: int,
    dim3: int,
) -> bytes:
    """Pack a 32-byte .macs.residual header."""
    parent_hash_trunc = parent_sha256_bytes[:4]
    return struct.pack(
        '<4s4sQIIII',
        MACR_MAGIC,
        parent_hash_trunc,
        data_length,
        dim1,
        dim2,
        dim3,
        0,  # reserved
    )


def unpack_residual_header(data: bytes) -> dict:
    """Unpack a 32-byte .macs.residual header.  Raises ValueError on bad magic."""
    if len(data) < RESIDUAL_HEADER_SIZE:
        raise ValueError("Data too short to contain a valid .macs.residual header")
    if data[:4] != MACR_MAGIC:
        raise ValueError(f"Invalid .macs.residual file: bad magic bytes {data[:4]!r}")
    (
        _magic,
        parent_hash,
        data_length,
        dim1,
        dim2,
        dim3,
        _reserved,
    ) = struct.unpack('<4s4sQIIII', data[:RESIDUAL_HEADER_SIZE])
    return {
        'parent_hash': parent_hash.hex(),
        'data_length': data_length,
        'dim1':        dim1,
        'dim2':        dim2,
        'dim3':        dim3,
    }
