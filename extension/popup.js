/**
 * popup.js — MACS Compressor Chrome Extension
 *
 * Architecture (per spec §6):
 *   Section 1 — API Layer        : compressFile(), decompressFiles()
 *   Section 2 — UI Layer         : showXxxState() functions
 *   Section 3 — Event Handlers   : onXxx() handlers
 *   Section 4 — Utility Functions: formatBytes(), b64ToBlob(), etc.
 *   Section 5 — Storage (History): saveCompressionRecord(), loadHistory()
 */

'use strict';

const BASE_URL = 'http://localhost:5000';

// ═══════════════════════════════════════════════════════════════════════════
// SECTION 1 — API Layer
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Compress a file by POSTing to /compress.
 * Uses XMLHttpRequest (not fetch) to expose upload progress events.
 *
 * @param {File} file
 * @param {function(number)} onProgress   — called with 0–100
 * @returns {Promise<object>}             — parsed JSON response
 */
function compressFile(file, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const fd  = new FormData();
    fd.append('file', file);

    xhr.open('POST', `${BASE_URL}/compress`);

    xhr.upload.addEventListener('progress', (e) => {
      if (e.lengthComputable) {
        const pct = Math.round((e.loaded / e.total) * 80); // upload = 0–80%
        onProgress(pct);
      }
    });

    xhr.addEventListener('load', () => {
      try {
        const data = JSON.parse(xhr.responseText);
        if (xhr.status >= 200 && xhr.status < 300 && data.status === 'success') {
          onProgress(100);
          resolve(data);
        } else {
          reject(data);
        }
      } catch (e) {
        reject({ status: 'error', error_code: 'BACKEND_ERROR', message: 'Invalid JSON response from server.' });
      }
    });

    xhr.addEventListener('error', () => {
      reject({
        status: 'error',
        error_code: 'CONNECTION_ERROR',
        message: 'Could not connect to the backend. Make sure the Flask server is running at localhost:5000.',
      });
    });

    xhr.addEventListener('timeout', () => {
      reject({ status: 'error', error_code: 'TIMEOUT', message: 'Request timed out. The file may be too large.' });
    });

    xhr.timeout = 600000; // 10 minutes — large videos need time
    xhr.send(fd);
  });
}

/**
 * Decompress files by POSTing to /decompress.
 *
 * @param {File}      compressedFile
 * @param {File|null} residualFile    — optional
 * @returns {Promise<object>}
 */
function decompressFiles(compressedFile, residualFile) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const fd  = new FormData();
    fd.append('compressed_file', compressedFile);
    if (residualFile) { fd.append('residual_file', residualFile); }

    xhr.open('POST', `${BASE_URL}/decompress`);

    xhr.addEventListener('load', () => {
      try {
        const data = JSON.parse(xhr.responseText);
        if (xhr.status >= 200 && xhr.status < 300 && data.status === 'success') {
          resolve(data);
        } else {
          reject(data);
        }
      } catch (e) {
        reject({ status: 'error', error_code: 'BACKEND_ERROR', message: 'Invalid JSON from server.' });
      }
    });

    xhr.addEventListener('error', () => {
      reject({
        status: 'error',
        error_code: 'CONNECTION_ERROR',
        message: 'Could not connect to the backend. Make sure Flask is running.',
      });
    });

    xhr.timeout = 600000; // 10 minutes
    xhr.send(fd);
  });
}

/**
 * Check if the backend is alive (GET /health).
 * Updates the status pill in the header.
 */
