"use strict";
// Codex Hark window. Talks to Python through window.pywebview.api (see Api in app.py).
// Opened in a plain browser, it uses fixture data so the screens can be reviewed and captured.

const $ = (sel, root = document) => root.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const icon = (id) => '<svg class="icon" aria-hidden="true"><use href="#' + id + '"/></svg>';

const I18N = {
  bg: {
    title: "Codex Hark", product: "Hark", nav: ["Начало", "Гласови команди", "Микрофон", "Дневник", "Настройки"],
    states: { starting: ["Стартира", "Слушателят стартира…"], listening: ["Слуша", "Слуша за ключовата дума"], chat: ["Гласов чат", "Гласовият чат е отворен"], dictation: ["Диктовка", "Диктовка в текущия чат"], paused: ["Пауза", "Слушането е на пауза"], error: ["Грешка", "Слушателят има проблем"] },
    kinds: { chat: "Гласов чат", dictation: "Диктовка", sent: "Изпратено", inserted: "В полето", error: "Грешка", pause: "Пауза", settings: "Настройки" },
    stateEyebrow: "Състояние", ready: "Готов за „{w}“", onPause: "На пауза", localNote: "Слушателят работи локално. Аудиото не се записва и не излиза от компютъра.",
    pause: "Пауза", resume: "Продължи", listener: "Слушателят", last: "Последно: {t} · {e}", noUse: "Още няма задействания днес.",
    hotkey: "Voice chat hotkey Alt+Z", codexOpen: "Отворен", codexClosed: "Не е отворен", defaultMic: "Микрофон по подразбиране", levelLine: "Ниво {l} · праг {t}",
    say: "Кажете", howTo: "Как се ползва", chatHelp: "Отваря гласов чат. Затваря се след {s} s тишина.", chatOff: "Гласовият чат е изключен.",
    dictHelp: "Диктовка в текущия чат. След {s} s тишина текстът се изпраща.", draftHelp: "Диктовка в текущия чат. Текстът остава в полето за преглед.", stopHelp: "Затваря гласовия чат веднага.", dictOff: "Диктовката е изключена.",
    recLangs: "Езици за разпознаване", recHelp: "Всички включени езици слушат едновременно. Моделите се изтеглят при първото включване.", langNames: { bg: "Български", en: "English" }, langSub: { bg: "руски модел, разбира и „Codex“", en: "американски английски" },
    modelReady: "Готов", modelMissing: "Не е изтеглен", modelDownloading: "Изтегля се {p}%", modelError: "Неуспешно изтегляне", download: "Изтегли", wordsFor: "Думи за",
    sendWords: "Пиши и изпрати", draftWords: "Чернова: текстът остава в полето", 
    recent: "Последни", events: "Събития", allLog: "Целият дневник →", noEvents: "Още няма събития.",
    cmdEyebrow: "Гласови команди", cmdTitle: "Какво чува и какво прави", cmdNote: "Промените действат веднага след „Запази“.",
    chat: "Гласов чат", chatSub: "Натиска Alt+Z в Codex", chatOn: "Гласов чат включен", wakeWords: "Ключови думи", closeAfter: "Секунди тишина",
    closeHelp: "Докато Codex търси или мисли, разговорът не се затваря (до 5 минути).", idleClose: "Затваряй след тишина", stopWords: "Фраза за край: ключова дума + една от тези думи", stopOn: "Фраза за край включена", busy: "Codex работи, разговорът остава отворен", chatStop: "„{w}, {s}“ го затваря веднага.", tryChat: "Пробвай: отвори гласов чат",
    dict: "Диктовка", dictSub: "Ключова дума + дума за диктовка", dictOn: "Диктовка включена", dictWords: "Думи за диктовка", dictEnd: "Край на диктовката след тишина",
    sensitivity: "Чувствителност", sensHelp: "По-висока стойност дава по-малко фалшиви задействания, но трябва да говорите по-ясно.",
    minConf: "Минимална увереност", cooldown: "Пауза след задействане", decoys: "Близки думи ({n})", decoysHelp: "Думи, които звучат подобно и поемат почти-попаденията, за да не се задейства слушателят.",
    add: "+ Добави", newWord: "нова дума", remove: "Премахни {w}",
    unsaved: "Има незапазени промени.", discard: "Откажи", save: "Запази", saved: "Запазено.", fix: "Има грешки. Поправете ги и запазете отново.",
    micEyebrow: "Микрофон", micTitle: "Вход и прагове за тишина", micNote: "Говорете и гледайте лентата. Чертата е прагът, над който звукът се брои за говор.",
    microphone: "Микрофон", winDefault: "Микрофон по подразбиране на Windows", notConnected: "(не е свързан)", levelNow: "Ниво в момента", speechRms: "Праг за говор",
    calibrate: "Нагласи автоматично", calibHelp: "5 s тишина, после 5 s говор. Прагът се избира между двете.", again: "Отново",
    quiet: "Мълчете…", speak: "Говорете нормално…", suggested: "Предложен праг: {v}. Натиснете „Запази“.", noDiff: "Няма ясна разлика между тишина и говор. Опитайте отново по-близо до микрофона.",
    codexVoice: "Гласът на Codex", codexVoiceHelp: "Докато Codex говори по-силно от този праг, гласовият чат не се затваря.", codexPeak: "Праг за звук от Codex",
    actEyebrow: "Дневник", actTitle: "Какво се е случило", actNote: "Пазят се последните 1000 събития. Аудио и текст от диктовката не се записват.",
    logFolder: "Папка с лога", copy: "Копирай", copied: "Копирано", copyFailed: "Неуспешно копиране", search: "Търсене", filters: ["Всички", "Гласов чат", "Диктовка", "Грешки"],
    time: "Време", event: "Събитие", details: "Подробности", none: "Няма събития.",
    setEyebrow: "Настройки", setTitle: "Приложение", setNote: "Тези настройки се запазват веднага.",
    autostart: "Стартирай с Windows", autostartHelp: "Иконата се появява в трея след влизане.", notifications: "Известия", notificationsHelp: "При проблем: няма микрофон, Codex не е отворен.",
    beep: "Звуков сигнал при задействане", beepHelp: "Кратък тон, когато чуе ключовата дума.", theme: "Тема", themes: ["Светла", "Тъмна", "Системна"],
    language: "Език", languages: ["Български", "English", "Като Windows"],
    localModel: "Работи изцяло локално. Модел: vosk-model-small-ru-0.22.", dataFolder: "Папка с данни", reset: "Върни настройките по подразбиране",
    resetConfirm: "Да се върнат ли всички настройки по подразбиране?", resetDone: "Настройките са върнати по подразбиране.",
    footer: "{s} · Codex {c} · Alt+Z", footerOpen: "е отворен", footerClosed: "не е отворен", version: "Codex Hark v{v}",
  },
  en: {
    title: "Codex Hark", product: "Hark", nav: ["Home", "Voice commands", "Microphone", "Activity", "Settings"],
    states: { starting: ["Starting", "The listener is starting…"], listening: ["Listening", "Listening for the wake word"], chat: ["Voice chat", "Voice chat is open"], dictation: ["Dictation", "Dictating in the current chat"], paused: ["Paused", "Listening is paused"], error: ["Error", "The listener has a problem"] },
    kinds: { chat: "Voice chat", dictation: "Dictation", sent: "Sent", inserted: "In the box", error: "Error", pause: "Pause", settings: "Settings" },
    stateEyebrow: "Status", ready: "Ready for “{w}”", onPause: "Paused", localNote: "The listener runs on this computer. Audio is never recorded or sent anywhere.",
    pause: "Pause", resume: "Resume", listener: "Listener", last: "Last: {t} · {e}", noUse: "Not used yet today.",
    hotkey: "Voice chat hotkey Alt+Z", codexOpen: "Open", codexClosed: "Not open", defaultMic: "Default microphone", levelLine: "Level {l} · threshold {t}",
    say: "Say", howTo: "How to use it", chatHelp: "Opens voice chat. Closes after {s} s of silence.", chatOff: "Voice chat is turned off.",
    dictHelp: "Dictation in the current chat. After {s} s of silence the text is sent.", draftHelp: "Dictation in the current chat. The text stays in the box for review.", stopHelp: "Closes the voice chat at once.", dictOff: "Dictation is turned off.",
    recLangs: "Recognition languages", recHelp: "All enabled languages listen at the same time. Models are downloaded when first enabled.", langNames: { bg: "Български", en: "English" }, langSub: { bg: "Russian model, also hears “Codex”", en: "US English" },
    modelReady: "Ready", modelMissing: "Not downloaded", modelDownloading: "Downloading {p}%", modelError: "Download failed", download: "Download", wordsFor: "Words for",
    sendWords: "Write and send", draftWords: "Draft: text stays in the box", 
    recent: "Recent", events: "Events", allLog: "Full activity →", noEvents: "No events yet.",
    cmdEyebrow: "Voice commands", cmdTitle: "What it hears and what it does", cmdNote: "Changes take effect as soon as you save.",
    chat: "Voice chat", chatSub: "Presses Alt+Z in Codex", chatOn: "Voice chat on", wakeWords: "Wake words", closeAfter: "Seconds of silence",
    closeHelp: "While Codex is searching or thinking, the conversation stays open (up to 5 minutes).", idleClose: "Close after silence", stopWords: "Stop phrase: wake word + one of these words", stopOn: "Stop phrase on", busy: "Codex is working, the conversation stays open", chatStop: "“{w}, {s}” closes it at once.", tryChat: "Try it: open voice chat",
    dict: "Dictation", dictSub: "Wake word + dictation word", dictOn: "Dictation on", dictWords: "Dictation words", dictEnd: "End dictation after silence",
    sensitivity: "Sensitivity", sensHelp: "A higher value means fewer false triggers, but you need to speak more clearly.",
    minConf: "Minimum confidence", cooldown: "Pause after a trigger", decoys: "Similar words ({n})", decoysHelp: "Words that sound alike and absorb near misses so the listener does not trigger.",
    add: "+ Add", newWord: "new word", remove: "Remove {w}",
    unsaved: "You have unsaved changes.", discard: "Discard", save: "Save", saved: "Saved.", fix: "Some values are invalid. Fix them and save again.",
    micEyebrow: "Microphone", micTitle: "Input and silence thresholds", micNote: "Speak and watch the bar. The mark is the threshold above which sound counts as speech.",
    microphone: "Microphone", winDefault: "Windows default microphone", notConnected: "(not connected)", levelNow: "Current level", speechRms: "Speech threshold",
    calibrate: "Calibrate", calibHelp: "5 s of silence, then 5 s of speech. The threshold is set between the two.", again: "Again",
    quiet: "Stay quiet…", speak: "Speak normally…", suggested: "Suggested threshold: {v}. Press Save.", noDiff: "No clear difference between silence and speech. Try again closer to the microphone.",
    codexVoice: "Codex voice", codexVoiceHelp: "While Codex is louder than this, voice chat stays open.", codexPeak: "Codex sound threshold",
    actEyebrow: "Activity", actTitle: "What happened", actNote: "The last 1000 events are kept. Audio and dictated text are never stored.",
    logFolder: "Log folder", copy: "Copy", copied: "Copied", copyFailed: "Copy failed", search: "Search", filters: ["All", "Voice chat", "Dictation", "Errors"],
    time: "Time", event: "Event", details: "Details", none: "No events.",
    setEyebrow: "Settings", setTitle: "Application", setNote: "These settings are saved right away.",
    autostart: "Start with Windows", autostartHelp: "The tray icon appears after you sign in.", notifications: "Notifications", notificationsHelp: "On problems: no microphone, Codex not open.",
    beep: "Beep on trigger", beepHelp: "A short tone when it hears the wake word.", theme: "Theme", themes: ["Light", "Dark", "System"],
    language: "Language", languages: ["Български", "English", "Same as Windows"],
    localModel: "Runs entirely on this computer. Model: vosk-model-small-ru-0.22.", dataFolder: "Data folder", reset: "Restore default settings",
    resetConfirm: "Restore all settings to their defaults?", resetDone: "Settings restored to defaults.",
    footer: "{s} · Codex {c} · Alt+Z", footerOpen: "is open", footerClosed: "is not open", version: "Codex Hark v{v}",
  },
};
const KIND = { chat: ["s-chat", "chat"], dictation: ["s-dictation", "pen"], sent: ["s-listening", "send"], inserted: ["s-listening", "ok"], error: ["s-error", "warn"], pause: ["", "pause"], settings: ["", "gear"] };
const STATE_CLASS = { starting: "", listening: "s-listening", chat: "s-chat", dictation: "s-dictation", paused: "", error: "s-error" };
let L = I18N.bg;
const T = (key, args = {}) => String(L[key]).replace(/\{(\w+)\}/g, (_, k) => args[k] ?? "");
const stateText = (s) => (L.states[s] || L.states.starting);
const FILTERS = { all: null, chat: ["chat"], dictation: ["dictation", "sent", "inserted"], error: ["error"] };

