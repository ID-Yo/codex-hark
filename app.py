"""Codex Hark: tray icon, window and listener in one process (CodexHark.exe)."""
import argparse
import ctypes
import logging
import os
import subprocess
import sys
import threading
import time
import webbrowser
import winreg

import wakeword as ww  # first: it stops platform from querying WMI

import pystray
import webview
from PIL import Image, ImageDraw

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = ww.APP_NAME
OLD_SHORTCUT = os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu",
                            "Programs", "Startup", "Codex Wake Word.lnk")
SHOW_EVENT = "Local\\CodexHarkShow"  # set by a second launch to bring up the window
UPDATED_EVENT = "Local\\CodexHarkUpdated"  # set by the new version once it runs after an update
UPDATE_START_TRIES = 3
UPDATE_START_WAIT_MS = 60000
COLORS = {"starting": (120, 132, 150), "listening": (7, 139, 69), "chat": (8, 104, 222),
          "dictation": (214, 106, 0), "paused": (120, 132, 150), "error": (181, 40, 53)}
TEXT = {
    "bg": {"update_unavailable": "Няма версия за инсталиране (или Hark не работи като exe).", "title": "Codex Hark", "open": "Отвори", "pause": "Пауза", "resume": "Продължи",
           "restart": "Рестартирай Hark", "autostart": "Стартирай с Windows", "quit": "Изход",
           "running": "Codex Hark вече работи.",
           "words": "Моделът за {language} не познава: {words}. Тези думи няма да се разпознават.",
           "mic": "Няма достъп до микрофона. Нов опит след 10 s.",
           "codex": "Бутонът Dictate не е намерен. Отворен ли е Codex?",
           "crash": "Hark се срина и се рестартира: {error}",
           "stopped": "Hark спря: {error} Отворете прозореца и изберете „Рестартирай Hark“.",
           "states": {"starting": "стартира", "listening": "слуша", "chat": "гласов чат",
                      "dictation": "диктовка", "paused": "пауза", "error": "грешка"}},
    "en": {"update_unavailable": "No version to install (or Hark is not running as the exe).", "title": "Codex Hark", "open": "Open", "pause": "Pause", "resume": "Resume",
           "restart": "Restart Hark", "autostart": "Start with Windows", "quit": "Quit",
           "running": "Codex Hark is already running.",
           "mic": "The microphone is not available. Retrying in 10 s.",
           "codex": "The Dictate button was not found. Is Codex open?",
           "words": "The {language} model does not know: {words}. These words will not be recognized.",
           "crash": "Hark crashed and is restarting: {error}",
           "stopped": "Hark stopped: {error} Open the window and choose Restart Hark.",
           "states": {"starting": "starting", "listening": "listening", "chat": "voice chat",
                      "dictation": "dictation", "paused": "paused", "error": "error"}},
}
NO_RESTART = {"theme", "notifications", "language", "update_check", "update_install"}  # applied without restarting the listener
MAX_RESTARTS = 3  # within RESTART_WINDOW_S
RESTART_WINDOW_S = 300
NOTICE_INTERVAL_S = 60
kernel32 = ctypes.windll.kernel32


def resource(*parts):
    return os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))), *parts)


def _microphone(draw, u, waves):
    """White microphone on a 256-unit canvas, optionally with sound waves."""
    white, line = (255, 255, 255, 255), int(13 * u)
    draw.rounded_rectangle((102 * u, 46 * u, 154 * u, 138 * u), radius=26 * u, fill=white)
    draw.arc((78 * u, 90 * u, 178 * u, 166 * u), 0, 180, fill=white, width=line)
    draw.line((128 * u, 166 * u, 128 * u, 192 * u), fill=white, width=line)
    draw.rounded_rectangle((98 * u, 186 * u, 158 * u, 199 * u), radius=6 * u, fill=white)
    for r, alpha in waves:
        box = (128 * u - r * u, 100 * u - r * u, 128 * u + r * u, 100 * u + r * u)
        for start, end in ((-40, 40), (140, 220)):
            draw.arc(box, start, end, fill=(255, 255, 255, alpha), width=int(10 * u))