async function checkBackendHealth() {
  const dot  = document.getElementById('statusDot');
  const text = document.getElementById('statusText');
  const url  = document.getElementById('statusUrl');

  // If we are actively compressing/decompressing, the Flask Dev Server (GIL)
  // may be blocked. Do not timeout and mark it offline.
  const isBusy =
    (!document.getElementById('stateProcessing').classList.contains('hidden')) ||
    (!document.getElementById('decompStateProcessing').classList.contains('hidden'));

  if (isBusy) {
    dot.className  = 'status-dot online';
    text.textContent = 'Backend Processing...';
    return;
  }

  try {
    const res  = await fetch(`${BASE_URL}/health`, { signal: AbortSignal.timeout(3000) });
    const data = await res.json();
    if (data.status === 'ok') {
      dot.className  = 'status-dot online';
      text.textContent = 'Backend Connected';
      if (url && data.version) url.textContent = `· v${data.version}`;
    } else {
      throw new Error('Not ok');
    }
  } catch {
    dot.className  = 'status-dot offline';
    text.textContent = 'Backend Offline';
    if (url) url.textContent = '';
  }
}


// ═══════════════════════════════════════════════════════════════════════════
// SECTION 2 — UI Layer
// ═══════════════════════════════════════════════════════════════════════════

// All states in the compression panel
const STATE_IDS_COMPRESS = ['stateIdle', 'stateProcessing', 'stateResults', 'stateError'];

function _showCompressState(id) {
  STATE_IDS_COMPRESS.forEach(s => {
    document.getElementById(s).classList.toggle('hidden', s !== id);
  });
}

function showIdleState() {
  _showCompressState('stateIdle');
}

function showProcessingState(filename, fileType, progressPercent) {
  _showCompressState('stateProcessing');

  const icons   = { text: '📄', image: '🖼', audio: '🎵', video: '🎬' };
  const laneStr = { text: 'Text / Code (Lane A)', image: 'Image File (Lane B)', audio: 'Audio File (Lane C)', video: 'Video File (Lane D)' };
  const badgeStr = { text: 'Lossless Mode', image: 'Lossy + Residual Mode', audio: 'Lossy + Residual Mode', video: 'H.264 Mode' };

  document.getElementById('processingFileIcon').textContent = icons[fileType] || '📄';
  document.getElementById('processingFileName').textContent = filename;
  document.getElementById('processingFileSize').textContent = '';
  document.getElementById('processingFileLane').textContent = laneStr[fileType] || 'Unknown';

  const badge = document.getElementById('processingLaneBadge');
  if (fileType === 'text') {
    badge.textContent = 'Lossless Mode';
    badge.className = 'lane-badge lossless';
  } else if (fileType === 'video') {
    badge.textContent = 'H.264 + Residual Mode';
    badge.className = 'lane-badge lossy-res';
  } else {
    badge.textContent = 'Lossy + Residual Mode';
    badge.className = 'lane-badge lossy-res';
  }

  updateProgress(progressPercent);
}

function updateProgress(pct) {
  const bar   = document.getElementById('progressBar');
  const pctEl = document.getElementById('progressPct');
  bar.style.width    = `${pct}%`;
  pctEl.textContent  = `${pct}%`;
}

