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
let instrumentalAudio = null;
let vocalsAudio = null;
let audioContext = null;
let instrumentalGain = null;
let vocalsGain = null;
let instrumentalMuted = false;
let vocalsMuted = false;
let syncTimer = null;
let pendingSeekTime = null;
let pendingSeekRatio = null;
let isSeeking = false;
let lastManualSeekAt = 0;
let audioGraphUnavailable = false;
let desiredPlaybackTime = 0;
let authPanelOpen = false;
let userPlaying = false;
let isPlayingStarted = false;





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
  if (instrumentalAudio) {
    playBtn.textContent = instrumentalAudio.paused ? t.play : t.pause;
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

const resetPlayer = async () => {
  if (instrumentalAudio) {
    instrumentalAudio.pause();
  }
  if (vocalsAudio) {
    vocalsAudio.pause();
  }
  if (syncTimer) {
    clearInterval(syncTimer);
  }
  instrumentalAudio = null;
  vocalsAudio = null;
  instrumentalGain = null;
  vocalsGain = null;
  audioGraphUnavailable = false;
  pendingSeekTime = null;
  pendingSeekRatio = null;
  desiredPlaybackTime = 0;
  userPlaying = false;
  isPlayingStarted = false;
  playBtn.textContent = t.play;

  seek.value = "0";
  timeLabel.textContent = "0:00 / 0:00";
};

const stopPlayerForDeletedJob = async (jobId) => {
  if (activeJobId !== jobId) {
    return;
  }

  await resetPlayer();
  activeJobId = null;
  playerSection.classList.add("hidden");
};

const ensureAudioGraph = () => {
  if (!instrumentalAudio || !vocalsAudio) {
    return;
  }

  if (instrumentalGain && vocalsGain) {
    return;
  }

  if (audioGraphUnavailable) {
    return;
  }

  if (!audioContext) {
    audioContext = new window.AudioContext();
  }

  try {
    const iSource = audioContext.createMediaElementSource(instrumentalAudio);
    const vSource = audioContext.createMediaElementSource(vocalsAudio);
    instrumentalGain = audioContext.createGain();
    vocalsGain = audioContext.createGain();

    iSource.connect(instrumentalGain).connect(audioContext.destination);
    vSource.connect(vocalsGain).connect(audioContext.destination);
  } catch {
    audioGraphUnavailable = true;
    instrumentalGain = null;
    vocalsGain = null;
  }
};

const refreshVolumes = () => {
  instrumentalMute.textContent = instrumentalMuted ? t.unmute : t.mute;
  vocalsMute.textContent = vocalsMuted ? t.unmute : t.mute;

  if (!instrumentalGain || !vocalsGain) {
    if (instrumentalAudio) {
      instrumentalAudio.volume = instrumentalMuted ? 0 : Number(instrumentalVolume.value) / 100;
    }
    if (vocalsAudio) {
      vocalsAudio.volume = vocalsMuted ? 0 : Number(vocalsVolume.value) / 100;
    }
    return;
  }

  instrumentalGain.gain.value = instrumentalMuted
    ? 0
    : Number(instrumentalVolume.value) / 100;
  vocalsGain.gain.value = vocalsMuted ? 0 : Number(vocalsVolume.value) / 100;

};

const currentDuration = () => {
  const duration = instrumentalAudio?.duration || vocalsAudio?.duration || 0;
  return Number.isFinite(duration) ? duration : 0;
};

const setAudioTime = (audio, time) => {
  audio.currentTime = time;
};

const waitForSeek = (audio, targetTime) =>
  new Promise((resolve) => {
    if (Math.abs((audio.currentTime || 0) - targetTime) < 0.2) {
      resolve();
      return;
    }

    const done = () => {
      cleanup();
      resolve();
    };
    const cleanup = () => {
      clearTimeout(timer);
      audio.removeEventListener("seeked", done);
      audio.removeEventListener("timeupdate", done);
      audio.removeEventListener("canplay", done);
    };
    const timer = setTimeout(done, 650);
    audio.addEventListener("seeked", done, { once: true });
    audio.addEventListener("timeupdate", done, { once: true });
    audio.addEventListener("canplay", done, { once: true });
  });

const applySeekTime = (time) => {
  if (!instrumentalAudio || !vocalsAudio) {
    return false;
  }

  const duration = currentDuration();
  if (duration <= 0) {
    pendingSeekTime = Math.max(0, time);
    return false;
  }

  const nextTime = Math.max(0, Math.min(duration, time));
  desiredPlaybackTime = nextTime;
  setAudioTime(instrumentalAudio, nextTime);
  setAudioTime(vocalsAudio, nextTime);
  lastManualSeekAt = Date.now();
  pendingSeekTime = null;
  pendingSeekRatio = null;
  seek.value = String(Math.round((nextTime / duration) * 1000));
  timeLabel.textContent = `${formatTime(nextTime)} / ${formatTime(duration)}`;
  return true;
};

const seekBoth = async (time) => {
  if (!instrumentalAudio || !vocalsAudio) {
    return;
  }

  const duration = currentDuration();
  if (duration <= 0) {
    return;
  }

  const nextTime = Math.max(0, Math.min(duration, time));
  desiredPlaybackTime = nextTime;
  setAudioTime(instrumentalAudio, nextTime);
  setAudioTime(vocalsAudio, nextTime);
  await Promise.all([
    waitForSeek(instrumentalAudio, nextTime),
    waitForSeek(vocalsAudio, nextTime),
  ]);
  setAudioTime(instrumentalAudio, nextTime);
  setAudioTime(vocalsAudio, nextTime);
};

const applyPendingSeek = () => {
  const duration = currentDuration();
  if (pendingSeekRatio !== null && duration > 0) {
    applySeekTime(pendingSeekRatio * duration);
    return;
  }

  if (pendingSeekTime !== null) {
    applySeekTime(pendingSeekTime);
  }
};

const setupTimeSync = () => {
  if (syncTimer) {
    clearInterval(syncTimer);
  }

  syncTimer = setInterval(() => {
    if (!instrumentalAudio || !vocalsAudio) {
      return;
    }

    const t = instrumentalAudio.currentTime || 0;
    const duration = currentDuration();
    const settlingAfterSeek = isSeeking || Date.now() - lastManualSeekAt < 1000;
    if (!settlingAfterSeek) {
      desiredPlaybackTime = t;
    }
    if (!settlingAfterSeek && duration > 0) {
      seek.value = String(Math.round((t / duration) * 1000));
    }

    timeLabel.textContent = `${formatTime(t)} / ${formatTime(duration)}`;

    if (settlingAfterSeek) {
      return;
    }

    const drift = Math.abs((vocalsAudio.currentTime || 0) - t);
    if (drift > 0.08) {
      vocalsAudio.currentTime = t;
    }
  }, 100);
};

const loadPlayer = async (job) => {
  if (!job.instrumental_url || !job.vocals_url) {
    return;
  }

  await resetPlayer();
  activeJobId = job.id;
  const instrumentalUrl = new URL(job.instrumental_url, window.location.origin).toString();
  const vocalsUrl = new URL(job.vocals_url, window.location.origin).toString();

  instrumentalAudio = new Audio();
  instrumentalAudio.crossOrigin = "use-credentials";
  instrumentalAudio.src = instrumentalUrl;

  vocalsAudio = new Audio();
  vocalsAudio.crossOrigin = "use-credentials";
  vocalsAudio.src = vocalsUrl;

  instrumentalAudio.preload = "auto";
  vocalsAudio.preload = "auto";
  instrumentalAudio.addEventListener("loadedmetadata", applyPendingSeek);
  vocalsAudio.addEventListener("loadedmetadata", applyPendingSeek);

  let isInstrumentalWaiting = false;
  let isVocalsWaiting = false;

  const handleWaiting = (isInstrumental) => {
    if (isInstrumental) isInstrumentalWaiting = true;
    else isVocalsWaiting = true;

    if (userPlaying && isPlayingStarted && (!instrumentalAudio.paused || !vocalsAudio.paused)) {
      isPlayingStarted = false;
      if (isInstrumental) {
        vocalsAudio.pause();
      } else {
        instrumentalAudio.pause();
      }
      playBtn.textContent = "...";
    }
  };

  const handlePlaying = (isInstrumental) => {
    if (isInstrumental) isInstrumentalWaiting = false;
    else isVocalsWaiting = false;

    if (userPlaying && !isInstrumentalWaiting && !isVocalsWaiting) {
      isPlayingStarted = false;
      Promise.all([
        instrumentalAudio.play().catch(() => {}),
        vocalsAudio.play().catch(() => {})
      ]).then(() => {
        if (userPlaying) {
          isPlayingStarted = true;
        }
      });
      playBtn.textContent = t.pause;
    }
  };

  instrumentalAudio.addEventListener("waiting", () => handleWaiting(true));
  vocalsAudio.addEventListener("waiting", () => handleWaiting(false));

  instrumentalAudio.addEventListener("playing", () => handlePlaying(true));
  vocalsAudio.addEventListener("playing", () => handlePlaying(false));

  const handleEnded = () => {
    userPlaying = false;
    isPlayingStarted = false;
    instrumentalAudio.pause();
    vocalsAudio.pause();
    instrumentalAudio.currentTime = 0;
    vocalsAudio.currentTime = 0;
    playBtn.textContent = t.play;
    seek.value = "0";
  };

  instrumentalAudio.addEventListener("ended", handleEnded);
  vocalsAudio.addEventListener("ended", handleEnded);

  const handleAudioError = (e) => {
    console.error("Audio error:", e);
    setStatus(t.error("Failed to load audio stream."));
  };
  instrumentalAudio.addEventListener("error", handleAudioError);
  vocalsAudio.addEventListener("error", handleAudioError);


  playerTitle.textContent = job.filename;
  downloadInstrumental.href = instrumentalUrl;
  downloadVocals.href = vocalsUrl;
  playerSection.classList.remove("hidden");

  renderJobs();
  ensureAudioGraph();
  refreshVolumes();
  setupTimeSync();
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
    await stopPlayerForDeletedJob(job.id);
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
  await resetPlayer();
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
  if (!instrumentalAudio || !vocalsAudio) {
    return;
  }

  ensureAudioGraph();
  if (audioContext?.state === "suspended") {
    await audioContext.resume();
  }

  if (instrumentalAudio.paused) {
    userPlaying = true;
    isPlayingStarted = false;
    applyPendingSeek();
    await seekBoth(desiredPlaybackTime);
    try {
      await Promise.all([instrumentalAudio.play(), vocalsAudio.play()]);
      if (userPlaying) {
        isPlayingStarted = true;
      }
    } catch (e) {
      console.warn("Playback was interrupted or aborted:", e);
    }
    playBtn.textContent = t.pause;
  } else {
    userPlaying = false;
    isPlayingStarted = false;
    instrumentalAudio.pause();
    vocalsAudio.pause();
    playBtn.textContent = t.play;
  }

});

const handleSeek = () => {
  if (!instrumentalAudio || !vocalsAudio) {
    return;
  }

  const duration = currentDuration();
  if (duration <= 0) {
    pendingSeekRatio = Number(seek.value) / 1000;
    pendingSeekTime = null;
    return;
  }

  const requestedTime = duration > 0 ? (Number(seek.value) / 1000) * duration : 0;
  desiredPlaybackTime = requestedTime;
  applySeekTime(requestedTime);
};

seek.addEventListener("pointerdown", () => {
  isSeeking = true;
  isPlayingStarted = false;
});
seek.addEventListener("pointerup", () => {
  isSeeking = false;
  isPlayingStarted = false;
  handleSeek();
});
seek.addEventListener("touchend", () => {
  isSeeking = false;
  isPlayingStarted = false;
  handleSeek();
});
seek.addEventListener("input", handleSeek);
seek.addEventListener("change", handleSeek);

instrumentalVolume.addEventListener("input", refreshVolumes);
vocalsVolume.addEventListener("input", refreshVolumes);

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

