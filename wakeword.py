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
import sys
import threading
import time
import urllib.parse
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

__version__ = "0.14.2"

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
MODEL_NAME = "vosk-model-small-en-us-0.15"  # bundled in the exe; every other language is downloaded
HERE = os.path.dirname(os.path.abspath(__file__))

# Recognition languages: a small Vosk model each; commands are the wake word plus one word after it.
MODELS = {
    # English is the base language: bundled in the exe, it can be switched off but not removed.
    "en": {"name": "vosk-model-small-en-us-0.15", "size_mb": 41,
           "sha256": "30F26242C4EB449F948E42CB302DD7A686CB29A3423A8367F99FF41780942498"},
    # Languages the user can add in Settings; all small Vosk models under Apache-2.0.
    # No Bulgarian Vosk model exists; the Russian one hears "Кодекс", "пиши", "стоп" and English "Codex".
    "bg": {"name": "vosk-model-small-ru-0.22", "size_mb": 45,
           "sha256": "961D5FF98A17F4AA6DE69864D0AA71FA5BAC682301D2B5D17A3F24C5C99A46D4"},
    "de": {"name": "vosk-model-small-de-0.15", "size_mb": 45,
           "sha256": "B7E53C90B1F0A38456F4CD62B366ECD58803CD97CD42B06438E2C131713D5E43"},
    "fr": {"name": "vosk-model-small-fr-0.22", "size_mb": 41,
           "sha256": "CABF6180E177EB9B3A9A9D43A437BD5E549F3A7D09525E5D69A3FED787BE12AD"},
    "es": {"name": "vosk-model-small-es-0.42", "size_mb": 39,
           "sha256": "09B239888F633EF2F0B4E09736E3D9936ACFD810BC65D53FAD45261762C6511F"},
    "it": {"name": "vosk-model-small-it-0.22", "size_mb": 48,
           "sha256": "9EC65E75861D1C6C2E457CCCD932705340DCDF233F5B239F00733B4DE0BF3267"},
    "pl": {"name": "vosk-model-small-pl-0.22", "size_mb": 50,
           "sha256": "C4CD16498EA544F446F9E9A55CBD602B71CFE5A2B6F2B0834D81E1B6FCE15F0D"},
    "nl": {"name": "vosk-model-small-nl-0.22", "size_mb": 39,
           "sha256": "039811C3B829DE64E4F123A9F684A53784005B212A346AC0B899DC7EFCE2ED0A"},
    "uk": {"name": "vosk-model-small-uk-v3-nano", "size_mb": 74,
           "sha256": "D6B50BE0A2D20F891720F3A83C98290BB2D396FD666142DBF716E8AD302F8233"},
}
MODEL_URL = "https://alphacephei.com/vosk/models/{name}.zip"
# Name of each recognition language: LANGUAGE_NAMES[interface language][code].
LANGUAGE_NAMES = {
    "bg": {"bg": "български", "en": "английски", "de": "немски", "fr": "френски", "es": "испански", "it": "италиански",
           "pl": "полски", "nl": "нидерландски", "uk": "украински"},
    "en": {"bg": "Bulgarian", "en": "English", "de": "German", "fr": "French", "es": "Spanish", "it": "Italian",
           "pl": "Polish", "nl": "Dutch", "uk": "Ukrainian"},
}
# Starting words of an added language; every word is in the vocabulary of its model (checked 2026-10-09).
ADDED_LANGUAGES = {
    "bg": {
        # "кодекс" also matches English "Codex"; "кодекса" covers "Кодекс, отвори...".
        "wake_words": ["кодекс", "кодекса"],
        "send_words": ["пиши"],  # dictate, then send to the agent
        "draft_words": ["чернова"],  # dictate, then leave the text in the message box
        "stop_words": ["стоп", "край"],  # end a voice chat at once
        # Similar-sounding words give the recognizer somewhere else to put near misses.
        "decoys": ["код", "кода", "коды", "коде", "тест", "текст", "индекс", "кейс", "алекса"],
    },
    "de": {"wake_words": ["codex", "kodex"], "send_words": ["schreib"], "draft_words": ["entwurf"],
           "stop_words": ["stopp", "ende"], "decoys": ["code", "text", "test", "index", "kontext"]},
    "fr": {"wake_words": ["codex"], "send_words": ["écris"], "draft_words": ["brouillon"],
           "stop_words": ["stop", "fin"], "decoys": ["code", "codes", "texte", "contexte", "index"]},
    "es": {"wake_words": ["codex"], "send_words": ["escribe"], "draft_words": ["borrador"],
           "stop_words": ["alto", "stop"], "decoys": ["código", "texto", "contexto", "índice"]},
    "it": {"wake_words": ["codex"], "send_words": ["scrivi"], "draft_words": ["bozza"],
           "stop_words": ["stop", "basta"], "decoys": ["codice", "testo", "contesto", "indice"]},
    "pl": {"wake_words": ["kodeks", "codex"], "send_words": ["pisz"], "draft_words": ["szkic"],
           "stop_words": ["stop", "koniec"], "decoys": ["kod", "kody", "tekst", "test", "indeks"]},
    "nl": {"wake_words": ["codex"], "send_words": ["schrijf"], "draft_words": ["concept"],
           "stop_words": ["stop"], "decoys": ["code", "tekst", "test", "context"]},
    "uk": {"wake_words": ["кодекс"], "send_words": ["пиши"], "draft_words": ["чернетка"],
           "stop_words": ["стоп", "кінець"], "decoys": ["код", "текст", "тест", "індекс"]},
}

