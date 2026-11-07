<div align="center">

<img src="assets/banner.en.svg" alt="botyaraMC Banner" width="100%"/>

<br/>

[![Tests](https://github.com/dimasbotyara/botyaraMC/actions/workflows/tests.yml/badge.svg)](https://github.com/dimasbotyara/botyaraMC/actions/workflows/tests.yml)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Loaders](https://img.shields.io/badge/Loaders-Vanilla%20%7C%20Fabric%20%7C%20Forge%20%7C%20NeoForge%20%7C%20Quilt-cba6f7)](#-features)
[![OS](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-89b4fa)](#-quick-start)
[![Languages](https://img.shields.io/badge/Lang-EN%20%7C%20RU-f9e2af)](#-bilingual-support--interactive-server-tui)
[![mclo.gs](https://img.shields.io/badge/Crash%20Sharing-mclo.gs-5cb85c)](https://mclo.gs)
[![License: MIT](https://img.shields.io/badge/License-MIT-a6e3a1.svg)](LICENSE)

<p>
  <strong>🇬🇧 English</strong> &nbsp;·&nbsp; <a href="README.ru.md">🇷🇺 Русский</a>
</p>

</div>

---

## ✨ What is botyaraMC?

**botyaraMC** is a clean, lightweight, zero-bloat Minecraft launcher paired with a self-hosted Python sync server — built specifically for playing modded Minecraft with friends over **Radmin VPN**, **Tailscale**, **ZeroTier**, or **LAN**.

No more sending 500 MB `.zip` archives over Discord or Telegram every time you add or update a couple of mods:
1. **The Host** configures the server via the interactive terminal TUI (`python tui.py`) or `config.txt` and drops `.jar` mods into `server/mods/` and `.zip` packs into `server/resourcepacks/`.
2. **Friends** press **`▶ PLAY`** — the launcher auto-discovers the server over UDP, previews the exact download size, resumes interrupted downloads via `HTTP Range`, verifies `SHA-256` checksums, installs the required Minecraft version, mod loader & Java runtime, and connects straight into the server when `auto_join` is enabled.

---

## 🧭 Table of Contents

- [Features](#-features)
- [How Mod Management, Server Switching & Instance Folders Work](#-how-mod-management-server-switching--instance-folders-work)
- [Repository Structure](#-repository-structure)
- [Quick Start](#-quick-start)
  - [1. Sync Server (Host)](#1-sync-server-host)
  - [2. Launcher (Players)](#2-launcher-players)
- [CLI Mode & Automation](#-cli-mode--automation)
- [Keyboard Shortcuts](#️-keyboard-shortcuts)
- [Color Themes](#-color-themes)
- [Config & Log Locations + Building a Standalone `.exe`](#-config--log-locations--building-a-standalone-exe)
- [Running Tests](#-running-tests)

---

## 🔥 Features

### 📦 Smart Sync, Multi-Server & Mod Cloaking
- **Upfront Download Size Preview** — Before launching, the Play button displays the exact remaining download size (e.g. `▶ PLAY • Download 45 MB`) along with live MB progress.
- **Resumable Downloads (`HTTP Range`) & Per-IP Rate Limiting** — Interrupted transfers keep their `.part` state and resume from the exact byte via `206 Partial Content`, verified end-to-end with `SHA-256`. A sliding-window per-IP rate limiter (`rate_limit_per_min`, default `300/min`) protects the server and pairs with automatic `Retry-After` handling on the client.
- **Multi-Server Profiles** — Add as many servers as you like in `⚙ Settings` (by IP, domain, or LAN auto-discovery) and switch between them in a single click right from the main screen.
- **Smart UDP Discovery** — When a server's IP changes, the launcher gracefully updates the selected server's address in place, never "hijacking" to a different server when multiple exist.
- **Isolated Instance Folders (`client_folder`)** — Hosts can configure a custom client folder name so the modpack lives cleanly inside `.minecraft/home/` with your chosen isolation mode (`family` → `Fabric-1.16`, `version` → `Fabric 1.16.5`), while sharing `versions/`, `libraries/`, `assets/`, and `runtime/` from base `.minecraft` without duplicating gigabytes on disk.
- **Rename Pack Folder in Launcher** — Don't like the folder name? In `⚙ Settings` you can rename a server's pack folder (worlds, mods, settings move automatically) or reset to auto-name — all without manual copying.
- **Per-Server Manifest Caches** — Each server has its own isolated cache (`manifest_cache_<id>.json`), switching between servers is instant and conflict-free.
- **Server-Side Mod Obfuscation (`hide_mods`)** — Keep secret content or technical mods hidden by cloaking `.jar` filenames on the fly using random word slugs (`silent-amber-otter-42.jar`) or salted HMAC hashes (`mod_7f3a9c12e4b08d51.jar`), globally or selectively. Direct requests to original filenames return `404`.
- **Offline Fallback** — If the sync server is temporarily offline, Minecraft still launches seamlessly from the selected server's cached manifest.
- **Non-Destructive `delete_user_mods`** — When enabled, extra `.jar` files are safely moved to `mods/old-mods/` instead of being deleted.

### 🌐 Domain Addresses & Auto MC-Server Resolution
- **Hosting Domains + IDN + `:port`** — In both launcher settings and server TUI, you can specify not just numeric IPs but also domains (`play.example.com:25456`) or internationalized domains (`мой-сервер.рф`).
- **`minecraft_server = "auto"` on Server** — In `config.txt`, set `minecraft_server = "auto"` and the Python server will automatically use the sync client's address (handy when both sync and MC server run on the same machine).

### 🎨 Custom Server Background
- **Server Background in Launcher** — The host drops `background.png` / `.jpg` / `.jpeg` / `.webp` into the `server/` root — the image is served via `/background`, cached by `SHA-256`, and beautifully rendered on the launcher's main screen (toggleable in `⚙ Settings`).

### 👑 Host Mode — Unique Folders & Safe Coexistence
- **Mandatory Unique Folders** — The "I'm the host" setting requires selecting a Minecraft server mods folder that **does not clash** with any other saved server's folder (reusing a folder is allowed if it was deleted on disk or the server was removed).
- **Sync Server Self-Protection** — The launcher refuses to let you accidentally pick the Python sync server's own serving folder as `server_mods_dir`.
- **Python Host Playing via Launcher** — Fully supported: sync mods to the MC server folder, then play yourself through the launcher — no conflicts.

### 📁 Version Isolation Modes
| Mode | Path | Description |
|------|------|-------------|
| **No separate folders** | `.minecraft` | Classic shared folder, all versions together |
| **Per family** | `home/Fabric-1.16` | Shared folder per major version (1.16, 1.20, …) |
| **Per version** | `home/Fabric 1.16.5` | Separate folder per exact version (like MultiMC/PolyMC) |

Each folder gets a `botyaramc.json` marker — if you rename the folder in Explorer/Dolphin, the launcher detects it and won't break.

### 🐧 Linux: GameMode & MangoHud
- **Feral GameMode (`gamemoderun`)** — Separate toggle in Settings (Linux only), verifies binary presence via `shutil.which`.
- **MangoHud (`mangohud`)** — Separate toggle for FPS overlay, also with install check.
- Work independently — enable both, one, or neither.

### 🖥️ Cozy Desktop UX & Crash Diagnostics
- **Time-of-Day Dynamic Greetings** — 240 warm, non-repetitive greetings tailored to morning, afternoon, evening, and night (English & Russian) that auto-rotate every 10 minutes while the launcher is open. Press **`R`** on the main screen to randomize instantly!
- **Thoughtful UX Details**:
  - **5 instant live themes** recoloring every widget without restart;
  - **Smooth animated color transitions** on the `▶ PLAY` button on hover/leave;
  - **Perfectly centered main screen** — the hero block (`botyaraMC`, greeting, `▶ PLAY`) is anchored at true center (vertically & horizontally); progress/status live in a separate lower container;
  - **Top bar symmetry** — `Auto-RAM: ... • 🌐 <Server Name>` aligned at 34 px height with top-right buttons; JVM preset name removed, showing selected server name instead;
  - **`▶ PLAY` stays in hover color** (`accent_hover`) while game runs, text changes to `🎮 GAME RUNNING` / `🎮 ИГРА ЗАПУЩЕНА`;
  - **Window behavior on launch** — `Keep open` / `Minimize` / `Hide until game exits` (with auto-restore);
  - **Live Minecraft Server Ping** — badge `🟢 Online: X/Y • Z ms` / `⚪ Minecraft server is currently offline` updates every 10 seconds;
  - **Instant Settings auto-save** with no Save/Cancel bar;
  - **No mouse-scroll value changes** on any Settings widget (sliders, dropdowns, etc.);
  - **Strict nickname validation** (`3–16` chars, `a-z`, `A-Z`, `0-9`, `_` only);
  - **Sign Out & Full Config Wipe** — `🚪 Sign out of botyaraMC & remove servers` deletes `~/.config/botyaraMC` (Linux) / `%APPDATA%\botyaraMC` (Windows) / `~/Library/Application Support/botyaraMC` (macOS) entirely, returning to the setup wizard.
- **Quick Folder Opener (`📂 Folders`)** — One-click (or `1–7` keys) access to the active instance folder, `mods`, `resourcepacks`, `screenshots`, `crash-reports`, and launcher config/logs.
- **Startup Watchdog Timeout** — Detects frozen launches if LWJGL/OpenAL fails to initialize within the configured timeout and terminates hung processes cleanly.
- **Built-in Crash Report Parser + [mclo.gs](https://mclo.gs/) Sharing** — Analyzes `game.log`, `crash-reports/crash-*.txt`, and `hs_err_pid*.log` (`OutOfMemoryError`, Java version mismatches, Fabric/Forge mod conflicts, Mixin errors, OpenGL/GPU driver crashes) and opens a full log viewer with **Copy**, **Share (mclo.gs)** (with automatic OS username & token scrubbing), **Retry launch**, and **Close**.

### ☕ Java, Memory & JVM Tuning
- **Java Auto-Detection & Manual Override** — Scans Windows, macOS, and Linux for installed JDKs/JREs (Temurin/Adoptium, Zulu, Liberica, GraalVM, Corretto, Oracle, OpenJDK, Mojang Runtimes) with concise vendor-aware labels (`Java 21 • Temurin (21.0.4)`), honors server `java_version` requirements, or downloads the official Mojang runtime automatically.
- **JVM Presets & Custom Flags Editor** — Built-in **`G1GC`**, **`Aikar's Flags`**, **`ZGC`** (auto-enables `-XX:+ZGenerational` on Java 21–22 and safely falls back to G1GC on Java < 17), and **`Minimal`**, plus a custom preset editor and extra JVM flags input.
- **Auto-RAM & Manual Slider** — Smart system memory calculation via `psutil` for low GC pause times, or manual MB slider + exact numeric input.

---

## 🧩 How Mod Management, Server Switching & Instance Folders Work

`botyaraMC` is designed to **never accidentally wipe** a player's personal files or re-download mods unnecessarily:

1. **First Sync on a Non-Empty Folder (`mods/old-mods/`)**
   If `mods/` already contains pre-existing mods, `.disabled` files, or subfolders before `botyaraMC`'s very first sync, everything inside is safely moved into `mods/old-mods/`. Nothing is lost.
2. **Zero-Download Server Switching (`mods/botyaraMC/`)**
   When switching from Server A to Server B, `botyaraMC`-installed mods from Server A aren't deleted — they are stashed inside `mods/botyaraMC/`. Switching back to Server A restores matching `SHA-256` jars instantly (`0 B` downloaded!).
3. **Personal Client Mods (`delete_user_mods`)**
   - With `delete_user_mods = false` *(default)*, players can freely add client-side QoL mods (minimap, shaders) without `botyaraMC` touching them.
   - With `delete_user_mods = true`, the server enforces a strict modpack and extra unmanaged `.jar` files are safely moved to `mods/old-mods/`.
4. **Resourcepacks (`resourcepacks/`)**
   Always synced in **add-only** mode — existing user resourcepacks are never overwritten or deleted. Server resourcepack updates happen via `SHA-256` comparison, and new ones are auto-enabled in `options.txt` once.

---

## 🗂 Repository Structure

```
botyaraMC/
├── server/                    # Python sync server (host)
│   ├── server.py              # HTTP server (manifest, files, Range, rate-limit, /background)
│   ├── mods_index.py          # Scanning mods/ & resourcepacks/, mod cloaking, background
│   ├── srv_config.py          # Server config (config.txt) + TUI utilities
│   ├── tui.py                 # Interactive configurator (questionary)
│   ├── discovery.py           # UDP server announcement in LAN/VPN
│   └── requirements.txt       # aiohttp, psutil, questionary, Pillow
│
├── launcher/                  # Launcher (GUI + CLI)
│   ├── main.py                # Entry point
│   ├── cli.py                 # CLI mode (python main.py --play ...)
│   ├── ui.py                  # GUI on CustomTkinter (wizard, main, settings, dialogs)
│   ├── config.py              # Launcher config, multi-server, folders, botyaramc.json markers
│   ├── sync.py                # HTTP client, smart download, SHA-256, old-mods/, background cache
│   ├── mc.py                  # .minecraft finder, version install, MC ping, GameMode, MangoHud, launch
│   ├── discovery.py           # UDP sync server discovery (discover_all + match_discovered_server)
│   ├── jvm.py                 # Java detection, JVM presets (G1GC, Aikar, ZGC, Custom)
│   ├── crash.py               # Crash parser + mclo.gs upload
│   ├── themes.py              # 5 live themes (Catppuccin Mocha/Latte, Gruvbox, Ayu, Monokai)
│   ├── i18n.py                # RU/EN localization, time-of-day greetings, nickname validation
│   ├── requirements.txt       # customtkinter, minecraft-launcher-lib, psutil, Pillow, pytest
│   └── icon.ico / icon.png    # App icons
│
├── tests/
│   └── test_botyaramc.py      # Comprehensive tests (10 tests, cover everything)
│
├── assets/
│   ├── banner.en.svg / .png   # English banner ("Smart Download")
│   └── banner.ru.svg / .png   # Russian banner ("Умная докачка")
│
├── README.md                  # English documentation (this file)
├── README.ru.md               # Russian documentation
└── LICENSE
```

---

## 🚀 Quick Start

### 1. Sync Server (Host)

```bash
cd server
pip install -r requirements.txt

# Interactive (recommended):
python tui.py          # full menu
python tui.py --wizard # step-by-step wizard

# Or edit config.txt manually:
# minecraft_server = "auto"           # or MC server IP/domain (play.example.com:25565)
# serve_background = true             # serve background.png via /background
# sync_port = 25456
# rate_limit_per_min = 300
# hide_mods = "words"                 # "words" | "hash" | "[]" | list of files
# salt = "super-secret"               # salt for hash mode
# auto_join = true
```

**Important:** place `.jar` mods in `server/mods/`, `.zip` resourcepacks in `server/resourcepacks/`. For custom background — `background.png` / `.jpg` / `.jpeg` / `.webp` in `server/`.

Run:
```bash
python server.py
```
The server will start announcing itself via UDP on LAN/VPN — player launchers will find it automatically.

### 2. Launcher (Players)

```bash
cd launcher
pip install -r requirements.txt
python main.py
```

**First-Run Wizard (4 steps):**
1. 🌐 Interface language (RU/EN)
2. ✏️ In-game nickname (strict validation)
3. 🎨 Color theme (live preview)
4. 🔍 Sync server address — enter IP/domain or click **"Auto-Find"**

After the wizard finishes, the main screen opens. Hit **`▶ PLAY`** — the launcher downloads files, prepares the Minecraft version, and launches the game.

---

## 💻 CLI Mode & Automation

```bash
cd launcher

# Sync mods + resourcepacks and launch immediately:
python main.py --lang en --play --nick Steve

# Full custom launch (server override, Auto-RAM, Aikar's Flags, fullscreen, auto-upload crash to mclo.gs):
python main.py --lang en --play --nick Steve --server 26.12.34.56 --auto-ram --jvm-preset "Aikar's Flags" --fullscreen --share-crash

# Sync modpack & prepare MC version without launching a window (works without X11!):
python main.py --sync-only --server 26.12.34.56

# List all Java installations detected on the machine:
python main.py --detect-java
```

#### CLI Flags Reference

| Flag | Description |
|---|---|
| `--play` | Sync files and launch Minecraft without GUI |
| `--sync-only` | Only sync mods/resourcepacks and install the MC version without starting the game |
| `--detect-java` | Print all detected Java installations on the system and exit |
| `--lang {ru,en}` | Output and crash diagnostics language (`en` or `ru`) |
| `--nick NICK` | In-game nickname (`3–16` chars: `A-Za-z0-9_`) |
| `--server HOST[:PORT]` | Sync server address (IP, domain, or IDN, e.g. `play.example.com:25456`) |
| `--mc-dir PATH` | Path to base `.minecraft` directory |
| `--isolation {none,family,version}` | Version folder isolation mode |
| `--ram MB` | Fixed RAM allocation in MB (e.g. `6144`) |
| `--auto-ram` | Automatically calculate RAM based on system memory |
| `--java PATH` | Explicit path to `java` executable |
| `--jvm-preset NAME` | JVM preset (`G1GC`, `"Aikar's Flags"`, `ZGC`, `Minimal`, or custom preset name) |
| `--jvm-args FLAGS` | Extra JVM arguments appended to the preset |
| `--fullscreen` | Launch Minecraft in fullscreen mode |
| `--resolution WxH` | Custom window resolution (e.g. `1920x1080`) |
| `--gamemode` | (Linux) Wrap launch with `gamemoderun` |
| `--mangohud` | (Linux) Enable `mangohud` FPS overlay |
| `--timeout SEC` | Startup initialization timeout in seconds (`0` to disable) |
| `--no-wait` | Detach immediately after starting the game process |
| `--share-crash` | Automatically upload crash logs to `https://mclo.gs` and print the link |

<details>
<summary><strong>📋 Example <code>systemd</code> User Unit (<code>~/.config/systemd/user/botyaramc.service</code>)</strong></summary>

```ini
[Unit]
Description=botyaraMC Auto-Sync & Launch
After=network-online.target

[Service]
Type=simple
WorkingDirectory=%h/botyaraMC/launcher
ExecStart=/usr/bin/python3 main.py --lang en --play --nick Steve --auto-ram --share-crash
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
```

`botyaraMC` forwards `SIGTERM` and `SIGINT` cleanly to the child JVM process on `systemctl --user stop botyaramc`.

</details>

---

## ⌨️ Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| `Enter` / `Ctrl + P` | Launch Minecraft (from main screen) |
| `R` / `К` (Cyrillic) | **Randomize greeting** |
| `F5` / `Ctrl + R` | Refresh server manifest & recalculate download size |
| `Ctrl + O` | Open quick folder selector (`1–7` keys inside) |
| `Ctrl + L` | Open latest game log viewer (`game.log`) |
| `Ctrl + ,` | Open `⚙ Settings` |
| `Esc` | Close active dialog or leave `⚙ Settings` |
| `F1` | Show keyboard shortcuts cheat sheet |

---

## 🎨 Color Themes

All themes switch instantaneously live (both in the setup wizard and in `⚙ Settings`):

| Theme | Mode | Background | Accent |
|---|---|---|---|
| **Catppuccin Mocha** *(default)* | Dark | `#1e1e2e` | `#cba6f7` |
| **Catppuccin Latte** | Light | `#eff1f5` | `#8839ef` |
| **Gruvbox** | Dark | `#282828` | `#fabd2f` |
| **Ayu** | Dark | `#1f2430` | `#ffcc66` |
| **Monokai** | Dark | `#272822` | `#a6e22e` |

---

## 🛠 Config & Log Locations + Building a Standalone `.exe`

Launcher settings (`config.json`), managed mod state (`managed.json`), per-server manifest caches (`manifest_cache_<id>.json`), and logs (`launcher.log`, `game.log`, `game.prev.log`) are stored in the standard OS user config directory:

- **Windows:** `%APPDATA%\botyaraMC`
- **Linux:** `~/.config/botyaraMC`
- **macOS:** `~/Library/Application Support/botyaraMC`
- *(Override for portable mode or testing via the `BOTYARAMC_CONFIG_DIR` environment variable)*

<details>
<summary><strong>📦 Packaging into a Single Windows <code>.exe</code> (PyInstaller)</strong></summary>

```powershell
cd launcher
pip install -r requirements.txt pyinstaller
pyinstaller --noconfirm --onefile --windowed --name botyaraMC ^
  --icon icon.ico ^
  --add-data "icon.ico;." ^
  --add-data "icon.png;." ^
  --collect-all customtkinter ^
  main.py
```

The standalone executable will be generated at `launcher/dist/botyaraMC.exe` with native Windows titlebar and taskbar icons.

</details>

---

## 🧪 Running Tests

The automated test suite verifies the HTTP Range sync server, mid-stream disconnect recovery, per-IP rate limiting (`429` + `Retry-After`), mod cloaking (`words`, `hash`, selective), `old-mods/` migration and `mods/botyaraMC/` server-switch caching, `delete_user_mods`, add-only resourcepack sync, isolated `client_folder` instances, `auto_join`, TUI validators, Java detection, JVM presets, launch timeout watchdog, crash report parser, `mclo.gs` privacy scrubbing, time-of-day greetings, strict nickname validation, headless CLI, and all CustomTkinter UI views:

```bash
pip install -r launcher/requirements.txt -r server/requirements.txt pytest
pytest -v
```

---

## 📄 License

Released under the [MIT License](LICENSE) © [dimasbotyara](https://github.com/dimasbotyara).