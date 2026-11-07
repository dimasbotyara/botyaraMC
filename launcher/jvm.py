"""Автодетект Java, выбор рантайма и менеджер JVM-пресетов (G1GC, Aikar's, ZGC и свои)."""
import logging
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import minecraft_launcher_lib as mll

log = logging.getLogger("botyaraMC.jvm")

BUILTIN_PRESETS = {
    "G1GC": (
        "-XX:+UnlockExperimentalVMOptions -XX:+UseG1GC "
        "-XX:G1NewSizePercent=20 -XX:G1ReservePercent=20 "
        "-XX:MaxGCPauseMillis=50 -XX:G1HeapRegionSize=32M"
    ),
    "Aikar's Flags": (
        "-XX:+UnlockExperimentalVMOptions -XX:+UseG1GC "
        "-XX:+ParallelRefProcEnabled -XX:MaxGCPauseMillis=200 "
        "-XX:+DisableExplicitGC -XX:+AlwaysPreTouch "
        "-XX:G1NewSizePercent=30 -XX:G1MaxNewSizePercent=40 "
        "-XX:G1HeapRegionSize=8M -XX:G1ReservePercent=20 "
        "-XX:G1HeapWastePercent=5 -XX:G1MixedGCCountTarget=4 "
        "-XX:InitiatingHeapOccupancyPercent=15 "
        "-XX:G1MixedGCLiveThresholdPercent=90 "
        "-XX:G1RSetUpdatingPauseTimePercent=5 -XX:SurvivorRatio=32 "
        "-XX:+PerfDisableSharedMem -XX:MaxTenuringThreshold=1"
    ),
    "ZGC": (
        "-XX:+UnlockExperimentalVMOptions -XX:+UseZGC "
        "-XX:+AlwaysPreTouch -XX:+DisableExplicitGC"
    ),
    "Минимальный": "",
}

PRESET_DESCRIPTIONS = {
    "G1GC": "Сбалансированный сборщик мусора (рекомендуется для большинства ПК)",
    "Aikar's Flags": "Тюнинг G1GC от Aikar — отлично подходит для тяжёлых сборок с модами",
    "ZGC": "Ультранизкие задержки без микрофризов (требуется Java 17+, лучше Java 21+)",
    "Минимальный": "Без дополнительных флагов сборщика — только выделение памяти",
}

_MOJANG_RUNTIME_BY_MAJOR = {
    8: "jre-legacy",
    16: "java-runtime-alpha",
    17: "java-runtime-gamma",
    21: "java-runtime-delta",
}

_probe_cache = {}
_VER_QUOTED_RE = re.compile(r'version\s+"([^"]+)"', re.IGNORECASE)
_VER_PLAIN_RE = re.compile(r'(?:openjdk|java)\s+(\d+(?:\.\d+)*)', re.IGNORECASE)


def normalize_java_binary(path_str):
    """Принимает путь к java/javaw или к папке JDK/JRE и возвращает путь к бинарнику java."""
    if not path_str:
        return ""
    p = Path(path_str).expanduser()
    exe = "java.exe" if sys.platform.startswith("win") else "java"
    if p.is_dir():
        for sub in (p / "bin" / exe, p / "Contents" / "Home" / "bin" / exe, p / exe):
            if sub.is_file():
                return str(sub)
        return str(p)
    # На Windows предпочитаем java.exe вместо javaw.exe (с CREATE_NO_WINDOW консоль не всплывает, зато пишется game.log)
    if sys.platform.startswith("win") and p.name.lower() == "javaw.exe":
        sibling = p.with_name("java.exe")
        if sibling.is_file():
            return str(sibling)
    return str(p)


def _parse_major(ver_str):
    parts = re.findall(r"\d+", ver_str or "")
    if not parts:
        return None
    first = int(parts[0])
    if first == 1 and len(parts) >= 2:
        return int(parts[1])
    return first