DEFAULTS = {
    "languages": {
        "en": {
            "enabled": True,
            "wake_words": ["codex"],
            "send_words": ["write"],
            "draft_words": ["draft"],
            "stop_words": ["stop"],
            "decoys": ["code", "codes", "coding", "text", "alexa", "context", "craft"],
        },
    },
    "stop_enabled": True,
    "idle_close": True,  # end a voice chat after idle_seconds of silence (never while Codex is working)
    "chat_enabled": True,
    "chat_target": "new",  # where a voice chat goes: a "new" chat each time, one Codex "thread" or one "project"
    "chat_thread": "",  # the Codex thread id for "thread"
    "chat_project": "",  # the project folder for "project"
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
    "update_check": True,  # look for a new release on GitHub after start and every UPDATE_INTERVAL_S
    "update_install": True,  # install a found release by itself (exe only), when no conversation is open
    "keys_checked": False,  # the first-run check of Codex's shortcuts has been done
}
# Allowed range of each number setting.
LIMITS = {"min_conf": (0.2, 0.95), "idle_seconds": (3, 120), "dictation_idle_seconds": (1, 30),
          "speech_rms": (20, 5000), "codex_audio_peak": (0.001, 0.5), "cooldown_seconds": (1, 60)}
WORD_LISTS = ("wake_words", "send_words", "draft_words", "stop_words", "decoys")
COMMAND_LISTS = WORD_LISTS[:4]  # a word may appear in only one of these per language
OLD_WORD_KEYS = ("wake_words", "dictate_words", "stop_words", "decoys", "dictation_send")
THEMES = ("system", "light", "dark")
CHAT_TARGETS = ("new", "thread", "project")
MAX_PHRASE_WORDS = 3  # a wake phrase such as "hey jarvis"; the other lists hold single words
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
    "update_available": {"bg": ("Има нова версия: {version}", "имате {current}"), "en": ("A new version is available: {version}", "you have {current}")},
    "update_installing": {"bg": ("Инсталира версия {version}", "Hark ще се рестартира"), "en": ("Installing version {version}", "Hark will restart")},
    "update_failed": {"bg": ("Обновяването не успя", "{error}"), "en": ("The update failed", "{error}")},
    "update_done": {"bg": ("Hark е обновен до {version}", "от {previous}"), "en": ("Hark was updated to {version}", "from {previous}")},
    "update_current": {"bg": ("Hark е последна версия", "{current}"), "en": ("Hark is up to date", "{current}")},
    "update_error": {"bg": ("Проверката за нова версия не успя", "{error}"), "en": ("The update check failed", "{error}")},
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
# Codex's own voice chat buttons. The voice chat key always starts a chat outside any project; these start it
# in the open chat ("Start voice chat") or as a new chat in the open project ("Start new voice chat").
VOICE_BUTTONS = {"thread": ("Start voice chat",), "project": ("Start new voice chat", "Start voice chat")}
END_VOICE_BUTTON = "End voice chat"
SEND_DICTATION_BUTTON = "Transcribe and send"  # ends dictation and sends the text to the agent
MIC_RETRY_S = 10
TARGET_WAIT_S = 1.5  # time Codex gets to open the chosen chat before the voice chat key
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
    """The message for the first problem in one word list, or None. Only wake_words may hold phrases."""
    limit = MAX_PHRASE_WORDS if key == "wake_words" else 1
    long = ", ".join(w for w in words if len(w.split()) > limit)
    if long:
        return msg("too_long", n=limit, words=long) if limit > 1 else msg("one_word", words=long)
    unknown = [t for w in words for t in w.split() if known_word and not known_word(code, t)]
    return msg("unknown", words=", ".join(dict.fromkeys(unknown))) if unknown else None


