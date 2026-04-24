const authSection = document.getElementById("authSection");
const authForm = document.getElementById("authForm");
const authStatus = document.getElementById("authStatus");
const loginBtn = document.getElementById("loginBtn");
const registerBtn = document.getElementById("registerBtn");
const accountBar = document.getElementById("accountBar");
const usernameLabel = document.getElementById("usernameLabel");
const logoutBtn = document.getElementById("logoutBtn");
const languageButtons = document.querySelectorAll("[data-lang]");
const appSection = document.getElementById("appSection");
const audioFile = document.getElementById("audioFile");
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

const translations = {
  en: {
    heroTitle: "Extract vocal or instrumental",
    logout: "Logout",
    username: "Username",
    password: "Password",
    login: "Login",
    createAccount: "Sign up",
    authPrompt: "Log in to see your tracks.",
    newSplit: "New",
    dropFile: "Upload audio or video",
    process: "Process",
    fastModeTitle: "Fast",
    fastModeHelp: "Quick result. Turn off for higher quality.",
    chooseFile: "Choose a file.",
    library: "Library",
    pastUploads: "Tracks",
    refresh: "Refresh",
    mixer: "Mixer",
    player: "Player",
    play: "Play",
    pause: "Pause",
    instrumental: "Instrumental",
    vocals: "Vocals",
    mute: "Mute",
    unmute: "Unmute",
    downloadInstrumental: "Download music",
    downloadVocals: "Download vocal",
    noUploads: "No uploads yet.",
    loaded: "Loaded",
    delete: "Delete",
    confirmDelete: (filename) => `Delete "${filename}" from your account?`,
    songDeleted: "Song deleted.",
    chooseFileFirst: "Choose a file first.",
    uploading: "Uploading...",
    jobQueued: "Queued.",
    loginProgress: "Logging in...",
    createAccountProgress: "Signing up...",
    readyToStart: "Choose a file.",
    queued: (position) =>
      `${position ? `Queue: ${position}. ` : ""}Waiting. You can close this page.`,
    processing: "Processing. You can close this page.",
    ready: (mode) => `Ready · ${mode === "fast" ? "Fast" : "High quality"} mode`,
    failed: "Processing failed.",
    error: (message) => `Error: ${message}`,
  },
  uk: {
    heroTitle: "Витягти вокал або інструментал",
    logout: "Вийти",
    username: "Логін",
    password: "Пароль",
    login: "Увійти",
    createAccount: "Реєстрація",
    authPrompt: "Увійдіть, щоб бачити треки.",
    newSplit: "Новий",
    dropFile: "Аудіо або відео",
    process: "Запустити",
    fastModeTitle: "Швидко",
    fastModeHelp: "Для швидкого результату. Вимкніть для якості.",
    chooseFile: "Оберіть файл.",
    library: "Архів",
    pastUploads: "Треки",
    refresh: "Оновити",
    mixer: "Мікшер",
    player: "Плеєр",
    play: "Грати",
    pause: "Пауза",
    instrumental: "Мінус",
    vocals: "Вокал",
    mute: "Без звуку",
    unmute: "Звук",
    downloadInstrumental: "Завантажити мінус",
    downloadVocals: "Завантажити вокал",
    noUploads: "Треків ще немає.",
    loaded: "Вибрано",
    delete: "Видалити",
    confirmDelete: (filename) => `Видалити "${filename}"?`,
    songDeleted: "Трек видалено.",
    chooseFileFirst: "Спочатку оберіть файл.",
    uploading: "Завантаження...",
    jobQueued: "У черзі.",
    loginProgress: "Входимо...",
    createAccountProgress: "Реєструємо...",
    readyToStart: "Оберіть файл.",
    queued: (position) =>
      `${position ? `Черга: ${position}. ` : ""}Очікує. Сторінку можна закрити.`,
    processing: "Обробляємо. Сторінку можна закрити.",
    ready: (mode) => `Готово · ${mode === "fast" ? "Швидко" : "Якісно"}`,
    failed: "Не вдалося.",
    error: (message) => `Помилка: ${message}`,
  },
};

const detectLanguage = () => {
  const savedLanguage = localStorage.getItem("stemdeck-language");
  if (savedLanguage && translations[savedLanguage]) {
    return savedLanguage;
  }
  return (navigator.language || "").toLowerCase().startsWith("uk") ? "uk" : "en";
};

let language = detectLanguage();
let t = translations[language];

let jobs = [];
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
  refreshVolumes();
  renderJobs();
  if (instrumentalAudio) {
    playBtn.textContent = instrumentalAudio.paused ? t.play : t.pause;
  }
  if (!activeJobId && playerSection.classList.contains("hidden")) {
    playerTitle.textContent = t.player;
  }
};

const setLanguage = (nextLanguage) => {
  if (!translations[nextLanguage]) {
    return;
  }

  language = nextLanguage;
  t = translations[language];
  localStorage.setItem("stemdeck-language", language);
  refreshLocalizedUi();
};

const showApp = (user) => {
  authSection.classList.add("hidden");
  appSection.classList.remove("hidden");
  accountBar.classList.remove("hidden");
  usernameLabel.textContent = user.username;
};

const showAuth = () => {
  authSection.classList.remove("hidden");
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

  instrumentalAudio = new Audio(instrumentalUrl);
  vocalsAudio = new Audio(vocalsUrl);
  instrumentalAudio.preload = "auto";
  vocalsAudio.preload = "auto";
  instrumentalAudio.addEventListener("loadedmetadata", applyPendingSeek);
  vocalsAudio.addEventListener("loadedmetadata", applyPendingSeek);

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

const init = async () => {
  try {
    const payload = await api("/api/me");
    showApp(payload.user);
    await refreshJobs();
  } catch {
    showAuth();
  }
};

authForm.addEventListener("submit", (event) => {
  event.preventDefault();
  submitAuth("login");
});

registerBtn.addEventListener("click", () => submitAuth("register"));

logoutBtn.addEventListener("click", async () => {
  await api("/api/logout", { method: "POST" });
  jobs = [];
  await resetPlayer();
  showAuth();
});

refreshBtn.addEventListener("click", refreshJobs);

processBtn.addEventListener("click", async () => {
  const file = audioFile.files?.[0];
  if (!file) {
    setStatus(t.chooseFileFirst);
    return;
  }

  const formData = new FormData();
  formData.append("file", file);
  formData.append("fast_mode", fastMode.checked ? "true" : "false");

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
    await refreshJobs();
  } catch (error) {
    setStatus(t.error(error.message));
  } finally {
    processBtn.disabled = false;
  }
});

playBtn.addEventListener("click", async () => {
  if (!instrumentalAudio || !vocalsAudio) {
    return;
  }

  ensureAudioGraph();
  if (audioContext?.state === "suspended") {
    await audioContext.resume();
  }

  if (instrumentalAudio.paused) {
    applyPendingSeek();
    await seekBoth(desiredPlaybackTime);
    await Promise.all([instrumentalAudio.play(), vocalsAudio.play()]);
    playBtn.textContent = t.pause;
  } else {
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
});
seek.addEventListener("pointerup", () => {
  isSeeking = false;
  handleSeek();
});
seek.addEventListener("touchend", () => {
  isSeeking = false;
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

applyTranslations();
init();