function showCompressionResults(data) {
  _showCompressState('stateResults');

  const ft = data.file_type || 'text';
  const icons = { text: '📄', image: '🖼', audio: '🎵', video: '🎬' };

  document.getElementById('resultFileIcon').textContent   = icons[ft] || '📄';
  document.getElementById('resultFileName').textContent   = data.original_filename || '—';
  document.getElementById('resultFileSize').textContent   = formatBytes(data.original_size_bytes);
  document.getElementById('resultFileLane').textContent   = { text: 'Text / Code (Lane A)', image: 'Image File (Lane B)', audio: 'Audio File (Lane C)', video: 'Video File (Lane D)' }[ft] || 'File';
  
  let modeName = 'Lossy Mode';
  if (ft === 'text') {
    modeName = 'Lossless Mode';
  } else if (data.has_residual) {
    modeName = 'Lossy + Residual Mode';
  }
  document.getElementById('resultLaneBadge').textContent  = modeName;

  // Metric cards
  document.getElementById('mOriginal').textContent   = formatBytes(data.original_size_bytes);
  document.getElementById('mCompressed').textContent = formatBytes(data.compressed_size_bytes);
  document.getElementById('mRatio').textContent      = `${data.compression_ratio}x (${data.space_savings_percent}%)`;

  if (data.has_residual) {
    document.getElementById('mResidual').textContent   = formatBytes(data.residual_size_bytes);
    document.getElementById('mTotal').textContent      = formatBytes(data.total_size_bytes);
    document.getElementById('mTotalRatio').textContent = `${data.total_ratio_with_residual}x (${data.total_savings_with_residual_percent}%)`;
  } else {
    document.getElementById('mResidual').textContent   = 'N/A';
    document.getElementById('mTotal').textContent      = formatBytes(data.compressed_size_bytes);
    document.getElementById('mTotalRatio').textContent = `${data.compression_ratio}x compression`;
  }

  // Quality grid
  const qualityGrid = document.getElementById('qualityGrid');
  const audioInfo   = document.getElementById('audioInfo');

  if (ft === 'image') {
    qualityGrid.classList.remove('hidden');
    audioInfo.classList.add('hidden');
    document.getElementById('qPsnr').textContent = data.psnr_db != null ? `${data.psnr_db} dB` : '—';
    document.getElementById('qSsim').textContent = data.ssim_score != null ? data.ssim_score.toFixed(4) : '—';
    document.getElementById('qMse').textContent  = data.mse != null ? data.mse.toFixed(2) : '—';
  } else if (ft === 'audio') {
    qualityGrid.classList.add('hidden');
    audioInfo.classList.remove('hidden');
    document.getElementById('audioClass').textContent   = data.audio_class ? data.audio_class.toUpperCase() : '—';
    document.getElementById('audioBitrate').textContent = `Bitrate: ${data.bitrate || '—'}`;
  } else {
    qualityGrid.classList.add('hidden');
    audioInfo.classList.add('hidden');
  }

  // Download buttons — residual is hidden by default (CSS display:none),
  // only revealed when the backend confirms residual data exists.
  const residualBtn = document.getElementById('btnDownloadResidual');
  if (data.has_residual && data.residual_file_b64) {
    residualBtn.style.display = 'flex';
  } else {
    residualBtn.style.display = 'none';
  }
}

function showDecompressionResults(data) {
  // Switch to decompression panel if not already there
  switchTab('decompress');

  ['stateDecompressIdle', 'stateDecompResults', 'stateApproximate'].forEach(id => {
    document.getElementById(id).classList.add('hidden');
  });

  if (data.reconstruction_mode === 'perfect') {
    document.getElementById('stateDecompResults').classList.remove('hidden');
    document.getElementById('decompResultBadge').textContent = '✅ Reconstruction Complete';
    document.getElementById('decompMode').textContent = 'Perfect Rebuild';

    const match   = data.sha256_match;
    const shaEl   = document.getElementById('shaResult');
    shaEl.textContent       = match ? '✅ PERFECT MATCH' : '❌ VERIFICATION FAILED';
    shaEl.style.color       = match ? 'var(--green)' : 'var(--red)';

    const truncate = h => h ? `${h.substring(0, 8)}...${h.slice(-4)}` : '—';
    document.getElementById('shaOriginal').textContent = truncate(data.sha256_original);
    document.getElementById('shaRebuilt').textContent  = truncate(data.sha256_reconstructed);
  } else {
    document.getElementById('stateApproximate').classList.remove('hidden');
  }
}

function showError(errorCode, message) {
  _showCompressState('stateError');
  document.getElementById('errorCode').textContent = errorCode || 'ERROR';
  document.getElementById('errorMsg').textContent  = message   || 'An unexpected error occurred.';

  const hints = {
    'CONNECTION_ERROR':  'Make sure the Flask backend is running: python app.py',
    'UNSUPPORTED_FILE_TYPE': 'Supported: txt, py, js, json, jpg, png, mp3, wav, mp4, and more.',
    'FILE_TOO_LARGE':    'Video: max 500 MB. Other files: max 700 MB.',
    'MODEL_VERSION_MISMATCH': 'The .macs file was compressed with an incompatible model version.',
    'INVALID_MACS_FILE': 'The file does not appear to be a valid .macs file.',
  };
  document.getElementById('errorHint').textContent = hints[errorCode] || '';
}

