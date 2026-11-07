"""Интерактивный TUI-конфигуратор сервера botyaraMC на базе questionary. Запуск: python tui.py"""
import sys

import questionary
from questionary import Choice, Style

import srv_config as C

CATPPUCCIN_STYLE = Style([
    ("qmark", "fg:#cba6f7 bold"),
    ("question", "fg:#cdd6f4 bold"),
    ("answer", "fg:#a6e3a1 bold"),
    ("pointer", "fg:#cba6f7 bold"),
    ("highlighted", "fg:#cba6f7 bold"),
    ("selected", "fg:#a6e3a1"),
    ("separator", "fg:#6c7086"),
    ("instruction", "fg:#a6adc8"),
    ("text", "fg:#cdd6f4"),
])

STRINGS = {
    "ru": {
        "banner": "🎮 Конфигуратор сервера botyaraMC (автосохранение в config.txt)",
        "pick_action": "Выбери параметр для изменения:",
        "wizard_run": "✨ Пройти быструю настройку по шагам",
        "lang": "🌐 Язык настроек и логов",
        "server_name": "🏷  Имя сервера",
        "client_folder": "📁 Папка сборки у клиентов",
        "mc_ver": "🧱 Версия Minecraft",
        "loader": "🧩 Загрузчик модов",
        "java_ver": "☕ Требуемая версия Java",
        "auto_join": "🚀 Автовход на Minecraft-сервер",
        "mc_addr": "🌍 Адрес Minecraft-сервера (IP:порт)",
        "del_user_mods": "🧹 Удалять сторонние моды игроков",
        "hide_mods": "🕵  Скрытие названий модов",
        "ports_rl": "🔌 Порты и Rate-Limit",
        "exit": "✅ Готово — выйти",
        "yes": "Да",
        "no": "Нет",
        "default_mc": "по умолчанию (.minecraft)",
        "saved": "✔ Сохранено в config.txt!",
        "q_lang": "Выбери язык / Choose language:",
        "q_name": "Название твоего сервера (увидят игроки в лаунчере):",
        "q_folder": "Имя папки сборки у клиентов (пусто = стандартный .minecraft, только a-z, 0-9, _, -, .):",
        "err_folder": "Используй только латинские буквы, цифры, '_', '-' или '.' (либо оставь пустым)!",
        "q_mc_ver": "Версия Minecraft (например 1.20.1, 1.21.1, 1.19.2):",
        "q_loader": "Выбери загрузчик модов:",
        "q_java": "Какую версию Java требовать у клиентов?",
        "java_auto": "Авто (определится по версии Minecraft)",
        "java_custom": "Ввести свою мажорную версию…",
        "q_java_num": "Мажорная версия Java (число от 8 до 40):",
        "q_auto_join": "Автоматически подключать игроков к Minecraft-серверу при входе в игру?",
        "q_mc_ip": "IP Minecraft-сервера (например твой IP в Radmin VPN 26.x.x.x):",
        "q_mc_port": "Порт Minecraft-сервера:",
        "q_del_mods": "Удалять ли моды, которые игроки закинули себе вручную?",
        "del_no": "Нет — не трогать чужие клиентские моды (рекомендуется)",
        "del_yes": "Да — строгий режим сборки (удалять всё лишнее)",
        "q_hide": "Скрывать ли настоящие имена модов у клиентов?",
        "hide_none": "none — не скрывать (обычные имена .jar)",
        "hide_words": "words — случайные слова (silent-amber-otter-42.jar)",
        "hide_hash": "hash — криптохэш с солью (mod_7f3a9c12e4b08d51.jar)",
        "q_hide_scope": "Какие моды скрывать?",
        "scope_all": "Все моды в папке mods/",
        "scope_pick": "Выбрать конкретные моды из списка",
        "q_hide_pick": "Отметь пробелом моды, которые нужно скрыть:",
        "q_hide_manual": "Перечисли имена .jar через запятую (пусто = скрывать все):",
        "q_http_port": "HTTP TCP-порт раздачи модов:",
        "q_udp_port": "UDP-порт автообнаружения:",
        "q_rl": "Лимит запросов с одного IP в минуту (рекомендуется 300, 0 = выключить):",
        "err_port": "Введи порт от 1 до 65535",
        "err_int": "Введи целое число >= 0",
        "bye": "Настройки сохранены! Запускай сервер командой: python server.py 🚀",
    },
    "en": {
        "banner": "🎮 botyaraMC Sync-Server Configurator (auto-saved to config.txt)",
        "pick_action": "Select a setting to edit:",
        "wizard_run": "✨ Run step-by-step setup wizard",
        "lang": "🌐 Config & server language",
        "server_name": "🏷  Server display name",
        "client_folder": "📁 Client instance folder name",
        "mc_ver": "🧱 Minecraft version",
        "loader": "🧩 Mod loader",
        "java_ver": "☕ Required Java version",
        "auto_join": "🚀 Auto-join Minecraft server",
        "mc_addr": "🌍 Minecraft server address (IP:port)",
        "del_user_mods": "🧹 Remove unmanaged player mods",
        "hide_mods": "🕵  Cloak mod filenames",
        "ports_rl": "🔌 Ports & per-IP Rate-Limit",
        "exit": "✅ Done — exit",
        "yes": "Yes",
        "no": "No",
        "default_mc": "default (.minecraft)",
        "saved": "✔ Saved to config.txt!",
        "q_lang": "Choose language / Выбери язык:",
        "q_name": "Server display name (shown in players' launchers):",
        "q_folder": "Client folder name (empty = default .minecraft; only a-z, 0-9, _, -, .):",
        "err_folder": "Use only ASCII letters, digits, '_', '-' or '.' (or leave empty)!",
        "q_mc_ver": "Minecraft version (e.g. 1.20.1, 1.21.1, 1.19.2):",
        "q_loader": "Choose mod loader:",
        "q_java": "Required Java version on clients:",
        "java_auto": "Auto (detected from Minecraft version)",
        "java_custom": "Enter custom major version…",
        "q_java_num": "Java major version (integer 8–40):",
        "q_auto_join": "Automatically connect players to the Minecraft server on launch?",
        "q_mc_ip": "Minecraft server IP (e.g. your Radmin VPN IP 26.x.x.x):",
        "q_mc_port": "Minecraft server port:",
        "q_del_mods": "Remove custom mods added manually by players?",
        "del_no": "No — keep players' personal QoL mods (recommended)",
        "del_yes": "Yes — strict modpack mode (remove unmanaged .jar files)",
        "q_hide": "Cloak mod filenames on client machines?",
        "hide_none": "none — keep original .jar names",
        "hide_words": "words — random word slugs (silent-amber-otter-42.jar)",
        "hide_hash": "hash — salted hash (mod_7f3a9c12e4b08d51.jar)",
        "q_hide_scope": "Which mods should be cloaked?",
        "scope_all": "All mods in mods/",
        "scope_pick": "Select specific mods",
        "q_hide_pick": "Press Space to select mods to cloak:",
        "q_hide_manual": "Comma-separated .jar filenames (empty = cloak all):",
        "q_http_port": "HTTP TCP port:",
        "q_udp_port": "UDP discovery port:",
        "q_rl": "Per-IP rate limit in requests/min (recommended 300, 0 = off):",
        "err_port": "Enter a port between 1 and 65535",
        "err_int": "Enter an integer >= 0",
        "bye": "Configuration saved! Start the server with: python server.py 🚀",
    },
}