def make_app_icon(size=256):
    """The application icon: a blue rounded square with a microphone, sound waves and a green dot."""
    n = size * 4
    u = n / 256
    ramp = Image.linear_gradient("L").resize((n, n))
    diagonal = Image.blend(ramp, ramp.rotate(90), 0.5)  # 0 at the top left, 255 at the bottom right
    base = Image.composite(Image.new("RGBA", (n, n), (5, 70, 168, 255)),
                           Image.new("RGBA", (n, n), (30, 144, 255, 255)), diagonal)
    mask = Image.new("L", (n, n), 0)
    ImageDraw.Draw(mask).rounded_rectangle((8 * u, 8 * u, 248 * u, 248 * u), radius=58 * u, fill=255)
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    img.paste(base, (0, 0), mask)
    glyph = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    draw = ImageDraw.Draw(glyph)
    draw.ellipse((-60 * u, -150 * u, 230 * u, 100 * u), fill=(255, 255, 255, 30))
    glyph.putalpha(Image.composite(glyph.getchannel("A"), Image.new("L", (n, n), 0), mask))
    draw = ImageDraw.Draw(glyph)
    _microphone(draw, u, ((66, 170), (92, 95)))
    draw.ellipse((180 * u, 178 * u, 226 * u, 224 * u), fill=(46, 204, 113, 255), outline=(255, 255, 255, 255),
                 width=int(7 * u))
    return Image.alpha_composite(img, glyph).resize((size, size), Image.LANCZOS)


def make_image(color, size=64):
    """Tray icon: the microphone on a rounded square in the colour of the state."""
    n = size * 4
    u = n / 256
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((4 * u, 4 * u, 252 * u, 252 * u), radius=60 * u, fill=color + (255,))
    _microphone(draw, u * 1.12, ())  # a slightly larger microphone reads better at 16 px
    return img.resize((size, size), Image.LANCZOS)


def save_icon(path):
    make_app_icon(256).save(path, sizes=[(s, s) for s in (16, 20, 24, 32, 40, 48, 64, 128, 256)])


def launch_command():
    if getattr(sys, "frozen", False):
        command = f'"{sys.executable}"'
    else:
        pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        command = f'"{pythonw}" "{os.path.abspath(__file__)}"'
    return command + " --hidden"  # Windows start-up opens only the tray icon


def autostart_command():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            return winreg.QueryValueEx(key, RUN_VALUE)[0]
    except OSError:
        return None


def set_autostart(enabled):
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        if enabled:
            winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, launch_command())
        else:
            try:
                winreg.DeleteValue(key, RUN_VALUE)
            except FileNotFoundError:
                pass
    logging.info("autostart %s", "on: " + launch_command() if enabled else "off")
    if enabled and os.path.exists(OLD_SHORTCUT):
        os.remove(OLD_SHORTCUT)  # the old Python listener would otherwise start too
        logging.info("removed old startup shortcut %s", OLD_SHORTCUT)


def refresh_autostart():
    """Follow the exe if it was moved while autostart is on (a source run leaves it alone)."""
    current = autostart_command()
    if getattr(sys, "frozen", False) and current and current != launch_command():
        logging.info("autostart pointed to %s", current)
        set_autostart(True)


def system_dark():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0
    except OSError:
        return False


def set_clipboard(text):
    user32 = ctypes.windll.user32
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    data = text.encode("utf-16-le") + b"\0\0"
    if not user32.OpenClipboard(None):
        return False
    try:
        user32.EmptyClipboard()
        handle = kernel32.GlobalAlloc(0x0002, len(data))  # GMEM_MOVEABLE
        ctypes.memmove(kernel32.GlobalLock(handle), data, len(data))
        kernel32.GlobalUnlock(handle)
        return bool(user32.SetClipboardData(13, handle))  # CF_UNICODETEXT
    finally:
        user32.CloseClipboard()


