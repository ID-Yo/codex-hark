# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/). Versions follow [SemVer](https://semver.org/).

## [Unreleased]

## [0.14.0] - 2026-10-09

### Added
- Self-update: when the check finds a newer release, Hark downloads its `CodexHark.exe`, checks it against the release `SHA256SUMS.txt`, swaps the exe and restarts as the new version. It waits until no conversation or dictation is open. **Settings > Install updates automatically** (on by default) turns it off; **Update now** installs at once. Only download links of this repository are used, and a file that does not match its SHA256 is deleted.

## [0.13.0] - 2026-10-09

### Added
- About links to the donation pages (Buy Me a Coffee, PayPal).

### Changed
- Discard and Save are at the top right and stay there while you scroll, so unsaved changes are hard to miss.

## [0.12.0] - 2026-10-09

### Added
- Update check: Hark asks GitHub for the newest public release a minute after start and every 12 hours, and shows a notification with a download link when there is a newer version. **Settings > New versions** has the on/off switch (on by default) and a **Check now** button. Hark does not download or install anything by itself.

## [0.11.1] - 2026-10-09

### Fixed
- "One project" and "One chat" really put the voice chat there. The Codex voice chat key always starts a chat outside any project, so Hark now opens the target and presses the Codex voice chat button in it ("Start new voice chat" / "Start voice chat"); the key is only the fallback.

## [0.11.0] - 2026-10-09

### Added
- Voice commands > Voice chat > "Conversations go to": a new chat each time (as before), one chat you pick, or a new chat in one project you pick. Hark opens the chat or project in Codex (codex:// link) before it presses the voice chat key, so the conversations collect there.

## [0.10.0] - 2026-10-09

### Changed
- About has its own tab next to Settings.
- Settings: the general options (interface language first) are on top; below them, recognition languages on the left and a Windows card (start with Windows, data folder, defaults) on the right.

## [0.9.0] - 2026-10-09

### Changed
- English first: the English model is bundled in the exe and a new install listens in English only. Bulgarian is now an added language that can be removed; it keeps working for existing settings, and its model is downloaded once after the update.
- Recognition languages moved from Voice commands to Settings, so the words stay at the top of Voice commands.
- The interface language choice lists English first.

## [0.8.0] - 2026-10-09

### Added
- Add a recognition language in Voice commands: German, French, Spanish, Italian, Polish, Dutch or Ukrainian. Each comes with words its model knows; the model is downloaded and checked after you save, and an added language can be removed again.

### Removed
- The ChatGPT Classic commands from 0.7.0. ChatGPT voice uses a model and tokens just like Codex, so they added nothing. Old settings for them are ignored.

## [0.7.0] - 2026-10-09

### Added
- About card in Settings: description, version, author and the link to https://IvanYosifov.com.
- On the first start Hark checks that Codex has keys for voice chat and dictation (`realtimeVoice` and `globalDictationHold` in `keybindings.json`) and adds the missing ones; a key you chose is kept and used. Settings has a button to run the check again.

### Changed
- The window starts smaller and always fits the screen (about 880x590 on a 1280x720 screen).
- Smaller fonts and controls throughout.
- The app is called Hark everywhere instead of "listener".

## [0.6.0] - 2026-10-09

### Added
- Wake phrases of up to three words, for example "hey jarvis" or „хей кодекс“.
- Word check in Voice commands: while you type, the window says whether the speech model knows each word, so an unusable word is refused before Save. Saved words the model does not know are marked in red.
- The listener warns at start (notification and Activity entry) when a word is missing from the model.

### Fixed
- Words typed for a language whose model was not loaded were accepted and then silently ignored.
- The English tray menu and notifications say "Codex Hark" instead of "Codex Listener".

## [0.5.0] - 2026-10-08

### Changed
- The exe no longer bundles the ASIO-enabled PortAudio libraries that came with sounddevice; Hark never used them.
- Renamed the project and the app to Codex Hark (`CodexHark.exe`). Settings in `%APPDATA%\CodexSlushatel` and the old start-up entry are moved automatically on first start.
- English README, MIT license, contributing and security documents.

## [0.4.0] - 2026-10-07

### Added
- Recognition language packs (Bulgarian and English) with their own words.
- "Codex, draft" phrase: dictation that stays in the input box for review.

## [0.3.0] - 2026-10-07

### Added
- Voice chat stays open while Codex is working.
- "Codex, stop" phrase closes the voice chat at once.

## [0.2.0] - 2026-10-07

### Added
- App window with five screens, Bulgarian and English interface, new icon, start with Windows and tray menu.

## [0.1.1] - 2026-10-07

### Fixed
- Starts even when WMI hangs.

## [0.1.0] - 2026-10-07

- First version: "Codex" opens voice chat with `Alt+Z`, closes it after silence; "Codex, write" starts dictation.