function showApproximateResult() {
  switchTab('decompress');
  ['stateDecompressIdle', 'stateDecompResults', 'stateApproximate'].forEach(id => {
    document.getElementById(id).classList.add('hidden');
  });
  document.getElementById('stateApproximate').classList.remove('hidden');
}


// ═══════════════════════════════════════════════════════════════════════════
// SECTION 3 — Event Handlers
// ═══════════════════════════════════════════════════════════════════════════

// Currently stored blobs for download
let _compressedBlob     = null;
let _residualBlob       = null;
let _reconstructedBlob  = null;
let _compressedFilename = 'file';
let _reconstructedFilename = 'reconstructed_file';

async function onCompressFileSelected(file) {
  if (!file) return;

  _compressedFilename = file.name;
  const fileType = detectFileTypeFromName(file.name);

  showProcessingState(file.name, fileType, 0);

  // Simulate server processing progress after upload completes
  let processingPct = 80;
  
  // Videos take much longer to process on the backend (FFmpeg), so slow down the progress simulation
  // so the user doesn't think it got stuck at 95% after 2 seconds.
  const isVideo = fileType === 'video';
  const increment = isVideo ? 0.2 : 2;
  const intervalTime = isVideo ? 500 : 300; // For video: +0.2% every 500ms -> takes ~37 seconds to hit 95%
  
  const processingInterval = setInterval(() => {
    processingPct = Math.min(processingPct + increment, 98);
    updateProgress(processingPct);
  }, intervalTime);

  try {
    const data = await compressFile(file, (pct) => {
      if (pct <= 80) updateProgress(pct);
    });

    clearInterval(processingInterval);
    updateProgress(100);

    // Decode base64 → blobs
    const mimeTypes = { text: 'application/octet-stream', image: 'application/octet-stream', audio: 'application/octet-stream', video: 'video/mp4' };
    _compressedBlob = await b64ToBlob(data.compressed_file_b64, 'application/octet-stream');
    _residualBlob   = data.residual_file_b64 ? await b64ToBlob(data.residual_file_b64, 'application/octet-stream') : null;

    showCompressionResults(data);
    saveCompressionRecord({
      filename:     data.original_filename,
      originalSize: data.original_size_bytes,
      compSize:     data.compressed_size_bytes,
      ratio:        data.compression_ratio,
      fileType:     data.file_type,
      ts:           Date.now(),
    });

  } catch (err) {
    clearInterval(processingInterval);
    const errObj = err && err.error_code ? err : { error_code: 'BACKEND_ERROR', message: String(err.message || err) };
    showError(errObj.error_code, errObj.message);
  }
}

async function onDecompressFilesSelected() {
  const macsInput     = document.getElementById('decompMacsInput');
  const residualInput = document.getElementById('decompResidualInput');

  const macsFile     = macsInput.files[0] || null;
  const residualFile = residualInput.files[0] || null;

  if (!macsFile) {
    alert('Please select a .macs file first.');
    return;
  }

  // Show loading state in decompress panel
  document.getElementById('stateDecompressIdle').classList.add('hidden');
  document.getElementById('stateDecompResults').classList.add('hidden');
  document.getElementById('stateApproximate').classList.add('hidden');

  // Simple loading message (reuse panel area)
  const loadDiv = document.createElement('div');
  loadDiv.id = 'decompLoading';
  loadDiv.style.cssText = 'padding:30px;text-align:center;color:var(--text-secondary);font-size:12px;';
  loadDiv.innerHTML = '⏳ Reconstructing file...';
  document.getElementById('panelDecompress').appendChild(loadDiv);

  try {
    const data = await decompressFiles(macsFile, residualFile);
    loadDiv.remove();

    // Store blob for download
    const mime = guessMimeFromFilename(data.original_filename || 'file');
    _reconstructedBlob     = await b64ToBlob(data.reconstructed_file_b64, mime);
    _reconstructedFilename = data.original_filename || 'reconstructed_file';

    showDecompressionResults(data);
  } catch (err) {
    loadDiv.remove();
    document.getElementById('stateDecompressIdle').classList.remove('hidden');
    const errObj = err && err.error_code ? err : { error_code: 'BACKEND_ERROR', message: String(err.message || err) };
    alert(`Error: ${errObj.message}`);
  }
}