def primary_work_area():
    """The primary screen without the taskbar, in logical pixels: (x, y, width, height)."""
    try:
        screens = webview.screens
        screen = next((s for s in screens if s.x == 0 and s.y == 0), screens[0])
        frame = screen.frame
        return frame.X, frame.Y, frame.Width, frame.Height
    except Exception:
        logging.exception("work area unknown")
        return 0, 0, 1920, 1000


class Api:
    """Methods the window calls as window.pywebview.api.<name>(...). Every result is JSON."""

    def __init__(self, app):
        self._app = app

    def state(self, after_id=0):
        app = self._app
        listener = app.listener
        return {"state": app.state, "paused": app.paused.is_set(), "codex_open": app.codex_open(),
                "level": round(listener.level) if listener else 0, "lang": app.lang(),
                "busy": bool(listener and listener.busy and app.state == "chat"),
                "threshold": app.settings["speech_rms"], "version": ww.__version__,
                "events": app.events.after(after_id, app.lang())}

    def get_settings(self):
        app = self._app
        return {"settings": app.settings, "defaults": ww.DEFAULTS, "limits": ww.LIMITS,
                "devices": ww.input_devices(), "autostart": autostart_command() is not None,
                "system_dark": system_dark(), "version": ww.__version__, "lang": app.lang(),
                "hotkeys": ww.codex_hotkeys(),
                "added_languages": {code: ww.language_defaults(code) for code in ww.ADDED_LANGUAGES}}

    def save_settings(self, raw):
        app = self._app
        settings, errors = ww.validate_settings(raw, app.word_checker(), app.lang())
        if errors:
            return {"ok": False, "errors": errors}
        ww.save_settings(settings)
        app.apply_settings(settings)
        return {"ok": True, "settings": settings}

    def check_words(self, lang, text):
        """Which words of a typed word or phrase the language's model knows, so the window can say so before Save.
        status: "ok", "unknown" (a word is missing from the model) or "no_model" (the model is not installed)."""
        words = text.lower().split()
        if lang not in ww.MODELS or not words:
            return {"status": "ok", "words": []}
        listener = self._app.listener
        if (not listener or lang not in listener.models) and ww.model_dir(lang) is None:
            return {"status": "no_model", "words": [{"word": w, "known": None} for w in words]}
        known = self._app.word_checker()
        found = [{"word": w, "known": known(lang, w)} for w in words]
        return {"status": "ok" if all(f["known"] for f in found) else "unknown", "words": found}

    def codex_targets(self):
        """Recent Codex chats and the projects, for choosing where voice chats go."""
        return ww.codex_targets()

    def check_updates(self):
        """The Settings button: look for a new version now."""
        return self._app.check_updates(manual=True)

    def install_update(self):
        """The Settings button: install the version found by the last check."""
        error = self._app.install_update(manual=True)
        return {"ok": error is None, "text": error or ""}

    def last_update(self):
        """The result of the last automatic check (None before the first)."""
        return self._app.update

    def check_keys(self):
        """The Settings button: check Codex's keybindings now and add the ones Hark needs."""
        return self._app.check_keys()

    def reset_settings(self):
        ww.save_settings(ww.DEFAULTS)
        self._app.apply_settings(dict(ww.DEFAULTS))
        return {"ok": True, "settings": ww.DEFAULTS}

    def set_paused(self, paused):
        self._app.set_paused(bool(paused))
        return self.state()

    def set_autostart(self, enabled):
        set_autostart(bool(enabled))
        return autostart_command() is not None

    def test_chat(self):
        ww.start_voice_chat(self._app.settings, ww.click_codex_button)
        return True

    def measure(self, seconds):
        """Microphone levels over the next seconds; the window turns two of these into a threshold."""
        listener = self._app.listener
        if not listener or self._app.state != "listening":
            return {"ok": False, "error": {"bg": "Hark трябва да слуша (не на пауза и не в разговор).",
                                           "en": "Hark must be listening (not paused or in a conversation)."}[self._app.lang()]}
        levels, end = [], time.monotonic() + min(float(seconds), 10)
        while time.monotonic() < end:
            levels.append(listener.level)
            time.sleep(0.25)
        return {"ok": True, "levels": levels}

    def models(self):
        """Every recognition language with the state of its model."""
        app = self._app
        out = []
        for code, info in ww.MODELS.items():
            d = app.downloads.get(code, {})
            installed = ww.model_dir(code) is not None
            out.append({"code": code, "model": info["name"], "size_mb": info["size_mb"], "installed": installed,
                        "state": "ready" if installed else d.get("state", "missing"),
                        "progress": d.get("progress", 0), "error": d.get("error", "")})
        return out

    def download_model(self, code):
        self._app.download(code)
        return self.models()

    def suggest_threshold(self, quiet, speech):
        return ww.suggest_threshold(quiet, speech)

    def open_folder(self):
        os.startfile(ww.DATA_DIR)
        return True

    def copy(self, text):
        return set_clipboard(text)

    def open_url(self, url):
        """Open one of the About links in the default browser; any other address is refused."""
        return bool(ww.about_link(url)) and webbrowser.open(url)


