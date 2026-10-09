"""Listen for wake phrases locally and drive Codex Desktop voice chat and dictation.

"Кодекс" presses the voice chat hotkey (Alt+Z). "Кодекс, пиши" clicks the Dictate
button of the current chat through UI Automation (Alt+X only works while Codex has focus)
and, after a pause, clicks "Transcribe and send" (or "Stop dictation").

Run directly (python wakeword.py) for a console-free listener without a window;
app.py wraps the same Listener in a tray application with a window (CodexHark.exe).
"""
import collections
import glob
import hashlib
import ctypes
import json
import logging
import logging.handlers
import os
import platform
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.request
import winreg
import zipfile


def _no_wmi(*args, **kwargs):
    raise OSError("WMI is not used")


# platform.win32_ver() (used by several libraries at import time) asks WMI first and hangs
# forever when the WMI service is stuck. Without WMI it falls back to sys.getwindowsversion().
platform._wmi_query = _no_wmi

import comtypes  # noqa: E402
import comtypes.client  # noqa: E402
import numpy as np  # noqa: E402
import psutil  # noqa: E402
import sounddevice as sd  # noqa: E402
import vosk  # noqa: E402
from _ctypes import COMError  # noqa: E402
from pycaw.pycaw import AudioUtilities, IAudioMeterInformation  # noqa: E402
from vosk import KaldiRecognizer, Model, SetLogLevel  # noqa: E402

comtypes.client.GetModule("UIAutomationCore.dll")
from comtypes.gen.UIAutomationClient import (  # noqa: E402
    CUIAutomation, IUIAutomation, IUIAutomationInvokePattern, TreeScope_Descendants,
    UIA_ButtonControlTypeId, UIA_ControlTypePropertyId, UIA_InvokePatternId, UIA_NamePropertyId)

__version__ = "0.7.0"

APP_NAME = "CodexHark"
DATA_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), APP_NAME)
LEGACY_DATA_DIR = os.path.join(os.path.dirname(DATA_DIR), "CodexSlushatel")  # name before the rename to Codex Hark
if not os.path.exists(DATA_DIR) and os.path.isdir(LEGACY_DATA_DIR):
    try:
        os.rename(LEGACY_DATA_DIR, DATA_DIR)
    except OSError:
        pass
SETTINGS_PATH = os.path.join(DATA_DIR, "settings.json")
LOG_PATH = os.path.join(DATA_DIR, "wakeword.log")
EVENTS_PATH = os.path.join(DATA_DIR, "events.jsonl")
MODEL_NAME = "vosk-model-small-ru-0.22"
HERE = os.path.dirname(os.path.abspath(__file__))

# Recognition languages: a small Vosk model each; commands are the wake word plus one word after it.
MODELS = {
    # No Bulgarian Vosk model exists; the Russian one hears "Кодекс", "пиши", "стоп" and English "Codex".
    "bg": {"name": "vosk-model-small-ru-0.22", "size_mb": 45,
           "sha256": "961D5FF98A17F4AA6DE69864D0AA71FA5BAC682301D2B5D17A3F24C5C99A46D4"},
    "en": {"name": "vosk-model-small-en-us-0.15", "size_mb": 41,
           "sha256": "30F26242C4EB449F948E42CB302DD7A686CB29A3423A8367F99FF41780942498"},
}
MODEL_URL = "https://alphacephei.com/vosk/models/{name}.zip"
LANGUAGE_NAMES = {"bg": {"bg": "български", "en": "английски"}, "en": {"bg": "Bulgarian", "en": "English"}}

DEFAULTS = {
    "languages": {
        "bg": {
            "enabled": True,
            # "кодекс" also matches English "Codex"; "кодекса" covers "Кодекс, отвори...".
            "wake_words": ["кодекс", "кодекса"],
            "send_words": ["пиши"],  # dictate, then send to the agent
            "draft_words": ["чернова"],  # dictate, then leave the text in the message box
            "stop_words": ["стоп", "край"],  # end a voice chat at once
            "chat_words": ["чат"],  # ChatGPT Classic: a voice conversation, or dictation with a dictation word
            # Similar-sounding words give the recognizer somewhere else to put near misses.
            "decoys": ["код", "кода", "коды", "коде", "тест", "текст", "индекс", "кейс", "алекса"],
        },
        "en": {
            "enabled": True,
            "wake_words": ["codex"],
            "send_words": ["write"],
            "draft_words": ["draft"],
            "stop_words": ["stop"],
            "chat_words": ["chat"],
            "decoys": ["code", "codes", "coding", "text", "alexa", "context", "craft"],
        },
    },
    "stop_enabled": True,
    "idle_close": True,  # end a voice chat after idle_seconds of silence (never while Codex is working)
    "chat_enabled": True,
    "chatgpt_enabled": False,  # the chat commands drive ChatGPT Classic; off until the user turns them on
    "dictation_enabled": True,
    "min_conf": 0.5,
    "idle_seconds": 10,  # end the voice chat after this much silence from you and Codex
    "dictation_idle_seconds": 4,  # end a dictation after this much silence from you
    "speech_rms": 200,  # mic level that counts as you talking
    "codex_audio_peak": 0.01,  # output level that counts as Codex talking
    "cooldown_seconds": 8,
    "mic_device": "",  # empty: the Windows default microphone
    "beep": False,
    "notifications": True,
    "theme": "system",
    "language": "auto",  # auto: Bulgarian when Windows is in Bulgarian, otherwise English
    "keys_checked": False,  # the first-run check of Codex's shortcuts has been done
}
# Allowed range of each number setting.
LIMITS = {"min_conf": (0.2, 0.95), "idle_seconds": (3, 120), "dictation_idle_seconds": (1, 30),
          "speech_rms": (20, 5000), "codex_audio_peak": (0.001, 0.5), "cooldown_seconds": (1, 60)}
