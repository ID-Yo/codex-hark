# AGENTS.md

Instructions for coding agents in this repository. README.md explains the product; this file says how to change it safely.

## Commands

- Set up: `py -3.13 -m venv .venv; .\.venv\Scripts\python -m pip install -r requirements.txt`
- Test: `.\.venv\Scripts\python -m unittest discover -s tests` (run before every commit)
- Run the app: `.\.venv\Scripts\pythonw.exe app.py` (needs the `vosk-model-small-ru-0.22` folder next to `app.py`; `build.ps1` downloads and verifies it)
- Listener only, no window: `.\.venv\Scripts\python.exe wakeword.py`
- Build: `./build.ps1` (clean venv, model SHA256 check, tests, PyInstaller; writes `dist\CodexHark.exe` and `dist\SHA256SUMS.txt`; needs about 0.5 GB of free disk space)
- Preview the UI without Python: open `ui/index.html#home-light-en` in a browser (sample data; hash = screen-theme-language)

## Structure

- `wakeword.py`: `Listener`, recognition grammar, settings validation, language models; `__version__` lives here
- `app.py`: tray icon, pywebview window and its `Api`, single-instance event, autostart, icon drawing
- `ui/`: HTML, CSS and JS; all user-visible strings exist in Bulgarian and English in `ui/app.js`, tray and notification strings in `app.py` and `wakeword.py`
- `tests/test_wakeword.py`: tests for pure logic only; no microphone, no Codex
- `.github/workflows/build.yml`: CI build; a tag `vX.Y.Z` +`+__version__+`+ creates a Release`__version__` creates a Release

## Conventions

- Python 3.13; keep dependencies pinned in `requirements.txt`; a new dependency needs a reason and an entry in `THIRD_PARTY.md`.
- Python sources use CRLF line endings; keep them so diffs show only real changes.
- Changing a user-visible string means changing both languages.
- Only `wake_words` may hold phrases (up to 3 words, matched as consecutive recognized words); every other word list holds single words. Vosk silently ignores words that are missing from the model, so new words must be checked with `model_knows` (the window uses `Api.check_words`).
- Keep the version in `wakeword.py` and the tag in sync; add a CHANGELOG entry for user-visible changes.

## Boundaries

- Never commit secrets, personal data, local absolute paths, speech models, logs or `dist/`, `build/`.
- Treat the Codex Desktop internals as fragile: `Alt+Z`, the button names `Dictate`, `Stop dictation`, `Transcribe and send`, the package name, the `ChatGPT.exe` process and the thread-history database are not covered by tests. Do not change them without checking against an installed Codex.
- Audio must stay local: do not add code that records, stores or uploads audio or dictated text.
- Ask before: adding dependencies, changing the settings file format, publishing a Release, anything that adds network access.

## Done means

- Tests pass; for changes in `app.py`, `wakeword.py` or `ui/` the built exe or the app was started and the changed behaviour was exercised, not only read in code.
- README, CHANGELOG and both language strings are updated when behaviour changes.