class App:
    def __init__(self):
        self.state = "starting"
        self.paused = threading.Event()
        self.listener = None
        self.downloads = {}  # language -> {"state": "downloading"|"error", "progress", "error"}
        self.window = None
        self.settings = ww.DEFAULTS
        self.events = ww.EventLog()
        self.restart_requested = False
        self.quitting = False
        self.crashes = []
        self.last_notice = {}
        self.update = None  # the last update check result for the window
        self.release = None  # a newer release found by the last check
        self._codex = (0.0, False)
        self.images = {state: make_image(color) for state, color in COLORS.items()}
        t = self.t
        menu = pystray.Menu(
            pystray.MenuItem(lambda item: t("open"), self.show, default=True),
            pystray.MenuItem(lambda item: f"{t('title')} {ww.__version__}: {t('states')[self.state]}", None,
                             enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(lambda item: t("resume") if self.paused.is_set() else t("pause"),
                             lambda: self.set_paused(not self.paused.is_set())),
            pystray.MenuItem(lambda item: t("restart"), self.restart),
            pystray.MenuItem(lambda item: t("autostart"), self.toggle_autostart,
                             checked=lambda item: autostart_command() is not None),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(lambda item: t("quit"), self.quit),
        )
        self.icon = pystray.Icon(ww.APP_NAME, self.images["starting"], self.tooltip(), menu)

    def lang(self):
        return ww.resolve_language(self.settings.get("language", "auto"))

    def t(self, key):
        return TEXT[self.lang()][key]

    def tooltip(self):
        return f"{self.t('title')}: {self.t('states')[self.state]}"

    def set_state(self, state):
        self.state = state
        self.icon.icon = self.images[state]
        self.icon.title = self.tooltip()
        self.icon.update_menu()

    def codex_open(self):
        checked, is_open = self._codex
        if time.monotonic() - checked > 2:
            self._codex = (time.monotonic(), bool(ww.codex_windows()))
        return self._codex[1]

    def word_checker(self):
        """known_word(lang, word) for validation: the listener's model, else the installed model loaded for
        this checker's lifetime, else True (a model that is not installed cannot be asked)."""
        loaded = {}

        def known(lang, word):
            model = self.listener.models.get(lang) if self.listener else None
            if model is None:
                if lang not in loaded:
                    path = ww.model_dir(lang)
                    loaded[lang] = ww.Model(path) if path else None
                model = loaded[lang]
            return model is None or ww.model_knows(model, word)
        return known

    def download(self, code):
        """Download a language model in the background, then restart the listener."""
        if self.downloads.get(code, {}).get("state") == "downloading" or ww.model_dir(code):
            return
        self.downloads[code] = {"state": "downloading", "progress": 0}
        self.events.add("settings", "model_downloading", language=code, size=ww.MODELS[code]["size_mb"])

        def progress(done, total):
            self.downloads[code]["progress"] = round(done / total, 3) if total else 0

        def work():
            try:
                ww.download_model(code, progress)
                self.downloads.pop(code, None)
                self.events.add("settings", "model_ready", language=code)
                self.restart()
            except Exception as e:
                logging.exception("model download")
                self.downloads[code] = {"state": "error", "error": str(e)}
                self.events.add("error", "model_error", language=code, error=str(e))

        threading.Thread(target=work, name=f"download-{code}", daemon=True).start()

    def ensure_models(self):
        for code, words in self.settings["languages"].items():
            if words["enabled"] and not ww.model_dir(code):
                self.download(code)

    def problem(self, key, **args):
        if "language" in args:
            args["language"] = ww.LANGUAGE_NAMES[self.lang()].get(args["language"], args["language"])
        self.notify(key, self.t(key).format(**args))

    def notify(self, key, message):
        if not self.settings.get("notifications", True):
            return
        now = time.monotonic()
        if now - self.last_notice.get(key, -NOTICE_INTERVAL_S) < NOTICE_INTERVAL_S:
            return
        self.last_notice[key] = now
        logging.info("notice: %s", message)
        try:
            self.icon.notify(message, self.t("title"))
        except Exception:
            logging.exception("notification failed")

    def check_keys(self, first_run=False):
        """Check Codex's keybindings (adding what Hark needs), tell the user, and return the result for the window."""
        result = ww.check_codex_keys(fix=True)
        status, hotkeys = result["status"], ww.codex_hotkeys()
        args = {"commands": ", ".join(result["added"]), "voice": hotkeys["voice"], "dictation": hotkeys["dictation"],
                "conflicts": ", ".join(f"{ww.CODEX_KEYS[c]} ({other})" for c, other in result["conflicts"].items()),
                "error": result.get("error", "")}
        code = "keys_" + status
        self.events.add("settings" if status in ("ok", "added") else "error", code, **args)
        text, detail = ww.message(code, self.lang(), **args)
        message = f"{text} — {detail}" if detail else text
        if status != "ok":
            self.notify(code, message)
        if first_run and status in ("ok", "added", "conflict", "invalid"):
            ww.save_settings({**ww.load_settings(), "keys_checked": True})
        return {"status": status, "text": message, "hotkeys": hotkeys}

    def check_updates(self, manual=False):
        """Ask GitHub for the newest public release; tell the user when it is newer. Returns the result for the window."""
        current = ww.__version__
        try:
            latest = ww.latest_release()
            status = ww.update_status(latest["version"], current)
            args = {"version": latest["version"], "current": current}
        except (OSError, ValueError) as e:
            latest, status, args = {"url": ""}, "error", {"error": str(e), "current": current}
        code = "update_" + {"new": "available"}.get(status, status)
        text, detail = ww.message(code, self.lang(), **args)
        if manual or status == "new":
            self.events.add("error" if status == "error" else "settings", code, **args)
        if status == "new":
            self.notify(code, f"{text} — {detail}")
        else:
            logging.info("update check: %s %s", text, detail)
        self.update = {"status": status, "text": f"{text} — {detail}" if detail else text,
                       "version": args.get("version", ""), "url": latest.get("url", ""),
                       "can_install": status == "new" and getattr(sys, "frozen", False) and bool(latest.get("exe"))}
        self.release = latest if status == "new" else None
        return self.update

    def install_update(self, manual=False):
        """Download the found release, check its SHA256, swap the exe and start the new one. Returns an error text
        (None when the new version is starting)."""
        release = self.release
        if not release or not getattr(sys, "frozen", False):
            return self.t("update_unavailable")
        args = {"version": release["version"], "current": ww.__version__}
        try:
            self.events.add("settings", "update_installing", **args)
            new_exe = ww.download_update(release, os.path.join(ww.DATA_DIR, "update"))
            ww.install_update(new_exe, sys.executable)
        except (OSError, ValueError) as e:
            self.events.add("error", "update_failed", error=str(e))
            text, detail = ww.message("update_failed", self.lang(), error=str(e))
            self.notify("update_failed", f"{text} — {detail}")
            self.release = None  # do not retry this release until the next check
            return f"{text} — {detail}"
        logging.info("installed %s; starting it", release["version"])
        # Not a daemon: this process stays alive (without its window and tray icon) until the new one runs.
        threading.Thread(target=self.start_new_version, args=(manual,), name="update").start()
        return None

    def start_new_version(self, manual):
        """Close this version, start the new exe and wait until it says it runs. A freshly written one-file exe
        sometimes fails to unpack (it then shows an error box and hangs), so try again a few times and put the
        old exe back if the new one never starts."""
        exe, previous = sys.executable, ww.__version__
        self.quit()
        time.sleep(2)
        ww.release_single_instance()
        ready = kernel32.CreateEventW(None, True, False, UPDATED_EVENT)
        # A fresh start of the one-file exe: without this it inherits this process's PyInstaller variables and
        # looks for its files in this process's temporary folder, which is deleted when this process exits.
        env = {**os.environ, "PYINSTALLER_RESET_ENVIRONMENT": "1"}
        command = [exe, "--after-update", "--previous", previous] + ([] if manual else ["--hidden"])
        for attempt in range(1, UPDATE_START_TRIES + 1):
            process = subprocess.Popen(command, close_fds=True, env=env)
            if kernel32.WaitForSingleObject(ready, UPDATE_START_WAIT_MS) == 0:
                logging.info("the new version runs")
                return
            logging.warning("the new version did not start (try %d of %d)", attempt, UPDATE_START_TRIES)
            kill_tree(process.pid)
        try:
            ww.install_update(exe + ".old", exe)  # put the old exe back
        except OSError:
            logging.exception("cannot put the old version back")
        logging.warning("update rolled back to %s", previous)
        subprocess.Popen([exe] + ([] if manual else ["--hidden"]), close_fds=True, env=env)

    def watch_updates(self):
        """Check for a new version a minute after start and then every 12 hours, while the setting is on."""
        next_check = time.monotonic() + ww.UPDATE_FIRST_DELAY_S
        while not self.quitting:
            time.sleep(5)
            if time.monotonic() >= next_check:
                next_check = time.monotonic() + ww.UPDATE_INTERVAL_S
                if self.settings.get("update_check", True):
                    self.check_updates()
            # Install a found release by itself, but never in the middle of a conversation or dictation.
            if (self.release and self.settings.get("update_install", True) and getattr(sys, "frozen", False)
                    and self.state in ("listening", "paused")):
                self.install_update()

    def show(self):
        if self.window:
            self.window.show()
            self.window.restore()
            ctypes.windll.user32.AllowSetForegroundWindow(-1)

    def set_paused(self, paused):
        if paused == self.paused.is_set():
            return
        if paused:
            self.paused.set()
            self.events.add("pause", "paused")
        else:
            self.paused.clear()
            self.events.add("pause", "resumed")
        self.icon.update_menu()

    def toggle_autostart(self):
        set_autostart(autostart_command() is None)
        self.icon.update_menu()

    def apply_settings(self, settings):
        """Store new settings; restart the listener only if something it uses has changed."""
        old, self.settings = self.settings, settings
        self.events.add("settings", "settings_saved")
        self.icon.title = self.tooltip()
        self.icon.update_menu()
        if self.window:
            self.window.set_title(self.t("title"))
        self.ensure_models()
        if any(old.get(k) != v for k, v in settings.items() if k not in NO_RESTART):
            self.restart()

    def restart(self):
        logging.info("restart requested")
        self.restart_requested = True
        if self.listener:
            self.listener.stop()

    def quit(self):
        logging.info("exit requested")
        self.quitting = True
        if self.listener:
            self.listener.stop()
        self.icon.stop()
        if self.window:
            self.window.destroy()

    def supervise(self):
        """Run the listener, re-reading settings on each start; restart it after a crash."""
        if not ww.load_settings().get("keys_checked"):
            self.check_keys(first_run=True)
        while not self.quitting:
            self.restart_requested = False
            try:
                self.settings = ww.load_settings()
                self.listener = ww.Listener(self.settings, self.set_state, self.problem, self.paused,
                                            self.events)
                self.listener.run()
            except Exception as e:
                logging.exception("listener crashed")
                self.events.add("error", "crash", error=str(e))
                now = time.monotonic()
                self.crashes = [t for t in self.crashes if now - t < RESTART_WINDOW_S] + [now]
                self.set_state("error")
                if len(self.crashes) > MAX_RESTARTS:
                    self.problem("stopped", error=e)
                    self.wait_for_restart()
                    continue
                self.problem("crash", error=e)
                time.sleep(2)
                continue
            if not self.restart_requested:
                return

    def wait_for_restart(self):
        while not self.quitting and not self.restart_requested:
            time.sleep(0.2)
        self.crashes = []

    def watch_second_launch(self):
        handle = kernel32.CreateEventW(None, False, False, SHOW_EVENT)
        while not self.quitting:
            if kernel32.WaitForSingleObject(handle, 500) == 0:
                self.show()

    def on_closing(self):
        if self.quitting:
            return True
        self.window.hide()
        return False  # keep running in the tray

    def run(self, show_window):
        self.settings = ww.load_settings()
        self.ensure_models()
        x, y, width, height = ww.window_rect(*primary_work_area())
        self.window = webview.create_window(
            self.t("title"), resource("ui", "index.html"), js_api=Api(self), x=x, y=y, width=width, height=height,
            min_size=(700, 460), hidden=not show_window, background_color="#F2F6FC")
        self.window.events.closing += self.on_closing
        self.icon.run_detached()
        threading.Thread(target=self.supervise, name="listener", daemon=True).start()
        threading.Thread(target=self.watch_second_launch, name="show", daemon=True).start()
        threading.Thread(target=self.watch_updates, name="updates", daemon=True).start()
        icon = os.path.join(ww.DATA_DIR, "icon.ico")
        save_icon(icon)
        webview.start(private_mode=True, storage_path=os.path.join(ww.DATA_DIR, "webview"), icon=icon)


def kill_tree(pid):
    try:
        process = ww.psutil.Process(pid)
        for child in process.children(recursive=True):
            child.kill()
        process.kill()
    except ww.psutil.Error:
        pass


def migrate_legacy_autostart():
    """Move the start-up entry of the pre-rename CodexSlushatel build to this build."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_ALL_ACCESS) as key:
            winreg.QueryValueEx(key, "CodexSlushatel")
            winreg.DeleteValue(key, "CodexSlushatel")
    except OSError:
        return
    set_autostart(True)


def main(argv=None):
    parser = argparse.ArgumentParser(prog=ww.APP_NAME)
    parser.add_argument("--autostart", choices=["on", "off"], help="turn start with Windows on or off")
    parser.add_argument("--hidden", action="store_true", help="start in the tray without opening the window")
    parser.add_argument("--after-update", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--previous", default="", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    ww.setup_logging()
    if args.autostart:
        set_autostart(args.autostart == "on")
        return
    if args.after_update:  # the old version is closing; wait until it lets go of the single-instance lock
        for _ in range(60):
            if ww.acquire_single_instance():
                break
            time.sleep(0.5)
    if not ww._instance and not ww.acquire_single_instance():
        handle = kernel32.OpenEventW(0x0002, False, SHOW_EVENT)  # EVENT_MODIFY_STATE
        if handle:
            kernel32.SetEvent(handle)
        return
    logging.info("%s %s started (%s)", ww.APP_NAME, ww.__version__, launch_command())
    if args.after_update:  # tell the old version that this one runs
        handle = kernel32.OpenEventW(0x0002, False, UPDATED_EVENT)
        if handle:
            kernel32.SetEvent(handle)
            kernel32.CloseHandle(handle)
    elif getattr(sys, "frozen", False):
        ww.remove_old_exe(sys.executable)
    migrate_legacy_autostart()
    refresh_autostart()
    app = App()
    if args.after_update and args.previous:
        app.events.add("settings", "update_done", version=ww.__version__, previous=args.previous)
    app.run(show_window=not args.hidden)


if __name__ == "__main__":
    main()
