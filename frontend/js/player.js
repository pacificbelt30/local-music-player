let playlist = [];
let currentIndex = -1;
let shuffleOn = false;
let repeatMode = "none"; // "none" | "all" | "one"
let shuffledOrder = [];

const audio = new Audio();

const bar = document.getElementById("player-bar");
const thumbEl = bar.querySelector(".player-thumb");
const titleEl = bar.querySelector(".player-title");
const artistEl = bar.querySelector(".player-artist");
const playBtn = bar.querySelector(".play-pause");
const prevBtn = bar.querySelector(".prev");
const nextBtn = bar.querySelector(".next");
const seekEl = bar.querySelector(".seek-range");
const currentTimeEl = bar.querySelector(".current-time");
const durationEl = bar.querySelector(".duration");
const shuffleBtn = bar.querySelector(".shuffle");
const repeatBtn = bar.querySelector(".repeat");
const volumeRange = bar.querySelector(".volume-range");
const closeBtn = bar.querySelector(".close-player");

function fmt(secs) {
  if (!secs || isNaN(secs)) return "0:00";
  const m = Math.floor(secs / 60);
  const s = Math.floor(secs % 60).toString().padStart(2, "0");
  return `${m}:${s}`;
}

function buildShuffleOrder() {
  shuffledOrder = [...Array(playlist.length).keys()];
  for (let i = shuffledOrder.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [shuffledOrder[i], shuffledOrder[j]] = [shuffledOrder[j], shuffledOrder[i]];
  }
  // Put currentIndex first so current track stays
  const pos = shuffledOrder.indexOf(currentIndex);
  if (pos > 0) {
    [shuffledOrder[0], shuffledOrder[pos]] = [shuffledOrder[pos], shuffledOrder[0]];
  }
}

function effectiveIndex(position) {
  if (!shuffleOn) return position;
  return shuffledOrder[position] ?? position;
}

function updateUI() {
  const track = playlist[currentIndex];
  if (!track) return;

  bar.classList.remove("hidden");
  titleEl.textContent = track.title;
  artistEl.textContent = track.artist || "";
  thumbEl.src = track.thumbnail_url || "";
  thumbEl.style.display = track.thumbnail_url ? "block" : "none";

  document.querySelectorAll(".track-item").forEach((el) => {
    el.classList.toggle("active", el.dataset.trackId === String(track.id));
  });

  shuffleBtn.classList.toggle("active", shuffleOn);
  repeatBtn.textContent = repeatMode === "one" ? "🔂" : "🔁";
  repeatBtn.classList.toggle("active", repeatMode !== "none");

  saveState();
}

audio.addEventListener("timeupdate", () => {
  if (!isNaN(audio.duration)) {
    seekEl.value = (audio.currentTime / audio.duration) * 100;
    currentTimeEl.textContent = fmt(audio.currentTime);
    savePositionThrottled();
  }
});

audio.addEventListener("loadedmetadata", () => {
  durationEl.textContent = fmt(audio.duration);
});

audio.addEventListener("play", () => { playBtn.textContent = "⏸"; });
audio.addEventListener("pause", () => { playBtn.textContent = "▶"; });
audio.addEventListener("ended", () => {
  if (repeatMode === "one") {
    audio.currentTime = 0;
    audio.play();
  } else {
    next();
  }
});

seekEl.addEventListener("input", () => {
  if (!isNaN(audio.duration)) {
    audio.currentTime = (seekEl.value / 100) * audio.duration;
  }
});

playBtn.addEventListener("click", () => {
  if (audio.paused) audio.play();
  else audio.pause();
});

prevBtn.addEventListener("click", prev);
nextBtn.addEventListener("click", next);

shuffleBtn.addEventListener("click", () => {
  shuffleOn = !shuffleOn;
  if (shuffleOn) buildShuffleOrder();
  updateUI();
});

repeatBtn.addEventListener("click", () => {
  if (repeatMode === "none") repeatMode = "all";
  else if (repeatMode === "all") repeatMode = "one";
  else repeatMode = "none";
  updateUI();
});

