const authSection = document.getElementById("authSection");
const authForm = document.getElementById("authForm");
const authStatus = document.getElementById("authStatus");
const loginBtn = document.getElementById("loginBtn");
const registerBtn = document.getElementById("registerBtn");
const accountBar = document.getElementById("accountBar");
const usernameLabel = document.getElementById("usernameLabel");
const authToggleBtn = document.getElementById("authToggleBtn");
const logoutBtn = document.getElementById("logoutBtn");
const languageButtons = document.querySelectorAll("[data-lang]");
const appSection = document.getElementById("appSection");
const audioFile = document.getElementById("audioFile");
const youtubeUrl = document.getElementById("youtubeUrl");
const uploadPanelTitle = document.getElementById("uploadPanelTitle");
const fastMode = document.getElementById("fastMode");
const processBtn = document.getElementById("processBtn");
const refreshBtn = document.getElementById("refreshBtn");
const statusEl = document.getElementById("status");
const jobsList = document.getElementById("jobsList");
const playerSection = document.getElementById("playerSection");
const playerTitle = document.getElementById("playerTitle");
const playBtn = document.getElementById("playBtn");
const seek = document.getElementById("seek");
const timeLabel = document.getElementById("timeLabel");
const instrumentalVolume = document.getElementById("instrumentalVolume");
const vocalsVolume = document.getElementById("vocalsVolume");
const instrumentalMute = document.getElementById("instrumentalMute");
const vocalsMute = document.getElementById("vocalsMute");
const downloadInstrumental = document.getElementById("downloadInstrumental");
const downloadVocals = document.getElementById("downloadVocals");

const fallbackTranslations = {
  en: {
    heroTitle: "Extract vocal or instrumental",
    logout: "Logout",
    username: "Username",
    password: "Password",
    login: "Login",
    createAccount: "Sign up",
    authPrompt: "Optional: sign in to keep tracks longer.",
    guest: "Guest",
    toolsLabel: "Tools",
    featureExtractor: "Extract",
    newSplit: "New",
    dropFile: "Upload audio or video",
    orDivider: "— OR —",
    process: "Process",
    fastModeTitle: "Fast mode",
    fastModeHelp: "Recommended for quick results. Turn off for higher quality.",
    chooseFile: "Choose a file or YouTube link.",
    youtubePlaceholder: "https://www.youtube.com/watch?v=...",
    youtubeError: "Please enter a valid YouTube URL first.",
    library: "Library",
    pastUploads: "Past uploads",
    refresh: "Refresh",
    mixer: "Mixer",
    player: "Player",
    play: "Play",
    pause: "Pause",
    instrumental: "Instrumental",
    vocals: "Vocals",
    mute: "Mute",
    unmute: "Unmute",
    downloadInstrumental: "Download instrumental",
    downloadVocals: "Download vocals",
    noJobs: "No tracks yet.",
    delete: "Delete",
    loginProgress: "Logging in...",
    createAccountProgress: "Creating account...",
    readyToStart: "Choose a file or YouTube link.",
    chooseFileFirst: "Choose a file or enter a YouTube link first.",
    queued: (position) =>
      `${position ? `Queue: ${position}. ` : ""}Waiting. You can close this page.`,
    processing: "Processing. You can close this page.",
    ready: (mode) => `Ready · ${mode === "fast" ? "Fast" : "Quality"}`,
    failed: "Failed.",
    error: (message) => `Error: ${message}`,
  },
};

const i18n = window.StemdeckI18n || {
  translations: fallbackTranslations,
  detectLanguage: () => "en",
};
const { translations: appTranslations, detectLanguage: detectAppLanguage } = i18n;

let language = detectAppLanguage();
let t = appTranslations[language];

let jobs = [];
let currentUser = null;
let activeJobId = null;
let pollTimer = null;
let audioContext = null;
let instrumentalBuffer = null;
let vocalsBuffer = null;
let instrumentalSource = null;
let vocalsSource = null;
let instrumentalGain = null;
let vocalsGain = null;
let instrumentalMuted = false;
let vocalsMuted = false;
let syncTimer = null;
let desiredPlaybackTime = 0;
let playbackStartTime = 0;
let isSeeking = false;
let wasPlayingBeforeSeek = false;
let authPanelOpen = false;
let userPlaying = false;

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

