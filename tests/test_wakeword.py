"""Tests for the pure logic of wakeword.py: phrase parsing and settings precedence."""
import hashlib
import json
import os
import pathlib
import sqlite3
import sys
import tempfile
import time
import unittest
import zipfile
from unittest.mock import patch
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    import wakeword as ww
except ImportError as e:  # the listener's dependencies live in .venv or the build venv
    raise unittest.SkipTest(f"listener dependencies missing: {e}")


def result(*words):
    return json.dumps({"result": [{"word": w, "conf": c} for w, c in words]})


BG = ww.language_defaults("bg")
EN = ww.DEFAULTS["languages"]["en"]


class HeardTests(unittest.TestCase):
    def test_wake_word_alone(self):
        self.assertEqual(ww.heard(result(("кодекс", 1.0)), BG, 0.5), ("кодекс", "", 1.0))

    def test_word_after_the_wake_word_is_returned(self):
        self.assertEqual(ww.heard(result(("кодекс", 1.0), ("чернова", 0.9)), BG, 0.5), ("кодекс", "чернова", 1.0))
        self.assertEqual(ww.heard(result(("codex", 0.8), ("draft", 0.9)), EN, 0.5), ("codex", "draft", 0.8))

    def test_each_language_only_knows_its_own_wake_words(self):
        self.assertEqual(ww.heard(result(("codex", 1.0)), BG, 0.5)[0], "")

    def test_dictate_word_without_wake_word_does_nothing(self):
        self.assertEqual(ww.heard(result(("кода", 1.0), ("пиши", 1.0)), BG, 0.5)[0], "")

    def test_low_confidence_wake_word_is_ignored(self):
        self.assertEqual(ww.heard(result(("кодекс", 0.3), ("стоп", 1.0)), BG, 0.5)[0], "")

    def test_grammar_has_every_word_of_the_language(self):
        words = json.loads(ww.grammar(EN))
        self.assertEqual(set(words), {"codex", "write", "draft", "stop", "[unk]", *EN["decoys"]})


class WakePhraseTests(unittest.TestCase):
    PHRASE = {**EN, "wake_words": ["hey jarvis"]}

    def test_phrase_needs_all_its_words_in_a_row(self):
        self.assertEqual(ww.heard(result(("hey", 1.0), ("jarvis", 0.8), ("write", 1.0)), self.PHRASE, 0.5),
                         ("hey jarvis", "write", 0.9))
        self.assertEqual(ww.heard(result(("jarvis", 1.0)), self.PHRASE, 0.5)[0], "")
        self.assertEqual(ww.heard(result(("hey", 1.0)), self.PHRASE, 0.5)[0], "")
        self.assertEqual(ww.heard(result(("hey", 1.0), ("[unk]", 1.0), ("jarvis", 1.0)), self.PHRASE, 0.5)[0], "")
        self.assertEqual(ww.heard(result(("jarvis", 1.0), ("hey", 1.0)), self.PHRASE, 0.5)[0], "")

    def test_phrase_confidence_is_the_mean_of_its_words(self):
        self.assertEqual(ww.heard(result(("hey", 0.2), ("jarvis", 0.4)), self.PHRASE, 0.5)[0], "")
        self.assertEqual(ww.heard(result(("hey", 0.4), ("jarvis", 0.8)), self.PHRASE, 0.5)[0], "hey jarvis")

    def test_phrase_can_follow_other_words_and_the_longer_phrase_wins(self):
        words = {**EN, "wake_words": ["codex", "hey codex"]}
        self.assertEqual(ww.heard(result(("hey", 1.0), ("codex", 1.0), ("stop", 1.0)), words, 0.5),
                         ("hey codex", "stop", 1.0))
        self.assertEqual(ww.heard(result(("codex", 1.0), ("stop", 1.0)), words, 0.5), ("codex", "stop", 1.0))
        self.assertEqual(ww.heard(result(("so", 1.0), ("hey", 1.0), ("jarvis", 1.0)), self.PHRASE, 0.5)[0], "hey jarvis")

    def test_grammar_keeps_the_phrase_as_one_item(self):
        self.assertIn("hey jarvis", json.loads(ww.grammar(self.PHRASE)))

    def test_unknown_words_of_a_phrase_are_listed_once(self):
        model_knows = lambda model, word: word not in ("jarvis", "hark")  # noqa: E731
        words = {**EN, "wake_words": ["hey jarvis", "jarvis hark"], "decoys": ["code"]}
        with patch.object(ww, "model_knows", model_knows):
            self.assertEqual(ww.unknown_words(object(), words), ["jarvis", "hark"])


class CodexBusyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.temp.name, "thread_history_1.sqlite")
        con = sqlite3.connect(self.db)
        con.executescript("""
            create table thread_realtime_items (thread_id text, item_id text, rollout_ordinal integer,
                created_at_ms integer, item_type text, item_json text);
            create table thread_turns (thread_id text, turn_id text, rollout_ordinal integer, status text);""")
        con.commit(); con.close()
        self.now = int(time.time() * 1000)

    def tearDown(self):
        self.temp.cleanup()

    def add(self, sql, *rows):
        con = sqlite3.connect(self.db)
        con.executemany(sql, rows); con.commit(); con.close()

    def session(self, thread, kind, ms):
        self.add("insert into thread_realtime_items values (?, ?, 0, ?, ?, '{}')", (thread, kind + thread, ms, kind))

    def test_busy_only_while_the_open_voice_chat_has_an_unfinished_turn(self):
        self.assertFalse(ww.codex_busy(self.db))
        self.session("voice", "realtime_session_started", self.now - 5000)
        self.assertFalse(ww.codex_busy(self.db))
        self.add("insert into thread_turns values (?, ?, 0, ?)", ("voice", "t1", "inProgress"))
        self.assertTrue(ww.codex_busy(self.db))
        self.session("voice", "realtime_session_closed", self.now - 1000)
        self.assertFalse(ww.codex_busy(self.db))

    def test_other_threads_working_do_not_count(self):
        self.session("voice", "realtime_session_started", self.now - 5000)
        self.add("insert into thread_turns values (?, ?, 0, ?)", ("agent", "t1", "inProgress"))
        self.assertFalse(ww.codex_busy(self.db))

    def test_missing_database_is_unknown(self):
        self.assertIsNone(ww.codex_busy(os.path.join(self.temp.name, "missing", "x.sqlite")))


def langs(**bg):
    return {"languages": {"bg": {**BG, **bg}}}


