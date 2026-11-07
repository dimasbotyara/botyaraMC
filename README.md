<div align="center">

<img src="assets/banner.svg" alt="botyaraMC Banner" width="100%"/>

<br/>

[![Tests](https://github.com/dimasbotyara/botyaraMC/actions/workflows/tests.yml/badge.svg)](https://github.com/dimasbotyara/botyaraMC/actions/workflows/tests.yml)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Loaders](https://img.shields.io/badge/Loaders-Vanilla%20%7C%20Fabric%20%7C%20Forge%20%7C%20NeoForge%20%7C%20Quilt-cba6f7)](#-features)
[![OS](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-89b4fa)](#-quick-start)
[![Languages](https://img.shields.io/badge/Lang-EN%20%7C%20RU-f9e2af)](#️-bilingual-support--interactive-server-tui)
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
- **Multi-Server Profiles** — Add as many servers as you like in `⚙ Settings` (by IP or LAN auto-discovery) and switch between them in a single click right from the main screen.
- **Isolated Instance Folders (`client_folder`)** — Hosts can configure a custom client folder name so the modpack lives cleanly inside `.minecraft/instances/<client_folder>` while sharing `versions/`, `libraries/`, `assets/`, and `runtime/` from base `.minecraft` without duplicating gigabytes on disk.
- **Server-Side Mod Obfuscation (`hide_mods`)** — Keep secret content or technical mods hidden by cloaking `.jar` filenames on the fly using random word slugs (`silent-amber-otter-42.jar`) or salted HMAC hashes (`mod_7f3a9c12e4b08d51.jar`), globally or selectively. Direct requests to original filenames return `404`.
- **Offline Fallback** — If the sync server is temporarily offline, Minecraft still launches seamlessly from the selected server's cached manifest.

### 🎛️ Bilingual Support (`EN` / `RU`) & Interactive Server TUI
- **Full English & Russian Localization** — Language selection is the **very first step** of the launcher setup wizard (before nickname entry) and switches live in `⚙ Settings`. Server `config.txt` comments, console logs, and the TUI configurator are localized too.
- **Interactive `questionary` TUI (`server/tui.py`)** — Configure every server setting via arrow-key terminal menus, pick selective `.jar` files to cloak via checkboxes, or run step-by-step `--wizard` mode with instant auto-save.

### ☕ Java, Memory & JVM Tuning
- **Java Auto-Detection & Manual Override** — Scans Windows, macOS, and Linux for installed JDKs/JREs (Temurin/Adoptium, Zulu, Liberica, GraalVM, Corretto, Oracle, OpenJDK, Mojang Runtimes) with concise vendor-aware labels (`Java 21 • Temurin (21.0.4)`), honors server `java_version` requirements, or downloads the official Mojang runtime automatically.
- **JVM Presets & Custom Flags Editor** — Built-in **`G1GC`**, **`Aikar's Flags`**, **`ZGC`** (auto-enables `-XX:+ZGenerational` on Java 21–22 and safely falls back to G1GC on Java < 17), and **`Minimal`**, plus a custom preset editor and extra JVM flags input.
- **Auto-RAM & Manual Slider** — Smart system memory calculation via `psutil` for low GC pause times, or manual MB slider + exact numeric input.

### 🖥️ Cozy Desktop UX & Crash Diagnostics
- **Time-of-Day Dynamic Greetings** — 240 warm, non-repetitive greetings tailored to morning, afternoon, evening, and night (in English & Russian) that automatically rotate every 10 minutes while the launcher is open.
- **Thoughtful UX Details**:
  - **5 instant live themes** recoloring every widget without restarting;
  - **smooth animated color transitions** on the `▶ PLAY` button on mouse hover/leave;
  - **clean idle main screen** — the progress bar stays hidden until a launch is in progress;
  - **instant Settings auto-save** with no clunky Save/Cancel bar;
  - **strict nickname validation** (`3–16` characters, `a-z`, `A-Z`, `0-9`, and `_` only);
  - **one-click Sign Out & Server Reset** (preserving all Minecraft files and worlds on disk).
- **Quick Folder Opener (`📂 Folders`)** — One-click (or `1–7` number keys) access to the active instance folder, `mods`, `resourcepacks`, `screenshots`, `crash-reports`, and launcher config/logs.
- **Startup Watchdog Timeout** — Detects frozen launches if LWJGL/OpenAL fails to initialize within the configured timeout and terminates hung processes cleanly.
- **Built-in Crash Report Parser + [mclo.gs](https://mclo.gs/) Sharing** — Analyzes `game.log`, `crash-reports/crash-*.txt`, and `hs_err_pid*.log` (`OutOfMemoryError`, Java version mismatches, Fabric/Forge mod conflicts, Mixin errors, OpenGL/GPU driver crashes) and opens a full log viewer with **Copy**, **Share (mclo.gs)** (with automatic OS username & token scrubbing), **Retry launch**, and **Close**.

---

## 🧩 How Mod Management, Server Switching & Instance Folders Work

`botyaraMC` is designed to **never accidentally wipe** a player's personal files or re-download mods unnecessarily:

1. **First Sync on a Non-Empty Folder (`mods/old-mods/`)**  
   If `mods/` already contains pre-existing mods, `.disabled` files, or subfolders before `botyaraMC`'s very first sync, everything inside is safely moved into `mods/old-mods/`. Nothing is lost.
2. **Zero-Download Server Switching (`mods/botyaraMC/`)**  
   When switching from Server A to Server B, `botyaraMC`-installed mods from Server A aren't deleted — they are stashed inside `mods/botyaraMC/`. Switching back to Server A restores matching `SHA-256` jars instantly (`0 B` downloaded!).
3. **Personal Client Mods (`delete_user_mods`)**  
   - With `delete_user_mods = false` *(default)*, players can freely add client-side QoL mods (minimap, shaders) without `botyaraMC` touching them.  
   - With `delete_user_mods = true`, the server enforces a strict modpack and removes extra unmanaged `.jar` files from `mods/`.
4. **Resourcepacks (`resourcepacks/`)**  
   Always synced in **add-only** mode — existing user resourcepacks are never overwritten or deleted.

---

## 🗂 Repository Structure

```text
botyaraMC/
├── assets/
│   ├── banner.svg / banner.png       # English banner (SVG + PNG 1200×360)
│   ├── banner.ru.svg / banner.ru.png # Russian banner (SVG + PNG 1200×360)
│   ├── icon.svg / icon.png / icon.ico# Window & taskbar icons (SVG, PNG & multi-size .ico)
│   └── icon_1080p.png                # High-resolution 1080p icon (1080×1080)
├── server/                           # Runs on the host machine
│   ├── server.py                     # Multi-threaded HTTP server (HTTP Range 206 + Rate Limiter, pure stdlib!)
│   ├── tui.py                        # Interactive questionary TUI configurator
│   ├── srv_config.py                 # Localized config.txt (EN/RU) with live reload
│   ├── mods_index.py                 # SHA-256 indexer + words/hash mod filename obfuscator
│   ├── discovery.py                  # UDP broadcast responder (LAN & Radmin VPN)
│   ├── requirements.txt              # questionary (needed only for tui.py)
│   ├── mods/                         # Drop server/modpack .jar files here
│   └── resourcepacks/                # Drop .zip resourcepacks here
├── launcher/                         # Distributed to players
│   ├── main.py                       # Entry point (routes to GUI or zero-Tk CLI)
│   ├── ui.py / themes.py             # CustomTkinter UI, multi-server profiles, auto-save & themes
│   ├── i18n.py                       # EN/RU translations, 240 time-of-day greetings & strict nick validator
│   ├── sync.py                       # old-mods, mods/botyaraMC stash, HTTP Range resume & SHA-256 sync
│   ├── mc.py / jvm.py                # Version/loader installer, auto-join, Java scanner & JVM presets
│   ├── crash.py                      # Crash analyzer (EN/RU) & mclo.gs v1 JSON API client
│   ├── cli.py / config.py / discovery.py
│   └── requirements.txt
└── tests/
    └── test_botyaramc.py             # Comprehensive pytest suite (Server + TUI + Sync + CLI + GUI)
```

---

## 🚀 Quick Start

### 1. Sync Server (Host)

`server.py` runs on pure **Python 3.10+** standard library with zero external dependencies. Install `questionary` if you want the interactive terminal configurator:

```bash
cd server
pip install -r requirements.txt   # optional, for interactive tui.py

# Option A — configure the server interactively in your terminal:
python tui.py                     # arrow-key menu (or `python tui.py --wizard` for step-by-step setup)

# Option B — start the server right away (auto-generates config.txt, mods/ and resourcepacks/ on first run):
python server.py
```

Checklist for the host:
- Place modpack `.jar` files in `server/mods/` and `.zip` packs in `server/resourcepacks/`.
- Allow **TCP `25456`** (HTTP manifest & file sync) and **UDP `25457`** (LAN / VPN auto-discovery) in your firewall.
- Set `online-mode=false` in your Minecraft server's `server.properties` (since players connect with offline nicknames).

#### `server/config.txt` Reference

All settings except TCP/UDP ports reload **live on the fly** whenever `config.txt` is edited or updated via `tui.py`:

| Key | Default | Description |
|---|---|---|
| `language` | `ru` | Language for server console logs, TUI, and `config.txt` comments (`en` / `ru`) |
| `server_name` | `botyaraMC Server` | Server display name shown in players' launchers |
| `client_folder` | *(empty)* | Optional isolated instance subfolder under `.minecraft/instances/<name>` (empty = base `.minecraft`) |
| `http_port` | `25456` | TCP port serving `/ping`, `/manifest`, `/mods/*`, and `/resourcepacks/*` |
| `discovery_port` | `25457` | UDP port for automatic LAN / Radmin VPN discovery |
| `rate_limit_per_min` | `300` | Max HTTP requests per IP per minute (`0` = disable rate limit) |
| `mc_version` | `1.20.1` | Target Minecraft version installed & launched on clients |
| `loader` | `fabric` | Mod loader: `fabric`, `forge`, `neoforge`, `quilt`, or `none` (Vanilla) |
| `java_version` | `auto` | Required major Java version (`auto`, `8`, `17`, `21`, etc.) |
| `delete_user_mods` | `false` | Delete extra unmanaged `.jar` mods added manually by players (`true` = strict modpack, `false` = allow client QoL mods) |
| `hide_mods` | `none` | Mod filename cloaking: `none`, `words` (`silent-amber-otter-42.jar`), or `hash` (`mod_7f3a9c12e4b08d51.jar`) |
| `hide_mods_list` | *(empty)* | Comma-separated `.jar` filenames to cloak selectively (empty = cloak all mods when `hide_mods != none`) |
| `auto_join` | `true` | Automatically join the Minecraft server upon launch (`true` / `false`) |
| `minecraft_server` | `127.0.0.1` | Minecraft server IP (`127.0.0.1` / `auto` automatically resolves to the sync server IP for remote players!) |
| `minecraft_port` | `25565` | Minecraft server port |

---

### 2. Launcher (Players)

```bash
cd launcher
pip install -r requirements.txt
python main.py
```

On first launch, a **4-step setup wizard** walks through:
1. **Language** (`English` / `Русский`)
2. **Nickname** (`3–16` characters: `a-z`, `A-Z`, `0-9`, and `_` only)
3. **Color Theme** (with instant live preview)
4. **Sync Server** (enter IP or click **🔍 Auto-Find**)

> 💡 **Host Tip:** Open `⚙ Settings`, enable **👑 Host Mode**, and select your Minecraft server's `mods/` directory — pressing `▶ PLAY` will keep both your client mods and your dedicated server's `mods/` synced simultaneously.

---

## 🤖 CLI Mode & Automation

Run `botyaraMC` headlessly without importing Tkinter — ideal for custom shortcuts, shell scripts, headless machines, and `systemd` user services:

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
| `--server HOST[:PORT]` | Sync server address (e.g. `26.12.34.56` or `26.12.34.56:25456`) |
| `--mc-dir PATH` | Path to base `.minecraft` directory |
| `--ram MB` | Fixed RAM allocation in MB (e.g. `6144`) |
| `--auto-ram` | Automatically calculate RAM based on system memory |
| `--java PATH` | Explicit path to `java` executable |
| `--jvm-preset NAME` | JVM preset (`G1GC`, `"Aikar's Flags"`, `ZGC`, `Minimal`, or custom preset name) |
| `--jvm-args FLAGS` | Extra JVM arguments appended to the preset |
| `--fullscreen` | Launch Minecraft in fullscreen mode |
| `--resolution WxH` | Custom window resolution (e.g. `1920x1080`) |
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

Launcher settings (`config.json`), managed mod state (`managed.json`), per-server manifest caches (`manifest_cache_*.json`), and logs (`launcher.log`, `game.log`, `game.prev.log`) are stored in the standard OS user config directory:

- **Windows:** `%APPDATA%\botyaraMC`
- **Linux:** `~/.config/botyaraMC`
- **macOS:** `~/Library/Application Support/botyaraMC`
- *(Override for portable mode or testing via the `BOTYARAMC_CONFIG_DIR` environment variable)*

<details>
<summary><strong>📦 Packaging into a Single Windows <code>.exe</code> (PyInstaller)</strong></summary>

```powershell
cd launcher
pip install -r requirements.txt pyinstaller
pyinstaller --noconfirm --onefile --windowed --name botyaraMC `
  --icon icon.ico `
  --add-data "icon.ico;." `
  --add-data "icon.png;." `
  --collect-all customtkinter `
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