WORD_LISTS = ("wake_words", "chat_words", "send_words", "draft_words", "stop_words", "decoys")
COMMAND_LISTS = WORD_LISTS[:5]  # a word may appear in only one of these per language
OLD_WORD_KEYS = ("wake_words", "dictate_words", "stop_words", "decoys", "dictation_send")
THEMES = ("system", "light", "dark")
MAX_PHRASE_WORDS = 3  # a wake phrase such as "hey jarvis"; the other lists hold single words
PHRASE_LISTS = ("wake_words", "chat_words")
LANGUAGES = ("auto", "bg", "en")
# Environment variables keep working and win over settings.json.
ENV_OVERRIDES = {"min_conf": "CODEX_WAKE_CONF", "idle_seconds": "CODEX_IDLE_SECONDS",
                 "dictation_idle_seconds": "CODEX_DICTATION_IDLE_SECONDS"}

# Event and message texts: code -> {language: (text, detail)}. Details may use the event args.
MESSAGES = {
    "wake_chat": {"bg": ("Гласов чат: „{phrase}“", "увереност {conf}"), "en": ("Voice chat: “{phrase}”", "confidence {conf}")},
    "wake_dictation": {"bg": ("Диктовка с изпращане: „{phrase}“", "увереност {conf}"), "en": ("Dictation and send: “{phrase}”", "confidence {conf}")},
    "wake_draft": {"bg": ("Чернова: „{phrase}“", "увереност {conf}"), "en": ("Draft: “{phrase}”", "confidence {conf}")},
    "model_downloading": {"bg": ("Изтегляне на модела за {language}", "{size} MB"), "en": ("Downloading the {language} model", "{size} MB")},
    "model_ready": {"bg": ("Моделът за {language} е готов", ""), "en": ("The {language} model is ready", "")},
    "model_error": {"bg": ("Моделът за {language} не се изтегли", "{error}"), "en": ("The {language} model could not be downloaded", "{error}")},
    "chat_opened": {"bg": ("Гласовият чат е отворен", ""), "en": ("Voice chat opened", "")},
    "chat_closing": {"bg": ("Затваряне на гласовия чат", "{seconds} s тишина"), "en": ("Closing voice chat", "{seconds} s of silence")},
    "chat_closed": {"bg": ("Гласовият чат е затворен", ""), "en": ("Voice chat closed", "")},
    "manual_dictation": {"bg": ("Диктовка, пусната ръчно", ""), "en": ("Dictation started by hand", "")},
    "manual_dictation_ended": {"bg": ("Ръчната диктовка приключи", ""), "en": ("Manual dictation ended", "")},
    "dictation_stopped": {"bg": ("Диктовката е спряна в Codex", ""), "en": ("Dictation was stopped in Codex", "")},
    "sent": {"bg": ("Диктовката е изпратена на агента", "след {seconds} s тишина"), "en": ("Dictation sent to the agent", "after {seconds} s of silence")},
    "inserted": {"bg": ("Текстът е оставен в полето", "след {seconds} s тишина"), "en": ("Text left in the message box", "after {seconds} s of silence")},
    "button_missing": {"bg": ("Бутонът {button} не е намерен", "Отворен ли е Codex?"), "en": ("The {button} button was not found", "Is Codex open?")},
    "mic_error": {"bg": ("Няма достъп до микрофона", "{error}"), "en": ("The microphone is not available", "{error}")},
    "crash": {"bg": ("Hark се срина", "{error}"), "en": ("Hark crashed", "{error}")},
    "paused": {"bg": ("Слушането е спряно", ""), "en": ("Listening paused", "")},
    "resumed": {"bg": ("Слушането продължава", ""), "en": ("Listening resumed", "")},
    "stop_phrase": {"bg": ("Край на разговора: „{phrase}“", "увереност {conf}"), "en": ("Conversation ended: “{phrase}”", "confidence {conf}")},
    "busy_start": {"bg": ("Codex работи, разговорът остава отворен", ""), "en": ("Codex is working, the conversation stays open", "")},
    "busy_end": {"bg": ("Codex приключи", ""), "en": ("Codex finished", "")},
    "busy_limit": {"bg": ("Codex работи над {minutes} минути", "тишината отново затваря разговора"), "en": ("Codex has been working for over {minutes} minutes", "silence closes the conversation again")},
    "words_unknown": {"bg": ("Моделът за {language} не познава: {words}", "тези думи няма да се разпознават"),
                      "en": ("The {language} model does not know: {words}", "these words will not be recognized")},
    "keys_ok": {"bg": ("Shortcut-ите на Codex са наред", "гласов чат {voice}, диктовка {dictation}"),
                "en": ("Codex shortcuts are set", "voice chat {voice}, dictation {dictation}")},
    "keys_added": {"bg": ("Hark добави shortcut-и в Codex: {commands}", "рестартирайте Codex, за да ги прочете"),
                   "en": ("Hark added Codex shortcuts: {commands}", "restart Codex so it picks them up")},
    "keys_conflict": {"bg": ("Клавишът в Codex е зает от друга команда: {conflicts}", "задайте shortcut ръчно в настройките на Codex"),
                      "en": ("A key in Codex is used by another command: {conflicts}", "set the shortcut by hand in Codex settings")},
    "keys_invalid": {"bg": ("Файлът keybindings.json на Codex не може да се прочете", "Hark не го промени"),
                     "en": ("Codex's keybindings.json cannot be read", "Hark did not change it")},
    "keys_no_codex": {"bg": ("Папката на Codex не е намерена", "стартирайте Codex поне веднъж"),
                      "en": ("The Codex folder was not found", "start Codex at least once")},
    "keys_error": {"bg": ("Hark не успя да запише keybindings.json на Codex", "{error}"),
                   "en": ("Hark could not write Codex's keybindings.json", "{error}")},
    "wake_chatgpt": {"bg": ("ChatGPT: „{phrase}“ → гласов разговор", "увереност {conf}"), "en": ("ChatGPT: “{phrase}” → voice conversation", "confidence {conf}")},
    "wake_chatgpt_dictation": {"bg": ("ChatGPT: „{phrase}“ → диктовка", "увереност {conf}"), "en": ("ChatGPT: “{phrase}” → dictation", "confidence {conf}")},
    "chatgpt_stopped": {"bg": ("ChatGPT: край на разговора „{phrase}“", "увереност {conf}"), "en": ("ChatGPT: conversation ended “{phrase}”", "confidence {conf}")},
    "chatgpt_missing": {"bg": ("ChatGPT Classic не е намерен или не е влязъл в профила", "инсталирайте го и влезте"), "en": ("ChatGPT Classic was not found or is not signed in", "install it and sign in")},
    "settings_saved": {"bg": ("Настройките са запазени", ""), "en": ("Settings saved", "")},
}
ERRORS = {
    "range": {"bg": "Стойността трябва да е между {lo} и {hi}.", "en": "The value must be between {lo} and {hi}."},
    "list": {"bg": "Очаква се списък с думи.", "en": "A list of words is expected."},
    "empty": {"bg": "Нужна е поне една дума.", "en": "At least one word is needed."},
    "unknown": {"bg": "Моделът не познава: {words}.", "en": "The speech model does not know: {words}."},
    "choice": {"bg": "Невалиден избор.", "en": "Invalid choice."},
    "type": {"bg": "Невалиден тип.", "en": "Invalid type."},
    "overlap": {"bg": "Една дума може да е само в един списък на езика.", "en": "A word can be in only one list per language."},
    "one_word": {"bg": "Тук се допуска само една дума: {words}.", "en": "Only single words are allowed here: {words}."},
    "too_long": {"bg": "Фразата може да е най-много от {n} думи: {words}.", "en": "A phrase can have at most {n} words: {words}."},
    "no_language": {"bg": "Включете поне един език.", "en": "Turn on at least one language."},
}