def _ask(prompt_obj):
    res = prompt_obj.ask()
    if res is None:
        raise KeyboardInterrupt
    return res


def edit_language(cfg):
    ans = _ask(questionary.select(
        STRINGS[cfg["language"]]["q_lang"],
        choices=[
            Choice("🇷🇺 Русский", value="ru"),
            Choice("🇬🇧 English", value="en"),
        ],
        default=cfg.get("language", "ru"),
        style=CATPPUCCIN_STYLE,
    ))
    cfg["language"] = ans
    C.save(cfg)


def edit_server_name(cfg, t):
    ans = _ask(questionary.text(
        t["q_name"],
        default=cfg.get("server_name", "botyaraMC"),
        validate=lambda v: True if v.strip() else "!",
        style=CATPPUCCIN_STYLE,
    ))
    cfg["server_name"] = ans.strip()[:64]
    C.save(cfg)


def edit_client_folder(cfg, t):
    def _val(v):
        v = v.strip()
        if not v:
            return True
        return True if C.sanitize_folder_name(v) else t["err_folder"]

    ans = _ask(questionary.text(
        t["q_folder"],
        default=cfg.get("client_folder", ""),
        validate=_val,
        style=CATPPUCCIN_STYLE,
    ))
    cfg["client_folder"] = C.sanitize_folder_name(ans)
    C.save(cfg)