def _detect_vendor(out_text, path_str):
    low = out_text.lower()
    plow = path_str.lower()
    if "runtime" in plow and ("minecraft" in plow or "java-runtime" in plow or "jre-legacy" in plow):
        return "Mojang"
    for marker, label in (
        ("temurin", "Temurin"),
        ("adoptium", "Adoptium"),
        ("graalvm", "GraalVM"),
        ("zulu", "Azul Zulu"),
        ("liberica", "BellSoft"),
        ("corretto", "Corretto"),
        ("microsoft", "Microsoft"),
        ("jetbrains", "JetBrains"),
        ("hotspot", "Oracle/OpenJDK"),
        ("openjdk", "OpenJDK"),
    ):
        if marker in low or marker in plow:
            return label
    return "Java"


def probe_java(executable):
    """Проверяет бинарник java -version и возвращает словарь с версией или None."""
    norm = normalize_java_binary(executable)
    if not norm:
        return None
    p = Path(norm)
    if not p.is_file():
        found = shutil.which(norm)
        if not found:
            return None
        p = Path(normalize_java_binary(found))
    try:
        resolved = str(p.resolve())
        st = p.stat()
        cache_key = (resolved, st.st_mtime_ns)
        if cache_key in _probe_cache:
            return _probe_cache[cache_key]
    except OSError:
        return None

    flags = subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0
    try:
        res = subprocess.run(
            [resolved, "-version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=4,
            creationflags=flags,
        )
        out = res.stdout.decode("utf-8", errors="replace").strip()
    except (OSError, subprocess.SubprocessError):
        _probe_cache[cache_key] = None
        return None

    m = _VER_QUOTED_RE.search(out) or _VER_PLAIN_RE.search(out)
    if not m:
        _probe_cache[cache_key] = None
        return None

    ver_str = m.group(1)
    major = _parse_major(ver_str)
    if not major:
        _probe_cache[cache_key] = None
        return None

    low = out.lower()
    is_64 = "32-bit" not in low
    vendor = _detect_vendor(out, resolved)
    arch_note = "" if is_64 else ", 32-bit"
    info = {
        "path": resolved,
        "major": major,
        "version": ver_str,
        "vendor": vendor,
        "is_64bit": is_64,
        "label": f"Java {major} ({vendor} {ver_str}{arch_note})",
    }
    _probe_cache[cache_key] = info
    return info


def _candidate_paths(mc_dir=None):
    exe = "java.exe" if sys.platform.startswith("win") else "java"
    cands = []

    # 1. Рантаймы Mojang в .minecraft/runtime
    if mc_dir:
        rt_root = Path(mc_dir) / "runtime"
        if rt_root.is_dir():
            for p in rt_root.rglob(exe):
                if p.parent.name == "bin":
                    cands.append(p)

    # 2. Переменные окружения и PATH
    for env_name in ("JAVA_HOME", "JDK_HOME", "JRE_HOME"):
        val = os.environ.get(env_name)
        if val:
            cands.append(Path(val) / "bin" / exe)
    which_java = shutil.which("java")
    if which_java:
        cands.append(Path(which_java))
    for path_dir in os.environ.get("PATH", "").split(os.pathsep):
        if path_dir:
            cands.append(Path(path_dir) / exe)

    # 3. Типичные системные директории разных ОС
    home = Path.home()
    roots = []
    if sys.platform.startswith("win"):
        for env_k in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            base = os.environ.get(env_k)
            if base:
                b = Path(base)
                for vendor_dir in (
                    "Eclipse Adoptium", "AdoptOpenJDK", "Java", "Zulu",
                    "BellSoft", "Microsoft", "Amazon Corretto", "GraalVM",
                ):
                    roots.append(b / vendor_dir)
                roots.append(b / "Programs" / "Eclipse Adoptium")
    elif sys.platform == "darwin":
        roots += [
            Path("/Library/Java/JavaVirtualMachines"),
            home / "Library/Java/JavaVirtualMachines",
            Path("/opt/homebrew/opt"),
            Path("/usr/local/opt"),
        ]
    else:
        roots += [
            Path("/usr/lib/jvm"),
            Path("/usr/java"),
            Path("/opt/java"),
            Path("/opt/jdk"),
        ]
    roots += [home / ".jdks", home / ".sdkman/candidates/java"]

    for root in roots:
        try:
            if not root.is_dir():
                continue
            for sub in root.iterdir():
                if not sub.is_dir():
                    continue
                cands.append(sub / "bin" / exe)
                cands.append(sub / "jre" / "bin" / exe)
                cands.append(sub / "Contents" / "Home" / "bin" / exe)
        except OSError:
            continue

    return cands


def detect_java_installations(mc_dir=None):
    """Возвращает список найденных в системе Java: [{'path','major','version','vendor','is_64bit','label'}]."""
    seen = set()
    found = []
    for cand in _candidate_paths(mc_dir):
        try:
            if not cand.exists():
                continue
            real = str(cand.resolve())
        except OSError:
            continue
        if real in seen:
            continue
        seen.add(real)
        info = probe_java(real)
        if info and info["path"] not in {x["path"] for x in found}:
            found.append(info)

    found.sort(key=lambda j: (
        -j["major"],
        0 if j["vendor"] == "Mojang" else 1,
        0 if j["is_64bit"] else 1,
        j["path"],
    ))
    return found


def mojang_component_for_major(major):
    if not major:
        return None
    if major in _MOJANG_RUNTIME_BY_MAJOR:
        return _MOJANG_RUNTIME_BY_MAJOR[major]
    if major < 16:
        return "jre-legacy"
    if major < 21:
        return "java-runtime-gamma"
    return "java-runtime-delta"


def resolve_java(cfg, mc_dir, version_id=None, server_java_version=None, cb=None):
    """
    Возвращает (java_executable_path, major_version).
    Учитывает ручной выбор игрока, требование сервера (server_java_version) и метаданные версии MC.
    """
    mc_dir = Path(mc_dir)

    # 1. Ручной выбор Java в настройках
    if cfg.get("java_mode") == "manual" and str(cfg.get("java_path", "")).strip():
        manual_raw = str(cfg["java_path"]).strip()
        info = probe_java(manual_raw)
        if not info:
            raise RuntimeError(f"Выбранная вручную Java не найдена или не запускается: {manual_raw}")
        if server_java_version and info["major"] < int(server_java_version):
            log.warning(
                "Ручная Java %s ниже рекомендуемой сервером Java %s",
                info["major"], server_java_version,
            )
        return info["path"], info["major"]

    # 2. Определяем требуемую версию Java
    req_major = int(server_java_version) if server_java_version else None
    rt_component = mojang_component_for_major(req_major) if req_major else None

    if version_id:
        try:
            rt_info = mll.runtime.get_version_runtime_information(version_id, str(mc_dir))
            if rt_info:
                if req_major is None:
                    req_major = int(rt_info["javaMajorVersion"])
                    rt_component = rt_info["name"]
                elif int(rt_info["javaMajorVersion"]) == req_major:
                    rt_component = rt_info["name"]
        except Exception:
            log.debug("не удалось прочитать runtime-инфо для %s", version_id, exc_info=True)

    # 3. Проверяем уже установленные Java (сначала точное совпадение мажорной версии)
    installed = detect_java_installations(mc_dir)
    if req_major:
        exact = [j for j in installed if j["major"] == req_major and j["is_64bit"]]
        if not exact:
            exact = [j for j in installed if j["major"] == req_major]
        if exact:
            return exact[0]["path"], exact[0]["major"]

    # 4. Докачиваем официальный рантайм Mojang нужной версии
    if rt_component:
        try:
            existing_rt = mll.runtime.get_executable_path(rt_component, str(mc_dir))
            if not existing_rt:
                log.info("Устанавливаем Java-рантайм Mojang: %s (Java %s)", rt_component, req_major)
                mll.runtime.install_jvm_runtime(rt_component, str(mc_dir), callback=cb or {})
                existing_rt = mll.runtime.get_executable_path(rt_component, str(mc_dir))
            if existing_rt:
                probed = probe_java(existing_rt)
                return existing_rt, (probed["major"] if probed else (req_major or 17))
        except Exception:
            log.exception("не удалось установить рантайм Mojang %s", rt_component)

    # 5. Запасной вариант: любая подходящая системная Java >= req_major
    if req_major:
        compat = [j for j in installed if j["major"] >= req_major]
        if compat:
            compat.sort(key=lambda j: j["major"])
            return compat[0]["path"], compat[0]["major"]
    if installed:
        return installed[0]["path"], installed[0]["major"]
    return "java", (req_major or 17)


# ------------------------------------------------------------ JVM-пресеты
def all_presets(cfg):
    """Словарь {имя: строка_флагов}, объединяющий встроенные и пользовательские пресеты."""
    merged = dict(BUILTIN_PRESETS)
    custom = cfg.get("custom_jvm_presets")
    if isinstance(custom, dict):
        for k, v in custom.items():
            if isinstance(k, str) and k.strip():
                if isinstance(v, list):
                    merged[k.strip()] = " ".join(str(x) for x in v)
                elif isinstance(v, str):
                    merged[k.strip()] = v.strip()
    return merged


def split_jvm_args(text):
    """Разбивает строку JVM-аргументов в список без поломки Windows-путей."""
    if not text or not str(text).strip():
        return []
    raw = str(text).strip()
    try:
        parts = shlex.split(raw, posix=(not sys.platform.startswith("win")))
        if sys.platform.startswith("win"):
            parts = [p[1:-1] if len(p) >= 2 and p[0] == p[-1] and p[0] in "\"'" else p for p in parts]
        return [p for p in parts if p]
    except ValueError:
        return raw.split()


def build_jvm_arguments(cfg, ram_mb, java_major=17):
    """Формирует итоговый список JVM-аргументов из RAM + пресета + доп. параметров."""
    ram = max(1024, int(ram_mb))
    presets = all_presets(cfg)
    preset_name = cfg.get("jvm_preset", "G1GC")
    if preset_name not in presets:
        preset_name = "G1GC"

    preset_flags = split_jvm_args(presets.get(preset_name, ""))
    extra_flags = split_jvm_args(cfg.get("extra_jvm_args", ""))

    # Защита от падения, если выбран ZGC на старой Java (< 17) + авто-ZGenerational на Java 21-22
    has_zgc = any(f == "-XX:+UseZGC" for f in preset_flags)
    if has_zgc and java_major and java_major < 17:
        log.warning("ZGC не поддерживается на Java %s — переключаемся на G1GC", java_major)
        preset_flags = split_jvm_args(BUILTIN_PRESETS["G1GC"])
    elif has_zgc and java_major in (21, 22) and "-XX:+ZGenerational" not in preset_flags:
        preset_flags.append("-XX:+ZGenerational")

    combined = preset_flags + extra_flags
    has_custom_xmx = any(a.startswith("-Xmx") for a in combined)
    has_custom_xms = any(a.startswith("-Xms") for a in combined)

    mem_args = []
    if not has_custom_xmx:
        mem_args.append(f"-Xmx{ram}M")
    if not has_custom_xms:
        xms = min(ram, 2048) if preset_name != "Aikar's Flags" else min(ram, 4096)
        mem_args.append(f"-Xms{xms}M")

    # Гарантируем, что незнакомые конкретной подверсии JVM тонкие опции не уронят старт
    guard = ["-XX:+IgnoreUnrecognizedVMOptions"]
    dedup = []
    for arg in mem_args + guard + combined:
        if arg not in dedup or arg.startswith("-D") or arg.startswith("--add-"):
            dedup.append(arg)
    return dedup
