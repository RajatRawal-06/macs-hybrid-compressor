"""
app.py — MACS Compressor Flask backend.

Routes
------
  GET  /health      → {"status": "ok", "version": "2.0"}
  POST /compress    → compress an uploaded file
  POST /decompress  → decompress a .macs file (+ optional .macs.residual)

All temporary files are created with tempfile.mkdtemp() and cleaned up in
a finally block — never written to the shared backend/temp/ directory.
"""

import os
import sys
import base64
import tempfile
import shutil

# Add FFmpeg to PATH programmatically if on Windows (fallback for winget installs)
if os.name == 'nt':
    ffmpeg_path = os.path.join(os.environ.get('LOCALAPPDATA', ''), 
                               r'Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1-full_build\bin')
    if os.path.exists(ffmpeg_path) and ffmpeg_path not in os.environ.get('PATH', ''):
        os.environ['PATH'] = ffmpeg_path + os.pathsep + os.environ.get('PATH', '')

from flask import Flask, request, jsonify
from flask_cors import CORS

# ── Path setup so compressors/ and utils/ are importable ─────────────────────
sys.path.insert(0, os.path.dirname(__file__))

from compressors.file_detector import (
    detect_file_type,
    supported_extensions_list,
)
from compressors import text_compressor, image_compressor, audio_compressor, video_compressor
from utils.header import (
    pack_header, unpack_header,
    pack_residual_header, unpack_residual_header,
    HEADER_SIZE, RESIDUAL_HEADER_SIZE,
    FILE_TYPE_TEXT, FILE_TYPE_IMAGE, FILE_TYPE_AUDIO, FILE_TYPE_VIDEO,
)
from utils.metrics import (
    sha256_of_bytes,
    compression_ratio, space_savings,
    total_compression_ratio, total_space_savings,
    psnr_label,
)

# ── App setup ─────────────────────────────────────────────────────────────────

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})  # allow chrome-extension:// and localhost
# In production, restrict to: {"origins": "chrome-extension://*"}

MAX_GENERAL_SIZE = 700 * 1024 * 1024  # 700 MB
MAX_VIDEO_SIZE   = 500 * 1024 * 1024  # 500 MB

_FILE_TYPE_CODES = {
    'text':  FILE_TYPE_TEXT,
    'image': FILE_TYPE_IMAGE,
    'audio': FILE_TYPE_AUDIO,
    'video': FILE_TYPE_VIDEO,
}

# ── Global error handler ──────────────────────────────────────────────────────

@app.errorhandler(Exception)
def handle_exception(e):
    return jsonify({
        "status":     "error",
        "error_code": "BACKEND_ERROR",
        "message":    str(e),
    }), 500


# ── Health check ──────────────────────────────────────────────────────────────

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok", "version": "2.0"})


# ── POST /compress ────────────────────────────────────────────────────────────

