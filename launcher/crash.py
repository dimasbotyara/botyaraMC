"""Парсер краш-репортов Minecraft (RU/EN) и отправка логов на https://mclo.gs."""
import json
import logging
import re
import urllib.error
import urllib.request
from pathlib import Path

log = logging.getLogger("botyaraMC.crash")

MCLOGS_POST_URL = "https://api.mclo.gs/1/log"
MCLOGS_MAX_LINES = 25_000
MCLOGS_MAX_BYTES = 10 * 1024 * 1024  # 10 MiB

_CRASH_MARKERS = (
    "---- Minecraft Crash Report ----",
    "#@!@# Game crashed!",
    "A fatal error has been detected by the Java Runtime Environment",
    "Incompatible mods found!",
    "net.fabricmc.loader.impl.FormattedException",
    "Could not create the Java Virtual Machine",
    "Unrecognized VM option",
    "Invalid maximum heap size",
)

_PRIVACY_RULES = (
    (re.compile(r"C:\\Users\\([^\\]+)\\", re.I), r"C:\\Users\\********\\"),
    (re.compile(r"C:/Users/([^/]+)/", re.I), r"C:/Users/********/"),
    (re.compile(r"(?<!\w)/home/[^/\s]+/"), "/home/********/"),
    (re.compile(r"(?<!\w)/Users/[^/\s]+/"), "/Users/********/"),
    (re.compile(r"--accessToken\s+\S+", re.I), "--accessToken ****************"),
    (re.compile(r"\(Session ID is token:[^)]+\)", re.I), "(Session ID is token:****************)"),
)

_EXCEPTION_RE = re.compile(
    r"^\s*(?:Caused by:\s*)?([a-zA-Z0-9_$.]+(?:Exception|Error)(?::\s*[^\r\n]+)?)",
    re.MULTILINE,
)
_DESC_RE = re.compile(r"^Description:\s*(.+)$", re.MULTILINE)
_CLASS_VER_RE = re.compile(r"class file version (\d+)\.\d+", re.I)
_MIXIN_CFG_RE = re.compile(r"([a-zA-Z0-9_.-]+?)\.mixins?\.json", re.I)
_JAR_NAME_RE = re.compile(r"([a-zA-Z0-9_.+-]{3,80}\.jar)")
_SUSPECTED_MODS_RE = re.compile(r"Suspected Mods:\s*(.+)", re.I)
_FABRIC_MOD_RE = re.compile(r"-\s*Mod\s+'([^']+)'\s*\(([^)]+)\)", re.I)