function onDownloadCompressedClicked() {
  if (!_compressedBlob) return;
  const match = _compressedFilename.match(/(\.[^.]+)$/);
  const ext = match ? match[1].toLowerCase() : '';
  const base = _compressedFilename.replace(/\.[^.]+$/, '');
  // All compressed files get .macs extension to make them identifiable
  triggerDownload(_compressedBlob, `${base}.macs`);
}

function onDownloadResidualClicked() {
  if (!_residualBlob) return;
  const base = _compressedFilename.replace(/\.[^.]+$/, '');
  triggerDownload(_residualBlob, `${base}.macs.residual`);
}

function onDownloadReconstructedClicked() {
  if (!_reconstructedBlob) return;
  triggerDownload(_reconstructedBlob, _reconstructedFilename || 'reconstructed_file');
}

function onResetClicked() {
  _compressedBlob  = null;
  _residualBlob    = null;
  document.getElementById('compressFileInput').value = '';
  showIdleState();
}

function onRetryWithResidualClicked() {
  _reconstructedBlob = null;
  ['stateDecompressIdle', 'stateDecompResults', 'stateApproximate'].forEach(id => {
    document.getElementById(id).classList.add('hidden');
  });
  document.getElementById('stateDecompressIdle').classList.remove('hidden');
}


// ═══════════════════════════════════════════════════════════════════════════
// SECTION 4 — Utility Functions
// ═══════════════════════════════════════════════════════════════════════════

function formatBytes(bytes) {
  if (bytes == null || isNaN(bytes)) return '—';
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
  if (bytes >= 1024)        return `${(bytes / 1024).toFixed(1)} KB`;
  return `${bytes} B`;
}

function formatRatio(ratio) {
  return ratio != null ? `${ratio.toFixed(1)} : 1` : '—';
}

function formatPercent(value) {
  return value != null ? `${value.toFixed(1)}%` : '—';
}

function triggerDownload(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a   = document.createElement('a');
  a.href     = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}

async function b64ToBlob(b64string, mimeType) {
  const byteChars = atob(b64string);
  const len = byteChars.length;
  const bytes = new Uint8Array(len);
  
  const CHUNK_SIZE = 512 * 1024; // 512 KB chunks
  for (let i = 0; i < len; i += CHUNK_SIZE) {
    const end = Math.min(i + CHUNK_SIZE, len);
    for (let j = i; j < end; j++) {
      bytes[j] = byteChars.charCodeAt(j);
    }
    // Yield to the event loop every chunk to keep the UI responsive
    await new Promise(resolve => setTimeout(resolve, 0));
  }
  return new Blob([bytes], { type: mimeType });
}

function detectFileTypeFromName(filename) {
  const ext = filename.split('.').pop().toLowerCase();
  const map = {
    txt: 'text', csv: 'text', py: 'text', js: 'text', ts: 'text',
    json: 'text', html: 'text', css: 'text', xml: 'text', md: 'text',
    jpg: 'image', jpeg: 'image', png: 'image', webp: 'image', bmp: 'image',
    wav: 'audio', mp3: 'audio', aac: 'audio', flac: 'audio',
    mp4: 'video', mov: 'video', avi: 'video', mkv: 'video',
  };
  return map[ext] || 'text';
}

