<div align="center">

<img src="assets/banner.svg" alt="botyaraMC Banner" width="100%"/>

<br/>

[![Tests](https://github.com/dimasbotyara/botyaraMC/actions/workflows/tests.yml/badge.svg)](https://github.com/dimasbotyara/botyaraMC/actions/workflows/tests.yml)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Loaders](https://img.shields.io/badge/Loaders-Vanilla%20%7C%20Fabric%20%7C%20Forge%20%7C%20NeoForge%20%7C%20Quilt-cba6f7)](#-возможности)
[![OS](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-89b4fa)](#-быстрый-старт)
[![mclo.gs](https://img.shields.io/badge/Crash%20Sharing-mclo.gs-5cb85c)](https://mclo.gs)
[![License: MIT](https://img.shields.io/badge/License-MIT-a6e3a1.svg)](LICENSE)

<p>
  <a href="README.md">🇬🇧 English</a> &nbsp;·&nbsp; <strong>🇷🇺 Русский</strong>
</p>

</div>

---

## ✨ Что такое botyaraMC?

**botyaraMC** — это минималистичный, быстрый и уютный лаунчер Minecraft в паре с собственным Python-сервером синхронизации модов и ресурспаков. Создан специально для игры с друзьями по **Radmin VPN**, **Tailscale**, **ZeroTier** или **локальной сети**.

Больше не нужно каждый раз пересылать архивы со сборкой на 400 МБ в Telegram или Discord:
1. **Хост** просто закидывает `.jar` в `server/mods/` и `.zip` в `server/resourcepacks/`.
2. **Друзья** нажимают **`▶ ИГРАТЬ`** — лаунчер сам находит сервер по UDP, докачивает недостающие файлы с поддержкой HTTP `Range`, сверяет `SHA-256`, ставит нужную версию игры, загрузчик и Java, после чего сразу подключает игрока к серверу.

---

## 🔥 Возможности

### 📦 Умная синхронизация и скрытие модов
- **Показ суммарного размера до скачивания** — ещё до запуска кнопка показывает точный объём докачки (например `▶ ИГРАТЬ • Скачать 45 МБ`) и живой прогресс в мегабайтах.
- **Докачка прерванных загрузок (`HTTP Range`)** — при обрыве соединения `.part`-файлы не пропадают, а докачиваются ровно с места разрыва через `206 Partial Content` с финальной проверкой `SHA-256`.
- **Бережное отношение к файлам игрока**:
  - Свои клиентские моды (миникарта, шейдеры, оптимизация) лаунчер **не трогает** — удаляются только устаревшие моды, поставленные самим лаунчером (`managed.json`).
  - Ресурспаки (`server/resourcepacks/*.zip`) синхронизируются **строго на добавление новых** — существующие ресурспаки игрока никогда не удаляются и не перезаписываются.
- **Скрытие названий модов на сервере (`hide_mods`)** — хочешь сохранить интригу в сборке или спрятать античит? Сервер умеет на лету маскировать имена `.jar` под красивые случайные слова (`silent-amber-otter-42.jar`) или криптохэш с секретной солью (`mod_7f3a9c12e4b08d51.jar`) — для всех модов сразу или только выбранных. Прямой доступ по исходному имени отдаёт `404`.
- **Офлайн-режим по кэшу** — если sync-сервер временно недоступен, игра всё равно запустится по последнему сохранённому манифесту.

### ☕ Java, память и тюнинг JVM
- **Автодетект и ручной выбор Java** — сканирует установленные JDK/JRE (Temurin/Adoptium, Zulu, Liberica, GraalVM, Oracle, OpenJDK и рантаймы Mojang) на Windows, macOS и Linux, учитывает требуемую сервером `java_version` или автоматически докачивает официальный рантайм Mojang.
- **JVM-пресеты и редактор флагов** — встроенные профили **`G1GC`**, **`Aikar's Flags`**, **`ZGC`** (автоматически включает `-XX:+ZGenerational` на Java 21–22 и безопасно откатывается на G1GC при Java < 17) и **`Минимальный`**, плюс визуальный редактор своих пресетов и поле для дописывания дополнительных параметров JVM.
- **Авто-RAM по системе и ручной выбор** — умный расчёт оптимального объёма памяти через `psutil` без лишних фризов сборщика мусора либо ручной ползунок + ввод точного числа в МБ.

### 🖥️ Удобство интерфейса и разбор крашей
- **5 живых тем оформления** — *Catppuccin Mocha*, *Catppuccin Latte*, *Gruvbox*, *Ayu (Mirage)* и *Monokai* — мгновенно перекрашивают весь лаунчер без перезапуска.
- **Режимы окна игры** — обычное окно, `Полный экран` (`--fullscreen`) или своё разрешение `Ширина × Высота` с быстрыми пресетами (`1280×720`, `1600×900`, `1920×1080`, `2560×1440`).
- **Быстрое открытие папок (`📂 Папки`)** — в один клик (или клавишами `1–6`) открывает `.minecraft`, `mods`, `resourcepacks`, `screenshots`, `crash-reports` и папку логов/настроек лаунчера.
- **Таймаут запуска** — отслеживает инициализацию LWJGL/OpenAL и аккуратно завершает зависший на старте процесс с понятной диагностикой.
- **Краш-репорт-парсер + интеграция с [mclo.gs](https://mclo.gs/)** — при падении игры анализирует `game.log`, `crash-reports/crash-*.txt` и `hs_err_pid*.log` (`OutOfMemoryError`, несовпадение версии Java, конфликт модов Fabric/Forge, сбой Mixin, ошибки драйвера OpenGL/GLFW) и открывает окно полного лога с кнопками **Скопировать**, **Поделиться** (отправка на `mclo.gs` с авто-маскировкой имени пользователя ОС и токенов), **Перезапуск** и **Закрыть**.

### 🤖 Auto-play без интерфейса (CLI)
- Полноценный консольный запуск синхронизации и игры без загрузки GUI (`python main.py --play --nick Steve`) — удобно для скриптов, ярлыков и `systemd`-юнитов.

---

## 🗂 Структура репозитория

```text
botyaraMC/
├── assets/                    # Векторный SVG и Retina PNG баннер + иконка окна
├── server/                    # Запускается у хоста (только стандартная библиотека Python!)
│   ├── server.py              # Многопоточный HTTP-сервер (с поддержкой Range 206)
│   ├── srv_config.py          # Автосоздание и горячее перечитывание config.txt
│   ├── mods_index.py          # Индекс SHA-256 + обфускация имён модов (words / hash)
│   ├── discovery.py           # UDP-ответчик автообнаружения (LAN и Radmin VPN)
│   ├── mods/                  # Папка для .jar модов
│   └── resourcepacks/         # Папка для .zip ресурспаков
├── launcher/                  # Раздаётся игрокам
│   ├── main.py                # Точка входа (GUI или чистый CLI без импорта Tkinter)
│   ├── ui.py / themes.py      # Интерфейс CustomTkinter, диалоги, хоткеи и темы
│   ├── sync.py                # Расчёт размера, Range-докачка .part и синк по SHA-256
│   ├── mc.py / jvm.py         # Установка MC/лоадера, поиск Java и менеджер JVM-пресетов
│   ├── crash.py               # Анализатор крашей и клиент JSON API mclo.gs v1
│   ├── cli.py / config.py / discovery.py
│   └── requirements.txt
└── tests/                     # Набор автотестов pytest (сервер + синк + CLI + UI)
```

---

## 🚀 Быстрый старт

### 1. Сервер синхронизации (у хоста)

Нужен только **Python 3.10+** (никаких сторонних библиотек на сервере не требуется):

```bash
cd server
python server.py
```

При первом запуске появятся `config.txt`, `mods/` и `resourcepacks/`. Открой в брандмауэре порты **TCP `25456`** (раздача файлов) и **UDP `25457`** (автообнаружение).

#### Настройки `server/config.txt`

Все параметры (кроме портов) подхватываются **на лету** без перезапуска `server.py`:

| Параметр | По умолчанию | Описание |
|---|---|---|
| `http_port` | `25456` | TCP-порт для `/manifest`, `/mods/*` и `/resourcepacks/*` |
| `discovery_port` | `25457` | UDP-порт автообнаружения в локальной сети / Radmin VPN |
| `mc_version` | `1.20.1` | Версия Minecraft, которую лаунчер поставит и запустит у всех |
| `loader` | `fabric` | Загрузчик модов: `fabric`, `forge`, `neoforge`, `quilt` или `none` |
| `java_version` | `auto` | Требуемая мажорная версия Java (`auto`, `8`, `17`, `21` и т.д.) |
| `hide_mods` | `none` | Скрытие имён модов: `none`, `words` (`silent-amber-otter-42.jar`) или `hash` (`mod_7f3a9c12e4b08d51.jar`) |
| `hide_mods_list` | *(пусто)* | Список `.jar` через запятую для выборочного скрытия (пусто = скрывать все моды при включённом `hide_mods`) |
| `minecraft_server` | `127.0.0.1` | IP Minecraft-сервера для автоподключения (например IP хоста в Radmin VPN `26.x.x.x`) |
| `minecraft_port` | `25565` | Порт Minecraft-сервера (в `server.properties` должен стоять `online-mode=false`) |

---

### 2. Лаунчер (у игроков)

```bash
cd launcher
pip install -r requirements.txt
python main.py
```

При первом запуске откроется короткий мастер: **ник** → **тема оформления** (с живым предпросмотром) → **IP сервера** (или кнопка **«🔍 Найти автоматически»**).

> **Совет для хоста:** включи переключатель **«я хост! 👑»** в `⚙ Настройках` и укажи папку `mods/` своего Minecraft-сервера — лаунчер будет синхронизировать моды сразу и в твой `.minecraft/mods`, и в папку сервера.

---

## 🤖 CLI-режим и автоматизация

Запуск без графического интерфейса (Tkinter даже не импортируется) — отлично подходит для скриптов и `systemd`-юнитов:

```bash
cd launcher

# Синхронизировать моды + ресурспаки и сразу запустить игру:
python main.py --play --nick Steve

# Кастомный запуск (сервер, Авто-RAM, пресет Aikar, полный экран, авто-выгрузка краша на mclo.gs):
python main.py --play --nick Steve --server 26.12.34.56 --auto-ram --jvm-preset "Aikar's Flags" --fullscreen --share-crash

# Только синхронизировать сборку и подготовить версию MC без запуска окна (работает даже без X11!):
python main.py --sync-only --server 26.12.34.56

# Показать все найденные в системе установки Java:
python main.py --detect-java
```

<details>
<summary><strong>📋 Пример <code>systemd</code>-юнита (<code>~/.config/systemd/user/botyaramc.service</code>)</strong></summary>

```ini
[Unit]
Description=botyaraMC Auto-Sync & Launch
After=network-online.target

[Service]
Type=simple
WorkingDirectory=%h/botyaraMC/launcher
ExecStart=/usr/bin/python3 main.py --play --nick Steve --auto-ram --share-crash
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
```

При остановке сервиса (`systemctl --user stop botyaramc`) CLI аккуратно перехватывает `SIGTERM` / `SIGINT` и штатно завершает дочерний процесс игры.

</details>

---

## ⌨️ Горячие клавиши

| Сочетание | Действие |
|---|---|
| `Enter` / `Ctrl + P` | Запустить игру (на главном экране) |
| `F5` / `Ctrl + R` | Перепроверить сервер и пересчитать размер загрузки |
| `Ctrl + O` | Открыть быстрый селектор папок (внутри работают клавиши `1–6`) |
| `Ctrl + L` | Открыть окно последнего лога игры (`game.log`) |
| `Ctrl + ,` | Открыть `⚙ Настройки` |
| `Ctrl + S` | Сохранить настройки |
| `Esc` | Закрыть открытое окно / выйти из Настроек без сохранения |
| `F1` | Открыть шпаргалку по всем горячим клавишам |

---

## 🎨 Встроенные темы

| Тема | Режим | Фон | Акцент |
|---|---|---|---|
| **Catppuccin Mocha** *(по умолчанию)* | Тёмная | `#1e1e2e` | `#cba6f7` |
| **Catppuccin Latte** | Светлая | `#eff1f5` | `#8839ef` |
| **Gruvbox** | Тёмная | `#282828` | `#fabd2f` |
| **Ayu** | Тёмная | `#1f2430` | `#ffcc66` |
| **Monokai** | Тёмная | `#272822` | `#a6e22e` |

---

## 🧪 Автотесты

Набор тестов проверяет HTTP Range-сервер, восстановление после обрыва TCP-потока на середине файла, скрытие имён модов (`words`, `hash`, выборочный список), бережную синхронизацию ресурспаков, автодетект Java, JVM-пресеты, таймаут запуска, парсер краш-репортов, фильтрацию приватных данных перед отправкой на `mclo.gs`, CLI-режим и все экраны интерфейса:

```bash
pip install -r launcher/requirements.txt pytest
pytest -v
```

---

## 📄 Лицензия

Проект распространяется под лицензией [MIT License](LICENSE) © [dimasbotyara](https://github.com/dimasbotyara).