@app.route('/compress', methods=['POST'])
def compress():
    tmp_dir = tempfile.mkdtemp()
    try:
        # ── Validate upload ───────────────────────────────────────────────────
        if 'file' not in request.files:
            return jsonify({
                "status": "error", "error_code": "BACKEND_ERROR",
                "message": "No file field in request.",
            }), 400

        upload   = request.files['file']
        filename = upload.filename or 'unknown'
        file_bytes = upload.read()
        original_size = len(file_bytes)

        # ── Type detection ────────────────────────────────────────────────────
        try:
            file_type = detect_file_type(filename, file_bytes[:16])
        except ValueError as e:
            return jsonify({
                "status": "error", "error_code": "UNSUPPORTED_FILE_TYPE",
                "message": str(e),
            }), 400

        # ── Size limits ───────────────────────────────────────────────────────
        size_limit = MAX_VIDEO_SIZE if file_type == 'video' else MAX_GENERAL_SIZE
        if original_size > size_limit:
            mb = size_limit // (1024 * 1024)
            return jsonify({
                "status": "error", "error_code": "FILE_TOO_LARGE",
                "message": f"File exceeds {mb} MB limit for {file_type} files.",
            }), 400

        # ── SHA-256 of original ───────────────────────────────────────────────
        sha256_orig_hex = sha256_of_bytes(file_bytes)
        sha256_orig_bytes = bytes.fromhex(sha256_orig_hex)

        # ── Run the correct lane ──────────────────────────────────────────────
        macs_data = None
        residual_data = None
        compressed_bytes = 0
        residual_bytes   = 0
        model_version    = 0x00
        has_residual     = False

        extra_metrics = {}   # lane-specific additions (PSNR, SSIM, audio_class…)

        file_type_code = _FILE_TYPE_CODES[file_type]

        if file_type == 'text':
            payload, model_version = text_compressor.compress(file_bytes)
            macs_data = (
                pack_header(file_type_code, False, model_version,
                            original_size, sha256_orig_bytes, filename)
                + payload
            )
            compressed_bytes = len(macs_data)
            residual_data = None
            has_residual     = False

        elif file_type == 'image':
            result = image_compressor.compress(file_bytes, filename)
            H, W, C = result['shape']

            # SHA-256 is computed over the *canonical PNG pixel bytes* (not the
            # raw upload bytes) so that the decompressor can verify
            # bit-perfectly after re-encoding to PNG.
            sha256_orig_bytes  = bytes.fromhex(result['sha256_canonical'])
            sha256_orig_hex    = result['sha256_canonical']

            # Build .macs file (header appended to END so it remains a valid JPEG)
            macs_data = (
                result['jpeg_payload']
                + pack_header(file_type_code, True, 0x00,
                              original_size, sha256_orig_bytes, filename)
            )

            # Build .macs.residual file
            res_payload = result['residual_payload']
            res_header  = pack_residual_header(
                sha256_orig_bytes,
                len(res_payload),
                H, W, C,
            )
            residual_data = res_header + res_payload
            compressed_bytes = len(macs_data)
            residual_bytes   = len(residual_data)
            has_residual     = True

            extra_metrics = {
                'psnr_db':    result['psnr_db'],
                'ssim_score': result['ssim'],
                'mse':        result['mse'],
                'psnr_label': psnr_label(result['psnr_db']),
                'jpeg_quality': result['quality'],
            }

        elif file_type == 'audio':
            import struct
            try:
                result = audio_compressor.compress(file_bytes, filename)
                res_payload = result['residual_payload']
                res_header  = pack_residual_header(
                    sha256_orig_bytes,
                    len(res_payload),
                    result['frame_count'],
                    result['channels'],
                    result['sample_width'],
                )
                sr_bytes      = struct.pack('<I', result['sample_rate'])
                residual_data = res_header + sr_bytes + res_payload

                macs_data = (
                    result['mp3_payload']
                    + pack_header(file_type_code, True, 0x00,
                                  original_size, sha256_orig_bytes, filename)
                )
                compressed_bytes = len(macs_data)
                residual_bytes   = len(residual_data)
                has_residual     = True
                extra_metrics = {
                    'audio_class': result['audio_class'],
                    'bitrate':     result['bitrate'],
                    'sample_rate': result['sample_rate'],
                }
            except Exception as audio_err:
                # FFmpeg not installed — fall back to zstd lossless copy
                import zstandard as _zstd
                zstd_payload = _zstd.ZstdCompressor(level=3).compress(file_bytes)
                macs_data = (
                    zstd_payload
                    + pack_header(file_type_code, False, 0x00,
                                  original_size, sha256_orig_bytes, filename)
                )
                compressed_bytes = len(macs_data)
                residual_data = None
                residual_bytes   = 0
                has_residual     = False
                extra_metrics = {
                    'audio_class': 'fallback',
                    'bitrate':     'N/A (FFmpeg not found)',
                    'sample_rate': 0,
                    'audio_warn': str(audio_err),
                }

        elif file_type == 'video':
            result = video_compressor.compress(file_bytes, filename)
            res_payload = result.get('residual_payload')
            has_residual = (res_payload is not None)

            macs_data = (
                result['video_payload']
                + pack_header(file_type_code, has_residual, 0x00,
                              original_size, sha256_orig_bytes, filename)
            )
            compressed_bytes = len(macs_data)
            
            if has_residual:
                # Use standard residual header for consistency
                res_header = pack_residual_header(
                    sha256_orig_bytes,
                    len(res_payload),
                    result['width'],
                    result['height'],
                    int(result['fps']),
                )
                residual_data  = res_header + res_payload
                residual_bytes = len(residual_data)
            else:
                residual_data   = None
                residual_bytes = 0

        # ── Build response ────────────────────────────────────────────────────
        lossy_ratio  = compression_ratio(original_size, compressed_bytes)
        lossy_saving = space_savings(original_size, compressed_bytes)
        total_ratio  = total_compression_ratio(original_size, compressed_bytes, residual_bytes)
        total_saving = total_space_savings(original_size, compressed_bytes, residual_bytes)

        metadata = {
            "status":                        "success",
            "original_filename":             filename,
            "original_size_bytes":           original_size,
            "compressed_size_bytes":         compressed_bytes,
            "residual_size_bytes":           residual_bytes,
            "total_size_bytes":              compressed_bytes + residual_bytes,
            "compression_ratio":             lossy_ratio,
            "total_ratio_with_residual":     total_ratio,
            "space_savings_percent":         lossy_saving,
            "total_savings_with_residual_percent": total_saving,
            "file_type":                     file_type,
            "has_residual":                  has_residual,
            "sha256_original":               sha256_orig_hex,
            **extra_metrics,
        }

        import json
        from flask import Response, stream_with_context

        def generate_json_stream():
            yield '{"compressed_file_b64":"'
            
            chunk_sz = 3 * 1024 * 1024
            for i in range(0, len(macs_data), chunk_sz):
                yield base64.b64encode(macs_data[i:i+chunk_sz]).decode('ascii')
                
            yield '","residual_file_b64":'
            if residual_data:
                yield '"'
                for i in range(0, len(residual_data), chunk_sz):
                    yield base64.b64encode(residual_data[i:i+chunk_sz]).decode('ascii')
                yield '"'
            else:
                yield 'null'
                
            for k, v in metadata.items():
                yield f',"{k}":{json.dumps(v)}'
                
            yield '}'

        return Response(stream_with_context(generate_json_stream()), mimetype='application/json')

    except Exception as e:
        return jsonify({
            "status": "error", "error_code": "COMPRESSION_FAILED",
            "message": str(e),
        }), 500
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ── POST /decompress ──────────────────────────────────────────────────────────