def language_defaults(code):
    """The words of a language before the user changes them; an added language starts switched on."""
    if code in DEFAULTS["languages"]:
        return DEFAULTS["languages"][code]
    return {"enabled": True, **ADDED_LANGUAGES[code]}


def _validate_languages(value, known_word, msg, errors):
    """Validate the per-language word lists; known_word(language, word) checks the speech model."""
    langs = {}
    if not isinstance(value, dict):
        errors["languages"] = msg("type")
        value = {}
    # English is always there; an added language (Bulgarian too) stays while it is in the settings.
    codes = list(DEFAULTS["languages"]) + [c for c in value if c in ADDED_LANGUAGES]
    for code in codes:
        default = language_defaults(code)
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
        elif ((key == "theme" and value not in THEMES) or (key == "language" and value not in LANGUAGES)
              or (key == "chat_target" and value not in CHAT_TARGETS)
              or (key == "chat_thread" and value and not THREAD_ID.fullmatch(str(value)))):
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
        bg = json.loads(json.dumps(language_defaults("bg")))
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
ABOUT_LINKS = ("https://ivanyosifov.com", "https://github.com/id-yo/codex-hark",
               "https://buymeacoffee.com/ivan.yosifov", "https://paypal.me/ivanyosifov")


def about_link(url):
    """Is this one of the project's own addresses (or one of its releases)? Case and a trailing slash do not matter."""
    return isinstance(url, str) and (url.rstrip("/").lower() in ABOUT_LINKS or bool(RELEASE_PAGE.fullmatch(url.lower())))


LATEST_RELEASE_API = "https://api.github.com/repos/ID-Yo/codex-hark/releases/latest"
RELEASE_PAGE = re.compile(r"https://github\.com/id-yo/codex-hark/releases/tag/v\d+(\.\d+){1,3}")
UPDATE_INTERVAL_S = 12 * 3600  # two checks a day
UPDATE_FIRST_DELAY_S = 60  # the first check, after start
RELEASE_ASSETS = "https://github.com/id-yo/codex-hark/releases/download/"
EXE_NAME = "CodexHark.exe"


def version_tuple(text):
    """ "v0.11.1" -> (0, 11, 1); None if it is not a version."""
    m = re.fullmatch(r"v?(\d+(?:\.\d+){1,3})", text.strip())
    return tuple(int(p) for p in m.group(1).split(".")) if m else None