def edit_mc_version(cfg, t):
    ans = _ask(questionary.text(
        t["q_mc_ver"],
        default=cfg.get("mc_version", "1.20.1"),
        validate=lambda v: True if v.strip() else "!",
        style=CATPPUCCIN_STYLE,
    ))
    cfg["mc_version"] = ans.strip()
    C.save(cfg)


def edit_loader(cfg, t):
    ans = _ask(questionary.select(
        t["q_loader"],
        choices=[Choice(ld, value=ld) for ld in C.VALID_LOADERS],
        default=cfg.get("loader", "fabric"),
        style=CATPPUCCIN_STYLE,
    ))
    cfg["loader"] = ans
    C.save(cfg)


def edit_java(cfg, t):
    cur = cfg.get("java_version")
    preset_choices = [
        Choice(t["java_auto"], value="auto"),
        Choice("Java 21 (MC 1.20.5+ / 1.21+)", value="21"),
        Choice("Java 17 (MC 1.18 – 1.20.4)", value="17"),
        Choice("Java 8  (MC 1.12.2 – 1.16.5)", value="8"),
        Choice(t["java_custom"], value="custom"),
    ]
    def_val = str(cur) if str(cur) in ("21", "17", "8") else ("auto" if not cur else "custom")
    ans = _ask(questionary.select(t["q_java"], choices=preset_choices, default=def_val, style=CATPPUCCIN_STYLE))
    if ans == "auto":
        cfg["java_version"] = None
    elif ans == "custom":
        num = _ask(questionary.text(
            t["q_java_num"],
            default=str(cur or 21),
            validate=lambda v: True if (v.strip().isdigit() and 6 <= int(v.strip()) <= 40) else "6..40",
            style=CATPPUCCIN_STYLE,
        ))
        cfg["java_version"] = int(num.strip())
    else:
        cfg["java_version"] = int(ans)
    C.save(cfg)


def edit_auto_join_and_addr(cfg, t, ask_addr=True):
    aj = _ask(questionary.confirm(
        t["q_auto_join"],
        default=bool(cfg.get("auto_join", True)),
        style=CATPPUCCIN_STYLE,
    ))
    cfg["auto_join"] = bool(aj)
    if aj and ask_addr:
        edit_mc_addr_only(cfg, t)
    else:
        C.save(cfg)


def edit_mc_addr_only(cfg, t):
    ip = _ask(questionary.text(
        t["q_mc_ip"],
        default=cfg.get("minecraft_server", "127.0.0.1"),
        validate=lambda v: True if v.strip() and " " not in v.strip() else "!",
        style=CATPPUCCIN_STYLE,
    ))
    port = _ask(questionary.text(
        t["q_mc_port"],
        default=str(cfg.get("minecraft_port", 25565)),
        validate=lambda v: True if (v.strip().isdigit() and 1 <= int(v.strip()) <= 65535) else t["err_port"],
        style=CATPPUCCIN_STYLE,
    ))
    cfg["minecraft_server"] = ip.strip()
    cfg["minecraft_port"] = int(port.strip())
    C.save(cfg)