function guessMimeFromFilename(filename) {
  const ext = filename.split('.').pop().toLowerCase();
  const map = {
    jpg: 'image/jpeg', jpeg: 'image/jpeg', png: 'image/png', webp: 'image/webp', bmp: 'image/bmp',
    wav: 'audio/wav', mp3: 'audio/mpeg', aac: 'audio/aac', flac: 'audio/flac',
    mp4: 'video/mp4', mov: 'video/quicktime', avi: 'video/avi', mkv: 'video/x-matroska',
    txt: 'text/plain', csv: 'text/csv', py: 'text/x-python', js: 'text/javascript',
    json: 'application/json', html: 'text/html', css: 'text/css', md: 'text/markdown',
  };
  return map[ext] || 'application/octet-stream';
}

function switchTab(tabId) {
  // Activate tab button
  document.querySelectorAll('.tab-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.tab === tabId);
  });
  // Show correct panel
  document.querySelectorAll('.tab-panel').forEach(p => {
    p.classList.toggle('hidden', p.id !== `panel${tabId.charAt(0).toUpperCase() + tabId.slice(1)}`);
  });
}


// ═══════════════════════════════════════════════════════════════════════════
// SECTION 5 — Storage (History) — justifies "storage" permission in manifest
// ═══════════════════════════════════════════════════════════════════════════

const HISTORY_KEY = 'macs_compression_history';
const MAX_HISTORY = 50;

function saveCompressionRecord(record) {
  if (typeof chrome === 'undefined' || !chrome.storage) return;
  chrome.storage.local.get([HISTORY_KEY], (result) => {
    const history = result[HISTORY_KEY] || [];
    history.unshift(record);
    if (history.length > MAX_HISTORY) history.pop();
    chrome.storage.local.set({ [HISTORY_KEY]: history });
  });
}

function loadHistory() {
  return new Promise((resolve) => {
    if (typeof chrome === 'undefined' || !chrome.storage) { resolve([]); return; }
    chrome.storage.local.get([HISTORY_KEY], (result) => {
      resolve(result[HISTORY_KEY] || []);
    });
  });
}

function clearHistory() {
  if (typeof chrome === 'undefined' || !chrome.storage) return;
  chrome.storage.local.remove([HISTORY_KEY]);
}

function renderHistory(items) {
  const list = document.getElementById('historyList');
  if (!items || items.length === 0) {
    list.innerHTML = '<div class="history-empty">No compressions yet.</div>';
    return;
  }
  list.innerHTML = items.map(item => {
    const date = new Date(item.ts).toLocaleString();
    return `
      <div class="history-item">
        <div class="history-item-name">${escapeHtml(item.filename)}</div>
        <div class="history-item-meta">
          ${item.fileType || '?'} · ${formatBytes(item.originalSize)} → ${formatBytes(item.compSize)}
          · ${item.ratio}x · ${date}
        </div>
      </div>
    `;
  }).join('');
}

function escapeHtml(str) {
  const d = document.createElement('div');
  d.textContent = str;
  return d.innerHTML;
}