def latest_release(timeout=15):
    """The newest public release: {"version": "0.12.0", "url": release page}. Raises OSError/ValueError on failure."""
    request = urllib.request.Request(LATEST_RELEASE_API, headers={
        "Accept": "application/vnd.github+json", "User-Agent": f"CodexHark/{__version__}"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))
    version = version_tuple(str(data.get("tag_name", "")))
    if version is None:
        raise ValueError(f"unexpected release tag {data.get('tag_name')!r}")
    url = str(data.get("html_url", ""))
    assets = {a.get("name"): str(a.get("browser_download_url", "")) for a in data.get("assets") or []}
    own = lambda u: u if u.lower().startswith(RELEASE_ASSETS) else ""  # noqa: E731
    return {"version": ".".join(map(str, version)), "url": url if RELEASE_PAGE.fullmatch(url.lower()) else "",
            "exe": own(assets.get(EXE_NAME, "")), "sums": own(assets.get("SHA256SUMS.txt", ""))}


def _fetch(url, timeout=60):
    request = urllib.request.Request(url, headers={"User-Agent": f"CodexHark/{__version__}"})
    return urllib.request.urlopen(request, timeout=timeout)


def download_update(release, folder):
    """Download the release exe into folder and check it against the release SHA256SUMS.txt. Returns its path.
    Raises OSError/ValueError; a file that does not match is deleted."""
    if not release.get("exe") or not release.get("sums"):
        raise ValueError("the release has no CodexHark.exe or SHA256SUMS.txt")
    with _fetch(release["sums"], 30) as response:
        sums = response.read().decode("utf-8", "replace")
    want = next((line.split()[0].lower() for line in sums.splitlines()
                 if len(line.split()) == 2 and line.split()[1].lstrip("*") == EXE_NAME), None)
    if not want or not re.fullmatch(r"[0-9a-f]{64}", want):
        raise ValueError("SHA256SUMS.txt has no hash for CodexHark.exe")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, EXE_NAME)
    digest = hashlib.sha256()
    with _fetch(release["exe"]) as response, open(path + ".part", "wb") as f:
        for chunk in iter(lambda: response.read(1 << 20), b""):
            digest.update(chunk)
            f.write(chunk)
    if digest.hexdigest() != want:
        os.remove(path + ".part")
        raise ValueError("the downloaded file does not match its SHA256")
    os.replace(path + ".part", path)
    return path


def install_update(new_exe, exe):
    """Put new_exe in place of the running exe. Windows lets a running exe be renamed, so it becomes exe.old
    (deleted on the next start); if the move fails the old exe is put back."""
    old = exe + ".old"
    if os.path.exists(old):
        os.remove(old)
    os.replace(exe, old)
    try:
        shutil.move(new_exe, exe)
    except OSError:
        os.replace(old, exe)
        raise


def remove_old_exe(exe):
    """Delete exe.old left by an update; it stays if the old process still holds it."""
    try:
        os.remove(exe + ".old")
    except OSError:
        pass


def update_status(latest, current=None):
    """ "new" if the release is newer than this build, otherwise "current"."""
    return "new" if version_tuple(latest) > version_tuple(current or __version__) else "current"


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


def model_dir(lang="en"):
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


_instance = None  # the single-instance mutex handle


def acquire_single_instance():
    """Return False if another listener (exe or script) already runs."""
    global _instance
    handle = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\CodexHark")
    if ctypes.windll.kernel32.GetLastError() == 183:
        ctypes.windll.kernel32.CloseHandle(handle)
        return False
    _instance = handle
    return True


def release_single_instance():
    """Let another instance start (the new version after an update)."""
    global _instance
    if _instance:
        ctypes.windll.kernel32.CloseHandle(_instance)
        _instance = None


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


