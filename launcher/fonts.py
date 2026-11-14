"""Bundled fonts: registration in process (Win/macOS) or user directory (Linux).

Inter — single UI font (matches the fonts of the banner SVG), JetBrains Mono — logs and crash reports
(with Cyrillic support). Both families are under SIL OFL 1.1 (see fonts/OFL-*.txt).
All loading is done as best-effort: if it fails, standard system fonts are used,
as it was before. A system-wide installation is NOT performed:
- Windows: AddFontResourceExW with FR_PRIVATE (font visible only to our process);
- macOS:  CoreText with kCTFontManagerScopeProcess (same, only for the process);
- Linux:  copying to ~/.local/share/fonts/botyaraMC + fc-cache (user directory,
          deleted manually or when clearing the config folder is not required).
"""
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

log = logging.getLogger("botyaraMC.fonts")

FONTS_DIR = Path(__file__).resolve().parent / "fonts"

UI_FAMILY = "Inter"
MONO_FAMILY = "JetBrains Mono"

FONT_FILES = (
    "Inter-Regular.ttf",
    "Inter-Bold.ttf",
    "JetBrainsMono-Regular.ttf",
    "JetBrainsMono-Bold.ttf",
)

_LINUX_FONT_SUBDIR = "botyaraMC"

_loaded = False


def ensure_loaded() -> bool:
    """Loads bundled fonts. Call strictly BEFORE creating the Tk root
    (on Linux, fontconfig scans the user directory during Tk startup).
    Idempotent, any failures are silent: fallback -> system fonts."""
    global _loaded
    if _loaded:
        return True
    _loaded = True
    paths = [FONTS_DIR / name for name in FONT_FILES if (FONTS_DIR / name).is_file()]
    if not paths:
        log.debug("bundled fonts are missing - using system fonts")
        return False
    try:
        if sys.platform.startswith("win"):
            _load_windows(paths)
        elif sys.platform == "darwin":
            _load_macos(paths)
        else:
            _install_linux(paths)
        return True
    except Exception:
        log.debug("font loading failed - using system fonts", exc_info=True)
        return False


def resolve_families(root):
    """After creating the Tk root: actually checks what was picked up by the system.
    Returns (ui_family, mono_family); None -> caller takes the system fallback."""
    try:
        from tkinter import font as tkfont
        fams = set(tkfont.families(root))
    except Exception:
        return None, None
    ui = UI_FAMILY if UI_FAMILY in fams else None
    mono = MONO_FAMILY if MONO_FAMILY in fams else None
    return ui, mono


# ----------------------------------------------------------------------------
def _load_windows(paths):
    """FR_PRIVATE: fonts live only in our process, without polluting the system registry."""
    import ctypes
    FR_PRIVATE = 0x10
    for p in paths:
        ok = ctypes.windll.gdi32.AddFontResourceExW(str(p), FR_PRIVATE, 0)
        if not ok:
            log.debug("AddFontResourceExW failed: %s", p.name)


def _load_macos(paths):
    """Registering fonts in the process scope via CoreText (no touching the system)."""
    import ctypes
    import ctypes.util

    ct_path = ctypes.util.find_library("CoreText")
    cf_path = ctypes.util.find_library("CoreFoundation")
    if not ct_path or not cf_path:
        return
    ct = ctypes.cdll.LoadLibrary(ct_path)
    cf = ctypes.cdll.LoadLibrary(cf_path)

    cf.CFURLCreateFromFileSystemRepresentation.restype = ctypes.c_void_p
    cf.CFURLCreateFromFileSystemRepresentation.argtypes = [
        ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long, ctypes.c_bool]
    cf.CFRelease.argtypes = [ctypes.c_void_p]
    ct.CTFontManagerRegisterFontsForURL.restype = ctypes.c_bool
    ct.CTFontManagerRegisterFontsForURL.argtypes = [
        ctypes.c_void_p, ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p)]

    kCTFontManagerScopeProcess = 1
    for p in paths:
        url = cf.CFURLCreateFromFileSystemRepresentation(None, str(p).encode("utf-8"), len(str(p).encode("utf-8")), False)
        if not url:
            continue
        try:
            err = ctypes.c_void_p()
            ct.CTFontManagerRegisterFontsForURL(url, kCTFontManagerScopeProcess, ctypes.byref(err))
        finally:
            cf.CFRelease(url)


def _install_linux(paths, target_dir=None):
    """Linux: fonts go to the user font directory, fontconfig picks them up on the next Tk startup."""
    if target_dir is None:
        xdg = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        target_dir = Path(xdg) / "fonts" / _LINUX_FONT_SUBDIR
    target_dir = Path(target_dir)
    changed = False
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    for p in paths:
        dst = target_dir / p.name
        try:
            if not dst.is_file() or dst.stat().st_size != p.stat().st_size:
                shutil.copyfile(p, dst)
                changed = True
        except OSError:
            log.debug("failed to copy font %s", p.name)
    if changed:
        fc = shutil.which("fc-cache")
        if fc:
            try:
                subprocess.run([fc, "-f", str(target_dir)], timeout=15,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except (OSError, subprocess.TimeoutExpired):
                pass
