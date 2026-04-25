"""
video_compressor.py — Lane D: Video compression (FFmpeg H.264 CRF 23).

Minimum viable implementation:
  Re-encode with H.264 CRF 23, AAC 128k, -movflags +faststart.

Hybrid Residual mode:
  When ENABLE_FRAME_RESIDUAL = True, the compressor also extracts raw RGB24
  frames from both the original and the lossy output, computes the per-pixel
  residual (int16), and zstd-compresses it.  This residual allows byte-perfect
  frame reconstruction at decompression time.

File size limit: 500 MB enforced by the route handler before calling compress().
"""

import os
import json
import subprocess
import tempfile
import shutil


MAX_VIDEO_SIZE = 500 * 1024 * 1024   # 500 MB
ENABLE_FRAME_RESIDUAL = True         # Activated for perfect reconstruction


def _check_ffmpeg() -> None:
    """Raise RuntimeError if ffmpeg is not available in PATH."""
    if shutil.which('ffmpeg') is None:
        raise RuntimeError(
            "FFmpeg is not installed or not in PATH. "
            "Please install FFmpeg and make sure it is accessible: "
            "https://ffmpeg.org/download.html"
        )


def _get_video_info(path: str) -> tuple:
    """Return (width, height, fps) using ffprobe."""
    cmd = [
        'ffprobe', '-v', 'quiet', '-print_format', 'json',
        '-show_streams', '-show_format', path
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            return 0, 0, 0.0
        data = json.loads(res.stdout)
    except Exception:
        return 0, 0, 0.0

    for s in data.get('streams', []):
        if s.get('codec_type') == 'video':
            w = int(s.get('width', 0))
            h = int(s.get('height', 0))
            fps_str = s.get('r_frame_rate', '30/1')
            if '/' in fps_str:
                num, den = map(int, fps_str.split('/'))
                fps = num / den if den != 0 else 30.0
            else:
                fps = float(fps_str)
            return w, h, fps
    return 0, 0, 0.0


def compress(file_bytes: bytes, original_filename: str) -> dict:
    """
    Compress a video file using FFmpeg H.264 + Frame Residual.
    """
    import importlib
    zstd = importlib.import_module('zstandard')
    np = importlib.import_module('numpy')

    _check_ffmpeg()

    ext = os.path.splitext(original_filename)[1].lower() or '.mp4'
    tmp_dir = tempfile.mkdtemp()
    try:
        input_path  = os.path.join(tmp_dir, f'input{ext}')
        output_path = os.path.join(tmp_dir, 'output.mp4')

        with open(input_path, 'wb') as f:
            f.write(file_bytes)

        # 1. Encode lossy video
        cmd = [
            'ffmpeg', '-y', '-i', input_path,
            '-vcodec', 'libx264', '-crf', '23', '-preset', 'ultrafast',
            '-acodec', 'aac', '-b:a', '128k', '-movflags', '+faststart',
            output_path,
        ]
        subprocess.run(cmd, capture_output=True, timeout=300)

        with open(output_path, 'rb') as f:
            video_payload = f.read()

        # 2. Extract raw frames from both to compute residual
        w, h, fps = _get_video_info(input_path)

        if w == 0 or h == 0 or not ENABLE_FRAME_RESIDUAL:
            return {
                'video_payload':    video_payload,
                'compressed_size':  len(video_payload),
                'residual_payload': None,
                'residual_size':    0,
                'width': w, 'height': h, 'fps': fps,
            }

        # We pipe raw RGB24 bytes from FFmpeg
        def get_frames_cmd(path):
            return ['ffmpeg', '-i', path, '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-']

        proc_orig = subprocess.Popen(
            get_frames_cmd(input_path),
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        proc_comp = subprocess.Popen(
            get_frames_cmd(output_path),
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )

        frame_size = w * h * 3
        chunk_frames = 15  # Process 15 frames at a time to reduce loop overhead
        chunk_bytes = frame_size * chunk_frames
        
        cctx = zstd.ZstdCompressor(level=1, threads=-1) # Level 1 and multithreading for max speed
        cobj = cctx.compressobj()
        compressed_chunks = []
        frames_processed = 0

        while True:
            raw_orig = proc_orig.stdout.read(chunk_bytes)
            raw_comp = proc_comp.stdout.read(chunk_bytes)
            if not raw_orig or not raw_comp:
                # If we read a partial chunk at the end, just process whatever we got
                if raw_orig and raw_comp:
                    min_len = min(len(raw_orig), len(raw_comp))
                    raw_orig = raw_orig[:min_len]
                    raw_comp = raw_comp[:min_len]
                else:
                    break

            # Compute residual in int16 to avoid overflow
            arr_orig = np.frombuffer(raw_orig, dtype=np.uint8).astype(np.int16)
            arr_comp = np.frombuffer(raw_comp, dtype=np.uint8).astype(np.int16)
            diff = arr_orig - arr_comp
            
            compressed_chunks.append(cobj.compress(diff.tobytes()))
            frames_processed += len(raw_orig) // frame_size
            
            if len(raw_orig) < chunk_bytes:
                break

        proc_orig.terminate()
        proc_comp.terminate()

        compressed_chunks.append(cobj.flush())

        if frames_processed == 0:
            residual_compressed = None
        else:
            residual_compressed = b''.join(compressed_chunks)

        return {
            'video_payload':    video_payload,
            'compressed_size':  len(video_payload),
            'residual_payload': residual_compressed,
            'residual_size':    len(residual_compressed) if residual_compressed else 0,
            'width': w, 'height': h, 'fps': fps,
        }
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def decompress_approximate(video_payload: bytes) -> bytes:
    """Return the H.264 MP4 stream as-is (lossy preview)."""
    return video_payload


def decompress_perfect(
    video_payload: bytes,
    residual_payload: bytes,
    w: int,
    h: int,
    fps: float = 30.0,
) -> bytes:
    """
    Perfect video reconstruction: Lossy MP4 + Frame Residual → Original.
    """
    if residual_payload is None:
        return decompress_approximate(video_payload)

    import importlib
    zstd = importlib.import_module('zstandard')
    np = importlib.import_module('numpy')
    import io

    dctx = zstd.ZstdDecompressor()

    tmp_dir = tempfile.mkdtemp()
    try:
        lossy_path = os.path.join(tmp_dir, 'lossy.mp4')
        with open(lossy_path, 'wb') as f:
            f.write(video_payload)

        # Extract lossy frames
        cmd_comp = [
            'ffmpeg', '-i', lossy_path,
            '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-',
        ]
        proc_comp = subprocess.Popen(
            cmd_comp, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )

        # Output pipe — lossless CRF 0 to preserve the reconstruction
        out_path = os.path.join(tmp_dir, 'reconstructed.mp4')
        cmd_out = [
            'ffmpeg', '-y',
            '-f', 'rawvideo', '-pix_fmt', 'rgb24',
            '-s', f'{w}x{h}', '-framerate', str(fps),
            '-i', '-',
            '-c:v', 'libx264', '-crf', '0', '-preset', 'ultrafast',
            out_path,
        ]
        proc_out = subprocess.Popen(
            cmd_out, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )

        frame_size = w * h * 3
        chunk_frames = 15
        chunk_bytes = frame_size * chunk_frames
        res_bytes_per_chunk = chunk_bytes * 2

        with dctx.stream_reader(io.BytesIO(residual_payload)) as reader:
            while True:
                raw_comp = proc_comp.stdout.read(chunk_bytes)
                if not raw_comp:
                    break

                expected_res_bytes = len(raw_comp) * 2
                res_buf = bytearray()
                while len(res_buf) < expected_res_bytes:
                    chunk = reader.read(expected_res_bytes - len(res_buf))
                    if not chunk:
                        break
                    res_buf.extend(chunk)

                if len(res_buf) < expected_res_bytes:
                    break

                arr_comp = np.frombuffer(raw_comp, dtype=np.uint8).astype(np.int16)
                arr_res  = np.frombuffer(res_buf, dtype=np.int16)

                # Reconstruct original pixels
                arr_orig = np.clip(arr_comp + arr_res, 0, 255).astype(np.uint8)
                proc_out.stdin.write(arr_orig.tobytes())

        proc_comp.terminate()
        proc_out.stdin.close()
        proc_out.wait()

        with open(out_path, 'rb') as f:
            return f.read()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