function renderMetrics(items) {
  const emptyEl  = document.getElementById('metricsEmpty');
  const gridEl   = document.querySelector('.metrics-grid');
  const breakEl  = document.getElementById('metricsBreakdown');

  if (!items || items.length === 0) {
    gridEl.classList.add('hidden');
    breakEl.innerHTML = '';
    emptyEl.classList.remove('hidden');
    return;
  }

  gridEl.classList.remove('hidden');
  emptyEl.classList.add('hidden');

  // Aggregate totals
  let totalOriginal   = 0;
  let totalCompressed = 0;
  let ratioSum        = 0;
  const byType = {};

  items.forEach(item => {
    const orig  = item.originalSize || 0;
    const comp  = item.compSize     || 0;
    const ratio = parseFloat(item.ratio) || 1;
    const type  = (item.fileType || 'other').toLowerCase();

    totalOriginal   += orig;
    totalCompressed += comp;
    ratioSum        += ratio;

    if (!byType[type]) byType[type] = { count: 0, saved: 0 };
    byType[type].count++;
    byType[type].saved += (orig - comp);
  });

  const spaceSaved   = totalOriginal - totalCompressed;
  const avgRatio     = (ratioSum / items.length).toFixed(2);
  const savingsPct   = totalOriginal > 0
    ? ((spaceSaved / totalOriginal) * 100).toFixed(1)
    : '0.0';

  document.getElementById('metricFilesCount').textContent    = items.length;
  document.getElementById('metricSpaceSaved').textContent    = formatBytes(spaceSaved);
  document.getElementById('metricOriginalSize').textContent  = formatBytes(totalOriginal);
  document.getElementById('metricCompressedSize').textContent = formatBytes(totalCompressed);
  document.getElementById('metricAvgRatio').textContent      = avgRatio + 'x';
  document.getElementById('metricSavingsPct').textContent    = savingsPct + '%';

  // Per-type breakdown
  const icons = { text: '📄', image: '🖼️', audio: '🎵', video: '🎬', other: '📦' };
  const typeColors = {
    text:  '#6366f1',
    image: '#0ea5e9',
    audio: '#a855f7',
    video: '#eab308',
    other: '#64748b',
  };
  const maxSaved = Math.max(...Object.values(byType).map(v => v.saved), 1);

  const sortedTypes = Object.keys(byType).sort((a, b) => byType[b].saved - byType[a].saved);

  breakEl.innerHTML = `<div class="metrics-breakdown-title">By File Type</div>` +
    sortedTypes.map(type => {
      const { count, saved } = byType[type];
      const pct = Math.round((saved / maxSaved) * 100);
      const color = typeColors[type] || typeColors.other;
      return `
        <div class="breakdown-row">
          <div class="breakdown-type-icon ${type}">${icons[type] || '📦'}</div>
          <div class="breakdown-info">
            <div class="breakdown-bar-row">
              <span class="breakdown-name">${type.charAt(0).toUpperCase() + type.slice(1)}</span>
              <div class="breakdown-bar-bg">
                <div class="breakdown-bar-fill" style="width:${pct}%;background:${color}"></div>
              </div>
              <span class="breakdown-count">${count} file${count !== 1 ? 's' : ''} · ${formatBytes(saved)} saved</span>
            </div>
          </div>
        </div>`;
    }).join('');
}


// ═══════════════════════════════════════════════════════════════════════════
// INITIALISATION
// ═══════════════════════════════════════════════════════════════════════════

