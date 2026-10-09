# Third-party components

Codex Hark is released under the MIT License (see [LICENSE](LICENSE)). The release exe bundles the components below, each under its own license. Versions are the ones pinned or resolved at build time; licenses were read from the installed package metadata on 2026-10-08 unless noted.

| Component | Version | License | Notes |
|---|---|---|---|
| Vosk (`vosk`) | 0.3.45 | Apache-2.0 | Offline speech recognition |
| Vosk model `vosk-model-small-en-us-0.15` | - | Apache-2.0 | Bundled; license from the [Vosk models page](https://alphacephei.com/vosk/models) |
| Vosk models `vosk-model-small-ru-0.22` (Bulgarian), `vosk-model-small-de-0.15`, `-fr-0.22`, `-es-0.42`, `-it-0.22`, `-pl-0.22`, `-nl-0.22`, `-uk-v3-nano` | - | Apache-2.0 | Downloaded only when the language is added; same source |
| sounddevice | 0.5.6 | MIT | Includes PortAudio (MIT) binaries; the ASIO-enabled builds (Steinberg ASIO API) that come with the wheel are removed at build time and are not distributed |
| NumPy | 2.5.3 | BSD-3-Clause and others (see package) | |
| pycaw | 20260927 | MIT | Audio session meters |
| comtypes | 1.4.17 | MIT | Windows UI Automation |
| psutil | 7.2.2 | BSD-3-Clause | |
| pystray | 0.19.5 | LGPL-3.0 | See "LGPL component" below |
| Pillow | 12.3.0 | MIT-CMU | Tray icon drawing |
| pywebview | 6.2.1 | BSD-3-Clause | Window; uses the system WebView2 Runtime (not bundled) |
| pythonnet, clr_loader | 3.2.0, 0.3.1 | MIT (pythonnet); clr_loader states no license in its metadata, verify upstream | pywebview dependency |
| bottle, proxy_tools, typing_extensions | 0.13.4, 0.1.0, 4.16.0 | MIT, MIT, PSF-2.0 | pywebview dependencies |
| requests, urllib3, idna, charset-normalizer, certifi | 2.34.2, 2.8.0, 3.20, 3.5.2, 2026.7.22 | Apache-2.0, MIT, BSD-3-Clause, MIT, MPL-2.0 | Vosk dependencies; unmodified |
| cffi, pycparser, srt, tqdm, websockets | 2.1.1, 3.1, 3.5.3, 4.70.1, 17.2 | MIT-0, BSD-3-Clause, MIT, MPL-2.0 and MIT, BSD-3-Clause | Vosk dependencies; unmodified |
| six, colorama | 1.17.0, 0.4.6 | MIT, BSD | Other transitive dependencies |
| PyInstaller | 6.22.3 | GPL-2.0-or-later with a special exception | Build tool; its bootloader is embedded in the exe, and the exception allows distributing the result under any license |

The Codex Desktop app, its name and its icon belong to OpenAI. Codex Hark is not affiliated with OpenAI.

## LGPL component

pystray is licensed under the LGPL-3.0 and is bundled unmodified. To run Hark with another version of it, change the pin in `requirements.txt` and build with `./build.ps1`.
