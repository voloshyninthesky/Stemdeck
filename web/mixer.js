/* ── Neubrutalist Telegram Mixer.js — Synced Web Audio API playback ── */

(function () {
  'use strict';

  // Signal readiness to the Telegram WebApp host as early as possible.
  try {
    if (window.Telegram && window.Telegram.WebApp) {
      window.Telegram.WebApp.ready();
      window.Telegram.WebApp.expand();
    }
  } catch (e) {
    // Non-critical: running outside Telegram.
  }

  const params = new URLSearchParams(window.location.search);
  const JOB_ID = params.get('job_id');
  const TOKEN = params.get('token');

  if (!JOB_ID) {
    showError('Missing job ID in URL.');
    return;
  }

  // ── DOM Refs ──
  const loadingEl = document.getElementById('mixer-loading');
  const errorEl = document.getElementById('mixer-error');
  const contentEl = document.getElementById('mixer-content');
  const errorMsgEl = document.getElementById('error-message');
  const trackNameEl = document.getElementById('track-name');

  const playBtn = document.getElementById('play-btn');
  const seekBar = document.getElementById('seek-bar');
  const timeDisplay = document.getElementById('time-display');

  const vocalsSlider = document.getElementById('vocals-volume');
  const instSlider = document.getElementById('inst-volume');
  const vocalsValue = document.getElementById('vocals-value');
  const instValue = document.getElementById('inst-value');
  const vocalsMute = document.getElementById('vocals-mute');
  const instMute = document.getElementById('inst-mute');

  // ── State ──
  // Both stems are fully downloaded and decoded into AudioBuffers, then played
  // back through AudioBufferSourceNodes scheduled on the same hardware clock.
  // This guarantees sample-accurate sync (no drift correction required).
  let audioCtx = null;
  let vocalsArrayBuffer = null;
  let instArrayBuffer = null;
  let vocalsBuffer = null;
  let instBuffer = null;
  let vocalsSource = null;
  let instSource = null;
  let vocalsGain = null;
  let instGain = null;
  let downloadPromise = null;
  let decoded = false;
  let decodePromise = null;
  let isPlaying = false;
  let startTime = 0;
  let pauseOffset = 0;
  let duration = 0;
  let animFrameId = null;

  let muteState = { vocals: false, instrumental: false };
  let volumeState = { vocals: 1.0, instrumental: 1.0 };

  // ── Helpers ──
  function stemUrl(stem) {
    let url = `/api/jobs/${JOB_ID}/files/${stem}?format=mp3`;
    if (TOKEN) url += `&token=${encodeURIComponent(TOKEN)}`;
    return url;
  }

  function formatTime(s) {
    if (!isFinite(s)) s = 0;
    const m = Math.floor(s / 60);
    const sec = Math.floor(s % 60);
    return `${m}:${sec.toString().padStart(2, '0')}`;
  }

  function withTimeout(promise, ms, message) {
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error(message)), ms);
      promise.then(
        (val) => { clearTimeout(timer); resolve(val); },
        (err) => { clearTimeout(timer); reject(err); }
      );
    });
  }

  function showError(msg) {
    if (loadingEl) loadingEl.style.display = 'none';
    if (contentEl) contentEl.style.display = 'none';
    if (errorEl) errorEl.style.display = 'flex';
    if (errorMsgEl) errorMsgEl.textContent = msg;
  }

  function showContent() {
    if (loadingEl) loadingEl.style.display = 'none';
    if (errorEl) errorEl.style.display = 'none';
    if (contentEl) contentEl.style.display = 'flex';
  }

  function setDuration(value) {
    if (!isFinite(value) || value <= 0) return;
    duration = value;
    seekBar.max = Math.floor(duration * 100);
    timeDisplay.textContent = `${formatTime(pauseOffset)} / ${formatTime(duration)}`;
  }

  // ── Fetch Job Information ──
  async function fetchJobInfo() {
    try {
      let url = `/api/jobs/${JOB_ID}`;
      if (TOKEN) url += `?token=${encodeURIComponent(TOKEN)}`;
      const resp = await fetch(url, { credentials: 'include' });
      if (resp.ok) {
        const data = await resp.json();
        if (data.job && data.job.filename) {
          trackNameEl.textContent = data.job.filename;
        }
        // Duration from metadata lets the seek bar render before decoding.
        if (data.job && data.job.duration) {
          setDuration(Number(data.job.duration));
        }
      }
    } catch (e) {
      // Non-critical: defaults to "Track Name"
    }
  }

  // ── Decode Web Audio Data Safely ──
  const safeDecodeAudioData = (context, arrayBuffer) => {
    return new Promise((resolve, reject) => {
      try {
        const promise = context.decodeAudioData(arrayBuffer, resolve, reject);
        if (promise && typeof promise.then === 'function') {
          promise.then(resolve).catch(reject);
        }
      } catch (e) {
        try {
          context.decodeAudioData(arrayBuffer, resolve, reject);
        } catch (err) {
          reject(err);
        }
      }
    });
  };

  // ── Download both stems in full (parallel) ──
  function loadAudioBytes() {
    if (downloadPromise) return downloadPromise;
    downloadPromise = (async () => {
      const [vocalsResp, instResp] = await Promise.all([
        withTimeout(fetch(stemUrl('vocals')), 60000, 'Timed out loading vocals.'),
        withTimeout(fetch(stemUrl('instrumental')), 60000, 'Timed out loading instrumental.'),
      ]);

      if (!vocalsResp.ok || !instResp.ok) {
        throw new Error('Failed to load audio stems. The link may have expired.');
      }

      [vocalsArrayBuffer, instArrayBuffer] = await Promise.all([
        vocalsResp.arrayBuffer(),
        instResp.arrayBuffer(),
      ]);
    })();
    return downloadPromise;
  }

  // ── Decode + wire up audio graph (runs inside the first user gesture) ──
  async function ensureReady() {
    if (decoded) return;
    if (decodePromise) return decodePromise;

    decodePromise = (async () => {
      await loadAudioBytes();

      if (!audioCtx) {
        audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      }
      // Must run inside a user gesture on iOS / Telegram WebView.
      if (audioCtx.state === 'suspended') {
        try { await audioCtx.resume(); } catch (e) { /* best effort */ }
      }

      // decodeAudioData detaches the ArrayBuffer, so decode from copies to
      // keep the originals available for a potential retry.
      [vocalsBuffer, instBuffer] = await withTimeout(
        Promise.all([
          safeDecodeAudioData(audioCtx, vocalsArrayBuffer.slice(0)),
          safeDecodeAudioData(audioCtx, instArrayBuffer.slice(0)),
        ]),
        30000,
        'Timed out decoding audio.'
      );

      setDuration(Math.max(vocalsBuffer.duration, instBuffer.duration));

      vocalsGain = audioCtx.createGain();
      instGain = audioCtx.createGain();
      vocalsGain.connect(audioCtx.destination);
      instGain.connect(audioCtx.destination);

      applyVolumes();
      decoded = true;
    })();

    return decodePromise;
  }

  // ── Synced Playback using Web Audio Hardware Scheduling ──
  function play(offset) {
    if (offset === undefined) offset = pauseOffset;
    if (offset >= duration) offset = 0;

    stopSources();

    vocalsSource = audioCtx.createBufferSource();
    instSource = audioCtx.createBufferSource();
    vocalsSource.buffer = vocalsBuffer;
    instSource.buffer = instBuffer;

    vocalsSource.connect(vocalsGain);
    instSource.connect(instGain);

    // Schedule playback exactly 50ms in the future for perfect sync on mobile WebKit/Safari
    const playTime = audioCtx.currentTime + 0.05;
    vocalsSource.start(playTime, offset);
    instSource.start(playTime, offset);

    startTime = playTime - offset;
    isPlaying = true;

    playBtn.textContent = 'Pause';
    playBtn.classList.add('playing');

    vocalsSource.onended = function () {
      if (isPlaying && getCurrentTime() >= duration - 0.1) {
        stop();
        pauseOffset = 0;
        updateUI();
      }
    };

    updateUI();
  }

  function pause() {
    if (!isPlaying) return;
    pauseOffset = getCurrentTime();
    stopSources();
    isPlaying = false;
    playBtn.textContent = 'Play';
    playBtn.classList.remove('playing');
    if (animFrameId) {
      cancelAnimationFrame(animFrameId);
      animFrameId = null;
    }
  }

  function stop() {
    stopSources();
    isPlaying = false;
    playBtn.textContent = 'Play';
    playBtn.classList.remove('playing');
    if (animFrameId) {
      cancelAnimationFrame(animFrameId);
      animFrameId = null;
    }
  }

  function stopSources() {
    if (vocalsSource) {
      try {
        vocalsSource.onended = null;
        vocalsSource.stop();
      } catch (e) {}
      vocalsSource = null;
    }
    if (instSource) {
      try {
        instSource.onended = null;
        instSource.stop();
      } catch (e) {}
      instSource = null;
    }
  }

  function getCurrentTime() {
    if (!isPlaying) return pauseOffset;
    return audioCtx.currentTime - startTime;
  }

  function updateUI() {
    if (!isPlaying) return;

    const ct = getCurrentTime();
    seekBar.value = Math.floor(ct * 100);
    seekBar.style.setProperty('--seek-percent', `${(ct / duration) * 100}%`);
    timeDisplay.textContent = `${formatTime(ct)} / ${formatTime(duration)}`;

    animFrameId = requestAnimationFrame(updateUI);
  }

  // ── Gain node & Neubrutalist volume-percent sliders update ──
  function applyVolumes() {
    const vVol = muteState.vocals ? 0 : volumeState.vocals;
    const iVol = muteState.instrumental ? 0 : volumeState.instrumental;

    vocalsSlider.style.setProperty('--volume-percent', `${vVol * 100}%`);
    instSlider.style.setProperty('--volume-percent', `${iVol * 100}%`);

    if (vocalsGain) vocalsGain.gain.setValueAtTime(vVol, audioCtx.currentTime);
    if (instGain) instGain.gain.setValueAtTime(iVol, audioCtx.currentTime);
  }

  // ── Event Listeners ──
  playBtn.addEventListener('click', async function () {
    if (isPlaying) {
      pause();
      return;
    }

    // Decode lazily on the first tap so it happens within a user gesture.
    if (!decoded) {
      playBtn.disabled = true;
      playBtn.textContent = 'Loading...';
      try {
        await ensureReady();
      } catch (err) {
        console.error('Mixer decode error:', err);
        playBtn.disabled = false;
        playBtn.textContent = 'Play';
        showError(err.message || 'Failed to load audio stems.');
        return;
      }
      playBtn.disabled = false;
    }

    if (audioCtx && audioCtx.state === 'suspended') {
      try { await audioCtx.resume(); } catch (e) {}
    }
    play();
  });

  seekBar.addEventListener('input', function () {
    const seekTo = parseFloat(seekBar.value) / 100;
    pauseOffset = seekTo;
    seekBar.style.setProperty('--seek-percent', `${(seekTo / duration) * 100}%`);
    timeDisplay.textContent = `${formatTime(seekTo)} / ${formatTime(duration)}`;
    if (isPlaying) {
      play(seekTo);
    }
  });

  vocalsSlider.addEventListener('input', function () {
    const v = parseFloat(vocalsSlider.value) / 100;
    volumeState.vocals = v;
    vocalsValue.textContent = `${Math.round(v * 100)}%`;
    applyVolumes();
  });

  instSlider.addEventListener('input', function () {
    const v = parseFloat(instSlider.value) / 100;
    volumeState.instrumental = v;
    instValue.textContent = `${Math.round(v * 100)}%`;
    applyVolumes();
  });

  vocalsMute.addEventListener('click', function () {
    muteState.vocals = !muteState.vocals;
    vocalsMute.classList.toggle('active', muteState.vocals);
    vocalsMute.textContent = muteState.vocals ? 'Unmute' : 'Mute';
    applyVolumes();
  });

  instMute.addEventListener('click', function () {
    muteState.instrumental = !muteState.instrumental;
    instMute.classList.toggle('active', muteState.instrumental);
    instMute.textContent = muteState.instrumental ? 'Unmute' : 'Mute';
    applyVolumes();
  });

  // ── Init ──
  async function init() {
    // Start downloading both stems immediately, in parallel with the job-info
    // request, so the bytes are already in flight (often done) by the time the
    // user taps Play. Errors here surface on the first Play attempt.
    loadAudioBytes().catch(() => { /* handled on play */ });

    await fetchJobInfo();
    // Show the player right away; the download continues in the background.
    showContent();
  }

  init();
})();