const ui = {
  screen: location.hash.slice(1).split("-")[0] || "home",
  live: null, events: [], lastId: 0, lang: null,
  saved: null, draft: null, meta: null, errors: {}, notice: null,
  filter: "all", query: "", calib: null, adding: null, wordsLang: "bg", models: null,
};

// ---------- API ----------
function fixtureApi() {
  const [, theme, lang = "bg"] = location.hash.slice(1).split("-");
  const now = new Date();
  const t = (min) => new Date(now - min * 60000 - now.getTimezoneOffset() * 60000).toISOString().slice(0, 19);
  const raw = [
    [95, "pause", "paused", {}], [92, "pause", "resumed", {}], [6, "chat", "wake_chat", { conf: "1.00" }], [5.5, "chat", "chat_opened", {}],
    [4, "chat", "chat_closed", {}], [3, "dictation", "wake_dictation", { conf: "0.97" }], [2.4, "sent", "sent", { seconds: "4" }],
  ];
  const texts = {
    bg: { paused: ["Слушането е спряно", ""], resumed: ["Слушането продължава", ""], wake_chat: ["„Кодекс“ → гласов чат", "увереност {conf}"], chat_opened: ["Гласовият чат е отворен", ""], chat_closed: ["Гласовият чат е затворен", ""], wake_dictation: ["„Кодекс, пиши“ → диктовка", "увереност {conf}"], sent: ["Диктовката е изпратена на агента", "след {seconds} s тишина"] },
    en: { paused: ["Listening paused", ""], resumed: ["Listening resumed", ""], wake_chat: ["“Codex” → voice chat", "confidence {conf}"], chat_opened: ["Voice chat opened", ""], chat_closed: ["Voice chat closed", ""], wake_dictation: ["“Codex, write” → dictation", "confidence {conf}"], sent: ["Dictation sent to the agent", "after {seconds} s of silence"] },
  };
  const events = raw.map(([m, kind, code, args], i) => {
    const [text, detail] = texts[lang][code];
    return { id: i + 1, time: t(m), kind, code, args, text, detail: detail.replace(/\{(\w+)\}/g, (_, k) => args[k]) };
  });
  const defaults = {
    chat_enabled: true, dictation_enabled: true, min_conf: 0.5, idle_seconds: 10,
    dictation_idle_seconds: 4, speech_rms: 200, codex_audio_peak: 0.01, cooldown_seconds: 8,
    mic_device: "", beep: false, notifications: true, theme: "system", language: "auto", stop_enabled: true, idle_close: true,
    languages: {
      bg: { enabled: true, wake_words: ["кодекс", "кодекса"], send_words: ["пиши"], draft_words: ["чернова"], stop_words: ["стоп", "край"], decoys: ["код", "кода", "коды", "коде", "тест", "текст", "индекс", "кейс", "алекса"] },
      en: { enabled: true, wake_words: ["codex"], send_words: ["write"], draft_words: ["draft"], stop_words: ["stop"], decoys: ["code", "codes", "coding", "text", "alexa", "context", "craft"] },
    },
  };
  let settings = { ...clone(defaults), theme: theme || "system", language: lang };
  const limits = { min_conf: [0.2, 0.95], idle_seconds: [3, 120], dictation_idle_seconds: [1, 30], speech_rms: [20, 5000], codex_audio_peak: [0.001, 0.5], cooldown_seconds: [1, 60] };
  return {
    state: async (after) => ({ state: location.hash.includes("busy") ? "chat" : "listening", busy: location.hash.includes("busy"), paused: false, codex_open: true, level: 520, lang, threshold: settings.speech_rms, version: "0.4.0", events: events.filter((e) => e.id > after) }),
    get_settings: async () => ({ settings, defaults, limits, devices: ["Microphone Array (Realtek(R) Au", "Headset (Jabra Evolve2 65)"], autostart: true, version: "0.4.0", lang }),
    save_settings: async (s) => { settings = s; return { ok: true, settings }; },
    reset_settings: async () => { settings = clone(defaults); return { ok: true, settings }; },
    set_paused: async () => ({}), set_autostart: async (v) => v, test_chat: async () => true,
    measure: async (s) => { await new Promise((r) => setTimeout(r, s * 1000)); return { ok: true, levels: [40, 60, 800, 900] }; },
    models: async () => [{ code: "bg", model: "vosk-model-small-ru-0.22", size_mb: 45, installed: true, state: "ready", progress: 0 }, { code: "en", model: "vosk-model-small-en-us-0.15", size_mb: 41, installed: !location.hash.includes("dl"), state: location.hash.includes("dl") ? "downloading" : "ready", progress: 0.42 }],
    download_model: async () => [], suggest_threshold: async () => 290, open_folder: async () => true, copy: async () => true,
  };
}
let api = null;
function ready() {
  return new Promise((resolve) => {
    if (window.pywebview?.api) return resolve(window.pywebview.api);
    window.addEventListener("pywebviewready", () => resolve(window.pywebview.api), { once: true });
    setTimeout(() => resolve(window.pywebview?.api || fixtureApi()), 700);
  });
}