volumeRange.addEventListener("input", () => {
  audio.volume = volumeRange.value / 100;
  localStorage.setItem("player_volume", volumeRange.value);
});

closeBtn.addEventListener("click", () => {
  audio.pause();
  bar.classList.add("hidden");
  document.querySelectorAll(".track-item").forEach((el) => el.classList.remove("active"));
  playlist = [];
  currentIndex = -1;
  localStorage.removeItem("player_playlist");
  localStorage.removeItem("player_index");
  localStorage.removeItem("player_position");
});

function play(tracks, index) {
  playlist = tracks;
  currentIndex = index;
  if (shuffleOn) buildShuffleOrder();
  const track = playlist[currentIndex];
  if (!track) return;
  audio.src = track.stream_url;
  audio.play();
  updateUI();
}

function prev() {
  if (shuffleOn) {
    const pos = shuffledOrder.indexOf(currentIndex);
    if (pos > 0) play(playlist, shuffledOrder[pos - 1]);
    else if (repeatMode === "all") play(playlist, shuffledOrder[shuffledOrder.length - 1]);
  } else {
    if (currentIndex > 0) play(playlist, currentIndex - 1);
    else if (repeatMode === "all") play(playlist, playlist.length - 1);
  }
}

function next() {
  if (shuffleOn) {
    const pos = shuffledOrder.indexOf(currentIndex);
    if (pos < shuffledOrder.length - 1) play(playlist, shuffledOrder[pos + 1]);
    else if (repeatMode === "all") play(playlist, shuffledOrder[0]);
  } else {
    if (currentIndex < playlist.length - 1) play(playlist, currentIndex + 1);
    else if (repeatMode === "all") play(playlist, 0);
  }
}

// ── State persistence ────────────────────────────────────────────────────────

let _savePositionTimer = null;
function savePositionThrottled() {
  if (_savePositionTimer) return;
  _savePositionTimer = setTimeout(() => {
    localStorage.setItem("player_position", audio.currentTime);
    _savePositionTimer = null;
  }, 2000);
}

function saveState() {
  if (!playlist.length) return;
  try {
    localStorage.setItem("player_playlist", JSON.stringify(playlist));
    localStorage.setItem("player_index", currentIndex);
    localStorage.setItem("player_shuffle", shuffleOn);
    localStorage.setItem("player_repeat", repeatMode);
  } catch {}
}

function restoreState() {
  try {
    const vol = localStorage.getItem("player_volume");
    if (vol !== null) {
      audio.volume = Number(vol) / 100;
      volumeRange.value = vol;
    }
    shuffleOn = localStorage.getItem("player_shuffle") === "true";
    repeatMode = localStorage.getItem("player_repeat") || "none";

    const saved = localStorage.getItem("player_playlist");
    const savedIndex = localStorage.getItem("player_index");
    if (!saved || savedIndex === null) return;

    playlist = JSON.parse(saved);
    currentIndex = Number(savedIndex);
    if (shuffleOn) buildShuffleOrder();

    const track = playlist[currentIndex];
    if (!track) return;

    audio.src = track.stream_url;
    const pos = Number(localStorage.getItem("player_position") || 0);
    audio.addEventListener("loadedmetadata", () => {
      if (pos > 0 && pos < audio.duration) audio.currentTime = pos;
    }, { once: true });

    bar.classList.remove("hidden");
    titleEl.textContent = track.title;
    artistEl.textContent = track.artist || "";
    thumbEl.src = track.thumbnail_url || "";
    thumbEl.style.display = track.thumbnail_url ? "block" : "none";
    shuffleBtn.classList.toggle("active", shuffleOn);
    repeatBtn.textContent = repeatMode === "one" ? "🔂" : "🔁";
    repeatBtn.classList.toggle("active", repeatMode !== "none");
  } catch {}
}

// ── Playlist panel integration ───────────────────────────────────────────────

window.addEventListener("play-playlist-track", (e) => {
  play([e.detail], 0);
});

// Restore on load
restoreState();

export const player = { play, prev, next };