document.addEventListener('DOMContentLoaded', () => {

  // ── Health check on open ─────────────────────────────────────────────────
  checkBackendHealth();
  setInterval(checkBackendHealth, 15000); // re-check every 15s

  // ── Tab switching ────────────────────────────────────────────────────────
  document.getElementById('tabCompress').addEventListener('click', () => switchTab('compress'));
  document.getElementById('tabDecompress').addEventListener('click', () => switchTab('decompress'));

  // ── Compress: file input ─────────────────────────────────────────────────
  const compressInput = document.getElementById('compressFileInput');
  compressInput.addEventListener('change', (e) => {
    const file = e.target.files[0];
    if (file) onCompressFileSelected(file);
  });

  // ── Compress: drag & drop ────────────────────────────────────────────────
  const dropZone = document.getElementById('dropZone');

  dropZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropZone.classList.add('drag-over');
  });

  dropZone.addEventListener('dragleave', () => {
    dropZone.classList.remove('drag-over');
  });

  dropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropZone.classList.remove('drag-over');
    const file = e.dataTransfer.files[0];
    if (file) onCompressFileSelected(file);
  });

  // ── Compress: download buttons ───────────────────────────────────────────
  document.getElementById('btnDownloadCompressed').addEventListener('click', onDownloadCompressedClicked);
  document.getElementById('btnDownloadResidual').addEventListener('click', onDownloadResidualClicked);

  // ── Compress: reset ──────────────────────────────────────────────────────
  document.getElementById('btnReset1').addEventListener('click', onResetClicked);
  document.getElementById('btnErrorReset').addEventListener('click', onResetClicked);

  // ── Compress: "Go to Decompression" CTA ─────────────────────────────────
  document.getElementById('btnGoDecompress').addEventListener('click', () => switchTab('decompress'));

  // ── Decompress: file inputs ──────────────────────────────────────────────
  const decompMacsInput     = document.getElementById('decompMacsInput');
  const decompResidualInput = document.getElementById('decompResidualInput');

  decompMacsInput.addEventListener('change', (e) => {
    const f = e.target.files[0];
    document.getElementById('macsChosen').textContent = f ? f.name : 'No file chosen';
  });

  decompResidualInput.addEventListener('change', (e) => {
    const f = e.target.files[0];
    document.getElementById('residualChosen').textContent = f ? f.name : 'No file chosen';
  });

  // Labels with "for" attribute natively trigger clicks on their inputs.

  // ── Decompress: submit ────────────────────────────────────────────────────
  document.getElementById('btnStartDecompress').addEventListener('click', onDecompressFilesSelected);

  // ── Decompress: download reconstructed ──────────────────────────────────
  document.getElementById('btnDownloadReconstructed').addEventListener('click', onDownloadReconstructedClicked);

  // ── Decompress: download approximate ─────────────────────────────────────
  document.getElementById('btnDownloadApproximate').addEventListener('click', () => {
    if (_reconstructedBlob) triggerDownload(_reconstructedBlob, _reconstructedFilename || 'reconstructed_file');
  });

  // ── Decompress: reset ────────────────────────────────────────────────────
  document.getElementById('btnReset2').addEventListener('click', onRetryWithResidualClicked);
  document.getElementById('btnRetryWithResidual').addEventListener('click', onRetryWithResidualClicked);

  // ── Bottom nav ────────────────────────────────────────────────────────────
  const historyPanel = document.getElementById('historyPanel');
  const metricsPanel = document.getElementById('metricsPanel');
  const aboutPanel   = document.getElementById('aboutPanel');

  function _hideAllOverlays() {
    historyPanel.classList.add('hidden');
    metricsPanel.classList.add('hidden');
    aboutPanel.classList.add('hidden');
    document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
  }

  document.getElementById('navHome').addEventListener('click', () => {
    _hideAllOverlays();
    document.getElementById('navHome').classList.add('active');
  });

  document.getElementById('navHistory').addEventListener('click', async () => {
    _hideAllOverlays();
    historyPanel.classList.remove('hidden');
    document.getElementById('navHistory').classList.add('active');
    const items = await loadHistory();
    renderHistory(items);
  });

  document.getElementById('navMetrics').addEventListener('click', async () => {
    _hideAllOverlays();
    metricsPanel.classList.remove('hidden');
    document.getElementById('navMetrics').classList.add('active');
    const items = await loadHistory();
    renderMetrics(items);
  });

  document.getElementById('navAbout').addEventListener('click', () => {
    _hideAllOverlays();
    aboutPanel.classList.remove('hidden');
    document.getElementById('navAbout').classList.add('active');
  });

  document.getElementById('closeHistory').addEventListener('click', () => {
    historyPanel.classList.add('hidden');
    document.getElementById('navHome').classList.add('active');
    document.getElementById('navHistory').classList.remove('active');
  });

  document.getElementById('closeMetrics').addEventListener('click', () => {
    metricsPanel.classList.add('hidden');
    document.getElementById('navHome').classList.add('active');
    document.getElementById('navMetrics').classList.remove('active');
  });

  document.getElementById('closeAbout').addEventListener('click', () => {
    aboutPanel.classList.add('hidden');
    document.getElementById('navHome').classList.add('active');
    document.getElementById('navAbout').classList.remove('active');
  });

  document.getElementById('clearHistory').addEventListener('click', () => {
    clearHistory();
    document.getElementById('historyList').innerHTML = '<div class="history-empty">No compressions yet.</div>';
  });

  // ── Learn how it works ────────────────────────────────────────────────────
  document.getElementById('learnBtn').addEventListener('click', () => {
    aboutPanel.classList.remove('hidden');
  });

});