const ensureAudioContextActive = async () => {
  if (!audioContext) return false;
  if (audioContext.state === "suspended") {
    try {
      await audioContext.resume();
    } catch (e) {
      console.error("Failed to resume AudioContext:", e);
      return false;
    }
  }
  return true;
};

const formatTime = (sec) => {
  const total = Math.max(0, Math.floor(sec || 0));
  const m = Math.floor(total / 60);
  const s = String(total % 60).padStart(2, "0");
  return `${m}:${s}`;
};

const api = async (url, options = {}) => {
  const res = await fetch(url, { credentials: "same-origin", ...options });
  if (!res.ok) {
    let detail = "Request failed";
    try {
      const payload = await res.json();
      detail = payload.detail || detail;
    } catch {
      detail = await res.text();
    }
    throw new Error(detail);
  }
  return res.json();
};

const scrubCredentialsFromUrl = () => {
  const currentUrl = new URL(window.location.href);
  if (!currentUrl.searchParams.has("password") && !currentUrl.searchParams.has("username")) {
    return;
  }

  currentUrl.searchParams.delete("password");
  currentUrl.searchParams.delete("username");
  window.history.replaceState({}, document.title, `${currentUrl.pathname}${currentUrl.search}${currentUrl.hash}`);
};

const setStatus = (text) => {
  statusEl.textContent = text;
};

const setAuthStatus = (text) => {
  authStatus.textContent = text;
};

const applyTranslations = () => {
  document.documentElement.lang = language;
  languageButtons.forEach((button) => {
    const active = button.dataset.lang === language;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });
  document.querySelectorAll("[data-i18n]").forEach((el) => {
    const key = el.dataset.i18n;
    const value = t[key];
    if (typeof value === "string") {
      el.textContent = value;
    }
  });
};




const refreshLocalizedUi = () => {
  applyTranslations();
  if (youtubeUrl) {
    youtubeUrl.placeholder = t.youtubePlaceholder;
  }
  if (audioFile && audioFile.files?.[0]) {
    setStatus(`${t.loaded}: ${audioFile.files[0].name}`);
  } else if (youtubeUrl && youtubeUrl.value?.trim() !== "") {
    setStatus(`${t.loaded}: YouTube Link`);
  } else {
    setStatus(t.chooseFile);
  }
  refreshVolumes();
  renderJobs();
  if (currentUser) {
    usernameLabel.textContent = currentUser.username;
  }
  if (instrumentalBuffer && vocalsBuffer) {
    playBtn.textContent = userPlaying ? t.pause : t.play;
  }
  if (!activeJobId && playerSection.classList.contains("hidden")) {
    playerTitle.textContent = t.player;
  }
};

const setLanguage = (nextLanguage) => {
  if (!appTranslations[nextLanguage]) {
    return;
  }

  language = nextLanguage;
  t = appTranslations[language];
  localStorage.setItem("stemdeck-language", language);
  refreshLocalizedUi();
};

const setAuthPanelOpen = (open, focusForm = false) => {
  authPanelOpen = open;
  authSection.classList.toggle("hidden", !open);
  if (open) {
    setAuthStatus(t.authPrompt);
  }
  if (open && focusForm) {
    document.getElementById("username")?.focus();
  }
};

const showApp = (user) => {
  currentUser = user;
  if (user.is_guest) {
    setAuthPanelOpen(false);
    usernameLabel.classList.add("hidden");
    authToggleBtn.classList.remove("hidden");
    logoutBtn.classList.add("hidden");
  } else {
    setAuthPanelOpen(false);
    usernameLabel.classList.remove("hidden");
    authToggleBtn.classList.add("hidden");
    logoutBtn.classList.remove("hidden");
  }
  appSection.classList.remove("hidden");
  accountBar.classList.remove("hidden");
  usernameLabel.textContent = user.username;
};