// ---------- helpers ----------
function clone(o) { return JSON.parse(JSON.stringify(o)); }
const dirty = () => JSON.stringify(ui.draft) !== JSON.stringify(ui.saved);
const hhmmss = (iso) => iso.slice(11, 19);
const dateTime = (iso) => iso.slice(8, 10) + "." + iso.slice(5, 7) + " " + iso.slice(11, 19);
const cap = (s) => (s ? s[0].toUpperCase() + s.slice(1) : "");
const quote = (s) => (ui.lang === "bg" ? "„" + s + "“" : "“" + s + "”");
const fmt = (v, step) => (step < 1 ? Number(v).toFixed(String(step).split(".")[1].length) : String(v));
function setLanguage(lang) {
  if (ui.lang === lang) return false;
  ui.lang = lang; L = I18N[lang] || I18N.en;
  document.documentElement.lang = lang;
  document.title = L.title;
  $(".brand-product").textContent = L.product;
  document.querySelectorAll(".tab").forEach((b, i) => { b.lastChild.textContent = L.nav[i]; });
  return true;
}
function applyTheme() {
  const t = ui.saved?.theme || "system";
  const dark = t === "dark" || (t === "system" && matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
}
function meterWidth(level) {
  const top = Math.max((ui.draft?.speech_rms || 200) * 5, 1000);
  return Math.min(100, (level / top) * 100);
}
function err(key) { return ui.errors[key] ? '<span class="error-text" role="alert">' + esc(ui.errors[key]) + "</span>" : ""; }
function eventRow(e) {
  const k = KIND[e.kind] || ["", "info"];
  return '<div class="ev"><time>' + hhmmss(e.time) + '</time><span class="k-' + e.kind + '">' + icon(k[1]) + "</span><span>" + esc(e.text) + "</span><small>" + esc(e.detail) + "</small></div>";
}
function range(key, label, step, unit, help = "") {
  const [lo, hi] = ui.meta.limits[key];
  const v = ui.draft[key];
  return '<div class="field"><div class="lab"><label for="r-' + key + '">' + label + '</label><output id="o-' + key + '">' + fmt(v, step) + unit + "</output></div>" +
    '<input type="range" id="r-' + key + '" data-key="' + key + '" data-unit="' + unit + '" min="' + lo + '" max="' + hi + '" step="' + step + '" value="' + v + '">' +
    (help ? "<small>" + help + "</small>" : "") + err(key) + "</div>";
}
const idOf = (path) => path.replace(/\./g, "_");
function getP(obj, path) { return path.split(".").reduce((o, k) => (o == null ? o : o[k]), obj); }
function setP(obj, path, value) { const keys = path.split("."); const last = keys.pop(); keys.reduce((o, k) => o[k], obj)[last] = value; }
function chips(key, label) {
  const words = getP(ui.draft, key);
  const add = ui.adding === key
    ? '<input class="chip-input" id="add-' + idOf(key) + '" data-add="' + key + '" placeholder="' + L.newWord + '" aria-label="' + L.newWord + '">'
    : '<button class="chip-add" data-add-start="' + key + '">' + L.add + "</button>";
  return '<div class="field">' + (label ? '<span class="label">' + label + "</span>" : "") + '<div class="chips">' +
    words.map((w, i) => '<span class="chip">' + esc(w) + '<button data-remove="' + key + '" data-i="' + i + '" aria-label="' + esc(T("remove", { w })) + '">×</button></span>').join("") +
    add + "</div>" + err(key) + "</div>";
}
function toggle(key, label) {
  return '<label class="switch" title="' + label + '"><input type="checkbox" data-key="' + key + '" aria-label="' + label + '"' + (getP(ui.draft, key) ? " checked" : "") + "><span></span></label>";
}
function seg(key, options) {
  return '<div class="seg" role="group">' + options.map(([v, l]) => '<button data-seg="' + key + '" data-v="' + v + '" aria-pressed="' + (ui.draft[key] === v) + '">' + l + "</button>").join("") + "</div>";
}
function saveBarInner() {
  if (!dirty() && !ui.notice) return "";
  if (!dirty()) return '<div class="alert ' + ui.notice[0] + '">' + icon(ui.notice[0] === "ok" ? "ok" : "warn") + esc(ui.notice[1]) + "</div>";
  const bad = Object.keys(ui.errors).length > 0;
  return '<div class="savebar"><small' + (bad ? ' class="error-text"' : "") + ">" + (bad ? L.fix : L.unsaved) + '</small><button class="btn btn-small" data-action="discard">' + L.discard + '</button><button class="btn btn-small btn-primary" data-action="save">' + icon("ok") + L.save + "</button></div>";
}
const saveBar = () => '<div id="savebar-slot">' + saveBarInner() + "</div>";
function updateSaveBar() { const slot = $("#savebar-slot"); if (slot) slot.innerHTML = saveBarInner(); }

// ---------- screens ----------
const screens = {
  home() {
    const live = ui.live || { state: "starting", level: 0 };
    const lastUse = [...ui.events].reverse().find((e) => ["chat", "dictation", "sent", "inserted"].includes(e.kind));
    const recent = ui.events.slice(-3).reverse();
    const s = ui.draft;
    const on = Object.entries(s.languages).filter(([, w]) => w.enabled);
    const wake = cap((on[0] || ["", s.languages.bg])[1].wake_words[0]);
    const say = (list) => on.filter(([, w]) => !list || w[list].length).map(([, w]) => quote(cap(w.wake_words[0]) + (list ? ", " + w[list][0] : ""))).join(" · ");
    const phrase = (cls, ic, list, help) => (say(list) ? '<div class="phrase"><span class="mark ' + cls + '">' + icon(ic) + "</span><div><strong>" + esc(say(list)) + "</strong><br><small>" + help + "</small></div></div>" : "");
    return '<div class="intro"><div><div class="eyebrow">' + L.stateEyebrow + "</div><h1>" + (live.paused ? L.onPause : esc(T("ready", { w: wake }))) + "</h1><small>" + L.localNote + "</small></div>" +
      '<button class="btn" data-action="pause">' + icon(live.paused ? "play" : "pause") + (live.paused ? L.resume : L.pause) + "</button></div>" +
      '<div class="grid-home"><section class="card">' +
      '<div class="hero"><div class="orb ' + live.state + '" id="orb">' + icon("mic") + '</div><div class="hero-text"><span class="eyebrow">' + L.listener + '</span><h2 id="hero-title">' + (live.busy ? L.busy : stateText(live.state)[1]) + "</h2><small>" + (lastUse ? esc(T("last", { t: hhmmss(lastUse.time).slice(0, 5), e: lastUse.text })) : L.noUse) + "</small></div></div>" +
      '<div class="row"><span class="mark">' + icon("codex") + "</span><div><strong>Codex Desktop</strong><small>" + L.hotkey + '</small></div><span class="status-text ' + (live.codex_open ? "good" : "bad") + '" id="codex-status"><span class="dot"></span>' + (live.codex_open ? L.codexOpen : L.codexClosed) + "</span></div>" +
      '<div class="row"><span class="mark">' + icon("mic") + "</span><div><strong>" + esc(s.mic_device || L.defaultMic) + '</strong><small id="level-text">' + T("levelLine", { l: live.level, t: s.speech_rms }) + '</small></div><div style="flex:0 0 130px"><div class="meter" aria-hidden="true"><i id="level-bar" style="width:' + meterWidth(live.level) + '%"></i><b style="left:' + meterWidth(s.speech_rms) + '%"></b></div></div></div>' +
      '</section><section class="card"><div><div class="eyebrow">' + L.say + "</div><h2>" + L.howTo + "</h2></div>" +
      (s.chat_enabled ? phrase("chat", "chat", null, s.idle_close ? T("chatHelp", { s: s.idle_seconds }) : "") : "") +
      (s.dictation_enabled ? phrase("dict", "pen", "send_words", T("dictHelp", { s: s.dictation_idle_seconds })) + phrase("dict", "pen", "draft_words", L.draftHelp) : "") +
      (s.chat_enabled && s.stop_enabled ? phrase("chat", "pause", "stop_words", L.stopHelp) : "") +
      '</section></div><section class="card"><div class="head"><div><div class="eyebrow">' + L.recent + "</div><h2>" + L.events + '</h2></div><button class="text-button" data-go="activity">' + L.allLog + "</button></div>" +
      '<div class="ev-list">' + (recent.length ? recent.map(eventRow).join("") : '<div class="empty">' + L.noEvents + "</div>") + "</div></section>";
  },
  commands() {
    const lang = ui.wordsLang;
    const w = "languages." + lang + ".";
    const models = ui.models || [];
    const modelRow = (m) => {
      const status = m.installed ? '<span class="status-text good"><span class="dot"></span>' + L.modelReady + "</span>"
        : m.state === "downloading" ? '<span class="status-text muted">' + T("modelDownloading", { p: Math.round(m.progress * 100) }) + "</span>"
        : '<span class="status-text ' + (m.state === "error" ? "bad" : "muted") + '">' + (m.state === "error" ? L.modelError : L.modelMissing) + '</span><button class="btn btn-small" data-action="download" data-lang="' + m.code + '">' + L.download + "</button>";
      return '<div class="set"><div><strong>' + L.langNames[m.code] + "</strong><small>" + L.langSub[m.code] + " · " + m.model + " · " + m.size_mb + " MB</small>" + (m.error ? '<span class="error-text">' + esc(m.error) + "</span>" : "") + '</div><div class="steps">' + status + toggle("languages." + m.code + ".enabled", L.langNames[m.code]) + "</div></div>";
    };
    return '<div class="intro"><div><div class="eyebrow">' + L.cmdEyebrow + "</div><h1>" + L.cmdTitle + "</h1><small>" + L.cmdNote + "</small></div></div>" +
      '<section class="card" style="gap:0"><div><h2>' + L.recLangs + "</h2><small>" + L.recHelp + "</small>" + err("languages") + "</div>" + models.map(modelRow).join("") + "</section>" +
      '<div class="steps"><span class="label">' + L.wordsFor + '</span><div class="seg" role="group">' + Object.keys(ui.draft.languages).map((c) => '<button data-words-lang="' + c + '" aria-pressed="' + (c === lang) + '">' + L.langNames[c] + "</button>").join("") + "</div></div>" +
      '<div class="grid2"><section class="card"><div class="head"><div class="head-title"><span class="mark chat">' + icon("chat") + "</span><div><h2>" + L.chat + "</h2><small>" + L.chatSub + "</small></div></div>" + toggle("chat_enabled", L.chatOn) + "</div>" +
      chips(w + "wake_words", L.wakeWords) +
      '<div class="set"><div><strong>' + L.idleClose + "</strong><small>" + L.closeHelp + "</small></div>" + toggle("idle_close", L.idleClose) + "</div>" +
      (ui.draft.idle_close ? range("idle_seconds", L.closeAfter, 1, " s") : "") +
      '<div class="set"><div><strong>' + L.stopWords + "</strong></div>" + toggle("stop_enabled", L.stopOn) + "</div>" +
      (ui.draft.stop_enabled ? chips(w + "stop_words", "") : "") +
      '<button class="btn btn-small" style="align-self:flex-start" data-action="test-chat">' + icon("play") + L.tryChat + "</button></section>" +
      '<section class="card"><div class="head"><div class="head-title"><span class="mark dict">' + icon("pen") + "</span><div><h2>" + L.dict + "</h2><small>" + L.dictSub + "</small></div></div>" + toggle("dictation_enabled", L.dictOn) + "</div>" +
      chips(w + "send_words", L.sendWords) + chips(w + "draft_words", L.draftWords) + range("dictation_idle_seconds", L.dictEnd, 1, " s") + "</section></div>" +
      '<section class="card"><div><h2>' + L.sensitivity + "</h2><small>" + L.sensHelp + "</small></div>" +
      range("min_conf", L.minConf, 0.05, "") + range("cooldown_seconds", L.cooldown, 1, " s") +
      "<details" + (ui.errors[w + "decoys"] || ui.adding === w + "decoys" ? " open" : "") + "><summary>" + T("decoys", { n: getP(ui.draft, w + "decoys").length }) + "</summary><small>" + L.decoysHelp + "</small>" + chips(w + "decoys", "") + "</details></section>" + saveBar();
  },
  mic() {
    const live = ui.live || { level: 0 };
    const devices = ui.meta.devices;
    const c = ui.calib;
    const calib = !c ? '<button class="btn btn-primary" data-action="calibrate">' + icon("mic") + L.calibrate + "</button><small>" + L.calibHelp + "</small>"
      : c.step === "done" ? '<div class="alert ' + (c.value ? "ok" : "warn") + '">' + icon(c.value ? "ok" : "warn") + esc(c.value ? T("suggested", { v: c.value }) : c.error || L.noDiff) + '</div><button class="text-button" data-action="calibrate">' + L.again + "</button>"
      : '<div class="alert">' + icon("info") + (c.step === "quiet" ? L.quiet : L.speak) + " " + c.left + " s</div>";
    return '<div class="intro"><div><div class="eyebrow">' + L.micEyebrow + "</div><h1>" + L.micTitle + "</h1><small>" + L.micNote + "</small></div></div>" +
      '<section class="card"><div class="field"><label for="device">' + L.microphone + '</label><select id="device" data-key="mic_device"><option value="">' + L.winDefault + "</option>" +
      devices.map((d) => '<option value="' + esc(d) + '"' + (d === ui.draft.mic_device ? " selected" : "") + ">" + esc(d) + "</option>").join("") +
      (ui.draft.mic_device && !devices.includes(ui.draft.mic_device) ? '<option selected value="' + esc(ui.draft.mic_device) + '">' + esc(ui.draft.mic_device) + " " + L.notConnected + "</option>" : "") +
      "</select>" + err("mic_device") + "</div>" +
      '<div class="field"><div class="lab"><span class="label">' + L.levelNow + '</span><output id="level-out">' + live.level + '</output></div><div class="meter big" aria-hidden="true"><i id="level-bar" style="width:' + meterWidth(live.level) + '%"></i><b id="thr-mark" style="left:' + meterWidth(ui.draft.speech_rms) + '%"></b></div></div>' +
      range("speech_rms", L.speechRms, 10, "") + '<div class="steps">' + calib + "</div></section>" +
      '<section class="card"><div><h2>' + L.codexVoice + "</h2><small>" + L.codexVoiceHelp + "</small></div>" + range("codex_audio_peak", L.codexPeak, 0.001, "") + "</section>" + saveBar();
  },
  activity() {
    const kinds = FILTERS[ui.filter];
    const q = ui.query.toLowerCase();
    const rows = ui.events.filter((e) => (!kinds || kinds.includes(e.kind)) && (!q || (e.text + " " + e.detail).toLowerCase().includes(q))).reverse();
    return '<div class="intro"><div><div class="eyebrow">' + L.actEyebrow + "</div><h1>" + L.actTitle + "</h1><small>" + L.actNote + "</small></div>" +
      '<div class="steps"><button class="btn btn-small" data-action="folder">' + icon("folder") + L.logFolder + '</button><button class="btn btn-small" data-action="copy">' + icon("copy") + L.copy + "</button></div></div>" +
      (ui.notice ? '<div class="alert ' + ui.notice[0] + '">' + esc(ui.notice[1]) + "</div>" : "") +
      '<div class="filters"><label class="search">' + icon("search") + '<input id="query" placeholder="' + L.search + '" value="' + esc(ui.query) + '" aria-label="' + L.search + '"></label>' +
      '<div class="seg" role="group">' + Object.keys(FILTERS).map((v, i) => '<button data-filter="' + v + '" aria-pressed="' + (ui.filter === v) + '">' + L.filters[i] + "</button>").join("") + "</div></div>" +
      '<section class="card table-card"><table><thead><tr><th>' + L.time + "</th><th>" + L.event + "</th><th>" + L.details + "</th></tr></thead><tbody>" +
      (rows.length ? rows.map((e) => '<tr><td class="t">' + dateTime(e.time) + '</td><td><span class="pill ' + (KIND[e.kind]?.[0] || "") + '"><span class="dot"></span>' + (L.kinds[e.kind] || e.kind) + "</span> " + esc(e.text) + '</td><td class="d">' + esc(e.detail) + "</td></tr>").join("") : '<tr><td colspan="3" class="empty">' + L.none + "</td></tr>") +
      "</tbody></table></section>";
  },
  settings() {
    const m = ui.meta;
    return '<div class="intro"><div><div class="eyebrow">' + L.setEyebrow + "</div><h1>" + L.setTitle + "</h1><small>" + L.setNote + "</small></div></div>" +
      '<div class="grid2"><section class="card" style="gap:0">' +
      '<div class="set"><div><strong>' + L.autostart + "</strong><small>" + L.autostartHelp + '</small></div><label class="switch"><input type="checkbox" id="autostart" aria-label="' + L.autostart + '"' + (m.autostart ? " checked" : "") + "><span></span></label></div>" +
      '<div class="set"><div><strong>' + L.notifications + "</strong><small>" + L.notificationsHelp + "</small></div>" + toggle("notifications", L.notifications) + "</div>" +
      '<div class="set"><div><strong>' + L.beep + "</strong><small>" + L.beepHelp + "</small></div>" + toggle("beep", L.beep) + "</div>" +
      '<div class="set"><div><strong>' + L.language + "</strong></div>" + seg("language", [["bg", L.languages[0]], ["en", L.languages[1]], ["auto", L.languages[2]]]) + "</div>" +
      '<div class="set"><div><strong>' + L.theme + "</strong></div>" + seg("theme", [["light", L.themes[0]], ["dark", L.themes[1]], ["system", L.themes[2]]]) + "</div></section>" +
      '<section class="card"><div class="head-title"><img class="app-icon" src="icon.png" alt=""><div><h2>' + L.title + " " + esc(m.version) + "</h2><small>github.com/ID-Yo/codex-hark</small></div></div>" +
      '<div class="alert">' + icon("info") + L.localModel + "</div>" +
      '<div class="steps"><button class="btn btn-small" data-action="folder">' + icon("folder") + L.dataFolder + '</button><button class="btn btn-small btn-danger" data-action="reset">' + L.reset + "</button></div>" +
      (ui.notice ? '<div class="alert ' + ui.notice[0] + '">' + esc(ui.notice[1]) + "</div>" : "") + "</section></div>";
  },
};

// ---------- rendering ----------
function render(focus) {
  document.querySelectorAll(".tab").forEach((t) => t.setAttribute("aria-current", t.dataset.screen === ui.screen ? "page" : "false"));
  const el = $("#screen");
  const active = document.activeElement?.id;
  const scroll = el.scrollTop;
  el.innerHTML = screens[ui.screen]();
  if (focus) { el.scrollTop = 0; el.focus(); return; }
  el.scrollTop = scroll;
  if (active && $("#" + active)) { const a = $("#" + active); a.focus(); if (a.setSelectionRange && a.value) a.setSelectionRange(a.value.length, a.value.length); }
  if (ui.adding) $("#add-" + idOf(ui.adding))?.focus();
}
function renderLive() {
  const live = ui.live;
  const st = stateText(live.state);
  const top = $("#top-state");
  top.className = "pill " + (STATE_CLASS[live.state] || "");
  top.lastElementChild.textContent = st[0];
  $("#foot-state").innerHTML = '<span class="dot" style="color:var(--' + (live.state === "error" ? "error" : live.state === "listening" ? "good" : "subtle") + ')"></span>' + esc(T("footer", { s: st[0], c: live.codex_open ? L.footerOpen : L.footerClosed }));
  $("#foot-version").textContent = T("version", { v: live.version });
  const bar = $("#level-bar");
  if (bar) bar.style.width = meterWidth(live.level) + "%";
  if ($("#level-out")) $("#level-out").textContent = live.level;
  if ($("#level-text")) $("#level-text").textContent = T("levelLine", { l: live.level, t: ui.draft.speech_rms });
  if (ui.screen === "home") {
    const orb = $("#orb");
    const cs = $("#codex-status");
    if ((orb && !orb.classList.contains(live.state)) || (cs && cs.classList.contains("good") !== live.codex_open)) render();
  }
}

async function poll() {
  try {
    const live = await api.state(ui.lastId);
    const changed = !ui.live || live.state !== ui.live.state || live.paused !== ui.live.paused || live.busy !== ui.live.busy;
    ui.live = live;
    if (setLanguage(live.lang)) {  // language changed: reload every event in the new language
      ui.events = (await api.state(0)).events.slice(-1000);
      render();
    } else if (live.events.length) {
      ui.events.push(...live.events);
      ui.events = ui.events.slice(-1000);
      if (ui.screen === "home" || (ui.screen === "activity" && document.activeElement?.id !== "query")) render();
    } else if (changed && ui.screen === "home") render();
    if (ui.events.length) ui.lastId = ui.events[ui.events.length - 1].id;
    if (ui.screen === "commands" || (ui.models || []).some((m) => m.state === "downloading")) {
      const models = await api.models();
      if (JSON.stringify(models) !== JSON.stringify(ui.models)) { ui.models = models; if (ui.screen === "commands" && !document.activeElement?.matches("input[type=range]")) render(); }
    }
    renderLive();
  } catch (e) { console.error(e); }
  setTimeout(poll, 500);
}

async function save(next = ui.draft) {
  const result = await api.save_settings(next);
  if (!result.ok) {
    ui.errors = result.errors; ui.notice = ["err", L.fix]; render(); updateSaveBar();
    const first = $(".error-text[role=alert]"); if (first) first.scrollIntoView({ block: "center" });
    return false;
  }
  ui.saved = clone(result.settings);
  ui.draft = { ...clone(result.settings), ...pending(next) };
  ui.errors = {};
  ui.notice = ["ok", L.saved];
  applyTheme(); render();
  setTimeout(() => { ui.notice = null; if (!dirty() && ["commands", "mic", "settings"].includes(ui.screen)) render(); }, 3000);
  return true;
}
// Unsaved edits on other screens survive an immediate save from the Settings screen.
function pending(next) { const out = {}; for (const k in ui.draft) if (next !== ui.draft && JSON.stringify(ui.draft[k]) !== JSON.stringify(ui.saved[k]) && !IMMEDIATE.includes(k)) out[k] = ui.draft[k]; return out; }
const IMMEDIATE = ["notifications", "beep", "theme", "language"];
async function setDraft(key, value) {
  delete ui.errors[key];
  if (IMMEDIATE.includes(key)) { ui.draft[key] = value; return save({ ...ui.saved, [key]: value }); }
  setP(ui.draft, key, value);
  ui.notice = null;
}

async function calibrate() {
  const run = async (step) => {
    ui.calib = { step, left: 5 }; render();
    const timer = setInterval(() => { if (ui.calib && ui.calib.left > 1) { ui.calib.left--; if (ui.screen === "mic") render(); } }, 1000);
    const r = await api.measure(5);
    clearInterval(timer);
    return r;
  };
  const quiet = await run("quiet");
  if (!quiet.ok) { ui.calib = { step: "done", error: quiet.error }; return render(); }
  const speech = await run("speech");
  if (!speech.ok) { ui.calib = { step: "done", error: speech.error }; return render(); }
  const value = await api.suggest_threshold(quiet.levels, speech.levels);
  ui.calib = { step: "done", value };
  if (value) ui.draft.speech_rms = Math.min(5000, Math.max(20, Math.round(value / 10) * 10));
  render();
}

// ---------- events ----------
document.addEventListener("click", async (ev) => {
  const t = ev.target.closest("button, [data-go]");
  if (!t) return;
  const d = t.dataset;
  if (d.screen || d.go) { ui.screen = d.screen || d.go; ui.notice = null; ui.adding = null; render(true); return; }
  if (d.seg) { const v = d.v === "true" ? true : d.v === "false" ? false : d.v; await setDraft(d.seg, v); render(); updateSaveBar(); return; }
  if (d.filter) { ui.filter = d.filter; render(); return; }
  if (d.remove) { setP(ui.draft, d.remove, getP(ui.draft, d.remove).filter((_, i) => i !== Number(d.i))); delete ui.errors[d.remove]; ui.notice = null; render(); return; }
  if (d.wordsLang) { ui.wordsLang = d.wordsLang; ui.adding = null; render(); return; }
  if (d.addStart) { ui.adding = d.addStart; render(); return; }
  switch (d.action) {
    case "pause": ui.live = await api.set_paused(!ui.live.paused); render(); renderLive(); break;
    case "save": await save(); break;
    case "discard": ui.draft = clone(ui.saved); ui.errors = {}; ui.calib = null; ui.notice = null; render(); break;
    case "test-chat": await api.test_chat(); break;
    case "download": ui.models = await api.download_model(d.lang); render(); break;
    case "calibrate": await calibrate(); break;
    case "folder": await api.open_folder(); break;
    case "copy": {
      const text = ui.events.slice().reverse().map((e) => dateTime(e.time) + "\t" + (L.kinds[e.kind] || e.kind) + "\t" + e.text + "\t" + e.detail).join("\n");
      ui.notice = (await api.copy(text)) ? ["ok", L.copied] : ["err", L.copyFailed]; render();
      setTimeout(() => { ui.notice = null; if (ui.screen === "activity") render(); }, 2500);
      break;
    }
    case "reset":
      if (confirm(L.resetConfirm)) {
        const r = await api.reset_settings();
        ui.saved = clone(r.settings); ui.draft = clone(r.settings); ui.errors = {};
        ui.notice = ["ok", L.resetDone]; applyTheme(); render();
      }
      break;
  }
});
document.addEventListener("input", (ev) => {
  const t = ev.target;
  if (t.id === "query") { ui.query = t.value; render(); return; }
  if (t.type === "range") {
    const key = t.dataset.key, v = Number(t.value);
    ui.draft[key] = v; delete ui.errors[key]; ui.notice = null;
    $("#o-" + key).textContent = fmt(v, Number(t.step)) + t.dataset.unit;
    if (key === "speech_rms" && $("#thr-mark")) $("#thr-mark").style.left = meterWidth(v) + "%";
    updateSaveBar();
  }
});
document.addEventListener("change", async (ev) => {
  const t = ev.target;
  if (t.id === "autostart") { ui.meta.autostart = await api.set_autostart(t.checked); return; }
  if (t.type === "checkbox" && t.dataset.key) { await setDraft(t.dataset.key, t.checked); render(); updateSaveBar(); return; }
  if (t.tagName === "SELECT" && t.dataset.key) { await setDraft(t.dataset.key, t.value); render(); updateSaveBar(); }
});
document.addEventListener("keydown", (ev) => {
  const t = ev.target;
  if (t.dataset?.add && (ev.key === "Enter" || ev.key === "Escape")) {
    const key = t.dataset.add, word = t.value.trim().toLowerCase();
    if (ev.key === "Enter" && word && !getP(ui.draft, key).includes(word)) { setP(ui.draft, key, [...getP(ui.draft, key), word]); ui.notice = null; }
    ui.adding = null; delete ui.errors[key]; render();
    $('[data-add-start="' + key + '"]')?.focus();
  }
});
document.addEventListener("focusout", (ev) => {
  if (ev.target.dataset?.add && ui.adding) setTimeout(() => { if (ui.adding && document.activeElement?.dataset?.add !== ui.adding) { ui.adding = null; render(); } }, 0);
});
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", applyTheme);

(async () => {
  api = await ready();
  ui.meta = await api.get_settings();
  ui.saved = clone(ui.meta.settings);
  ui.draft = clone(ui.meta.settings);
  ui.models = await api.models();
  setLanguage(ui.meta.lang);
  if (ui.draft.languages[ui.lang]) ui.wordsLang = ui.lang;
  applyTheme();
  ui.live = await api.state(0);
  ui.events = ui.live.events.slice(-1000);
  ui.lastId = ui.events.length ? ui.events[ui.events.length - 1].id : 0;
  render();
  renderLive();
  setTimeout(poll, 500);
})();

