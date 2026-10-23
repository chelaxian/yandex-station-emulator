const $ = (id) => document.getElementById(id);
const el = {
  device: $("device"), ringCore: $("ringCore"), ringGlow: $("ringGlow"),
  matrix: $("matrixCanvas"), midi: $("midi"), midiCanvas: $("midiCanvas"),
  stateName: $("stateName"), qemu: $("qemu"), conn: $("conn"), clockLive: $("clock-live"),
  bootlog: $("bootlog"), events: $("events"), ctlHint: $("ctlHint"),
  modelName: $("modelName"), arch: $("archLabel"), footer: $("footerModel"),
};

const matrixCtx = el.matrix.getContext("2d");
const midiCtx = el.midiCanvas.getContext("2d");
let state = { model: "mini", up: false, pid: null, models: [] };
let led = { connected: false, ring: [], clock: "", firmware: {} };
let logText = "";
let busy = false;
let toastTimer = null;
let midiHue = 268;

const DIGIT_SEGMENTS = {
  "0": "ABCDEF", "1": "BC", "2": "ABDEG", "3": "ABCDG", "4": "BCFG",
  "5": "ACDFG", "6": "ACDEFG", "7": "ABC", "8": "ABCDEFG", "9": "ABCDFG", "-": "G", " ": "",
};
const MINI_LINES = { A: [5, 4, 20, 4], B: [23, 7, 23, 20], C: [23, 27, 23, 40], D: [5, 43, 20, 43], E: [2, 27, 2, 40], F: [2, 7, 2, 20], G: [5, 24, 20, 24] };
const MIDI_LINES = { A: [6, 4, 40, 4], B: [44, 7, 44, 30], C: [44, 36, 44, 60], D: [6, 64, 40, 64], E: [4, 36, 4, 60], F: [4, 7, 4, 30], G: [6, 34, 40, 34] };

function toast(message) {
  const t = $("toast");
  t.textContent = message;
  t.classList.add("visible");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("visible"), 4000);
}

function pushEvent(kind, message) {
  const li = document.createElement("li");
  const time = document.createElement("span");
  const body = document.createElement("span");
  const k = document.createElement("span");
  time.className = "t";
  time.textContent = new Date().toLocaleTimeString("ru-RU");
  k.className = "event-kind";
  k.textContent = kind;
  body.append(k, document.createTextNode(String(message)));
  li.append(time, body);
  el.events.prepend(li);
  while (el.events.children.length > 60) el.events.lastChild.remove();
  $("eventCount").textContent = el.events.children.length;
}

/* ---------- Mini 2 visuals ---------- */
function drawMiniClock(clock) {
  const ctx = matrixCtx;
  ctx.clearRect(0, 0, 162, 57);
  const text = String(clock || "").replace(/[^0-9]/g, "").padEnd(4, " ").slice(0, 4);
  const dot = (x, y) => {
    ctx.fillStyle = "rgba(250,244,235,.92)";
    ctx.shadowBlur = 3;
    ctx.shadowColor = "#fff6e4";
    ctx.beginPath();
    ctx.arc(x, y, 1.35, 0, Math.PI * 2);
    ctx.fill();
  };
  for (let n = 0; n < 4; n++) {
    const offset = 13 + n * 33 + (n > 1 ? 8 : 0);
    for (const [seg, line] of Object.entries(MINI_LINES)) {
      if (!(DIGIT_SEGMENTS[text[n]] || "").includes(seg)) continue;
      const [x1, y1, x2, y2] = line;
      for (let i = 0; i < 5; i++) dot(offset + x1 + ((x2 - x1) * i) / 4, 5 + y1 + ((y2 - y1) * i) / 4);
    }
  }
}

function applyRing(colors) {
  const rgb = Array.from({ length: 6 }, (_, i) => {
    const c = /^#[0-9a-f]{6}$/i.test(colors[i] || "") ? colors[i] : "#000000";
    el.ringCore.style.setProperty("--led-" + i, c);
    return [1, 3, 5].map((o) => parseInt(c.slice(o, o + 2), 16));
  });
  const linear = (c) => (c <= 10.31475 ? c / 3294.6 : Math.pow((c / 255 + 0.055) / 1.055, 2.4));
  const srgb = (c) => Math.round(255 * (c <= 0.0031308 ? 12.92 * c : 1.055 * Math.pow(c, 1 / 2.4) - 0.055));
  const avg = [0, 1, 2].map((ch) => srgb(rgb.reduce((s, c) => s + linear(c[ch]), 0) / 6));
  const glow = "#" + avg.map((c) => c.toString(16).padStart(2, "0")).join("");
  el.device.style.setProperty("--ring-c", glow);
  const lit = rgb.some((c) => c.some((v) => v > 0));
  el.ringCore.classList.toggle("lit", lit);
  el.ringGlow.style.opacity = lit ? "0.7" : "0";
  el.ringGlow.style.background = `radial-gradient(circle, ${glow}75, transparent 70%)`;
}