def system_language():
    """bg when the Windows display language is Bulgarian, otherwise en."""
    try:
        return "bg" if ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF == 0x02 else "en"
    except (AttributeError, OSError):
        return "en"


def resolve_language(setting):
    return setting if setting in ("bg", "en") else system_language()


def message(code, lang, **args):
    """(text, detail) of an event code in a language."""
    text, detail = MESSAGES.get(code, {}).get(lang, (code, ""))
    args = collections.defaultdict(str, args)
    if "language" in args:
        args["language"] = LANGUAGE_NAMES[lang].get(args["language"], args["language"])
    try:
        return text.format_map(args), detail.format_map(args)
    except (ValueError, IndexError):
        return text, detail


RATE = 16000
BLOCK = 4000
CODEX_PROCESS = "chatgpt.exe"
CODEX_MIC_KEY = (r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager"
                 r"\ConsentStore\microphone\OpenAI.Codex_2p2nqsd0c76g0")
DICTATE_BUTTON = "Dictate"
STOP_DICTATION_BUTTON = "Stop dictation"  # present while dictation is running; inserts the text
SEND_DICTATION_BUTTON = "Transcribe and send"  # ends dictation and sends the text to the agent
# ChatGPT Classic (package OpenAI.ChatGPT-Desktop): buttons of its message box, found through UI Automation.
CLASSIC_PROCESS = "chatgpt classic.exe"
CLASSIC_APP = r"shell:AppsFolder\OpenAI.ChatGPT-Desktop_2p2nqsd0c76g0!ChatGPT"
CLASSIC_VOICE_BUTTON = "Start Voice"
CLASSIC_END_VOICE_BUTTON = "End Voice"
CLASSIC_CANCEL_LOADING_BUTTON = "Cancel loading"  # in place of End Voice while the voice conversation starts (about 10 s)
CLASSIC_DICTATE_BUTTON = "Start dictation"
CLASSIC_SUBMIT_DICTATION_BUTTON = "Submit dictation"  # ends dictation and leaves the text in the message box
CLASSIC_CANCEL_DICTATION_BUTTON = "Cancel dictation"  # present while dictation is running
CLASSIC_START_S = 15  # how long to wait for ChatGPT Classic to open its message box
MIC_RETRY_S = 10
CHAT_WAIT_S = 1.0  # a bare wake word waits this long in case another language heard a full command
BUSY_MAX_S = 300  # after this long the silence rule applies again, in case a turn never finishes

KEYUP = 0x0002
user32 = ctypes.windll.user32