def edit_delete_user_mods(cfg, t):
    ans = _ask(questionary.select(
        t["q_del_mods"],
        choices=[
            Choice(t["del_no"], value=False),
            Choice(t["del_yes"], value=True),
        ],
        default=bool(cfg.get("delete_user_mods", False)),
        style=CATPPUCCIN_STYLE,
    ))
    cfg["delete_user_mods"] = bool(ans)
    C.save(cfg)


def edit_hide_mods(cfg, t):
    mode = _ask(questionary.select(
        t["q_hide"],
        choices=[
            Choice(t["hide_none"], value="none"),
            Choice(t["hide_words"], value="words"),
            Choice(t["hide_hash"], value="hash"),
        ],
        default=cfg.get("hide_mods", "none"),
        style=CATPPUCCIN_STYLE,
    ))
    cfg["hide_mods"] = mode
    if mode != "none":
        scope = _ask(questionary.select(
            t["q_hide_scope"],
            choices=[
                Choice(t["scope_all"], value="all"),
                Choice(t["scope_pick"], value="pick"),
            ],
            default="pick" if cfg.get("hide_mods_list") else "all",
            style=CATPPUCCIN_STYLE,
        ))
        if scope == "all":
            cfg["hide_mods_list"] = []
        else:
            C.MODS_DIR.mkdir(exist_ok=True)
            jars = sorted(p.name for p in C.MODS_DIR.glob("*.jar") if not p.name.startswith("."))
            cur_set = {x.lower() for x in (cfg.get("hide_mods_list") or [])}
            if jars:
                picked = _ask(questionary.checkbox(
                    t["q_hide_pick"],
                    choices=[Choice(j, value=j, checked=(j.lower() in cur_set)) for j in jars],
                    style=CATPPUCCIN_STYLE,
                ))
                cfg["hide_mods_list"] = list(picked)
            else:
                raw = _ask(questionary.text(
                    t["q_hide_manual"],
                    default=", ".join(cfg.get("hide_mods_list") or []),
                    style=CATPPUCCIN_STYLE,
                ))
                cfg["hide_mods_list"] = [x.strip() for x in raw.split(",") if x.strip()]
    C.save(cfg)


def _validate_port(val, lang="ru"):
    t = STRINGS.get(lang, STRINGS["ru"])
    return True if (isinstance(val, str) and val.strip().isdigit() and 1 <= int(val.strip()) <= 65535) else t["err_port"]


def edit_ports_and_ratelimit(cfg, t):
    hp = _ask(questionary.text(
        t["q_http_port"],
        default=str(cfg.get("http_port", 25456)),
        validate=lambda v: True if (v.strip().isdigit() and 1 <= int(v.strip()) <= 65535) else t["err_port"],
        style=CATPPUCCIN_STYLE,
    ))
    up = _ask(questionary.text(
        t["q_udp_port"],
        default=str(cfg.get("discovery_port", 25457)),
        validate=lambda v: True if (v.strip().isdigit() and 1 <= int(v.strip()) <= 65535) else t["err_port"],
        style=CATPPUCCIN_STYLE,
    ))
    rl = _ask(questionary.text(
        t["q_rl"],
        default=str(cfg.get("rate_limit_per_min", 300)),
        validate=lambda v: True if (v.strip().isdigit() and int(v.strip()) >= 0) else t["err_int"],
        style=CATPPUCCIN_STYLE,
    ))
    cfg["http_port"] = int(hp.strip())
    cfg["discovery_port"] = int(up.strip())
    cfg["rate_limit_per_min"] = int(rl.strip())
    C.save(cfg)


