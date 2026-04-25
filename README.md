# MACS Compressor 🗜️

![Submitted — MACS JC Project 2](https://img.shields.io/badge/MACS%20JC-Project%202-blueviolet?style=for-the-badge)
![Version](https://img.shields.io/badge/version-1.0-blue?style=for-the-badge)
![Spec](https://img.shields.io/badge/spec-v2.0-00d4ff?style=for-the-badge)

## Overview

MACS Compressor is a Chrome Extension backed by a Flask server that compresses any file — text, image, audio, or video — into a custom `.macs` format, from which the **original file can be perfectly reconstructed byte-for-byte**. It achieves maximum compression through **Residual Coding**: a lossy stage produces the smallest possible output, and the exact difference (residual) between the original and the lossy reconstruction is stored separately. During decompression, `Lossy Output + Residual = Perfect Original`, verified by SHA-256 hash comparison.

## Team Members

| Member | Role |
|--------|------|
| Member 1 | Flask app, file detection, CORS, routing |
| Member 2 | LSTM + arithmetic coding (Lane A, text/code) |
| Member 3 | Image compression, residual pipeline, header format |
| Member 4 | Audio/video compression, FFmpeg integration |
| Member 5 | Chrome Extension UI (all 5 states, drag-drop, XHR) |
| Member 6 | Metrics, SHA-256 verification, README, testing |

## Features

- 🗜️ **All file types**: text (.txt, .py, .js, .json, .csv, .html…), image (.jpg, .png, .webp…), audio (.wav, .mp3, .flac…), video (.mp4, .mov, .avi…)
- 🔬 **Four compression algorithms**: LSTM + Arithmetic Coding, JPEG + zstd residual, MP3 + zstd residual, H.264 CRF 23
- 🔄 **Two reconstruction modes**: Lossy-only preview OR byte-perfect SHA-256 verified rebuild
- 📊 **Quality metrics**: PSNR, SSIM, MSE (images); speech/music/mixed classification + bitrate (audio)
- 🛡️ **SHA-256 verification**: Every reconstruction is independently verified
- 🚫 **Error handling**: 7 structured error codes, all errors shown in-UI
- 🖱️ **Drag-and-drop UI**: All 5 UI states, progress bar, history panel

## Installation

### Backend

```bash
git clone <repo-url>
cd macs-compressor/backend

python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate      # Mac/Linux

pip install -r requirements.txt

# Download LSTM weights (not committed to git)
# Place lstm_text_v1.h5 in backend/models/

python app.py
# Server starts at http://localhost:5000
# Verify: curl http://localhost:5000/health
```

### Chrome Extension

1. Open `chrome://extensions`
2. Enable **Developer mode**
3. Click **Load unpacked**
4. Select the `extension/` folder
5. The MACS icon appears in the Chrome toolbar
6. The popup shows 🟢 **Backend Connected** when Flask is running

## Compression Results

| File Type | Example File | Original Size | Compressed (.macs) | Residual (.macs.residual) | Total Savings | Lossy Ratio | Perfect Ratio |
|---|---|---|---|---|---|---|---|
| **Text/Code** | `sample.txt` | 2.5 KB | 1.7 KB | — | 32% | 1.47x | 1.47x |
| **Image** | `sample.jpg` | 258 KB | 38 KB | 72 KB | 57% | 6.7x | 2.33x |
| **Audio** | `sample.wav` | 861 KB | 120 KB | 280 KB | 53% | 7.1x | 2.15x |
| **Video** | `sample.mp4` | 15 MB | 2.3 MB | — (stretch) | 85% | 6.5x | 6.5x |

*\*Results vary heavily based on file complexity. The exact file bitrates scale adaptively (Lane B/C/D).*

## Algorithm Explanation

### Lane A — Text/Code (Lossless)
LSTM (2-layer, pre-trained on text/code corpora) predicts the probability of each next byte given all previous bytes. Arithmetic coding (constriction library) encodes the byte sequence to exactly `−Σ log₂ p(xₜ | x<ₜ)` bits — the theoretical entropy lower bound.

### Lane B — Images (Lossy + Residual)
1. Load as `uint8` NumPy array `X` (H×W×C)
2. Adaptive JPEG quality (60/75/85 based on Sobel edge strength × colour variance)
3. Decode JPEG → `int16` array `X̂`. **Critical:** cast to `int16` before subtraction to prevent uint8 overflow.
4. Residual `R = X − X̂` (int16), compressed with zstd level 3
5. Store `H, W, C` in residual header for reshape on decompression
6. Reconstruction: `clip(X̂ + R, 0, 255).astype(uint8)` → SHA-256 ✓

### Lane C — Audio (Lossy + Residual)
FFT-based speech/music/mixed classification → adaptive MP3 bitrate (64/128/192 kbps). MP3 encoder delay causes sample count mismatch — trim/pad decoded samples to `frame_count` before computing `R = X − X̂` (int32 zstd). Stored in residual header as `dim1=frame_count, dim2=channels, dim3=sample_width`.

### Lane D — Video (H.264)
FFmpeg H.264 CRF 23 (visually lossless quality), AAC 128k audio, `-movflags +faststart` for browser playback.

## Limitations

- Max file sizes: video 500 MB, all others 700 MB
- Video frame residual is a stretch goal (not in MVP)
- Chrome browser only (MV3)
- Flask backend must be running locally
- LSTM performance degrades on binary or non-text files (zlib fallback used)

## References

- Ballé et al. 2018 — Variational image compression with a scale hyperprior
- Shannon 1948 — A Mathematical Theory of Communication (arithmetic coding)
- [constriction library](https://github.com/bamler-lab/constriction) — arithmetic coding
- [pydub](https://github.com/jiaaro/pydub) — audio processing
- [Pillow](https://python-pillow.org/) — image processing
- [scikit-image](https://scikit-image.org/) — SSIM, Sobel
- [FFmpeg](https://ffmpeg.org/) — video encoding
- [zstandard](https://github.com/indygreg/python-zstandard) — zstd compression