@app.route('/decompress', methods=['POST'])
def decompress():
    tmp_dir = tempfile.mkdtemp()
    try:
        import struct

        if 'compressed_file' not in request.files:
            return jsonify({
                "status": "error", "error_code": "BACKEND_ERROR",
                "message": "No compressed_file field in request.",
            }), 400

        macs_bytes = request.files['compressed_file'].read()

        if len(macs_bytes) < HEADER_SIZE:
            return jsonify({
                "status": "error", "error_code": "INVALID_MACS_FILE",
                "message": "File is too small to be a valid .macs file.",
            }), 400

        if macs_bytes[:4] == b'MACS':
            # Text/Legacy mode: header at start
            try:
                header = unpack_header(macs_bytes[:HEADER_SIZE])
            except ValueError as e:
                return jsonify({"status": "error", "error_code": "INVALID_MACS_FILE", "message": str(e)}), 400
            payload = macs_bytes[HEADER_SIZE:]
        elif macs_bytes[-HEADER_SIZE:-HEADER_SIZE+4] == b'MACS':
            # Media mode: header at end
            try:
                header = unpack_header(macs_bytes[-HEADER_SIZE:])
            except ValueError as e:
                return jsonify({"status": "error", "error_code": "INVALID_MACS_FILE", "message": str(e)}), 400
            payload = macs_bytes[:-HEADER_SIZE]
        else:
            return jsonify({
                "status": "error", "error_code": "INVALID_MACS_FILE",
                "message": "File does not contain a valid .macs header."
            }), 400
        file_type_code = header['file_type']
        original_size  = header['original_size']
        stored_sha256  = header['sha256']
        model_version  = header['model_version']
        original_name  = header['original_name']
        sha256_orig_bytes = header['sha256_bytes']

        # Residual file (optional)
        has_residual_upload = 'residual_file' in request.files
        residual_payload_bytes = None
        residual_header = None

        if has_residual_upload:
            residual_raw = request.files['residual_file'].read()
            if len(residual_raw) >= RESIDUAL_HEADER_SIZE:
                try:
                    residual_header = unpack_residual_header(residual_raw[:RESIDUAL_HEADER_SIZE])
                    residual_payload_bytes = residual_raw[RESIDUAL_HEADER_SIZE:]
                except ValueError as e:
                    return jsonify({
                        "status": "error", "error_code": "INVALID_MACS_FILE",
                        "message": f"Residual file error: {e}",
                    }), 400

        # ── Reconstruct ───────────────────────────────────────────────────────
        reconstructed = None
        mode          = 'approximate'

        if file_type_code == FILE_TYPE_TEXT:
            try:
                reconstructed = text_compressor.decompress(payload, original_size, model_version)
                mode = 'perfect'
            except RuntimeError as e:
                err_msg = str(e)
                if 'MODEL_VERSION_MISMATCH' in err_msg:
                    return jsonify({
                        "status": "error", "error_code": "MODEL_VERSION_MISMATCH",
                        "message": err_msg,
                    }), 400
                raise

        elif file_type_code == FILE_TYPE_IMAGE:
            if residual_payload_bytes is not None and residual_header is not None:
                H = residual_header['dim1']
                W = residual_header['dim2']
                C = residual_header['dim3']
                # Detect original format from filename
                ext = original_name.rsplit('.', 1)[-1].upper() if '.' in original_name else 'PNG'
                fmt = ext if ext in ('JPEG', 'JPG', 'PNG', 'WEBP', 'BMP') else 'PNG'
                if fmt == 'JPG':
                    fmt = 'JPEG'
                # Perfect mode: always output PNG so pixel array is bit-exact
                reconstructed = image_compressor.decompress_perfect(
                    payload, residual_payload_bytes, (H, W, C), 'PNG'
                )
                mode = 'perfect'
            else:
                ext = original_name.rsplit('.', 1)[-1].upper() if '.' in original_name else 'PNG'
                fmt = ext if ext in ('JPEG', 'JPG', 'PNG', 'WEBP', 'BMP') else 'PNG'
                if fmt == 'JPG':
                    fmt = 'JPEG'
                reconstructed = image_compressor.decompress_approximate(payload, fmt)
                mode = 'approximate'

        elif file_type_code == FILE_TYPE_AUDIO:
            if residual_payload_bytes is not None and residual_header is not None:
                frame_count  = residual_header['dim1']
                channels     = residual_header['dim2']
                sample_width = residual_header['dim3']
                # First 4 bytes of residual_payload_bytes are sample_rate
                sample_rate = struct.unpack('<I', residual_payload_bytes[:4])[0]
                zstd_payload = residual_payload_bytes[4:]
                reconstructed = audio_compressor.decompress_perfect(
                    payload, zstd_payload, frame_count, sample_rate, channels, sample_width
                )
                mode = 'perfect'
            else:
                if payload.startswith(b'\x28\xb5\x2f\xfd'):
                    import zstandard as _zstd
                    reconstructed = _zstd.ZstdDecompressor().decompress(payload)
                    mode = 'perfect'
                else:
                    reconstructed = audio_compressor.decompress_approximate(payload)
                    mode = 'approximate'

        elif file_type_code == FILE_TYPE_VIDEO:
            if residual_payload_bytes is not None and residual_header is not None:
                w   = residual_header['dim1']
                h   = residual_header['dim2']
                fps = float(residual_header['dim3'])
                reconstructed = video_compressor.decompress_perfect(payload, residual_payload_bytes, w, h, fps)
                mode = 'perfect'
            else:
                reconstructed = video_compressor.decompress_approximate(payload)
                mode = 'approximate'

        else:
            return jsonify({
                "status": "error", "error_code": "INVALID_MACS_FILE",
                "message": f"Unknown file type code 0x{file_type_code:02x} in header.",
            }), 400

        # ── Verify SHA-256 ────────────────────────────────────────────────────
        sha256_match = False
        sha256_reconstructed = sha256_of_bytes(reconstructed)
        if mode == 'perfect':
            sha256_match = (sha256_reconstructed == stored_sha256)

        # ── Build response ────────────────────────────────────────────────────
        reconstructed_b64 = base64.b64encode(reconstructed).decode()

        return jsonify({
            "status":                  "success",
            "reconstruction_mode":     mode,
            "sha256_match":            sha256_match,
            "sha256_original":         stored_sha256,
            "sha256_reconstructed":    sha256_reconstructed,
            "original_filename":       original_name,
            "reconstructed_file_b64":  reconstructed_b64,
        })

    except Exception as e:
        return jsonify({
            "status": "error", "error_code": "COMPRESSION_FAILED",
            "message": str(e),
        }), 500
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_DEBUG', '0') == '1'
    print(f"[MACS] Starting Flask backend on http://localhost:{port}")
    app.run(host='0.0.0.0', port=port, debug=debug)
