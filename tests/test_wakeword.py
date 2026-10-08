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


BG = ww.DEFAULTS["languages"]["bg"]
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


if __name__ == "__main__":
    unittest.main()