def _read_text_safe(path):
    try:
        raw = Path(path).read_bytes()
    except OSError:
        return ""
    for enc in ("utf-8", "cp1251", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def collect_session_log(game_dir, log_path, start_time, lang="ru"):
    """
    Собирает полный лог сессии: game.log + свежие файлы из crash-reports/ и hs_err_pid*.log.
    Возвращает (full_text, has_crash_report_file, crash_file_path_or_None).
    """
    game_dir = Path(game_dir)
    game_text = _read_text_safe(log_path).strip()
    extra_blocks = []
    crash_file = None

    cr_dir = game_dir / "crash-reports"
    if cr_dir.is_dir():
        fresh = []
        for p in cr_dir.glob("crash-*.txt"):
            try:
                st = p.stat()
                if st.st_mtime >= start_time - 2.0:
                    fresh.append((st.st_mtime, p))
            except OSError:
                continue
        if fresh:
            fresh.sort(reverse=True)
            crash_file = fresh[0][1]
            cr_text = _read_text_safe(crash_file).strip()
            if cr_text and cr_text not in game_text:
                extra_blocks.append(
                    f"========== MINECRAFT CRASH REPORT ({crash_file.name}) ==========\n{cr_text}"
                )

    if game_dir.is_dir():
        hs_files = []
        for p in game_dir.glob("hs_err_pid*.log"):
            try:
                st = p.stat()
                if st.st_mtime >= start_time - 2.0:
                    hs_files.append((st.st_mtime, p))
            except OSError:
                continue
        if hs_files:
            hs_files.sort(reverse=True)
            hs_path = hs_files[0][1]
            if crash_file is None:
                crash_file = hs_path
            hs_text = _read_text_safe(hs_path).strip()
            if hs_text:
                extra_blocks.append(
                    f"========== JVM NATIVE CRASH ({hs_path.name}) ==========\n{hs_text}"
                )

    parts = [p for p in ([game_text] if game_text else []) + extra_blocks if p]
    empty_msg = (
        "(Log is empty — the process exited without output)"
        if lang == "en"
        else "(Лог пуст — процесс завершился без вывода)"
    )
    full_text = "\n\n".join(parts) if parts else empty_msg
    return full_text, crash_file is not None, crash_file


def is_crash(exit_code, log_text, has_crash_file=False, timed_out=False):
    """Определяет, завершилась ли игра аварийно."""
    if timed_out or has_crash_file:
        return True
    if exit_code not in (0, None):
        return True
    if log_text:
        for marker in _CRASH_MARKERS:
            if marker in log_text:
                return True
    return False


def _extract_suspected_mods(text):
    mods = []

    def add(item):
        item = item.strip()
        if item and item.lower() not in {x.lower() for x in mods}:
            if not any(skip in item.lower() for skip in (
                "minecraft.jar", "fabric-loader", "forge-", "java.base", "lwjgl",
            )):
                mods.append(item)

    m = _SUSPECTED_MODS_RE.search(text)
    if m:
        val = m.group(1).strip()
        if val.lower() not in ("none", "unknown", ""):
            add(val)

    for m_fab in _FABRIC_MOD_RE.finditer(text):
        add(f"{m_fab.group(1)} ({m_fab.group(2)})")

    for m_mix in _MIXIN_CFG_RE.finditer(text):
        add(m_mix.group(1))

    for line in text.splitlines():
        low = line.lower()
        if any(k in low for k in ("error", "exception", "failed", "conflict", "missing", "incompatible", "mod")):
            for jm in _JAR_NAME_RE.finditer(line):
                add(jm.group(1))
        if len(mods) >= 5:
            break

    return mods[:5]


def parse_crash(log_text, exit_code=1, timed_out=False, lang="ru"):
    """Анализирует лог краша и возвращает локализованный словарь диагностики."""
    en = (lang == "en")
    text = log_text or ""
    low = text.lower()
    desc_m = _DESC_RE.search(text)
    mc_desc = desc_m.group(1).strip() if desc_m else ""

    exc_matches = _EXCEPTION_RE.findall(text)
    exc_line = exc_matches[-1].strip() if exc_matches else ""
    if len(exc_line) > 160:
        exc_line = exc_line[:157] + "..."

    suspects = _extract_suspected_mods(text)
    title = "Game crashed unexpectedly 💥" if en else "Игра неожиданно завершилась 💥"
    summary = "Minecraft exited with an error." if en else "Процесс Minecraft завершился с ошибкой."
    solutions = []

    if timed_out:
        if en:
            title = "Launch timeout exceeded ⏱"
            summary = "Minecraft took too long to initialize and open a window, so the launch was aborted."
            solutions = [
                "Increase 'Launch timeout' in ⚙ Settings (especially for heavy modpacks or slow drives).",
                "Check the full log — one of the mods might have frozen during initialization.",
                "Allocate a bit more RAM or try the G1GC / Aikar's Flags preset.",
            ]
        else:
            title = "Превышен таймаут запуска ⏱"
            summary = (
                "Игра слишком долго не открывала окно и не подавала признаков инициализации, "
                "поэтому запуск был остановлен."
            )
            solutions = [
                "Увеличь «Таймаут запуска» в ⚙ Настройках (особенно если в сборке много модов или слабый диск).",
                "Проверь полный лог ниже — возможно, один из модов завис на стадии загрузки.",
                "Добавь немного больше RAM или попробуй пресет G1GC / Aikar's Flags.",
            ]

    elif "outofmemoryerror" in low or "insufficient memory" in low:
        if en:
            title = "Out of memory (OutOfMemoryError) 🧠"
            summary = "Minecraft ran out of allocated heap memory (RAM) or free system memory."
            solutions = [
                "Open ⚙ Settings and enable 'Auto RAM' or increase allocated memory.",
                "Close heavy background apps (browsers with many tabs, other launchers).",
                "Make sure a 64-bit Java runtime is selected.",
            ]
        else:
            title = "Недостаточно оперативной памяти (OutOfMemoryError) 🧠"
            summary = "Игре не хватило выделенной памяти (RAM), либо в системе закончилась свободная память."
            solutions = [
                "Открой ⚙ Настройки и включи «Авто-RAM» или увеличь объём выделенной памяти.",
                "Закрой тяжёлые программы на фоне (браузер с кучей вкладок, лишние лаунчеры).",
                "Убедись, что используется 64-битная Java.",
            ]

    elif "unsupportedclassversionerror" in low:
        cv_m = _CLASS_VER_RE.search(text)
        needed_java = (int(cv_m.group(1)) - 44) if cv_m else None
        if en:
            need_str = f"Java {needed_java}" if needed_java and needed_java > 0 else "a newer Java"
            title = f"Wrong Java version ({need_str} required) ☕"
            summary = f"A mod or Minecraft itself was compiled for {need_str}, while an older Java was used."
            solutions = [
                f"In ⚙ Settings, switch Java mode to 'Auto' or select {need_str}+.",
                "If Java is set manually, point it to a newer JDK/JRE.",
            ]
        else:
            need_str = f"Java {needed_java}" if needed_java and needed_java > 0 else "более новая Java"
            title = f"Неподходящая версия Java (нужна {need_str}) ☕"
            summary = f"Мод или сама игра скомпилированы под {need_str}, а запущена более старая версия Java."
            solutions = [
                f"В ⚙ Настройках переключи выбор Java в режим «Авто» или выбери {need_str}+.",
                "Если Java выбрана вручную — укажи более свежий JDK/JRE.",
            ]

    elif any(k in low for k in (
        "unrecognized vm option",
        "could not create the java virtual machine",
        "invalid maximum heap size",
        "improperly specified vm option",
    )):
        if en:
            title = "Invalid JVM launch flags ⚙"
            summary = "The Java Virtual Machine refused to start due to unsupported flags or heap size."
            solutions = [
                "Check 'Extra JVM flags' and your JVM preset in ⚙ Settings.",
                "Try switching the preset to 'G1GC' or 'Minimal'.",
                "Ensure you are using 64-bit Java ('Auto' mode).",
            ]
        else:
            title = "Ошибка параметров запуска JVM ⚙"
            summary = "Виртуальная машина Java не смогла запуститься из-за неподдерживаемых флагов или лимита памяти."
            solutions = [
                "Проверь «Доп. параметры JVM» и выбранный JVM-пресет в ⚙ Настройках.",
                "Попробуй переключить пресет на «G1GC» или «Минимальный».",
                "Если стоит 32-битная Java, переключись на «Авто» (64-битную).",
            ]

    elif any(k in low for k in (
        "incompatible mods found",
        "modresolutionexception",
        "missingmodsexception",
        "formattedexception",
        "failed to validate mod",
        "modloadingexception",
    )):
        if en:
            title = "Incompatible or missing mods 🧩"
            summary = "The mod loader detected incompatible versions or a missing required dependency (API)."
            solutions = [
                "Inspect the full log to see which dependency is missing (e.g. Fabric API).",
                "Check the mods/ folder for leftover extra mods built for another MC version.",
                "Click 'Share (mclo.gs)' in the log window and send the link to your server host.",
            ]
        else:
            title = "Конфликт или нехватка модов 🧩"
            summary = "Загрузчик модов обнаружил несовместимые версии или отсутствие обязательной библиотеки (API)."
            solutions = [
                "Посмотри полный лог: там точно указано, какого мода не хватает (например Fabric API).",
                "Проверь папку mods — возможно, там лежит сторонний мод не под эту версию игры.",
                "Отправь ссылку с mclo.gs хосту сервера, чтобы он обновил сборку.",
            ]

    elif any(k in low for k in ("mixinapplyerror", "mixintransformererror", "injectionerror", "critical injection failure")):
        if en:
            title = "Mod conflict (Mixin failure) 🧬"
            summary = "A mod failed to patch game code (usually caused by conflicting mods or wrong mod version)."
            solutions = [
                "If you added your own client-side mods (minimap, optimization, etc.), temporarily move them out of mods/.",
                "Click 'Share (mclo.gs)' in the log window and send the link to your host.",
            ]
        else:
            title = "Ошибка конфликта модов (Mixin) 🧬"
            summary = "Один из модов не смог пропатчить код игры (обычно из-за конфликта с другим модом или неверной версии)."
            solutions = [
                "Если ты добавлял свои клиентские моды (оптимизация, миникарта и т.д.) — временно убери их из папки mods.",
                "Нажми «Поделиться (mclo.gs)» в окне лога и скинь ссылку хосту.",
            ]

    elif any(k in low for k in (
        "glfw error 65542",
        "glfw error 65543",
        "wgl: the driver does not appear to support opengl",
        "pixel format not accelerated",
        "atio6axx.dll",
        "nvoglv64.dll",
        "ig7icd64.dll",
    )):
        if en:
            title = "GPU driver / OpenGL error 🖥"
            summary = "Minecraft could not initialize OpenGL graphics or the GPU driver crashed."
            solutions = [
                "Update your GPU drivers (NVIDIA / AMD / Intel) from the vendor's website.",
                "On laptops, ensure Java runs on the dedicated GPU rather than the basic display adapter.",
            ]
        else:
            title = "Ошибка видеодрайвера / OpenGL 🖥"
            summary = "Minecraft не смог инициализировать графику OpenGL или произошёл сбой в драйвере видеокарты."
            solutions = [
                "Обнови драйвер видеокарты (NVIDIA / AMD / Intel) с официального сайта.",
                "На ноутбуке убедись, что Java запускается на дискретной видеокарте, а не на базовом видеоадаптере Windows.",
            ]

    elif any(k in low for k in ("zipexception", "ziperror", "error in opening zip file")):
        if en:
            title = "Corrupted mod or library archive 📦"
            summary = "One of the .jar or .zip files is corrupted or incomplete."
            solutions = [
                "Click 'Retry launch' — botyaraMC will re-verify SHA-256 hashes and re-download broken mods.",
                "If you added custom mods manually, check your most recently downloaded .jar files.",
            ]
        else:
            title = "Повреждён файл мода или библиотеки 📦"
            summary = "Один из .jar или .zip архивов оказался битым или не докачался."
            solutions = [
                "Нажми «Перезапуск» — лаунчер перепроверит SHA-256 всех модов и перекачает битые файлы.",
                "Если добавлял свои моды вручную — проверь последние скачанные .jar.",
            ]

    elif "a fatal error has been detected by the java runtime environment" in low or "exception_access_violation" in low:
        if en:
            title = "JVM native crash ⚡"
            summary = "A low-level crash occurred inside a native library (often GPU drivers, audio, or overlays)."
            solutions = [
                "Disable overlays (Discord Overlay, MSI Afterburner / RivaTuner, GeForce Experience).",
                "Update GPU drivers and try launching again.",
            ]
        else:
            title = "Критический сбой JVM (Native Crash) ⚡"
            summary = "Произошла низкоуровневая ошибка в нативной библиотеке (часто драйвер видеокарты, аудио или оверлей)."
            solutions = [
                "Отключи оверлеи (Discord Overlay, MSI Afterburner / RivaTuner, GeForce Experience).",
                "Обнови драйверы видеокарты и попробуй перезапустить игру.",
            ]

    else:
        if mc_desc:
            summary = f"Crash description: {mc_desc}" if en else f"Описание сбоя: {mc_desc}"
        if en:
            solutions = [
                "Open the full log and click 'Share (mclo.gs)' — it highlights error lines automatically.",
                "Try restarting the game or checking custom mods in the mods/ folder.",
            ]
        else:
            solutions = [
                "Открой полный лог и нажми «Поделиться (mclo.gs)» — сайт автоматически подсветит строки ошибок.",
                "Попробуй перезапустить игру или проверить свои сторонние моды в папке mods.",
            ]

    return {
        "title": title,
        "summary": summary,
        "exception": exc_line,
        "description": mc_desc,
        "suspected_mods": suspects,
        "solutions": solutions,
        "exit_code": exit_code,
        "timed_out": timed_out,
    }


def sanitize_and_truncate_for_mclogs(content):
    """Очищает приватные пути/токены и аккуратно укладывает лог в лимиты mclo.gs (25 000 строк, 10 MiB)."""
    text = (content or "").strip()
    if not text:
        text = "(Empty log)"

    for pattern, repl in _PRIVACY_RULES:
        text = pattern.sub(repl, text)

    lines = text.splitlines()
    if len(lines) > MCLOGS_MAX_LINES:
        head_n = 4000
        tail_n = MCLOGS_MAX_LINES - head_n - 3
        lines = (
            lines[:head_n]
            + ["", f"... [{len(lines) - head_n - tail_n} lines omitted for mclo.gs limit] ...", ""]
            + lines[-tail_n:]
        )
    text = "\n".join(lines)

    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) > MCLOGS_MAX_BYTES - 1024:
        encoded = encoded[-(MCLOGS_MAX_BYTES - 1024):]
        text = encoded.decode("utf-8", errors="ignore")
    return text