const showAuth = () => {
  currentUser = null;
  setAuthPanelOpen(true);
  appSection.classList.add("hidden");
  accountBar.classList.add("hidden");
  playerSection.classList.add("hidden");
};

const resetPlayer = () => {
  userPlaying = false;
  stopSources();

  if (syncTimer) {
    clearInterval(syncTimer);
    syncTimer = null;
  }

  instrumentalBuffer = null;
  vocalsBuffer = null;
  instrumentalGain = null;
  vocalsGain = null;
  desiredPlaybackTime = 0;
  playbackStartTime = 0;
  playBtn.textContent = t.play;
  playBtn.disabled = false;

  seek.value = "0";
  timeLabel.textContent = "0:00 / 0:00";
};

const stopPlayerForDeletedJob = (jobId) => {
  if (activeJobId !== jobId) {
    return;
  }

  resetPlayer();
  activeJobId = null;
  playerSection.classList.add("hidden");
};

const ensureAudioGraph = () => {
  // Managed dynamically on buffer source instantiation
};

const refreshVolumes = () => {
  instrumentalMute.textContent = instrumentalMuted ? t.unmute : t.mute;
  vocalsMute.textContent = vocalsMuted ? t.unmute : t.mute;

  if (!audioContext) return;

  if (!instrumentalGain) {
    instrumentalGain = audioContext.createGain();
    instrumentalGain.connect(audioContext.destination);
  }
  if (!vocalsGain) {
    vocalsGain = audioContext.createGain();
    vocalsGain.connect(audioContext.destination);
  }

  const instVol = instrumentalMuted ? 0 : Number(instrumentalVolume.value) / 100;
  const vocVol = vocalsMuted ? 0 : Number(vocalsVolume.value) / 100;

  instrumentalGain.gain.setValueAtTime(instVol, audioContext.currentTime);
  vocalsGain.gain.setValueAtTime(vocVol, audioContext.currentTime);
};

const currentDuration = () => {
  return instrumentalBuffer ? instrumentalBuffer.duration : 0;
};

const startSources = (offset) => {
  if (!instrumentalBuffer || !vocalsBuffer || !audioContext) {
    return;
  }

  stopSources();

  instrumentalSource = audioContext.createBufferSource();
  vocalsSource = audioContext.createBufferSource();

  instrumentalSource.buffer = instrumentalBuffer;
  vocalsSource.buffer = vocalsBuffer;

  if (!instrumentalGain) {
    instrumentalGain = audioContext.createGain();
    instrumentalGain.connect(audioContext.destination);
  }
  if (!vocalsGain) {
    vocalsGain = audioContext.createGain();
    vocalsGain.connect(audioContext.destination);
  }

  instrumentalSource.connect(instrumentalGain);
  vocalsSource.connect(vocalsGain);

  const duration = currentDuration();
  const safeOffset = Math.max(0, Math.min(duration, offset));

  // Schedule playback exactly 50ms in the future to allow perfect hardware synchronization on mobile
  const playTime = audioContext.currentTime + 0.05;
  instrumentalSource.start(playTime, safeOffset);
  vocalsSource.start(playTime, safeOffset);

  playbackStartTime = playTime - safeOffset;
  desiredPlaybackTime = safeOffset;

  // Handle end of playback naturally without fragile threshold calculation
  instrumentalSource.onended = () => {
    if (userPlaying) {
      handleEnded();
    }
  };
};

const stopSources = () => {
  if (instrumentalSource) {
    try {
      instrumentalSource.onended = null;
      instrumentalSource.stop();
    } catch (e) {}
    instrumentalSource = null;
  }
  if (vocalsSource) {
    try {
      vocalsSource.onended = null;
      vocalsSource.stop();
    } catch (e) {}
    vocalsSource = null;
  }
};

const handleEnded = () => {
  userPlaying = false;
  stopSources();
  desiredPlaybackTime = 0;
  playBtn.textContent = t.play;
  seek.value = "0";
  timeLabel.textContent = `0:00 / ${formatTime(currentDuration())}`;
};

