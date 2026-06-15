/* ── Neubrutalist Telegram Mixer.js — progressive streaming + synced playback ── */

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
  // We stream the stems through two <audio> elements (progressive download +
  // native range requests) and route them through Web Audio gain nodes for
  // per-stem volume/mute. This lets playback begin after a small buffer
  // instead of waiting for the full files to download and decode.
  let audioCtx = null;
  let vocalsEl = null;
  let instEl = null;
  let vocalsGain = null;
  let instGain = null;
  let graphBuilt = false;
  let isPlaying = false;
  let duration = 0;
  let animFrameId = null;
  let driftTimer = null;

  // instEl is the master clock; vocalsEl is nudged to follow it.
  const DRIFT_THRESHOLD = 0.08; // seconds

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
    timeDisplay.textContent = `${formatTime(getCurrentTime())} / ${formatTime(duration)}`;
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
        // Duration from metadata lets the seek bar work before buffering.
        if (data.job && data.job.duration) {
          setDuration(Number(data.job.duration));
        }
      }
    } catch (e) {
      // Non-critical: defaults to "Track Name"
    }
  }

  // ── Create streaming <audio> elements ──
  function createAudioElements() {
    vocalsEl = new Audio();
    instEl = new Audio();
    for (const el of [vocalsEl, instEl]) {
      el.preload = 'auto';
      el.playsInline = true;
      el.setAttribute('playsinline', '');
    }
    vocalsEl.src = stemUrl('vocals');
    instEl.src = stemUrl('instrumental');

    // Prefer the real media duration once known.
    instEl.addEventListener('loadedmetadata', function () {
      if (isFinite(instEl.duration) && instEl.duration > 0) {
        setDuration(Math.max(duration, instEl.duration));
      }
    });

    instEl.addEventListener('ended', function () {
      stop();
      seekTo(0);
      updateOnce();
    });

    const onError = function () {
      showError('Failed to load audio stems. The link may have expired.');
    };
    vocalsEl.addEventListener('error', onError);
    instEl.addEventListener('error', onError);

    // Kick off buffering immediately.
    vocalsEl.load();
    instEl.load();
  }

  // ── Build Web Audio graph (must run inside a user gesture on iOS) ──
  function buildGraph() {
    if (graphBuilt) return;
    audioCtx = new (window.AudioContext || window.webkitAudioContext)();

    const vSrc = audioCtx.createMediaElementSource(vocalsEl);
    const iSrc = audioCtx.createMediaElementSource(instEl);
    vocalsGain = audioCtx.createGain();
    instGain = audioCtx.createGain();
    vSrc.connect(vocalsGain).connect(audioCtx.destination);
    iSrc.connect(instGain).connect(audioCtx.destination);

    graphBuilt = true;
    applyVolumes();
  }

  // ── Wait until both elements can play through enough to start ──
  function waitUntilPlayable() {
    const ready = (el) => el.readyState >= 3; // HAVE_FUTURE_DATA
    if (ready(vocalsEl) && ready(instEl)) return Promise.resolve();

    return withTimeout(
      new Promise((resolve) => {
        const check = () => {
          if (ready(vocalsEl) && ready(instEl)) {
            vocalsEl.removeEventListener('canplay', check);
            instEl.removeEventListener('canplay', check);
            resolve();
          }
        };
        vocalsEl.addEventListener('canplay', check);
        instEl.addEventListener('canplay', check);
        check();
      }),
      30000,
      'Timed out buffering audio.'
    );
  }

  // ── Playback ──
  async function play() {
    if (getCurrentTime() >= duration - 0.05) {
      seekTo(0);
    }

    // Align the follower to the master before starting.
    try { vocalsEl.currentTime = instEl.currentTime; } catch (e) {}

    await Promise.all([instEl.play(), vocalsEl.play()]);

    isPlaying = true;
    playBtn.textContent = 'Pause';
    playBtn.classList.add('playing');

    startDriftCorrection();
    updateUI();
  }

  function pause() {
    if (!isPlaying) return;
    instEl.pause();
    vocalsEl.pause();
    isPlaying = false;
    playBtn.textContent = 'Play';
    playBtn.classList.remove('playing');
    stopDriftCorrection();
    if (animFrameId) {
      cancelAnimationFrame(animFrameId);
      animFrameId = null;
    }
  }

  function stop() {
    if (instEl) instEl.pause();
    if (vocalsEl) vocalsEl.pause();
    isPlaying = false;
    playBtn.textContent = 'Play';
    playBtn.classList.remove('playing');
    stopDriftCorrection();
    if (animFrameId) {
      cancelAnimationFrame(animFrameId);
      animFrameId = null;
    }
  }

  function seekTo(t) {
    const clamped = Math.max(0, Math.min(t, duration || t));
    try { instEl.currentTime = clamped; } catch (e) {}
    try { vocalsEl.currentTime = clamped; } catch (e) {}
  }

  function getCurrentTime() {
    return instEl ? instEl.currentTime : 0;
  }

  // ── Drift correction: keep vocals locked to the instrumental clock ──
  function startDriftCorrection() {
    stopDriftCorrection();
    driftTimer = setInterval(function () {
      if (!isPlaying) return;
      const drift = Math.abs(vocalsEl.currentTime - instEl.currentTime);
      if (drift > DRIFT_THRESHOLD) {
        try { vocalsEl.currentTime = instEl.currentTime; } catch (e) {}
      }
    }, 500);
  }

  function stopDriftCorrection() {
    if (driftTimer) {
      clearInterval(driftTimer);
      driftTimer = null;
    }
  }

  function updateOnce() {
    const ct = getCurrentTime();
    seekBar.value = Math.floor(ct * 100);
    seekBar.style.setProperty('--seek-percent', `${duration ? (ct / duration) * 100 : 0}%`);
    timeDisplay.textContent = `${formatTime(ct)} / ${formatTime(duration)}`;
  }

  function updateUI() {
    if (!isPlaying) return;
    updateOnce();
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

    playBtn.disabled = true;
    const prevLabel = playBtn.textContent;
    playBtn.textContent = 'Loading...';
    try {
      buildGraph();
      if (audioCtx.state === 'suspended') {
        try { await audioCtx.resume(); } catch (e) {}
      }
      await waitUntilPlayable();
      await play();
    } catch (err) {
      console.error('Mixer play error:', err);
      playBtn.textContent = prevLabel;
      showError(err.message || 'Failed to play audio stems.');
      playBtn.disabled = false;
      return;
    }
    playBtn.disabled = false;
  });

  seekBar.addEventListener('input', function () {
    const seekToVal = parseFloat(seekBar.value) / 100;
    seekBar.style.setProperty('--seek-percent', `${duration ? (seekToVal / duration) * 100 : 0}%`);
    timeDisplay.textContent = `${formatTime(seekToVal)} / ${formatTime(duration)}`;
    if (graphBuilt) {
      seekTo(seekToVal);
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
    try {
      await fetchJobInfo();
      createAudioElements();
      // Show the player right away; stems stream in the background.
      showContent();
    } catch (err) {
      console.error('Mixer init error:', err);
      showError(err.message || 'Failed to load audio stems. The link may have expired.');
    }
  }

  init();
})();
