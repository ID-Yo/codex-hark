# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/). Versions follow [SemVer](https://semver.org/).

## [Unreleased]

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