class ValidateSettingsTests(unittest.TestCase):
    def test_defaults_are_valid(self):
        self.assertEqual(ww.validate_settings(ww.DEFAULTS), (ww.DEFAULTS, {}))

    def test_numbers_outside_limits_are_rejected(self):
        _, errors = ww.validate_settings({"idle_seconds": 500, "min_conf": True, "speech_rms": "200"})
        self.assertEqual(set(errors), {"idle_seconds", "min_conf", "speech_rms"})

    def test_words_are_cleaned_and_checked_against_the_language_model(self):
        settings, errors = ww.validate_settings(langs(wake_words=[" Кодекс ", "кодекс", ""]))
        self.assertEqual((settings["languages"]["bg"]["wake_words"], errors), (["кодекс"], {}))
        known = lambda lang, w: not (lang == "bg" and w == "диктовка")  # noqa: E731
        _, errors = ww.validate_settings(langs(send_words=["пиши", "диктовка"]), known_word=known)
        self.assertIn("диктовка", errors["languages.bg.send_words"])

    def test_word_lists_cannot_overlap_within_a_language(self):
        self.assertIn("languages.bg.wake_words", ww.validate_settings(langs(wake_words=[]))[1])
        self.assertIn("languages.bg.draft_words", ww.validate_settings(langs(draft_words=["пиши"]))[1])
        self.assertIn("languages.bg.stop_words", ww.validate_settings(langs(stop_words=["кодекс"]))[1])
        self.assertEqual(ww.validate_settings(langs(decoys=[], send_words=[]))[1], {})

    def test_only_wake_words_may_be_phrases(self):
        settings, errors = ww.validate_settings(langs(wake_words=["  Хей   Кодекс "]))
        self.assertEqual((settings["languages"]["bg"]["wake_words"], errors), (["хей кодекс"], {}))
        self.assertIn("languages.bg.send_words", ww.validate_settings(langs(send_words=["пиши ми"]))[1])
        self.assertIn("languages.bg.decoys", ww.validate_settings(langs(decoys=["един два"]))[1])
        _, errors = ww.validate_settings(langs(wake_words=["a b c d"]), lang="en")
        self.assertIn("at most 3 words", errors["languages.bg.wake_words"])

    def test_every_word_of_a_phrase_is_checked_against_the_model(self):
        known = lambda lang, w: w != "джарвис"  # noqa: E731
        _, errors = ww.validate_settings(langs(wake_words=["хей джарвис", "ей джарвис"]), known_word=known)
        self.assertTrue(errors["languages.bg.wake_words"].endswith("джарвис."))
        self.assertEqual(errors["languages.bg.wake_words"].count("джарвис"), 1)

    def test_a_language_must_be_on(self):
        off = {"languages": {code: {**w, "enabled": False} for code, w in ww.DEFAULTS["languages"].items()}}
        self.assertIn("languages", ww.validate_settings(off)[1])

    def test_errors_follow_the_language(self):
        self.assertIn("between 3 and 120", ww.validate_settings({"idle_seconds": 1}, lang="en")[1]["idle_seconds"])
        self.assertIn("language", ww.validate_settings({"language": "de"})[1])

    def test_theme_and_types(self):
        self.assertIn("theme", ww.validate_settings({"theme": "blue"})[1])
        self.assertIn("beep", ww.validate_settings({"beep": "yes"})[1])


class MigrationTests(unittest.TestCase):
    def test_v03_words_move_to_bulgarian(self):
        old = {"wake_words": ["кодекс"], "dictate_words": ["пиши", "запиши"], "stop_words": ["стоп"], "idle_seconds": 12}
        settings, errors = ww.validate_settings(ww.migrate_settings(old))
        bg = settings["languages"]["bg"]
        self.assertEqual((bg["wake_words"], bg["send_words"], bg["draft_words"], bg["stop_words"]),
                         (["кодекс"], ["пиши", "запиши"], ["чернова"], ["стоп"]))
        self.assertEqual((settings["idle_seconds"], settings["languages"]["en"], errors), (12, EN, {}))

    def test_leave_in_box_becomes_draft_words(self):
        bg = ww.migrate_settings({"dictate_words": ["пиши"], "dictation_send": False})["languages"]["bg"]
        self.assertEqual((bg["send_words"], bg["draft_words"]), ([], ["пиши"]))

    def test_new_settings_are_left_alone(self):
        new = {"languages": {}, "idle_seconds": 9}
        self.assertIs(ww.migrate_settings(new), new)


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.zip = os.path.join(self.temp.name, "model.zip")
        with zipfile.ZipFile(self.zip, "w") as z:
            z.writestr("vosk-model-small-en-us-0.15/am/final.mdl", "x")
        with open(self.zip, "rb") as f:
            self.sha = hashlib.sha256(f.read()).hexdigest().upper()
        self.patches = [patch.object(ww, "models_dir", lambda: os.path.join(self.temp.name, "models")),
                        patch.object(ww, "HERE", self.temp.name),
                        patch.object(ww, "MODEL_URL", pathlib.Path(self.zip).as_uri().replace("model.zip", "{name}.zip"))]
        os.rename(self.zip, os.path.join(self.temp.name, "vosk-model-small-en-us-0.15.zip"))
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.temp.cleanup()

    def test_download_checks_the_checksum_and_unpacks(self):
        with patch.dict(ww.MODELS, {"en": {**ww.MODELS["en"], "sha256": self.sha}}):
            path = ww.download_model("en")
        self.assertTrue(os.path.isfile(os.path.join(path, "am", "final.mdl")))

    def test_wrong_checksum_leaves_nothing(self):
        with patch.dict(ww.MODELS, {"en": {**ww.MODELS["en"], "sha256": "0" * 64}}):
            with self.assertRaises(ValueError):
                ww.download_model("en")
        self.assertIsNone(ww.model_dir("en"))
        self.assertEqual(os.listdir(os.path.join(self.temp.name, "models")), [])