def codex_windows():
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def collect(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            try:
                if psutil.Process(pid.value).name().lower() == CODEX_PROCESS:
                    found.append(hwnd)
            except psutil.Error:
                pass
        return True

    user32.EnumWindows(collect, 0)
    return found


def heard(result_json, words, min_conf):
    """Return (wake word or phrase, the word after it, confidence) for a final Vosk result of one language.

    A wake phrase such as "hey jarvis" must be heard as all of its words in a row; its confidence is the
    mean of theirs. Longer phrases win over shorter ones that start at the same word.
    """
    found = json.loads(result_json).get("result", [])
    phrases = sorted((p.split() for p in words["wake_words"]), key=len, reverse=True)
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


def codex_state_db():
    """Codex Desktop's thread and project list (state_<n>.sqlite in CODEX_HOME)."""
    home = os.environ.get("CODEX_HOME") or os.path.join(os.path.expanduser("~"), ".codex")
    found = glob.glob(os.path.join(home, "state_*.sqlite"))
    return max(found, key=os.path.getmtime) if found else None


THREAD_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
THREADS_SQL = """
select id, coalesce(nullif(name, ''), title), cwd from threads
where archived = 0 and source not like '%subagent%' and coalesce(nullif(name, ''), title, '') != ''
order by coalesce(recency_at_ms, updated_at_ms) desc limit 40
"""
PROJECTS_SQL = """
select p.name, r.path from projects p join project_roots r on r.project_id = p.id and r.position = 0
order by p.position
"""


def codex_targets(db=None):
    """Recent Codex chats and the projects, for choosing where voice chats go. Empty lists if unknown."""
    db = db or codex_state_db()
    out = {"threads": [], "projects": []}
    if not db:
        return out
    clean = lambda path: (path or "").removeprefix("\\\\?\\")  # noqa: E731
    try:
        con = sqlite3.connect("file:" + db.replace("\\", "/") + "?mode=ro", uri=True, timeout=1)
        try:
            for tid, title, cwd in con.execute(THREADS_SQL):
                title = " ".join(title.split())
                out["threads"].append({"id": tid, "title": title[:60] + ("…" if len(title) > 60 else ""),
                                       "folder": os.path.basename(clean(cwd))})
            out["projects"] = [{"name": name, "path": clean(path)} for name, path in con.execute(PROJECTS_SQL)]
        finally:
            con.close()
    except sqlite3.Error as e:
        logging.warning("cannot read the Codex chats: %s", e)
    return out


def chat_target_url(settings):
    """The codex:// link that opens the chat or project a voice chat should go to; None for a new chat."""
    target = settings.get("chat_target", "new")
    if target == "thread" and THREAD_ID.fullmatch(settings.get("chat_thread", "")):
        return "codex://threads/" + settings["chat_thread"]
    if target == "project" and settings.get("chat_project"):
        return "codex://threads/new?path=" + urllib.parse.quote(settings["chat_project"], safe="")
    return None


def start_voice_chat(settings, click=None):
    """Open the chosen chat or project in Codex and start the voice chat with its button there.

    click(name) presses a Codex button by name. Without a target, or if the button is missing, the voice chat
    key is pressed, which starts a new chat outside any project."""
    url = chat_target_url(settings)
    if url:
        try:
            os.startfile(url)
            time.sleep(TARGET_WAIT_S)
            if click and any(click(name) for name in VOICE_BUTTONS[settings["chat_target"]]):
                return
            logging.warning("no voice chat button in Codex; the voice chat key starts it outside the project")
        except OSError as e:
            logging.warning("cannot open %s: %s", url, e)
    press_voice_chat()


def click_codex_button(name, tries=3):
    """Press a Codex button by its accessible name from any thread (the window's Try button)."""
    comtypes.CoInitialize()
    uia = comtypes.client.CreateObject(CUIAutomation, interface=IUIAutomation)
    cond = uia.CreateAndCondition(
        uia.CreatePropertyCondition(UIA_NamePropertyId, name),
        uia.CreatePropertyCondition(UIA_ControlTypePropertyId, UIA_ButtonControlTypeId))
    for attempt in range(tries):
        for hwnd in codex_windows():
            try:
                button = uia.ElementFromHandle(hwnd).FindFirst(TreeScope_Descendants, cond)
                if button:
                    button.GetCurrentPattern(UIA_InvokePatternId).QueryInterface(IUIAutomationInvokePattern).Invoke()
                    return True
            except COMError:
                continue
        time.sleep(0.3)
    return False


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
        self._uia = None

    def stop(self):
        self.stopped.set()

    def _set(self, state):
        if state != self.state:
            self.state = state
            self.on_state(state)

    def _find_button(self, name, tries=1):
        """Find a Codex button by its accessible name; Chromium builds the tree on first use."""
        if self._uia is None:
            self._uia = comtypes.client.CreateObject(CUIAutomation, interface=IUIAutomation)
        uia = self._uia
        cond = uia.CreateAndCondition(
            uia.CreatePropertyCondition(UIA_NamePropertyId, name),
            uia.CreatePropertyCondition(UIA_ControlTypePropertyId, UIA_ButtonControlTypeId))
        for attempt in range(tries):
            for hwnd in codex_windows():
                try:
                    button = uia.ElementFromHandle(hwnd).FindFirst(TreeScope_Descendants, cond)
                except COMError:
                    continue
                if button:
                    return button
            if attempt + 1 < tries:
                time.sleep(0.3)
        return None

    def _click(self, name, tries=3):
        button = self._find_button(name, tries=tries)
        if not button:
            return False
        button.GetCurrentPattern(UIA_InvokePatternId).QueryInterface(IUIAutomationInvokePattern).Invoke()
        return True

    def _end_chat(self):
        """End the voice chat with Codex's End button; the voice chat key if there is none."""
        if not self._click(END_VOICE_BUTTON, tries=1):
            press_voice_chat()

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
            """Every wake phrase heard in this block, one per language: [(words, wake, following, conf)]."""
            hits = []
            for lang, r in recs:
                if r.AcceptWaveform(data):
                    words = s["languages"][lang]
                    wake, following, conf = heard(r.Result(), words, s["min_conf"])
                    if wake:
                        hits.append((words, wake, following, conf))
            return hits

        def is_command(hit):
            words, _, following, _ = hit
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
                        button = SEND_DICTATION_BUTTON if self._send else STOP_DICTATION_BUTTON
                        if self._click(button):
                            kind = "sent" if self._send else "inserted"
                            ev.add(kind, kind, seconds=f"{s['dictation_idle_seconds']:g}")
                        else:
                            ev.add("error", "button_missing", button=button)
                    elif now - last_check < 2:
                        continue
                    else:
                        last_check = now
                        if self._find_button(STOP_DICTATION_BUTTON):
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
                    hit = next((h for h in hits if h[2] in h[0]["stop_words"]), None)
                    if hit:
                        _, wake, following, conf = hit
                        ev.add("chat", "stop_phrase", phrase=f"{wake}, {following}", conf=f"{conf:.2f}")
                        self._end_chat()
                        last_sound = now
                        ignore_until = now + 2
                        continue
                    if self._check_busy(now) or rms > s["speech_rms"] or codex_talking(s["codex_audio_peak"]):
                        last_sound = now
                    elif s["idle_close"] and now - last_sound > s["idle_seconds"]:
                        ev.add("chat", "chat_closing", seconds=f"{s['idle_seconds']:g}")
                        self._end_chat()
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
                words, wake, following, conf = hit
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
                    start_voice_chat(s, self._click)
                elif self._click(DICTATE_BUTTON):
                    ev.add("dictation", "wake_dictation" if send else "wake_draft",
                           phrase=f"{wake}, {following}", conf=f"{conf:.2f}")
                    self._send = send
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

