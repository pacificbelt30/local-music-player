let playlist = [];
let currentIndex = -1;
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

function fmt(secs) {
  if (!secs || isNaN(secs)) return "0:00";
  const m = Math.floor(secs / 60);
  const s = Math.floor(secs % 60).toString().padStart(2, "0");
  return `${m}:${s}`;
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
}

audio.addEventListener("timeupdate", () => {
  if (!isNaN(audio.duration)) {
    seekEl.value = (audio.currentTime / audio.duration) * 100;
    currentTimeEl.textContent = fmt(audio.currentTime);
  }
});

audio.addEventListener("loadedmetadata", () => {
  durationEl.textContent = fmt(audio.duration);
});

audio.addEventListener("play", () => { playBtn.textContent = "⏸"; });
audio.addEventListener("pause", () => { playBtn.textContent = "▶"; });
audio.addEventListener("ended", () => next());

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

function play(tracks, index) {
  playlist = tracks;
  currentIndex = index;
  const track = playlist[currentIndex];
  if (!track) return;
  audio.src = track.stream_url;
  audio.play();
  updateUI();
}

function prev() {
  if (currentIndex > 0) play(playlist, currentIndex - 1);
}

function next() {
  if (currentIndex < playlist.length - 1) play(playlist, currentIndex + 1);
}

export const player = { play, prev, next };