class EventLogTests(unittest.TestCase):
    def test_events_are_numbered_kept_and_reloaded(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "events.jsonl")
            log = ww.EventLog(path, size=3)
            for i in range(5):
                log.add("chat", "chat_closing", seconds=str(i))
            self.assertEqual([e["detail"] for e in log.after(0, "en")],
                             ["2 s of silence", "3 s of silence", "4 s of silence"])
            self.assertEqual(log.after(4, "bg")[0]["text"], "Затваряне на гласовия чат")
            self.assertEqual([e["id"] for e in log.after(4)], [5])
            again = ww.EventLog(path, size=3)
            self.assertEqual([e["id"] for e in again.after(0)], [3, 4, 5])
            self.assertEqual(again.add("pause", "paused")["id"], 6)


class ThresholdTests(unittest.TestCase):
    def test_threshold_between_silence_and_speech(self):
        # 95th percentile of silence is 59, median speech is 900: 59 + (900 - 59) / 3
        self.assertEqual(ww.suggest_threshold([40, 50, 60], [600, 900, 1200]), 339)

    def test_no_threshold_without_clear_speech(self):
        self.assertIsNone(ww.suggest_threshold([100, 120], [130, 140]))


class NoWmiTests(unittest.TestCase):
    def test_windows_version_does_not_query_wmi(self):
        import platform
        platform._uname_cache = None
        with self.assertRaises(OSError):
            platform._wmi_query("OS", "Version")
        self.assertEqual(platform.system(), "Windows")
        self.assertTrue(platform.win32_ver()[1])


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp.name, "sub", "settings.json")

    def tearDown(self):
        self.temp.cleanup()

    def test_first_run_writes_defaults(self):
        self.assertEqual(ww.load_settings(self.path, env={}), ww.DEFAULTS)
        with open(self.path, encoding="utf-8") as f:
            self.assertEqual(json.load(f), ww.DEFAULTS)

    def test_file_overrides_defaults_and_ignores_unknown_keys(self):
        os.makedirs(os.path.dirname(self.path))
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"idle_seconds": 20, "unknown": 1}, f)
        settings = ww.load_settings(self.path, env={})
        self.assertEqual(settings["idle_seconds"], 20)
        self.assertNotIn("unknown", settings)

    def test_environment_wins_over_file(self):
        os.makedirs(os.path.dirname(self.path))
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"idle_seconds": 20}, f)
        settings = ww.load_settings(self.path, env={"CODEX_IDLE_SECONDS": "15"})
        self.assertEqual(settings["idle_seconds"], 15.0)

    def test_invalid_file_names_the_file(self):
        os.makedirs(os.path.dirname(self.path))
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{ broken")
        with self.assertRaisesRegex(ValueError, "settings.json"):
            ww.load_settings(self.path, env={})


class CodexKeysTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = os.path.join(self.temp.name, "keybindings.json")

    def write(self, entries):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(entries, f)

    def read(self):
        with open(self.path, encoding="utf-8") as f:
            return json.load(f)

    def test_no_codex_folder(self):
        missing = os.path.join(self.temp.name, "nothing", "keybindings.json")
        self.assertEqual(ww.check_codex_keys(missing, fix=True)["status"], "no_codex")

    def test_missing_file_is_reported_and_then_created(self):
        self.assertEqual(ww.check_codex_keys(self.path)["status"], "missing")
        self.assertFalse(os.path.exists(self.path))
        result = ww.check_codex_keys(self.path, fix=True)
        self.assertEqual((result["status"], sorted(result["added"])), ("added", ["globalDictationHold", "realtimeVoice"]))
        self.assertEqual({e["command"]: e["key"] for e in self.read()}, {"realtimeVoice": "Alt+Z", "globalDictationHold": "Alt+X"})
        self.assertEqual(ww.check_codex_keys(self.path, fix=True)["status"], "ok")

    def test_other_entries_stay_and_a_backup_is_made(self):
        other = {"command": "newTask", "key": "Ctrl+N"}
        self.write([other, {"command": "realtimeVoice", "key": None}])
        result = ww.check_codex_keys(self.path, fix=True)
        self.assertEqual(result["status"], "added")
        saved = self.read()
        self.assertEqual(saved[0], other)
        self.assertEqual([e for e in saved if e["command"] == "realtimeVoice"], [{"command": "realtimeVoice", "key": "Alt+Z"}])
        with open(self.path + ".hark-backup", encoding="utf-8") as f:
            self.assertEqual(json.load(f), [other, {"command": "realtimeVoice", "key": None}])

    def test_a_key_the_user_chose_is_kept_and_used(self):
        entries = [{"command": "realtimeVoice", "key": "Ctrl+Shift+V"}, {"command": "globalDictationHold", "key": "Alt+X"}]
        self.write(entries)
        result = ww.check_codex_keys(self.path, fix=True)
        self.assertEqual((result["status"], result["keys"]["realtimeVoice"]), ("ok", "Ctrl+Shift+V"))
        self.assertEqual(self.read(), entries)
        with patch.object(ww, "keybindings_path", return_value=self.path):
            self.assertEqual(ww.codex_hotkeys(), {"voice": "Ctrl+Shift+V", "dictation": "Alt+X"})

    def test_a_key_used_by_another_command_is_not_taken(self):
        self.write([{"command": "openTerminal", "key": "alt+z"}])
        result = ww.check_codex_keys(self.path, fix=True)
        self.assertEqual((result["status"], result["conflicts"], result["added"]),
                         ("conflict", {"realtimeVoice": "openTerminal"}, ["globalDictationHold"]))
        self.assertEqual([e["command"] for e in self.read() if e["key"] and e["key"].lower() == "alt+z"], ["openTerminal"])

    def test_an_unreadable_file_is_left_alone(self):
        for text in ("{not json", '{"command": "x"}', '["text"]'):
            with open(self.path, "w", encoding="utf-8") as f:
                f.write(text)
            self.assertEqual(ww.check_codex_keys(self.path, fix=True)["status"], "invalid")
            with open(self.path, encoding="utf-8") as f:
                self.assertEqual(f.read(), text)

    def test_hotkeys_become_key_codes(self):
        self.assertEqual(ww.parse_hotkey("Alt+Z"), [0x12, 0x5A])
        self.assertEqual(ww.parse_hotkey("Ctrl+Shift+V"), [0x11, 0x10, 0x56])
        self.assertEqual(ww.parse_hotkey("F9"), [0x78])
        self.assertIsNone(ww.parse_hotkey("Alt+Nope"))
        self.assertIsNone(ww.parse_hotkey("Hyper+Z"))

    def test_voice_key_defaults_to_alt_z(self):
        with patch.object(ww, "keybindings_path", return_value=self.path):
            self.assertEqual(ww.codex_hotkeys(), {"voice": "Alt+Z", "dictation": "Alt+X"})


class WindowSizeTests(unittest.TestCase):
    def test_window_is_centered_in_the_work_area_and_never_larger_than_it(self):
        self.assertEqual(ww.window_rect(0, 0, 1280, 680), (200, 40, 880, 600))  # 1920x1080 at 150%, taskbar 40
        self.assertEqual(ww.window_rect(0, 0, 1366, 728), (243, 64, 880, 600))
        self.assertEqual(ww.window_rect(0, 0, 800, 560), (40, 28, 720, 504))
        self.assertEqual(ww.window_rect(-1280, 0, 1097, 577), (-1172, 29, 880, 519))  # a second screen on the left
        for area in ((0, 0, 1280, 680), (0, 0, 800, 560), (0, 0, 1024, 600)):
            x, y, w, h = ww.window_rect(*area)
            self.assertTrue(x >= area[0] and y >= area[1] and x + w <= area[0] + area[2] and y + h <= area[1] + area[3])

    def test_only_the_about_links_open(self):
        self.assertTrue(ww.about_link("https://IvanYosifov.com"))
        self.assertTrue(ww.about_link("https://ivanyosifov.com/"))
        self.assertTrue(ww.about_link("https://github.com/ID-Yo/codex-hark"))
        for url in ("http://ivanyosifov.com", "https://ivanyosifov.com.evil.example", "file:///C:/Windows/notepad.exe",
                    "https://github.com/ID-Yo/other", "", None):
            self.assertFalse(ww.about_link(url), url)


class EnglishFirstTests(unittest.TestCase):
    def test_a_new_install_starts_with_english_only(self):
        self.assertEqual(list(ww.DEFAULTS["languages"]), ["en"])
        self.assertEqual(ww.MODEL_NAME, ww.MODELS["en"]["name"])

    def test_bulgarian_is_an_added_language_that_can_be_removed(self):
        self.assertIn("bg", ww.ADDED_LANGUAGES)
        settings, errors = ww.validate_settings({"languages": {"en": EN, "bg": BG}})
        self.assertEqual((list(settings["languages"]), errors), (["en", "bg"], {}))
        self.assertNotIn("bg", ww.validate_settings({"languages": {"en": EN}})[0]["languages"])


class AddedLanguageTests(unittest.TestCase):
    def test_an_added_language_is_kept_with_its_words_and_can_be_removed(self):
        raw = {"languages": {"bg": BG, "en": EN, "de": ww.language_defaults("de")}}
        settings, errors = ww.validate_settings(raw)
        self.assertEqual((list(settings["languages"]), errors), (["en", "bg", "de"], {}))
        self.assertEqual(settings["languages"]["de"]["send_words"], ["schreib"])
        self.assertEqual(list(ww.validate_settings({"languages": {"bg": BG, "en": EN}})[0]["languages"]), ["en", "bg"])
        self.assertEqual(list(ww.validate_settings({"languages": {"en": EN}})[0]["languages"]), ["en"])

    def test_english_stays_and_unknown_codes_are_dropped(self):
        settings, errors = ww.validate_settings({"languages": {"xx": {"enabled": True}, "uk": {"wake_words": ["кодекс"]}}})
        self.assertEqual((list(settings["languages"]), errors), (["en", "uk"], {}))
        self.assertEqual(settings["languages"]["uk"]["stop_words"], ww.ADDED_LANGUAGES["uk"]["stop_words"])

    def test_every_added_language_has_a_model_a_name_and_valid_words(self):
        for code in ww.ADDED_LANGUAGES:
            self.assertIn(code, ww.MODELS)
            self.assertTrue(all(code in names for names in ww.LANGUAGE_NAMES.values()), code)
            _, errors = ww.validate_settings({"languages": {"bg": BG, "en": EN, code: ww.language_defaults(code)}})
            self.assertEqual(errors, {}, code)


if __name__ == "__main__":
    unittest.main()
