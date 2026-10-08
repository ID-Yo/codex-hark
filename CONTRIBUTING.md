# Contributing to Codex Hark

Thanks for helping. Small, focused changes are easiest to review.

1. Open an issue first for anything larger than a small fix, so we can agree on the approach.
2. Fork the repository, create a branch, and make the change.
3. Run the tests: `.\.venv\Scripts\python -m unittest discover -s tests`. For changes that touch the exe, run `./build.ps1` too (details in [AGENTS.md](AGENTS.md)).
4. Open a pull request and fill in the template.

Rules:
- One topic per pull request; add or update tests for logic changes.
- Behaviour that depends on Codex Desktop (hotkey, buttons, microphone detection) cannot be unit tested: say how you checked it by hand and with which Codex version.
- No secrets, personal data, local absolute paths or model files in the repository.
- Keep the existing style; Python sources use Windows line endings (CRLF), so keep diffs free of line-ending noise.
