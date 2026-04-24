const authSection = document.getElementById("authSection");
const authForm = document.getElementById("authForm");
const authStatus = document.getElementById("authStatus");
const loginBtn = document.getElementById("loginBtn");
const registerBtn = document.getElementById("registerBtn");
const accountBar = document.getElementById("accountBar");
const usernameLabel = document.getElementById("usernameLabel");
const logoutBtn = document.getElementById("logoutBtn");
const appSection = document.getElementById("appSection");
const audioFile = document.getElementById("audioFile");
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
  if (audioContext) {
    await audioContext.close();
  }

  instrumentalAudio = null;
  vocalsAudio = null;
  audioContext = null;
  instrumentalGain = null;
  vocalsGain = null;
  playBtn.textContent = "Play";
  seek.value = "0";
  timeLabel.textContent = "0:00 / 0:00";
};

const ensureAudioGraph = () => {
  if (audioContext || !instrumentalAudio || !vocalsAudio) {
    return;
  }

  audioContext = new window.AudioContext();
  const iSource = audioContext.createMediaElementSource(instrumentalAudio);
  const vSource = audioContext.createMediaElementSource(vocalsAudio);
  instrumentalGain = audioContext.createGain();
  vocalsGain = audioContext.createGain();

  iSource.connect(instrumentalGain).connect(audioContext.destination);
  vSource.connect(vocalsGain).connect(audioContext.destination);
};

const refreshVolumes = () => {
  if (!instrumentalGain || !vocalsGain) {
    return;
  }

  instrumentalGain.gain.value = instrumentalMuted
    ? 0
    : Number(instrumentalVolume.value) / 100;
  vocalsGain.gain.value = vocalsMuted ? 0 : Number(vocalsVolume.value) / 100;

  instrumentalMute.textContent = instrumentalMuted ? "Unmute" : "Mute";
  vocalsMute.textContent = vocalsMuted ? "Unmute" : "Mute";
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
    const duration = instrumentalAudio.duration || 0;
    if (!seek.matches(":active") && duration > 0) {
      seek.value = String(Math.round((t / duration) * 1000));
    }

    timeLabel.textContent = `${formatTime(t)} / ${formatTime(duration)}`;

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

  playerTitle.textContent = job.filename;
  downloadInstrumental.href = instrumentalUrl;
  downloadVocals.href = vocalsUrl;
  playerSection.classList.remove("hidden");

  renderJobs();
  ensureAudioGraph();
  refreshVolumes();
  setupTimeSync();
};

const renderJobs = () => {
  if (!jobs.length) {
    jobsList.innerHTML = '<p class="empty">No uploads yet.</p>';
    return;
  }

  jobsList.innerHTML = "";
  for (const job of jobs) {
    const item = document.createElement("button");
    item.type = "button";
    item.className = `job-item ${job.id === activeJobId ? "active" : ""}`;
    item.disabled = job.status !== "done";

    const meta = document.createElement("div");
    meta.className = "job-meta";

    const title = document.createElement("strong");
    title.textContent = job.filename;

    const state = document.createElement("span");
    const percent = Math.max(0, Math.min(100, job.progress || 0));
    state.textContent = `${job.error || job.message || job.status} · ${percent}%`;

    meta.append(title, state);

    const progress = document.createElement("div");
    progress.className = "progress";
    const bar = document.createElement("span");
    bar.style.width = `${percent}%`;
    progress.appendChild(bar);

    item.append(meta, progress);
    if (job.status === "done") {
      item.addEventListener("click", () => loadPlayer(job));
    }
    jobsList.appendChild(item);
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
  setAuthStatus(mode === "login" ? "Logging in..." : "Creating account...");

  try {
    const payload = await api(`/api/${mode}`, {
      method: "POST",
      body: formData,
    });
    showApp(payload.user);
    setStatus("Choose a file to start a job.");
    await refreshJobs();
  } catch (error) {
    setAuthStatus(`Error: ${error.message}`);
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
    setStatus("Choose a file first.");
    return;
  }

  const formData = new FormData();
  formData.append("file", file);

  setStatus("Uploading...");
  processBtn.disabled = true;

  try {
    const payload = await api("/api/jobs", {
      method: "POST",
      body: formData,
    });
    jobs = [payload.job, ...jobs.filter((job) => job.id !== payload.job.id)];
    renderJobs();
    setStatus("Job queued.");
    audioFile.value = "";
    await refreshJobs();
  } catch (error) {
    setStatus(`Error: ${error.message}`);
  } finally {
    processBtn.disabled = false;
  }
});

playBtn.addEventListener("click", async () => {
  if (!instrumentalAudio || !vocalsAudio) {
    return;
  }

  ensureAudioGraph();
  if (audioContext.state === "suspended") {
    await audioContext.resume();
  }

  if (instrumentalAudio.paused) {
    vocalsAudio.currentTime = instrumentalAudio.currentTime;
    await Promise.all([instrumentalAudio.play(), vocalsAudio.play()]);
    playBtn.textContent = "Pause";
  } else {
    instrumentalAudio.pause();
    vocalsAudio.pause();
    playBtn.textContent = "Play";
  }
});

seek.addEventListener("input", () => {
  if (!instrumentalAudio || !vocalsAudio || !instrumentalAudio.duration) {
    return;
  }

  const newTime = (Number(seek.value) / 1000) * instrumentalAudio.duration;
  instrumentalAudio.currentTime = newTime;
  vocalsAudio.currentTime = newTime;
});

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

init();