const applySeekTime = (time) => {
  if (!instrumentalBuffer || !vocalsBuffer) {
    return false;
  }

  const duration = currentDuration();
  if (duration <= 0) {
    return false;
  }

  const nextTime = Math.max(0, Math.min(duration, time));
  desiredPlaybackTime = nextTime;

  if (userPlaying) {
    startSources(nextTime);
  } else {
    seek.value = String(Math.round((nextTime / duration) * 1000));
    timeLabel.textContent = `${formatTime(nextTime)} / ${formatTime(duration)}`;
  }
  return true;
};

const seekBoth = (time) => {
  applySeekTime(time);
};

const applyPendingSeek = () => {
  // Managed on-demand upon buffer loading completion
};

const setupTimeSync = () => {
  if (syncTimer) {
    clearInterval(syncTimer);
  }

  syncTimer = setInterval(() => {
    if (!instrumentalBuffer || !vocalsBuffer || !audioContext) {
      return;
    }

    const duration = currentDuration();
    if (duration <= 0) return;

    let t = desiredPlaybackTime;
    if (userPlaying) {
      t = audioContext.currentTime - playbackStartTime;
      if (t >= duration) {
        t = duration;
      }
    }

    if (!isSeeking) {
      seek.value = String(Math.round((t / duration) * 1000));
      timeLabel.textContent = `${formatTime(t)} / ${formatTime(duration)}`;
    }
  }, 200);
};

const loadPlayer = async (job) => {
  if (!job.instrumental_url || !job.vocals_url) {
    return;
  }

  resetPlayer();
  activeJobId = job.id;
  renderJobs();

  playerTitle.textContent = job.filename;
  downloadInstrumental.href = new URL(job.instrumental_url, window.location.origin).toString();
  downloadVocals.href = new URL(job.vocals_url, window.location.origin).toString();
  playerSection.classList.remove("hidden");

  setStatus("Loading stems into memory... please wait...");
  playBtn.disabled = true;
  playBtn.textContent = "Loading...";

  try {
    if (!audioContext) {
      audioContext = new (window.AudioContext || window.webkitAudioContext)();
    }

    const instrumentalUrl = new URL(job.instrumental_url, window.location.origin).toString();
    const vocalsUrl = new URL(job.vocals_url, window.location.origin).toString();

    const [iRes, vRes] = await Promise.all([
      fetch(instrumentalUrl, { credentials: "same-origin" }),
      fetch(vocalsUrl, { credentials: "same-origin" })
    ]);

    if (!iRes.ok || !vRes.ok) {
      throw new Error("Failed to fetch audio files from server.");
    }

    const [iArrayBuf, vArrayBuf] = await Promise.all([
      iRes.arrayBuffer(),
      vRes.arrayBuffer()
    ]);

    const [iBuffer, vBuffer] = await Promise.all([
      safeDecodeAudioData(audioContext, iArrayBuf),
      safeDecodeAudioData(audioContext, vArrayBuf)
    ]);

    instrumentalBuffer = iBuffer;
    vocalsBuffer = vBuffer;

    setStatus("Stems loaded!");
    playBtn.disabled = false;
    playBtn.textContent = t.play;

    refreshVolumes();
    setupTimeSync();
  } catch (e) {
    console.error("Failed to load/decode stems:", e);
    setStatus(t.error("Failed to load audio stream."));
    playBtn.textContent = t.play;
    playBtn.disabled = true;
  }
};

const describeJob = (job) => {
  if (job.status === "queued") {
    return t.queued(job.queue_position);
  }

  if (job.status === "processing") {
    return t.processing;
  }

  if (job.status === "done") {
    return t.ready(job.separation_mode);
  }

  if (job.status === "failed") {
    return job.error || t.failed;
  }

  return job.message || job.status;
};