def run_wizard(cfg):
    edit_language(cfg)
    t = STRINGS[cfg["language"]]
    edit_server_name(cfg, t)
    edit_client_folder(cfg, t)
    edit_mc_version(cfg, t)
    edit_loader(cfg, t)
    edit_java(cfg, t)
    edit_auto_join_and_addr(cfg, t, ask_addr=True)
    edit_delete_user_mods(cfg, t)
    edit_hide_mods(cfg, t)
    edit_ports_and_ratelimit(cfg, t)
    print(f"\n{t['saved']}")


def main():
    first_time = C.ensure_files()
    cfg = C.load()

    try:
        if first_time or "--wizard" in sys.argv:
            run_wizard(cfg)
            if "--wizard" in sys.argv:
                print(STRINGS[cfg["language"]]["bye"])
                return

        while True:
            t = STRINGS[cfg.get("language", "ru")]
            folder_disp = cfg["client_folder"] or t["default_mc"]
            java_disp = f"Java {cfg['java_version']}" if cfg["java_version"] else "auto"
            aj_disp = t["yes"] if cfg["auto_join"] else t["no"]
            del_disp = t["yes"] if cfg["delete_user_mods"] else t["no"]
            rl_disp = f"{cfg['rate_limit_per_min']}/min" if cfg["rate_limit_per_min"] else "off"

            print(f"\n{t['banner']}")
            action = _ask(questionary.select(
                t["pick_action"],
                choices=[
                    Choice(t["wizard_run"], value="wizard"),
                    Choice(f"{t['lang']}: [{cfg['language'].upper()}]", value="lang"),
                    Choice(f"{t['server_name']}: [{cfg['server_name']}]", value="name"),
                    Choice(f"{t['client_folder']}: [{folder_disp}]", value="folder"),
                    Choice(f"{t['mc_ver']}: [{cfg['mc_version']}]", value="mc_ver"),
                    Choice(f"{t['loader']}: [{cfg['loader']}]", value="loader"),
                    Choice(f"{t['java_ver']}: [{java_disp}]", value="java"),
                    Choice(f"{t['auto_join']}: [{aj_disp}]", value="auto_join"),
                    Choice(f"{t['mc_addr']}: [{cfg['minecraft_server']}:{cfg['minecraft_port']}]", value="mc_addr"),
                    Choice(f"{t['del_user_mods']}: [{del_disp}]", value="del_mods"),
                    Choice(f"{t['hide_mods']}: [{cfg['hide_mods']}]", value="hide"),
                    Choice(f"{t['ports_rl']}: [TCP {cfg['http_port']}, UDP {cfg['discovery_port']}, RL {rl_disp}]", value="ports"),
                    Choice(t["exit"], value="exit"),
                ],
                style=CATPPUCCIN_STYLE,
            ))

            if action == "exit":
                print(f"\n{t['bye']}")
                break
            elif action == "wizard":
                run_wizard(cfg)
            elif action == "lang":
                edit_language(cfg)
            elif action == "name":
                edit_server_name(cfg, t)
            elif action == "folder":
                edit_client_folder(cfg, t)
            elif action == "mc_ver":
                edit_mc_version(cfg, t)
            elif action == "loader":
                edit_loader(cfg, t)
            elif action == "java":
                edit_java(cfg, t)
            elif action == "auto_join":
                edit_auto_join_and_addr(cfg, t, ask_addr=False)
            elif action == "mc_addr":
                edit_mc_addr_only(cfg, t)
            elif action == "del_mods":
                edit_delete_user_mods(cfg, t)
            elif action == "hide":
                edit_hide_mods(cfg, t)
            elif action == "ports":
                edit_ports_and_ratelimit(cfg, t)
    except KeyboardInterrupt:
        C.save(cfg)
        print("\n👋")


if __name__ == "__main__":
    main()