/* ---------- MIDI visuals ---------- */
function drawMidiClock() {
  const ctx = midiCtx;
  const now = new Date();
  const text = String(now.getHours()).padStart(2, "0") + String(now.getMinutes()).padStart(2, "0");
  const xs = [12, 66, 132, 186];
  ctx.clearRect(0, 0, 260, 86);
  ctx.fillStyle = "#b5e2ff";
  ctx.shadowBlur = 6;
  ctx.shadowColor = "#59b4ff";
  const dot = (x, y) => {
    ctx.beginPath();
    ctx.arc(x, y, 1.5, 0, Math.PI * 2);
    ctx.fill();
  };
  for (let n = 0; n < 4; n++) {
    const segs = DIGIT_SEGMENTS[text[n]] || "";
    for (const [seg, line] of Object.entries(MIDI_LINES)) {
      if (!segs.includes(seg)) continue;
      const [x1, y1, x2, y2] = line;
      for (let i = 0; i < 7; i++) dot(xs[n] + x1 + ((x2 - x1) * i) / 6, 6 + y1 + ((y2 - y1) * i) / 6);
    }
  }
  dot(120, 28);
  dot(120, 56);
}

function animateMidi() {
  midiHue = (midiHue + 0.9) % 360;
  const lit = state.up && state.model === "midi";
  el.midi.style.setProperty("--midi-c", lit ? `hsl(${midiHue.toFixed(0)} 85% 64%)` : "#7c5cd6");
  drawMidiClock();
}

/* ---------- services ---------- */
function setService(name, value, fresh, model) {
  const node = $("service-" + name);
  if (!node) return;
  const label = node.querySelector("span");
  node.className = "service-status" + (fresh ? (value ? " ok" : " wait") : " off");
  label.textContent = !fresh ? "Нет данных" : value
    ? name === "network" ? "Настроена" : name === "sound" ? "Доступна" : "Работает"
    : name === "keymaster" ? "Недоступна" : "Остановлен";
}

function applyFirmware() {
  const fw = led.firmware || {};
  const hasData = Object.keys(fw).length > 0;
  // The bridge stamps every report with a host receive time; after ~20 s
  // without a new one the guest is considered silent, not healthy.
  const fresh = state.up && !!led.firmware_fresh;
  for (const name of ["platformd", "mediad", "network", "bluetooth", "sound", "keymaster"]) {
    setService(name, fresh ? fw[name] : undefined, fresh, state.model);
  }
  const note = $("firmwareStatus");
  if (!state.up) note.textContent = "Станция выключена. Запустите её, чтобы проверить сервисы.";
  else if (!fresh) note.textContent = hasData
    ? "Отчёт из гостевой системы устарел — службы не обновляются."
    : "Ожидается отчёт из гостевой системы.";
  else if (fw.platformd) note.textContent = "Службы Алисы запущены. Подключение из приложения ещё не готово.";
  else note.textContent = "Гостевая система работает. Службы Алисы запускаются.";

  if (!state.up) el.stateName.textContent = "Станция выключена";
  else if (!fresh) el.stateName.textContent = "Загрузка системы";
  else if (fw.platformd) el.stateName.textContent = state.model === "midi" ? "Миди · службы запущены" : "Алиса · службы запущены";
  else el.stateName.textContent = "Запуск служб Алисы";
  $("stateIndicator").style.background = state.up && fresh && fw.platformd ? "#8eb39f" : "#a993b8";
}

/* ---------- model / power ---------- */
function renderModel() {
  const model = state.model || "mini";
  const meta = state.models.find((m) => m.id === model) || {};
  el.modelName.textContent = model === "midi" ? "Миди" : "Мини 2";
  el.arch.textContent = model === "midi" ? "ARM64 / QEMU" : "ARM32 / QEMU";
  el.footer.textContent = model === "midi" ? "Миди · из дампа" : "Mini 2 · из резервной копии";
  el.device.hidden = model === "midi";
  el.midi.hidden = model !== "midi";
  document.querySelectorAll(".model-tab").forEach((b) => b.classList.toggle("active", b.dataset.model === model));
  el.ctlHint.textContent = state.up
    ? (model === "midi" ? "Состояние QEMU и консоль из гостевой системы" : "Состояние и подсветка поступают из прошивки")
    : "Включите станцию, чтобы продолжить";
}