const renderJobs = () => {
  if (!jobs.length) {
    jobsList.innerHTML = "";
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = t.noUploads;
    jobsList.appendChild(empty);
    return;
  }

  jobsList.innerHTML = "";
  for (const job of jobs) {
    const item = document.createElement("article");
    item.className = `job-item ${job.id === activeJobId ? "active" : ""}`;

    const meta = document.createElement("div");
    meta.className = "job-meta";

    const title = document.createElement("strong");
    title.textContent = job.filename;

    const state = document.createElement("span");
    state.textContent = describeJob(job);

    meta.append(title, state);

    const actions = document.createElement("div");
    actions.className = "job-actions";

    const play = document.createElement("button");
    play.type = "button";
    play.className = "secondary";
    play.textContent = job.id === activeJobId ? t.loaded : t.play;
    play.disabled = job.status !== "done";
    play.addEventListener("click", () => loadPlayer(job));

    const del = document.createElement("button");
    del.type = "button";
    del.className = "danger";
    del.textContent = t.delete;
    del.addEventListener("click", () => deleteJob(job));

    actions.append(play, del);
    item.append(meta, actions);
    jobsList.appendChild(item);
  }
};

const deleteJob = async (job) => {
  const ok = window.confirm(t.confirmDelete(job.filename));
  if (!ok) {
    return;
  }

  try {
    await api(`/api/jobs/${job.id}`, { method: "DELETE" });
    jobs = jobs.filter((item) => item.id !== job.id);
    stopPlayerForDeletedJob(job.id);
    renderJobs();
    setStatus(t.songDeleted);
  } catch (error) {
    setStatus(t.error(error.message));
  }
};