def setup_logging():
    os.makedirs(DATA_DIR, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(LOG_PATH, maxBytes=1_000_000, backupCount=3,
                                                   encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)


def _clean_words(value):
    if not isinstance(value, list) or not all(isinstance(w, str) for w in value):
        return None
    return list(dict.fromkeys(" ".join(w.lower().split()) for w in value if w.strip()))


def _word_error(key, words, code, known_word, msg):
    """The message for the first problem in one word list, or None. Only the wake word lists may hold phrases."""
    limit = MAX_PHRASE_WORDS if key in PHRASE_LISTS else 1
    long = ", ".join(w for w in words if len(w.split()) > limit)
    if long:
        return msg("too_long", n=limit, words=long) if limit > 1 else msg("one_word", words=long)
    unknown = [t for w in words for t in w.split() if known_word and not known_word(code, t)]
    return msg("unknown", words=", ".join(dict.fromkeys(unknown))) if unknown else None


def _validate_languages(value, known_word, msg, errors):
    """Validate the per-language word lists; known_word(language, word) checks the speech model."""
    langs = {}
    if not isinstance(value, dict):
        errors["languages"] = msg("type")
        value = {}
    for code, default in DEFAULTS["languages"].items():
        entry = value.get(code, default)
        clean = {k: list(v) if isinstance(v, list) else v for k, v in default.items()}
        if not isinstance(entry, dict):
            errors[f"languages.{code}"] = msg("type")
            langs[code] = clean
            continue
        if "enabled" in entry:
            if isinstance(entry["enabled"], bool):
                clean["enabled"] = entry["enabled"]
            else:
                errors[f"languages.{code}.enabled"] = msg("type")
        for key in WORD_LISTS:
            if key not in entry:
                continue
            path = f"languages.{code}.{key}"
            words = _clean_words(entry[key])
            if words is None:
                errors[path] = msg("list")
            elif key == "wake_words" and not words:
                errors[path] = msg("empty")
            elif problem := _word_error(key, words, code, known_word, msg):
                errors[path] = problem
            else:
                clean[key] = words
        seen = set()
        for key in COMMAND_LISTS:
            path = f"languages.{code}.{key}"
            if seen & set(clean[key]) and path not in errors:
                errors[path] = msg("overlap")
            seen |= set(clean[key])
        langs[code] = clean
    if not any(entry["enabled"] for entry in langs.values()):
        errors["languages"] = msg("no_language")
    return langs


def validate_settings(raw, known_word=None, lang="bg"):
    """Return (settings, errors). Unknown keys are dropped; errors maps a key (or languages.<code>.<list>) to a message."""
    settings, errors = json.loads(json.dumps(DEFAULTS)), {}
    msg = lambda code, **a: ERRORS[code][lang].format(**a)  # noqa: E731
    for key, value in raw.items():
        if key not in DEFAULTS:
            continue
        default = DEFAULTS[key]
        if key == "languages":
            settings[key] = _validate_languages(value, known_word, msg, errors)
            continue
        if key in LIMITS:
            lo, hi = LIMITS[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not lo <= value <= hi:
                errors[key] = msg("range", lo=lo, hi=hi)
                continue
        elif (key == "theme" and value not in THEMES) or (key == "language" and value not in LANGUAGES):
            errors[key] = msg("choice")
            continue
        elif type(value) is not type(default):
            errors[key] = msg("type")
            continue
        settings[key] = value
    return settings, errors


def migrate_settings(raw):
    """Move the v0.3 single-language word lists into languages.bg."""
    if not any(k in raw for k in OLD_WORD_KEYS):
        return raw
    raw = dict(raw)
    if "languages" not in raw:
        bg = json.loads(json.dumps(DEFAULTS["languages"]["bg"]))
        for old, new in (("wake_words", "wake_words"), ("stop_words", "stop_words"), ("decoys", "decoys")):
            if isinstance(raw.get(old), list):
                bg[new] = raw[old]
        if isinstance(raw.get("dictate_words"), list):
            if raw.get("dictation_send", True):
                bg["send_words"] = raw["dictate_words"]
            else:
                bg["draft_words"], bg["send_words"] = raw["dictate_words"], []
        raw["languages"] = {"bg": bg, "en": DEFAULTS["languages"]["en"]}
    for key in OLD_WORD_KEYS:
        raw.pop(key, None)
    return raw


def load_settings(path=SETTINGS_PATH, env=os.environ):
    """Defaults, then settings.json (created on first run, migrated from v0.3), then environment variables."""
    stored = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            try:
                stored = json.load(f)
            except ValueError as e:
                raise ValueError(f"Невалиден файл / Invalid file {path}: {e}") from e
    migrated = migrate_settings(stored)
    settings, errors = validate_settings(migrated)
    if not os.path.exists(path) or migrated is not stored:
        save_settings(settings, path)
    for key in errors:  # a bad hand edit falls back to the default for that key only
        logging.warning("settings: %s: %s -> default", key, errors[key])
    for key, var in ENV_OVERRIDES.items():
        if env.get(var):
            settings[key] = float(env[var])
    return settings


def save_settings(settings, path=SETTINGS_PATH):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


class EventLog:
    """The last events for the window, mirrored to events.jsonl. Never holds audio or dictated text."""

    def __init__(self, path=EVENTS_PATH, size=1000):
        self.path, self.size = path, size
        self.items = collections.deque(maxlen=size)
        self.lock = threading.Lock()
        self.next_id = 1
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                for line in f.readlines()[-size:]:
                    try:
                        self.items.append(json.loads(line))
                    except ValueError:
                        pass
            if self.items:
                self.next_id = self.items[-1]["id"] + 1

    def add(self, kind, code, **args):
        with self.lock:
            event = {"id": self.next_id, "time": time.strftime("%Y-%m-%dT%H:%M:%S"), "kind": kind,
                     "code": code, "args": args}
            self.next_id += 1
            self.items.append(event)
            try:
                os.makedirs(os.path.dirname(self.path), exist_ok=True)
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(event, ensure_ascii=False) + "\n")
                if self.next_id % self.size == 0:  # keep the file about as long as the buffer
                    with open(self.path, "w", encoding="utf-8") as f:
                        f.writelines(json.dumps(e, ensure_ascii=False) + "\n" for e in self.items)
            except OSError:
                logging.exception("events file")
        logging.info("%s: %s %s", kind, *message(code, "en", **args))
        return event

    def after(self, event_id=0, lang=None):
        """Events newer than event_id; with lang, each gets its text and detail in that language."""
        with self.lock:
            events = [e for e in self.items if e["id"] > event_id]
        if lang:
            events = [{**e, **dict(zip(("text", "detail"), message(e.get("code", ""), lang, **e.get("args", {}))))}
                      if "code" in e else e for e in events]
        return events


def suggest_threshold(quiet_levels, speech_levels):
    """A speech threshold a third of the way from loud silence to typical speech."""
    quiet = float(np.percentile(quiet_levels, 95))
    speech = float(np.percentile(speech_levels, 50))
    if speech <= quiet * 1.5:
        return None  # no clear difference between the two recordings
    return int(round(quiet + (speech - quiet) / 3))


def window_rect(area_x, area_y, area_width, area_height, want=(880, 600)):
    """Where the window opens, in logical pixels: the wanted size, but at most 90% of the work area (the screen
    without the taskbar), centered in it. Returns (x, y, width, height)."""
    width, height = min(want[0], area_width * 90 // 100), min(want[1], area_height * 90 // 100)
    return area_x + (area_width - width) // 2, area_y + (area_height - height) // 2, width, height


# The only addresses the window may open in the browser (About screen).
ABOUT_LINKS = ("https://ivanyosifov.com", "https://github.com/id-yo/codex-hark")


def about_link(url):
    """Is this one of the project's own addresses? Case and a trailing slash do not matter."""
    return isinstance(url, str) and url.rstrip("/").lower() in ABOUT_LINKS


def input_devices():
    """Microphones of the default host API (MME) by name."""
    try:
        api = sd.default.hostapi
        return sorted({d["name"] for d in sd.query_devices()
                       if d["max_input_channels"] > 0 and d["hostapi"] == api})
    except Exception:
        logging.exception("listing microphones")
        return []


def models_dir():
    return os.path.join(DATA_DIR, "models")


def model_dir(lang="bg"):
    """The model of a language: bundled in the exe, next to it, in the project folder or downloaded."""
    name = MODELS[lang]["name"]
    bases = [getattr(sys, "_MEIPASS", None),
             os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else None, HERE, models_dir()]
    for base in filter(None, bases):
        path = os.path.join(base, name)
        if os.path.isdir(os.path.join(path, "am")):
            return path
    return None


def download_model(lang, progress=None):
    """Download and unpack a language model into %APPDATA%\\CodexHark\\models after checking its SHA256."""
    info = MODELS[lang]
    folder = models_dir()
    os.makedirs(folder, exist_ok=True)
    part = os.path.join(folder, info["name"] + ".zip.part")
    digest, done = hashlib.sha256(), 0
    try:
        with urllib.request.urlopen(MODEL_URL.format(name=info["name"]), timeout=30) as response, open(part, "wb") as f:
            total = int(response.headers.get("Content-Length") or 0)
            while chunk := response.read(1 << 16):
                f.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
        if digest.hexdigest().upper() != info["sha256"]:
            raise ValueError("SHA256 mismatch")
        with zipfile.ZipFile(part) as z:
            z.extractall(folder)
    finally:
        if os.path.exists(part):
            os.remove(part)
    return model_dir(lang)


def acquire_single_instance():
    """Return False if another listener (exe or script) already runs."""
    ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\CodexHark")
    return ctypes.windll.kernel32.GetLastError() != 183


# Codex has no default key for these commands on Windows, so Hark checks that they are set (keybindings.json).
CODEX_KEYS = {"realtimeVoice": "Alt+Z", "globalDictationHold": "Alt+X"}
MODIFIER_CODES = {"alt": 0x12, "option": 0x12, "ctrl": 0x11, "control": 0x11, "commandorcontrol": 0x11,
                  "cmdorctrl": 0x11, "shift": 0x10, "win": 0x5B, "meta": 0x5B, "super": 0x5B}


def keybindings_path():
    """Codex's keybindings.json: [{"command": "realtimeVoice", "key": "Alt+Z"}, ...]."""
    home = os.environ.get("CODEX_HOME") or os.path.join(os.path.expanduser("~"), ".codex")
    return os.path.join(home, "keybindings.json")


def check_codex_keys(path=None, fix=False):
    """Check that Codex has a key for voice chat and dictation; with fix, add the ones that are missing.

    Returns {"status", "path", "keys", "added", "conflicts"}. status: ok, missing (not fixed), added,
    conflict (a default key is used by another command), no_codex, invalid (left untouched) or error.
    Keys the user chose are never replaced, and the other entries of the file stay as they are.
    """
    path = path or keybindings_path()
    result = {"status": "ok", "path": path, "keys": {}, "added": [], "conflicts": {}}
    if not os.path.isdir(os.path.dirname(path)):
        return {**result, "status": "no_codex"}
    entries = []
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
            entries = json.loads(text) if text.strip() else []
            if not isinstance(entries, list) or not all(isinstance(e, dict) and isinstance(e.get("command"), str) for e in entries):
                raise ValueError("not a list of commands")
        except (OSError, ValueError):
            return {**result, "status": "invalid"}
    keys = {c: next((e["key"] for e in entries if e["command"] == c and isinstance(e.get("key"), str) and e["key"]), None)
            for c in CODEX_KEYS}
    taken = {e["key"].lower(): e["command"] for e in entries if isinstance(e.get("key"), str)}
    conflicts = {c: taken[CODEX_KEYS[c].lower()] for c in CODEX_KEYS
                 if not keys[c] and taken.get(CODEX_KEYS[c].lower(), c) != c}
    missing = [c for c in CODEX_KEYS if not keys[c] and c not in conflicts]
    result.update(keys=keys, conflicts=conflicts)
    if not fix or not missing:
        result["status"] = "conflict" if conflicts else "missing" if missing else "ok"
        return result
    for command in missing:
        slot = next((e for e in entries if e["command"] == command and not e.get("key")), None)
        if slot is not None:
            slot["key"] = CODEX_KEYS[command]
        else:
            entries.append({"command": command, "key": CODEX_KEYS[command]})
        keys[command] = CODEX_KEYS[command]
    try:
        if os.path.exists(path):
            shutil.copyfile(path, path + ".hark-backup")
        with open(path + ".hark-tmp", "w", encoding="utf-8") as f:
            f.write(json.dumps(entries, indent=2) + "\n")
        os.replace(path + ".hark-tmp", path)
    except OSError as e:
        return {**result, "status": "error", "error": str(e), "keys": {c: None for c in CODEX_KEYS}}
    return {**result, "status": "conflict" if conflicts else "added", "added": missing}


def codex_hotkeys():
    """The keys Codex has for voice chat and dictation now; the ones Hark sets when a key is not there."""
    keys = check_codex_keys()["keys"]
    return {"voice": keys.get("realtimeVoice") or CODEX_KEYS["realtimeVoice"],
            "dictation": keys.get("globalDictationHold") or CODEX_KEYS["globalDictationHold"]}


def parse_hotkey(spec):
    """Virtual-key codes of a key such as "Alt+Z", "Ctrl+Shift+V" or "F9" (modifiers first); None if unknown."""
    codes = []
    parts = [p.strip() for p in str(spec).split("+")]
    for part in parts[:-1]:
        if part.lower() not in MODIFIER_CODES:
            return None
        codes.append(MODIFIER_CODES[part.lower()])
    key = parts[-1]
    if len(key) == 1 and key.isascii() and key.isalnum():
        codes.append(ord(key.upper()))
    elif re.fullmatch(r"[Ff](\d{1,2})", key) and 1 <= int(key[1:]) <= 24:
        codes.append(0x70 + int(key[1:]) - 1)
    else:
        return None
    return codes


def press_voice_chat():
    """Press Codex's voice chat key (Alt+Z unless Codex has another one)."""
    codes = parse_hotkey(codex_hotkeys()["voice"])
    if codes is None:
        logging.warning("cannot press the voice chat key of Codex; using Alt+Z")
        codes = parse_hotkey(CODEX_KEYS["realtimeVoice"])
    for code in codes:
        user32.keybd_event(code, 0, 0, 0)
    for code in reversed(codes):
        user32.keybd_event(code, 0, KEYUP, 0)


def beep():
    threading.Thread(target=lambda: ctypes.windll.kernel32.Beep(880, 120), daemon=True).start()


def voice_chat_active():
    """Windows marks an app's microphone use with LastUsedTimeStop == 0 while it is open."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CODEX_MIC_KEY) as key:
            return winreg.QueryValueEx(key, "LastUsedTimeStop")[0] == 0
    except OSError:
        return False


def codex_talking(peak):
    for s in AudioUtilities.GetAllSessions():
        if s.Process and s.Process.name().lower() == CODEX_PROCESS:
            if s._ctl.QueryInterface(IAudioMeterInformation).GetPeakValue() > peak:
                return True
    return False


def app_windows(process):
    """Visible top-level windows of the program with this file name (lower case)."""
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def collect(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            try:
                if psutil.Process(pid.value).name().lower() == process:
                    found.append(hwnd)
            except psutil.Error:
                pass
        return True

    user32.EnumWindows(collect, 0)
    return found


def codex_windows():
    return app_windows(CODEX_PROCESS)


def heard(result_json, words, min_conf, key="wake_words"):
    """Return (wake word or phrase, the word after it, confidence) for a final Vosk result of one language.

    A wake phrase such as "hey jarvis" must be heard as all of its words in a row; its confidence is the
    mean of theirs. Longer phrases win over shorter ones that start at the same word.
    """
    found = json.loads(result_json).get("result", [])
    phrases = sorted((p.split() for p in words[key]), key=len, reverse=True)
    for i in range(len(found)):
        for phrase in phrases:
            part = found[i:i + len(phrase)]
            if [w["word"] for w in part] != phrase:
                continue
            conf = sum(w["conf"] for w in part) / len(part)
            if conf >= min_conf:
                end = i + len(phrase)
                return " ".join(phrase), found[end]["word"] if end < len(found) else "", conf
    return "", "", 0.0


def codex_history_db():
    """Codex Desktop's thread history database (thread_history_<n>.sqlite in CODEX_HOME)."""
    home = os.environ.get("CODEX_HOME") or os.path.join(os.path.expanduser("~"), ".codex")
    found = glob.glob(os.path.join(home, "thread_history_*.sqlite"))
    return max(found, key=os.path.getmtime) if found else None


# The newest voice chat session that has not closed, and whether its agent has an unfinished turn.
BUSY_SQL = """
select exists(select 1 from thread_turns t where t.thread_id = s.thread_id and t.status = 'inProgress')
from (select thread_id, max(created_at_ms) as started from thread_realtime_items
      where item_type = 'realtime_session_started' and created_at_ms > ?
      group by thread_id order by started desc limit 1) s
where not exists (select 1 from thread_realtime_items c where c.thread_id = s.thread_id
                  and c.item_type = 'realtime_session_closed' and c.created_at_ms >= s.started)
"""


def codex_busy(db=None):
    """True while Codex works on the open voice chat (search, tools, thinking); None if unknown."""
    db = db or codex_history_db()
    if not db:
        return None
    try:
        con = sqlite3.connect("file:" + db.replace("\\", "/") + "?mode=ro", uri=True, timeout=1)
        try:
            since = (time.time() - 6 * 3600) * 1000
            row = con.execute(BUSY_SQL, (since,)).fetchone()
            return bool(row and row[0])
        finally:
            con.close()
    except sqlite3.Error:
        return None


def grammar(words):
    """Vosk grammar of one language: every command word or phrase plus [unk] for everything else."""
    words = [w for key in WORD_LISTS for w in words[key]] + ["[unk]"]
    return json.dumps(list(dict.fromkeys(words)), ensure_ascii=False)


def model_knows(model, word):
    """Is the word in the vocabulary of the loaded Vosk model? Vosk silently ignores words that are not."""
    return vosk._c.vosk_model_find_word(model._handle, word.encode("utf-8")) >= 0


def unknown_words(model, words):
    """The words of one language's lists (phrases split into words) that the model does not know."""
    return list(dict.fromkeys(t for key in WORD_LISTS for w in words[key] for t in w.split()
                              if not model_knows(model, t)))


class Listener:
    """The wake word loop. run() blocks until stop(); pause and resume through self.paused."""

    def __init__(self, settings, on_state=None, on_problem=None, paused=None, events=None):
        self.s = settings
        self.on_state = on_state or (lambda state: None)
        self.on_problem = on_problem or (lambda key, **args: None)
        self.paused = paused or threading.Event()
        self.events = events or EventLog(os.devnull)
        self.stopped = threading.Event()
        self.state = None
        self.level = 0.0  # RMS of the last microphone block
        self._reset_busy()
        self.models = {}  # language -> loaded Vosk model
        self._send = True  # the dictation in progress is sent (True) or left as a draft (False)
        self._classic = False  # the dictation in progress is in ChatGPT Classic, not in Codex
        self._uia = None

    def stop(self):
        self.stopped.set()

    def _set(self, state):
        if state != self.state:
            self.state = state
            self.on_state(state)

    def _find_button(self, name, tries=1, process=CODEX_PROCESS, button=True):
        """Find a button of Codex (or another Chromium app) by its accessible name; Chromium builds the tree on first use."""
        if self._uia is None:
            self._uia = comtypes.client.CreateObject(CUIAutomation, interface=IUIAutomation)
        uia = self._uia
        cond = uia.CreatePropertyCondition(UIA_NamePropertyId, name)
        if button:
            cond = uia.CreateAndCondition(cond, uia.CreatePropertyCondition(UIA_ControlTypePropertyId, UIA_ButtonControlTypeId))
        for attempt in range(tries):
            for hwnd in app_windows(process):
                try:
                    button = uia.ElementFromHandle(hwnd).FindFirst(TreeScope_Descendants, cond)
                except COMError:
                    continue
                if button:
                    return button
            if attempt + 1 < tries:
                time.sleep(0.3)
        return None

    def _click(self, name, process=CODEX_PROCESS):
        button = self._find_button(name, tries=3, process=process)
        if not button:
            return False
        button.GetCurrentPattern(UIA_InvokePatternId).QueryInterface(IUIAutomationInvokePattern).Invoke()
        return True

    def _open_classic(self):
        """Make sure ChatGPT Classic runs with its message box showing; True when it does."""
        if self._find_button(CLASSIC_VOICE_BUTTON, process=CLASSIC_PROCESS):
            return True
        if not app_windows(CLASSIC_PROCESS):
            subprocess.Popen(["explorer.exe", CLASSIC_APP])
        deadline = time.monotonic() + CLASSIC_START_S
        while time.monotonic() < deadline and not self.stopped.is_set():
            if self._find_button(CLASSIC_VOICE_BUTTON, process=CLASSIC_PROCESS):
                return True
            if self._find_button("Meet the new ChatGPT", process=CLASSIC_PROCESS, button=False):
                self._click("Close", CLASSIC_PROCESS)  # an offer that covers the message box
            time.sleep(0.5)
        return False

    def _chatgpt(self, words, wake, following, conf, can_start):
        """A chat command: a voice conversation, dictation or the end of the conversation in ChatGPT Classic.
        Returns "dictation" or "chat" for what it started, None when it started nothing."""
        ev = self.events
        phrase = f"{wake}, {following}" if following else wake
        if following in words["stop_words"]:
            if any(self._click(b, CLASSIC_PROCESS) for b in (CLASSIC_END_VOICE_BUTTON, CLASSIC_CANCEL_LOADING_BUTTON)):
                ev.add("chat", "chatgpt_stopped", phrase=phrase, conf=f"{conf:.2f}")
            return None
        if not can_start or any(self._find_button(b, process=CLASSIC_PROCESS)
                                for b in (CLASSIC_END_VOICE_BUTTON, CLASSIC_CANCEL_LOADING_BUTTON)):
            return None  # a conversation is already running
        dictate = following in words["send_words"] + words["draft_words"] and self.s["dictation_enabled"]
        button = CLASSIC_DICTATE_BUTTON if dictate else CLASSIC_VOICE_BUTTON
        if not self._open_classic():
            ev.add("error", "chatgpt_missing")
            self.on_problem("chatgpt")
            return None
        if self.s["beep"]:
            beep()
        if not self._click(button, CLASSIC_PROCESS):
            ev.add("error", "button_missing", button=button)
            return None
        ev.add("dictation" if dictate else "chat", "wake_chatgpt_dictation" if dictate else "wake_chatgpt",
               phrase=phrase, conf=f"{conf:.2f}")
        self._classic = dictate
        return "dictation" if dictate else "chat"

    def run(self):
        comtypes.CoInitialize()
        try:
            SetLogLevel(-1)
            s = self.s
            recs = []
            for lang, words in s["languages"].items():
                path = model_dir(lang) if words["enabled"] else None
                if path:
                    self.models[lang] = Model(path)
                    if unknown := unknown_words(self.models[lang], words):
                        logging.warning("%s: the model does not know %s; these words are ignored", lang, ", ".join(unknown))
                        self.events.add("error", "words_unknown", language=lang, words=", ".join(unknown))
                        self.on_problem("words", language=lang, words=", ".join(unknown))
                    rec = KaldiRecognizer(self.models[lang], RATE, grammar(words))
                    rec.SetWords(True)
                    recs.append((lang, rec))
            if not recs:  # every enabled language is still downloading; the app restarts us when ready
                logging.warning("no speech model available")
                self._set("error")
                self.stopped.wait()
                return
            logging.info("listening in %s (min conf %.2f, idle %ds, dictation idle %ds)",
                         ", ".join(f"{lang}: {'/'.join(s['languages'][lang]['wake_words'])}" for lang, _ in recs),
                         s["min_conf"], s["idle_seconds"], s["dictation_idle_seconds"])
            while not self.stopped.is_set():
                if self.paused.is_set():
                    self.level = 0.0
                    self._set("paused")
                    self.stopped.wait(0.2)
                    continue
                try:
                    self._listen(recs)
                except (sd.PortAudioError, ValueError) as e:
                    self.level = 0.0
                    self._set("error")
                    self.events.add("error", "mic_error", error=str(e))
                    self.on_problem("mic")
                    self.stopped.wait(MIC_RETRY_S)
        finally:
            self._uia = None
            comtypes.CoUninitialize()

    def _check_busy(self, now):
        """Is Codex working on the voice chat? Read at most once a second; capped at BUSY_MAX_S."""
        if now - self._busy_checked >= 1:
            self._busy_checked = now
            busy = bool(codex_busy())
            if busy and not self.busy:
                self._busy_since = now
                self.events.add("chat", "busy_start")
            elif self.busy and not busy:
                self.events.add("chat", "busy_end")
            self.busy = busy
        if self.busy and now - self._busy_since > BUSY_MAX_S:
            if not self._busy_capped:
                self._busy_capped = True
                self.events.add("chat", "busy_limit", minutes=f"{BUSY_MAX_S // 60}")
            return False
        return self.busy

    def _reset_busy(self):
        self.busy, self._busy_checked, self._busy_since, self._busy_capped = False, 0.0, 0.0, False

    def _listen(self, recs):
        """Listen until paused or stopped. Raises sd.PortAudioError when the mic is unavailable."""
        s = self.s

        def reset():
            for _, r in recs:
                r.Reset()

        def recognize(data):
            """Every wake phrase heard in this block, per language and target: [(words, wake, following, conf, target)]."""
            hits = []
            for lang, r in recs:
                if r.AcceptWaveform(data):
                    words, result = s["languages"][lang], r.Result()
                    for target, key in (("codex", "wake_words"), ("chatgpt", "chat_words")):
                        wake, following, conf = heard(result, words, s["min_conf"], key)
                        if wake and (target == "codex" or s["chatgpt_enabled"]):
                            hits.append((words, wake, following, conf, target))
            return hits

        def is_command(hit):
            words, following = hit[0], hit[2]
            return following in words["send_words"] + words["draft_words"] + words["stop_words"]

        pending = None  # (time, hit): a bare wake word waiting for a fuller command from another language

        ev = self.events
        last = 0.0
        # None, "chat" (voice chat), "dictation" (started by us) or "manual" (dictation started by hand).
        mode = None
        last_sound = last_check = ignore_until = 0.0
        self._reset_busy()
        device = s["mic_device"] or None
        with sd.RawInputStream(samplerate=RATE, channels=1, dtype="int16", blocksize=BLOCK,
                               device=device) as mic:
            self._set("listening")
            while not self.stopped.is_set() and not self.paused.is_set():
                data, _ = mic.read(BLOCK)
                now = time.monotonic()
                rms = float(np.sqrt(np.mean(np.frombuffer(data, dtype=np.int16).astype(np.float32) ** 2)))
                self.level = rms
                if mode == "dictation":
                    reset()
                    if rms > s["speech_rms"]:
                        last_sound = now
                    if now - last_sound > s["dictation_idle_seconds"]:
                        button = (CLASSIC_SUBMIT_DICTATION_BUTTON if self._classic
                                  else SEND_DICTATION_BUTTON if self._send else STOP_DICTATION_BUTTON)
                        if self._click(button, CLASSIC_PROCESS if self._classic else CODEX_PROCESS):
                            kind = "sent" if self._send else "inserted"
                            ev.add(kind, kind, seconds=f"{s['dictation_idle_seconds']:g}")
                        else:
                            ev.add("error", "button_missing", button=button)
                    elif now - last_check < 2:
                        continue
                    else:
                        last_check = now
                        if self._find_button(CLASSIC_CANCEL_DICTATION_BUTTON if self._classic else STOP_DICTATION_BUTTON,
                                             process=CLASSIC_PROCESS if self._classic else CODEX_PROCESS):
                            continue
                        ev.add("dictation", "dictation_stopped")
                    mode, last, ignore_until = None, now, now + 3
                    self._set("listening")
                    continue
                if now < ignore_until:
                    reset()
                    continue
                if voice_chat_active():
                    if mode is None:
                        mode, last_sound = ("manual" if self._find_button(STOP_DICTATION_BUTTON) else "chat"), now
                        if mode == "chat":
                            ev.add("chat", "chat_opened")
                        else:
                            ev.add("dictation", "manual_dictation")
                        self._set("chat" if mode == "chat" else "dictation")
                        reset()
                    if mode != "chat":
                        reset()
                        continue
                    # During a conversation only the stop phrase is acted on.
                    hits = recognize(bytes(data)) if s["stop_enabled"] else []
                    hit = next((h for h in hits if h[4] == "codex" and h[2] in h[0]["stop_words"]), None)
                    if hit:
                        _, wake, following, conf = hit
                        ev.add("chat", "stop_phrase", phrase=f"{wake}, {following}", conf=f"{conf:.2f}")
                        press_voice_chat()
                        last_sound = now
                        ignore_until = now + 2
                        continue
                    if self._check_busy(now) or rms > s["speech_rms"] or codex_talking(s["codex_audio_peak"]):
                        last_sound = now
                    elif s["idle_close"] and now - last_sound > s["idle_seconds"]:
                        ev.add("chat", "chat_closing", seconds=f"{s['idle_seconds']:g}")
                        press_voice_chat()
                        last_sound = now  # do not press again while Codex closes the chat
                    continue
                if mode is not None:
                    ev.add("chat" if mode == "chat" else "dictation",
                           "chat_closed" if mode == "chat" else "manual_dictation_ended")
                    mode, pending = None, None
                    self._reset_busy()
                    reset()
                    last = now  # short pause before the wake word works again
                    self._set("listening")
                hits = recognize(bytes(data))
                command = next(filter(is_command, hits), None)
                if command:
                    hit, pending = command, None
                elif hits:
                    pending = pending or (now, hits[0])
                    continue
                elif pending and now - pending[0] >= CHAT_WAIT_S:
                    hit, pending = pending[1], None
                else:
                    continue
                words, wake, following, conf, target = hit
                if target == "chatgpt":
                    started = self._chatgpt(words, wake, following, conf, can_start=now - last > s["cooldown_seconds"])
                    if started:
                        last = now
                        if started == "dictation":
                            mode, last_sound, last_check = "dictation", now, now
                            self._set("dictation")
                    continue
                if following in words["stop_words"] or now - last <= s["cooldown_seconds"]:
                    continue
                send = following in words["send_words"]
                dictate = (send or following in words["draft_words"]) and s["dictation_enabled"]
                if not dictate and not s["chat_enabled"]:
                    continue
                last = now
                if s["beep"]:
                    beep()
                if not dictate:
                    ev.add("chat", "wake_chat", phrase=wake, conf=f"{conf:.2f}")
                    press_voice_chat()
                elif self._click(DICTATE_BUTTON):
                    ev.add("dictation", "wake_dictation" if send else "wake_draft",
                           phrase=f"{wake}, {following}", conf=f"{conf:.2f}")
                    self._send, self._classic = send, False
                    mode, last_sound, last_check = "dictation", now, now
                    self._set("dictation")
                else:
                    ev.add("error", "button_missing", button=DICTATE_BUTTON)
                    self.on_problem("codex")
            reset()



def main():
    setup_logging()
    if not acquire_single_instance():
        sys.exit(0)
    try:
        Listener(load_settings(), events=EventLog()).run()
    except Exception:
        logging.exception("crashed")
        raise


if __name__ == "__main__":
    main()