async function api(path, body) {
  const opt = body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {};
  const r = await fetch(path, opt);
  return r.json();
}

async function selectModel(model) {
  if (state.model === model && state.up) return;
  busy = true;
  pushEvent("model", model === "midi" ? "Выбрана Миди" : "Выбрана Мини 2");
  await api("/api/select", { model });
  busy = false;
  await pollState();
  toast(model === "midi" ? "Модель: Миди" : "Модель: Мини 2");
}

async function qemuAction(action) {
  if (busy) return;
  busy = true;
  try {
    const j = await api("/api/qemu", { action });
    if (!j.ok) {
      pushEvent("error", j.error || "Ошибка");
      throw Error(j.hint ? `${j.error} — установите: ${j.hint}` : (j.error || "Не удалось выполнить действие"));
    }
    if (action === "clear") { el.bootlog.textContent = ""; logText = ""; }
    toast({ boot: "Станция запускается", stop: "Станция выключена", reboot: "Станция перезапускается", clear: "Журнал очищен" }[action]);
    pushEvent("qemu", { boot: "Запуск", stop: "Остановка", reboot: "Перезапуск", clear: "Очистка журнала" }[action]);
  } catch (e) {
    toast(e.message);
  } finally {
    busy = false;
    await pollState();
  }
}

/* ---------- polling ---------- */
async function pollState() {
  try {
    const s = await api("/api/state");
    state = s;
    if (!s.models.find((m) => m.id === s.model) && s.model) s.model = s.model;
    el.qemu.textContent = s.up ? "QEMU запущен" : "QEMU выключен";
    el.qemu.className = s.up ? "pill ok" : "pill dim";
    el.conn.textContent = "Соединено";
    el.conn.className = "pill ok";
    $("powerToggle").classList.toggle("running", s.up);
    $("powerLabel").textContent = busy ? "Подождите…" : s.up ? "Выключить" : "Запустить";
    $("powerToggle").disabled = busy;
    $("rebootButton").disabled = busy || !s.up;
    renderModel();
  } catch {
    el.conn.textContent = "Нет связи";
    el.conn.className = "pill dim";
  }
}

async function pollLed() {
  try {
    led = await api("/api/led");
    if (state.model === "mini") {
      const live = state.up && !!led.led_fresh;
      applyRing(live ? (led.ring || []) : []);
      drawMiniClock(live ? led.clock : "");
    }
    applyFirmware();
  } catch {}
}

async function loadConsole() {
  try {
    const j = await api("/api/console");
    const text = String(j.text || "").replace(/\x1b\[[0-9;?]*[ -/]*[@-~]/g, "").replace(/\r/g, "");
    if (text !== logText) { logText = text; el.bootlog.textContent = text; }
    if ($("autoScroll").checked) el.bootlog.scrollTop = el.bootlog.scrollHeight;
  } catch {}
}

/* ---------- wiring ---------- */
document.querySelectorAll(".model-tab").forEach((b) => b.addEventListener("click", () => selectModel(b.dataset.model)));
$("powerToggle").addEventListener("click", () => qemuAction(state.up ? "stop" : "boot"));
$("rebootButton").addEventListener("click", () => qemuAction("reboot"));
document.querySelectorAll("[data-qemu]").forEach((b) => b.addEventListener("click", () => qemuAction(b.dataset.qemu)));
$("downloadLog").addEventListener("click", async () => {
  await loadConsole();
  const url = URL.createObjectURL(new Blob([logText], { type: "text/plain;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = `${state.model}-console.log`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
el.bootlog.addEventListener("toggle", () => {}, { once: true });

function updateClockPill() {
  el.clockLive.textContent = new Date().toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
}

async function tick() {
  await pollState();
  await pollLed();
  if (state.model === "midi") animateMidi();
}

renderModel();
updateClockPill();
tick();
loadConsole();
setInterval(updateClockPill, 1000);
setInterval(async () => { await pollState(); await pollLed(); }, 2000);
setInterval(loadConsole, 2500);
setInterval(() => { if (state.model === "midi") animateMidi(); }, 250);