const refreshJobs = async () => {
  const payload = await api("/api/jobs");
  jobs = payload.jobs;
  renderJobs();

  const running = jobs.some((job) => job.status === "queued" || job.status === "processing");
  if (running && !pollTimer) {
    pollTimer = setInterval(refreshJobs, 1500);
  }
  if (!running && pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
};

const submitAuth = async (mode) => {
  const formData = new FormData(authForm);
  setAuthStatus(mode === "login" ? t.loginProgress : t.createAccountProgress);

  try {
    const payload = await api(`/api/${mode}`, {
      method: "POST",
      body: formData,
    });
    showApp(payload.user);
    setStatus(t.readyToStart);
    await refreshJobs();
  } catch (error) {
    setAuthStatus(t.error(error.message));
  }
};

const handleAuthSubmit = (event, mode = "login") => {
  event.preventDefault();
  event.stopPropagation();
  submitAuth(mode);
};

const init = async () => {

  try {
    const payload = await api("/api/me");
    showApp(payload.user);
    await refreshJobs();
  } catch {
    showAuth();
  }
};

authForm.addEventListener("submit", handleAuthSubmit, { capture: true });

authToggleBtn.addEventListener("click", () => setAuthPanelOpen(!authPanelOpen, true));

loginBtn.addEventListener("click", (event) => handleAuthSubmit(event, "login"));

registerBtn.addEventListener("click", (event) => handleAuthSubmit(event, "register"));

window.addEventListener("stemdeck:auth", async (event) => {
  const user = event.detail?.user;
  if (!user) {
    return;
  }

  showApp(user);
  setStatus(t.readyToStart);
  await refreshJobs();
});

logoutBtn.addEventListener("click", async () => {
  await api("/api/logout", { method: "POST" });
  jobs = [];
  resetPlayer();
  const payload = await api("/api/guest", { method: "POST" });
  showApp(payload.user);
  await refreshJobs();
});

refreshBtn.addEventListener("click", refreshJobs);

processBtn.addEventListener("click", async () => {
  const formData = new FormData();
  formData.append("fast_mode", fastMode.checked ? "true" : "false");

  const file = audioFile.files?.[0];
  const url = youtubeUrl.value?.trim();

  if (file) {
    formData.append("file", file);
  } else if (url) {
    if (!url.includes("youtube.com") && !url.includes("youtu.be")) {
      setStatus(t.youtubeError);
      return;
    }
    formData.append("youtube_url", url);
  } else {
    setStatus(t.chooseFileFirst);
    return;
  }

  setStatus(t.uploading);
  processBtn.disabled = true;

  try {
    const payload = await api("/api/jobs", {
      method: "POST",
      body: formData,
    });
    jobs = [payload.job, ...jobs.filter((job) => job.id !== payload.job.id)];
    renderJobs();
    setStatus(t.jobQueued);
    audioFile.value = "";
    youtubeUrl.value = "";
    await refreshJobs();
  } catch (error) {
    setStatus(t.error(error.message));
  } finally {
    processBtn.disabled = false;
  }
});

if (audioFile) {
  audioFile.addEventListener("change", () => {
    if (audioFile.files?.[0]) {
      if (youtubeUrl) {
        youtubeUrl.value = "";
      }
      setStatus(`${t.loaded}: ${audioFile.files[0].name}`);
    } else {
      setStatus(t.chooseFile);
    }
  });
}

if (youtubeUrl) {
  youtubeUrl.addEventListener("input", () => {
    const val = youtubeUrl.value.trim();
    if (val) {
      if (audioFile) {
        audioFile.value = "";
      }
      setStatus(`${t.loaded}: YouTube Link`);
    } else {
      setStatus(t.chooseFile);
    }
  });
}

playBtn.addEventListener("click", async () => {
  if (!instrumentalBuffer || !vocalsBuffer) {
    return;
  }

  await ensureAudioContextActive();

  if (!userPlaying) {
    userPlaying = true;
    startSources(desiredPlaybackTime);
    playBtn.textContent = t.pause;
  } else {
    userPlaying = false;
    if (audioContext) {
      desiredPlaybackTime = Math.max(0, audioContext.currentTime - playbackStartTime);
    }
    stopSources();
    playBtn.textContent = t.play;
  }
});

const handleSeek = () => {
  if (!instrumentalBuffer || !vocalsBuffer) {
    return;
  }

  const duration = currentDuration();
  if (duration <= 0) return;

  const requestedTime = (Number(seek.value) / 1000) * duration;
  desiredPlaybackTime = requestedTime;

  if (isSeeking) {
    timeLabel.textContent = `${formatTime(requestedTime)} / ${formatTime(duration)}`;
  } else {
    applySeekTime(requestedTime);
  }
};

const hardSync = (time) => {
  applySeekTime(time);
};

const onSeekStart = () => {
  if (isSeeking) return;
  isSeeking = true;
  if (instrumentalBuffer && vocalsBuffer) {
    wasPlayingBeforeSeek = userPlaying;
    if (userPlaying) {
      stopSources();
    }
  }
};

const onSeekEnd = async () => {
  if (!isSeeking) return;
  isSeeking = false;

  await ensureAudioContextActive();

  const duration = currentDuration();
  const requestedTime = duration > 0 ? (Number(seek.value) / 1000) * duration : 0;
  desiredPlaybackTime = requestedTime;
  timeLabel.textContent = `${formatTime(requestedTime)} / ${formatTime(duration)}`;

  if (wasPlayingBeforeSeek) {
    userPlaying = true;
    startSources(requestedTime);
  } else {
    applySeekTime(requestedTime);
  }
};

seek.addEventListener("mousedown", onSeekStart);
seek.addEventListener("touchstart", onSeekStart, { passive: true });

seek.addEventListener("mouseup", onSeekEnd);
seek.addEventListener("touchend", onSeekEnd, { passive: true });
seek.addEventListener("touchcancel", onSeekEnd, { passive: true });

seek.addEventListener("input", handleSeek);
seek.addEventListener("change", handleSeek);

instrumentalVolume.addEventListener("input", refreshVolumes);
instrumentalVolume.addEventListener("change", refreshVolumes);
vocalsVolume.addEventListener("input", refreshVolumes);
vocalsVolume.addEventListener("change", refreshVolumes);

instrumentalMute.addEventListener("click", () => {
  instrumentalMuted = !instrumentalMuted;
  refreshVolumes();
});

vocalsMute.addEventListener("click", () => {
  vocalsMuted = !vocalsMuted;
  refreshVolumes();
});

languageButtons.forEach((button) => {
  button.addEventListener("click", () => setLanguage(button.dataset.lang));
});



scrubCredentialsFromUrl();
applyTranslations();
init();

;