def upload_to_mclogs(content, mc_version="", loader="", exit_code=None, lang="ru"):
    """
    Отправляет лог на https://api.mclo.gs/1/log (JSON API v1).
    Возвращает словарь {'url': 'https://mclo.gs/...', 'id': '...', 'raw': '...', 'errors': int}.
    """
    en = (lang == "en")
    prepared = sanitize_and_truncate_for_mclogs(content)
    metadata = [
        {"key": "launcher", "value": "botyaraMC", "label": "Launcher", "visible": True},
    ]
    if mc_version:
        metadata.append({"key": "mc_version", "value": str(mc_version), "label": "Minecraft", "visible": True})
    if loader:
        metadata.append({"key": "loader", "value": str(loader), "label": "Loader", "visible": True})
    if exit_code is not None:
        metadata.append({"key": "exit_code", "value": int(exit_code), "label": "Exit Code", "visible": True})

    payload = json.dumps({
        "content": prepared,
        "source": "botyaraMC",
        "metadata": metadata,
    }, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(
        MCLOGS_POST_URL,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
            "User-Agent": "botyaraMC/2.0",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw_resp = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8", errors="replace")
            err_json = json.loads(err_body)
            if err_json.get("error"):
                msg = f"mclo.gs error ({e.code}): {err_json['error']}" if en else f"mclo.gs вернул ошибку ({e.code}): {err_json['error']}"
                raise RuntimeError(msg) from e
        except ValueError:
            pass
        msg = f"HTTP {e.code} while uploading to mclo.gs" if en else f"Ошибка HTTP {e.code} при отправке на mclo.gs"
        raise RuntimeError(msg) from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        msg = f"Failed to reach mclo.gs: {e}" if en else f"Не удалось подключиться к mclo.gs: {e}"
        raise RuntimeError(msg) from e

    data = json.loads(raw_resp)
    if not data.get("success") or not data.get("url"):
        raise RuntimeError(data.get("error") or ("Unknown mclo.gs response" if en else "Неизвестный ответ от mclo.gs"))

    return {
        "id": data.get("id", ""),
        "url": data["url"],
        "raw": data.get("raw", ""),
        "errors": int(data.get("errors", 0)),
    }
