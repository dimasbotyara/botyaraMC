"""Интерфейс botyaraMC: мастер первого запуска, главное окно, настройки, краш-парсер и хоткеи."""
import logging
import queue
import re
import sys
import threading
import time
import tkinter as tk
import webbrowser
from functools import partial
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

import config as cfgmod
import crash
import discovery
import jvm
import mc
import sync
import themes

log = logging.getLogger("botyaraMC.ui")
NICK_RE = re.compile(r"^[A-Za-z0-9_]{3,16}$")
DEFAULT_PORT = 25456

WINDOW_MODES_UI = {
    "Обычное": "default",
    "Полный экран": "fullscreen",
    "Свой размер": "custom",
}
WINDOW_MODES_REV = {v: k for k, v in WINDOW_MODES_UI.items()}


def parse_hostport(text):
    t = text.strip().rstrip("/")
    for prefix in ("http://", "https://"):
        if t.startswith(prefix):
            t = t[len(prefix):]
    if not t:
        return None
    host, port = t, DEFAULT_PORT
    if ":" in t:
        host, _, p = t.rpartition(":")
        if not p.isdigit() or not 0 < int(p) < 65536:
            return None
        port = int(p)
    if not host or " " in host:
        return None
    return host, port


class App(ctk.CTk):
    def __init__(self):
        if sys.platform.startswith("win"):
            try:
                import ctypes
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                    "dimasbotyara.botyaraMC.launcher"
                )
            except Exception:
                pass
        self.cfg = cfgmod.load()
        if self.cfg["theme"] not in themes.THEMES:
            self.cfg["theme"] = themes.DEFAULT
        self.theme = themes.THEMES[self.cfg["theme"]]
        ctk.set_appearance_mode(self.theme["mode"])
        super().__init__()
        self.title("botyaraMC")
        self.geometry("860x660")
        self.minsize(780, 600)
        self.configure(fg_color=self.theme["bg"])
        self._ico_path, self._icon_img = None, None
        self._apply_window_icon()

        self._reg = {}            # виджет -> {опция: ключ палитры}
        self._q = queue.Queue()   # сообщения из потоков в UI
        self.view = None
        self.view_name = ""
        self.playing = False
        self._status, self._prog = "", 0.0
        self._play_btn_text = "▶  ИГРАТЬ"
        self._server_badge_text = ""
        self._last_manifest = cfgmod.load_cache()
        self._save_settings_fn = None
        self._cancel_settings_fn = None
        self._active_dialogs = []
        self._force = False
        self.draft = {
            "nick": self.cfg["nickname"],
            "theme": self.cfg["theme"],
            "host": self._addr_text(),
        }

        self._bind_hotkeys()
        self.after(60, self._pump)
        self.show("main" if self.cfg["setup_done"] else "wizard")

    def _apply_window_icon(self):
        here = Path(__file__).resolve().parent
        for ico in (here / "icon.ico", here.parent / "assets" / "icon.ico"):
            if ico.is_file():
                self._ico_path = str(ico)
                break
        if sys.platform.startswith("win") and self._ico_path:
            try:
                self.iconbitmap(self._ico_path)
            except Exception:
                pass
        for cand in (here / "icon.png", here.parent / "assets" / "icon.png"):
            if cand.is_file():
                try:
                    self._icon_img = tk.PhotoImage(file=str(cand))
                    self.iconphoto(True, self._icon_img)
                except Exception:
                    pass
                break

    # ------------------------------------------------------------ темы
    def T(self, w, **opts):
        """Регистрирует виджет: opts = {опция_ctk: ключ_палитры}. Перекрашивается вживую."""
        self._reg.setdefault(w, {}).update(opts)
        w.configure(**{k: self.theme[v] for k, v in opts.items()})
        return w

    def apply_theme(self, name):
        if name not in themes.THEMES:
            return
        self.theme = themes.THEMES[name]
        ctk.set_appearance_mode(self.theme["mode"])
        self.configure(fg_color=self.theme["bg"])
        for w, opts in list(self._reg.items()):
            try:
                w.configure(**{k: self.theme[v] for k, v in opts.items()})
            except Exception:
                self._reg.pop(w, None)

    # ------------------------------------------------------------ хоткеи
    def _is_typing_widget(self):
        w = self.focus_get()
        if w is None:
            return False
        cls = w.winfo_class().lower()
        return any(t in cls for t in ("entry", "text"))

    def _bind_hotkeys(self):
        self.bind_all("<F1>", lambda _e: self._open_hotkeys_dialog())
        self.bind_all("<F5>", lambda _e: self._on_hotkey_refresh())
        self.bind_all("<Control-r>", lambda _e: self._on_hotkey_refresh())
        self.bind_all("<Control-R>", lambda _e: self._on_hotkey_refresh())
        self.bind_all("<Control-o>", lambda _e: self._on_hotkey_folders())
        self.bind_all("<Control-O>", lambda _e: self._on_hotkey_folders())
        self.bind_all("<Control-l>", lambda _e: self._on_hotkey_log())
        self.bind_all("<Control-L>", lambda _e: self._on_hotkey_log())
        self.bind_all("<Control-comma>", lambda _e: self._on_hotkey_settings())
        self.bind_all("<Control-p>", lambda _e: self._on_hotkey_play())
        self.bind_all("<Control-P>", lambda _e: self._on_hotkey_play())
        self.bind_all("<Control-s>", lambda _e: self._on_hotkey_save())
        self.bind_all("<Control-S>", lambda _e: self._on_hotkey_save())
        self.bind_all("<Return>", lambda _e: self._on_hotkey_enter())
        self.bind_all("<Escape>", lambda _e: self._on_hotkey_escape())

    def _clean_dialogs(self):
        self._active_dialogs = [d for d in self._active_dialogs if d.winfo_exists()]

    def _on_hotkey_play(self):
        if self.view_name == "main" and not self.playing:
            self.on_play()

    def _on_hotkey_enter(self):
        self._clean_dialogs()
        if self._active_dialogs or self._is_typing_widget():
            return
        if self.view_name == "main" and not self.playing:
            self.on_play()

    def _on_hotkey_refresh(self):
        if self.view_name == "main" and not self.playing:
            self.refresh_download_plan(manual=True)

    def _on_hotkey_folders(self):
        if self.cfg.get("setup_done"):
            self._open_folders_dialog()

    def _on_hotkey_log(self):
        if self.cfg.get("setup_done"):
            self._open_latest_game_log()

    def _on_hotkey_settings(self):
        if self.view_name == "main":
            self.show("settings")

    def _on_hotkey_save(self):
        if self.view_name == "settings" and self._save_settings_fn:
            self._save_settings_fn()

    def _on_hotkey_escape(self):
        self._clean_dialogs()
        if self._active_dialogs:
            top = self._active_dialogs.pop()
            try:
                top.destroy()
            except Exception:
                pass
            return
        if self.view_name == "settings" and self._cancel_settings_fn:
            self._cancel_settings_fn()

    # ------------------------------------------------------------ мелкие помощники
    def post(self, fn, *a, **kw):
        self._q.put(partial(fn, *a, **kw))

    def _pump(self):
        try:
            while True:
                self._q.get_nowait()()
        except queue.Empty:
            pass
        except Exception:
            log.exception("ошибка в UI-очереди")
        self.after(60, self._pump)

    def show(self, name, *a):
        self._save_settings_fn = None
        self._cancel_settings_fn = None
        if self.view is not None:
            self.view.destroy()
        self.view_name = name
        self.view = getattr(self, "_view_" + name)(*a)
        self.view.pack(fill="both", expand=True)
        if name == "main":
            self.refresh_download_plan(manual=False)

    def frame(self, parent, key="bg", **kw):
        kw.setdefault("corner_radius", 0)
        return self.T(ctk.CTkFrame(parent, **kw), fg_color=key)

    def scroll_frame(self, parent, key="panel", **kw):
        sf = ctk.CTkScrollableFrame(parent, corner_radius=12, **kw)
        return self.T(
            sf,
            fg_color=key,
            scrollbar_button_color="surface_hover",
            scrollbar_button_hover_color="accent",
        )

    def label(self, parent, text, size=14, bold=False, color="text", **kw):
        font = ctk.CTkFont(size=size, weight="bold" if bold else "normal")
        return self.T(ctk.CTkLabel(parent, text=text, font=font, justify="left", **kw),
                      text_color=color)

    def msg(self, lbl, text, kind="subtext"):
        lbl.configure(text=text)
        self.T(lbl, text_color=kind)

    def button(self, parent, text, command=None, primary=True, **kw):
        b = ctk.CTkButton(parent, text=text, command=command, corner_radius=10, **kw)
        if primary:
            return self.T(b, fg_color="accent", hover_color="accent_hover",
                          text_color="on_accent", text_color_disabled="surface_hover")
        return self.T(b, fg_color="surface", hover_color="surface_hover",
                      text_color="text", text_color_disabled="subtext")

    def danger_button(self, parent, text, command=None, **kw):
        b = ctk.CTkButton(parent, text=text, command=command, corner_radius=10, **kw)
        return self.T(b, fg_color="danger", hover_color="accent_hover",
                      text_color="on_accent", text_color_disabled="subtext")

    def entry(self, parent, **kw):
        return self.T(ctk.CTkEntry(parent, corner_radius=8, **kw), fg_color="surface",
                      border_color="border", text_color="text",
                      placeholder_text_color="subtext")

    def option_menu(self, parent, values, command=None, **kw):
        om = ctk.CTkOptionMenu(parent, values=values, command=command, corner_radius=8, **kw)
        return self.T(
            om,
            fg_color="surface",
            button_color="surface_hover",
            button_hover_color="border",
            text_color="text",
            dropdown_fg_color="surface",
            dropdown_hover_color="surface_hover",
            dropdown_text_color="text",
        )

    def segmented(self, parent, values, command=None, **kw):
        sb = ctk.CTkSegmentedButton(parent, values=values, command=command, corner_radius=8, **kw)
        return self.T(
            sb,
            fg_color="surface",
            selected_color="accent",
            selected_hover_color="accent_hover",
            unselected_color="surface",
            unselected_hover_color="surface_hover",
            text_color="on_accent",
        )

    def _make_dialog(self, title, width=560, height=440):
        dlg = ctk.CTkToplevel(self)
        dlg.title(title)
        dlg.geometry(f"{width}x{height}")
        dlg.minsize(min(460, width), min(320, height))
        self.T(dlg, fg_color="bg")
        if sys.platform.startswith("win") and self._ico_path:
            try:
                dlg.iconbitmap(self._ico_path)
            except Exception:
                pass
        dlg.transient(self)
        self._clean_dialogs()
        self._active_dialogs.append(dlg)
        dlg.after(80, lambda: self._focus_dialog(dlg))
        return dlg

    def _focus_dialog(self, dlg):
        try:
            if dlg.winfo_exists():
                dlg.lift()
                dlg.focus_force()
        except Exception:
            pass

    def _copy_clipboard(self, text):
        self.clipboard_clear()
        self.clipboard_append(text)
        self.update_idletasks()

    def _addr_text(self):
        h, p = self.cfg.get("sync_host", ""), self.cfg.get("sync_port", DEFAULT_PORT)
        return "" if not h else (h if p == DEFAULT_PORT else f"{h}:{p}")

    def _browse_dir(self, entry):
        path = filedialog.askdirectory()
        if path:
            entry.configure(state="normal")
            entry.delete(0, "end")
            entry.insert(0, path)

    def _browse_file(self, entry, on_change=None):
        filetypes = [("Java executable", "java.exe javaw.exe java"), ("Все файлы", "*.*")] \
            if sys.platform.startswith("win") else [("Все файлы", "*")]
        path = filedialog.askopenfilename(filetypes=filetypes)
        if path:
            entry.configure(state="normal")
            entry.delete(0, "end")
            entry.insert(0, path)
            if on_change:
                on_change()

    def _autofind(self, entry, lbl, btn):
        btn.configure(state="disabled")
        self.msg(lbl, "Ищем сервер в сети… 🔍")

        def work():
            self.post(done, discovery.discover(3.0))

        def done(res):
            try:
                btn.configure(state="normal")
                if res:
                    host, port = res
                    entry.delete(0, "end")
                    entry.insert(0, host if port == DEFAULT_PORT else f"{host}:{port}")
                    self.msg(lbl, f"Нашли сервер: {host} 🎉", "success")
                else:
                    self.msg(lbl, "Не нашли 😕 Включён Radmin VPN? Можно вписать IP руками.", "danger")
            except Exception:
                pass

        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------ мастер первого запуска
    def _view_wizard(self, step=1):
        root = self.frame(self, "bg")
        card = self.frame(root, "panel", corner_radius=18)
        card.pack(fill="both", expand=True, padx=28, pady=28)
        self.label(card, f"Шаг {step} из 3", 12, color="subtext").pack(
            anchor="w", padx=28, pady=(22, 0))
        getattr(self, f"_step{step}")(card)
        return root

    def _nav(self, card, back, next_text, next_cmd):
        bar = self.frame(card, "panel")
        bar.pack(side="bottom", fill="x", padx=28, pady=22)
        nxt = self.button(bar, next_text, next_cmd, width=170, height=42)
        nxt.pack(side="right")
        if back:
            self.button(bar, "← Назад", back, primary=False, width=110, height=42).pack(side="left")
        return nxt

    def _step1(self, card):
        self.label(card, "Привет! Добро пожаловать в botyaraMC 👋", 26, True).pack(
            anchor="w", padx=28, pady=(6, 4))
        self.label(card, "Как тебя зовут в игре? Это будет твой ник 😎", color="subtext").pack(
            anchor="w", padx=28)
        e = self.entry(card, height=44, width=340, placeholder_text="Например, Steve_228")
        e.pack(anchor="w", padx=28, pady=(20, 6))
        e.insert(0, self.draft["nick"])
        err = self.label(card, "3–16 символов: английские буквы, цифры и _", 12, color="subtext")
        err.pack(anchor="w", padx=28)

        def nxt():
            nick = e.get().strip()
            if not NICK_RE.match(nick):
                self.msg(err, "Ник: 3–16 символов, только a-z, A-Z, 0-9 и _ 🙂", "danger")
                return
            self.draft["nick"] = nick
            self.show("wizard", 2)

        e.bind("<Return>", lambda _e: nxt())
        self._nav(card, None, "Дальше →", nxt)

    def _step2(self, card):
        self.label(card, "Выбери тему 🎨", 26, True).pack(anchor="w", padx=28, pady=(6, 4))
        self.label(card, "Всё вокруг перекрашивается прямо сейчас — это и есть предпросмотр.",
                   color="subtext").pack(anchor="w", padx=28)
        body = self.frame(card, "panel")
        body.pack(fill="both", expand=True, padx=28, pady=14)
        left = self.frame(body, "panel")
        left.pack(side="left", fill="y")
        var = tk.StringVar(value=self.draft["theme"])

        def pick():
            self.draft["theme"] = var.get()
            self.apply_theme(var.get())

        for name in themes.THEME_NAMES:
            rb = ctk.CTkRadioButton(left, text=name, variable=var, value=name, command=pick,
                                    font=ctk.CTkFont(size=15))
            self.T(rb, text_color="text", fg_color="accent", hover_color="accent_hover",
                   border_color="subtext")
            rb.pack(anchor="w", pady=9)
        right = self.frame(body, "panel")
        right.pack(side="right", fill="both", expand=True, padx=(28, 0))
        self._mock(right)
        self._nav(card, lambda: self.show("wizard", 1), "Дальше →", lambda: self.show("wizard", 3))

    def _mock(self, parent):
        m = self.frame(parent, "bg", corner_radius=16, border_width=2)
        self.T(m, border_color="border")
        m.pack(fill="both", expand=True)
        self.label(m, "botyaraMC", 30, True, "accent").pack(pady=(26, 2))
        self.label(m, f"Привет, {self.draft['nick'] or 'игрок'}! 👋", color="subtext").pack()
        pb = ctk.CTkProgressBar(m, width=230)
        self.T(pb, fg_color="surface", progress_color="accent")
        pb.set(0.65)
        pb.pack(pady=18)
        self.button(m, "▶  ИГРАТЬ", None, width=210, height=42,
                    font=ctk.CTkFont(size=16, weight="bold")).pack()
        row = self.frame(m, "bg")
        row.pack(pady=20)
        for key in ("accent", "success", "danger", "surface", "text"):
            self.frame(row, key, corner_radius=10, width=26, height=26).pack(side="left", padx=4)

    def _step3(self, card):
        self.label(card, "Где живёт сервер синхронизации? 🌐", 26, True).pack(
            anchor="w", padx=28, pady=(6, 4))
        self.label(card, "Впиши IP в Radmin VPN или нажми «Найти автоматически».",
                   color="subtext").pack(anchor="w", padx=28)
        row = self.frame(card, "panel")
        row.pack(anchor="w", padx=28, pady=(20, 6))
        e = self.entry(row, height=44, width=290, placeholder_text="26.12.34.56")
        e.pack(side="left")
        e.insert(0, self.draft["host"])
        m = self.label(card, "", 13, color="subtext", wraplength=620)
        find = self.button(row, "🔍 Найти автоматически", primary=False, height=44, width=200)
        find.configure(command=lambda: self._autofind(e, m, find))
        find.pack(side="left", padx=12)
        m.pack(anchor="w", padx=28, pady=4)
        self._force = False

        def reset(_e=None):
            if self._force:
                self._force = False
                fin.configure(text="Готово 🚀")

        e.bind("<KeyRelease>", reset)

        def finish():
            parsed = parse_hostport(e.get())
            if not parsed:
                self.msg(m, "Не похоже на адрес 🤔 Пример: 26.12.34.56", "danger")
                return
            host, port = parsed
            self.draft["host"] = e.get()
            if self._force:
                return self._finish_setup(host, port)
            fin.configure(state="disabled")
            self.msg(m, "Проверяем связь… ⏳")

            def work():
                try:
                    mf = sync.fetch_manifest(host, port)
                    cfgmod.save_cache(mf)
                    self.post(done, True)
                except Exception:
                    log.exception("проверка сервера не прошла")
                    self.post(done, False)

            def done(ok):
                try:
                    fin.configure(state="normal")
                    if ok:
                        self._finish_setup(host, port)
                    else:
                        self._force = True
                        fin.configure(text="Сохранить так 💾")
                        self.msg(m, "Сервер не отвечает 😕 Проверь IP и Radmin VPN. "
                                    "Можно сохранить как есть и поправить позже.", "danger")
                except Exception:
                    pass

            threading.Thread(target=work, daemon=True).start()

        fin = self._nav(card, lambda: self.show("wizard", 2), "Готово 🚀", finish)

    def _finish_setup(self, host, port):
        c = self.cfg
        c.update(
            nickname=self.draft["nick"],
            theme=self.draft["theme"],
            sync_host=host,
            sync_port=port,
            setup_done=True,
            mc_dir=str(mc.find_minecraft_dir(c.get("mc_dir", ""))),
        )
        cfgmod.save(c)
        self.show("main")

    # ------------------------------------------------------------ главное окно
    def _view_main(self):
        root = self.frame(self, "bg")
        top = self.frame(root, "bg")
        top.pack(fill="x", padx=20, pady=(16, 0))

        self.button(top, "⚙ Настройки", lambda: self.show("settings"), primary=False,
                    width=130, height=34).pack(side="right")
        self.button(top, "📂 Папки ▾", self._open_folders_dialog, primary=False,
                    width=112, height=34).pack(side="right", padx=(0, 8))
        self.button(top, "📄 Лог", self._open_latest_game_log, primary=False,
                    width=84, height=34).pack(side="right", padx=(0, 8))
        self.button(top, "⌨", self._open_hotkeys_dialog, primary=False,
                    width=38, height=34).pack(side="right", padx=(0, 8))

        left_info = self.frame(top, "bg")
        left_info.pack(side="left")
        if self.cfg["is_host"]:
            self.label(left_info, "👑 режим хоста", 13, True, color="accent").pack(side="left", padx=(0, 10))
        ram_now = cfgmod.effective_ram_mb(self.cfg)
        ram_tag = "Авто-RAM" if self.cfg.get("auto_ram", True) else "RAM"
        self.label(
            left_info,
            f"{ram_tag}: {ram_now} МБ • {self.cfg.get('jvm_preset', 'G1GC')}",
            12, color="subtext",
        ).pack(side="left")

        center = self.frame(root, "bg")
        center.pack(expand=True)
        self.label(center, "botyaraMC", 56, True, "accent").pack()
        self.label(center, f"Привет, {self.cfg['nickname']}! 👋", 18, color="subtext").pack(pady=(0, 8))

        self.badge_lbl = self.label(center, self._server_badge_text, 13, color="subtext")
        self.badge_lbl.pack(pady=(0, 20))

        self.play_btn = self.button(
            center, self._play_btn_text, self.on_play,
            width=370, height=68,
            font=ctk.CTkFont(size=20, weight="bold"),
        )
        self.play_btn.pack()
        if self.playing:
            self.play_btn.configure(state="disabled")

        self.progress = ctk.CTkProgressBar(center, width=400)
        self.T(self.progress, fg_color="surface", progress_color="accent")
        self.progress.set(self._prog)
        self.progress.pack(pady=(24, 8))

        self.status_lbl = self.label(center, self._status, 14, color="subtext", wraplength=660)
        self.status_lbl.pack()

        bottom = self.frame(root, "bg")
        bottom.pack(side="bottom", fill="x", padx=22, pady=(0, 12))
        self.label(
            bottom,
            "Enter — играть  •  F5 — обновить размер  •  Ctrl+O — папки  •  Ctrl+L — лог  •  F1 — все хоткеи",
            11, color="subtext",
        ).pack(side="left")
        return root

    def _set_status(self, text):
        self._status = text
        try:
            self.status_lbl.configure(text=text)
        except Exception:
            pass

    def _set_progress(self, f):
        self._prog = max(0.0, min(1.0, f))
        try:
            self.progress.set(self._prog)
        except Exception:
            pass

    def _set_play_text(self, text):
        self._play_btn_text = text
        try:
            self.play_btn.configure(text=text)
        except Exception:
            pass

    def _set_badge(self, text):
        self._server_badge_text = text
        try:
            self.badge_lbl.configure(text=text)
        except Exception:
            pass

    def refresh_download_plan(self, manual=False):
        """Фоновая проверка манифеста и расчёт суммарного размера к скачиванию."""
        if self.playing:
            return
        if manual:
            self._set_status("Обновляем данные с сервера… 🔄")

        def work():
            cfg = self.cfg
            host, port = cfg.get("sync_host", ""), cfg.get("sync_port", DEFAULT_PORT)
            if not host:
                return
            try:
                mf = sync.fetch_manifest(host, port)
                cfgmod.save_cache(mf)
                self._last_manifest = mf
                mc_dir = mc.find_minecraft_dir(cfg.get("mc_dir", ""))
                plan = sync.plan_sync(
                    mf, mc_dir,
                    is_host=cfg.get("is_host", False),
                    server_mods_dir=cfg.get("server_mods_dir", ""),
                )
                self.post(_apply_plan, mf, plan, True)
            except Exception:
                cached = cfgmod.load_cache()
                self.post(_apply_plan, cached, None, False)

        def _apply_plan(mf, plan, online):
            if self.playing:
                return
            if mf:
                parts = [f"Minecraft {mf['mc_version']}", mf["loader"]]
                if mf.get("java_version"):
                    parts.append(f"Java {mf['java_version']}")
                parts.append(f"модов: {len(mf.get('mods', []))}")
                if mf.get("resourcepacks"):
                    parts.append(f"РП: {len(mf['resourcepacks'])}")
                if mf.get("mods_hidden"):
                    parts.append("🕵 скрыты")
                self._set_badge("  •  ".join(parts))

            if online and plan is not None:
                tb = plan["total_bytes"]
                if tb > 0:
                    sz = sync.format_size(tb)
                    self._set_play_text(f"▶  ИГРАТЬ  •  Скачать {sz}")
                    if manual or not self._status:
                        self._set_status(
                            f"Нужно докачать {sz} (модов: {plan['mods_count']}, ресурспаков: {plan['rp_count']}) 📦"
                        )
                elif plan["total_files"] > 0:
                    self._set_play_text("▶  ИГРАТЬ  •  Обновить файлы")
                else:
                    self._set_play_text("▶  ИГРАТЬ")
                    if manual:
                        self._set_status("Все моды и ресурспаки уже скачаны ✨")
            else:
                self._set_play_text("▶  ИГРАТЬ")
                if manual:
                    self._set_status("Сервер сейчас не в сети — запуск пойдёт из локального кэша 📡")

        threading.Thread(target=work, daemon=True).start()

    def _play_done(self):
        self.playing = False
        try:
            self.play_btn.configure(state="normal")
        except Exception:
            pass
        self.refresh_download_plan(manual=False)

    def on_play(self):
        if self.playing:
            return
        self.playing = True
        try:
            self.play_btn.configure(state="disabled")
        except Exception:
            pass
        threading.Thread(target=self._play_worker, daemon=True).start()

    def _play_worker(self):
        P = self.post
        try:
            cfg = self.cfg
            host, port = cfg["sync_host"], cfg["sync_port"]
            P(self._set_status, "Подключаемся к серверу… 🔌")
            P(self._set_progress, 0.03)
            manifest = None
            try:
                manifest = sync.fetch_manifest(host, port)
            except Exception:
                log.warning("sync-сервер недоступен по %s:%s, ищем заново", host, port)
            if manifest is None:
                found = discovery.discover(2.0)
                if found:
                    try:
                        manifest = sync.fetch_manifest(*found)
                        host, port = found
                        cfg["sync_host"], cfg["sync_port"] = host, port
                        cfgmod.save(cfg)
                    except Exception:
                        log.exception("найденный сервер не ответил")
            live = manifest is not None
            if live:
                cfgmod.save_cache(manifest)
                self._last_manifest = manifest
            else:
                manifest = cfgmod.load_cache()
            if manifest is None:
                P(self._set_status, "Сервер недоступен 😕 Проверь Radmin VPN и адрес в настройках.")
                return

            mc_dir = mc.find_minecraft_dir(cfg.get("mc_dir", ""))
            if live:
                plan = sync.plan_sync(
                    manifest, mc_dir,
                    is_host=cfg["is_host"],
                    server_mods_dir=cfg["server_mods_dir"],
                )
                if plan["total_bytes"] > 0:
                    P(self._set_status, f"Скачиваем {sync.format_size(plan['total_bytes'])}… 📥")
                else:
                    P(self._set_status, "Проверяем моды и ресурспаки… ✨")

                ok = sync.sync_all(
                    host, port, manifest, mc_dir,
                    is_host=cfg["is_host"],
                    server_mods_dir=cfg["server_mods_dir"],
                    on_progress=lambda f: P(self._set_progress, 0.05 + f * 0.40),
                    on_status=lambda s: P(self._set_status, s),
                )
                if not ok:
                    log.warning("синхронизация прошла не полностью")

            P(self._set_status, f"Подготавливаем Minecraft {manifest['mc_version']} ({manifest['loader']})… ☕")
            vid = mc.ensure_version(
                mc_dir, manifest["mc_version"], manifest["loader"],
                on_frac=lambda f: P(self._set_progress, 0.45 + f * 0.45),
                cfg=cfg,
                server_java_version=manifest.get("java_version"),
            )

            P(self._set_status, "Запускаем игру и ждём окно… 🚀")
            P(self._set_progress, 0.95)
            srv = manifest.get("server") or {}
            log_path = cfgmod.config_dir() / "game.log"
            start_time = time.time()
            ram_mb = cfgmod.effective_ram_mb(cfg)

            proc = mc.launch(
                mc_dir, vid, cfg["nickname"],
                srv.get("host"), srv.get("port"),
                ram_mb, log_path,
                cfg=cfg,
                server_java_version=manifest.get("java_version"),
            )

            def _on_game_ready():
                P(self._set_progress, 1.0)
                P(self._set_status, "Игра запущена! Удачного геймплея 🎮")

            rc, timed_out = mc.monitor_launch(
                proc, log_path,
                timeout_sec=cfg.get("launch_timeout", 120),
                on_ready=_on_game_ready,
            )

            full_log, has_cr, _ = crash.collect_session_log(mc_dir, log_path, start_time)
            if crash.is_crash(rc, full_log, has_crash_file=has_cr, timed_out=timed_out):
                report = crash.parse_crash(full_log, exit_code=rc, timed_out=timed_out)
                P(self._set_status, f"Упс: {report['title']}")
                P(self._set_progress, 0.0)
                P(self._open_crash_dialog, report, full_log, manifest)
            else:
                P(self._set_status, "Игра закрыта. Заходи ещё! 😊")
                P(self._set_progress, 0.0)
        except Exception as e:
            log.exception("запуск не удался")
            P(self._set_status, f"Ошибка запуска: {e} 😕 (подробности в launcher.log)")
            P(self._set_progress, 0.0)
        finally:
            P(self._play_done)

    # ------------------------------------------------------------ быстрое открытие папок (#5)
    def _open_folders_dialog(self):
        dlg = self._make_dialog("📂 Быстрое открытие папок", width=460, height=430)
        card = self.frame(dlg, "panel", corner_radius=16)
        card.pack(fill="both", expand=True, padx=18, pady=18)

        self.label(card, "📂 Какую папку открыть?", 20, True).pack(anchor="w", padx=20, pady=(16, 2))
        self.label(card, "Нажми мышкой или клавишу 1–6 на клавиатуре", 12, color="subtext").pack(
            anchor="w", padx=20, pady=(0, 12))

        mc_dir = mc.find_minecraft_dir(self.cfg.get("mc_dir", ""))
        items = [
            ("1", "📁  .minecraft — корневая папка игры", mc_dir),
            ("2", "🧩  mods — установленные моды", mc_dir / "mods"),
            ("3", "🎨  resourcepacks — ресурспаки", mc_dir / "resourcepacks"),
            ("4", "📸  screenshots — твои скриншоты", mc_dir / "screenshots"),
            ("5", "💥  crash-reports — отчёты о сбоях", mc_dir / "crash-reports"),
            ("6", "🛠  Конфиг и логи botyaraMC", cfgmod.config_dir()),
        ]
        if self.cfg.get("is_host") and self.cfg.get("server_mods_dir"):
            items.append(("7", "👑  Моды Minecraft-сервера", Path(self.cfg["server_mods_dir"])))

        def go(target_path):
            try:
                cfgmod.open_folder(target_path)
            except Exception:
                log.exception("не удалось открыть папку %s", target_path)
            if dlg.winfo_exists():
                dlg.destroy()

        for key_num, title_str, p in items:
            btn = self.button(
                card, f"[{key_num}]   {title_str}",
                command=partial(go, p),
                primary=False, height=38, anchor="w",
            )
            btn.pack(fill="x", padx=20, pady=4)
            dlg.bind(key_num, lambda _e, path=p: go(path))

        self.button(card, "Закрыть (Esc)", dlg.destroy, primary=False, width=130, height=34).pack(
            side="bottom", pady=(8, 14))

    # ------------------------------------------------------------ шпаргалка хоткеев (#6)
    def _open_hotkeys_dialog(self):
        dlg = self._make_dialog("⌨ Горячие клавиши", width=500, height=400)
        card = self.frame(dlg, "panel", corner_radius=16)
        card.pack(fill="both", expand=True, padx=18, pady=18)

        self.label(card, "⌨ Горячие клавиши botyaraMC", 20, True).pack(anchor="w", padx=22, pady=(16, 12))
        shortcuts = [
            ("Enter / Ctrl + P", "Запустить игру (на главном экране)"),
            ("F5 / Ctrl + R", "Перепроверить сервер и суммарный размер загрузки"),
            ("Ctrl + O", "Быстрое открытие папок (.minecraft, mods, screenshots…)"),
            ("Ctrl + L", "Открыть полный лог последнего запуска (game.log)"),
            ("Ctrl + ,", "Открыть ⚙ Настройки"),
            ("Ctrl + S", "Сохранить изменения в ⚙ Настройках"),
            ("Esc", "Закрыть окно / вернуться из Настроек без сохранения"),
            ("F1", "Показать эту подсказку"),
        ]
        grid = self.frame(card, "panel")
        grid.pack(fill="both", expand=True, padx=22)
        for idx, (keys, desc) in enumerate(shortcuts):
            k_lbl = self.label(grid, keys, 13, True, color="accent")
            k_lbl.grid(row=idx, column=0, sticky="w", pady=5, padx=(0, 18))
            self.label(grid, desc, 13, color="text").grid(row=idx, column=1, sticky="w", pady=5)

        self.button(card, "Понятно 👍", dlg.destroy, width=150, height=36).pack(
            side="bottom", pady=(8, 16))

    # ------------------------------------------------------------ краш-репорт и окно логов (#13)
    def _open_latest_game_log(self):
        mc_dir = mc.find_minecraft_dir(self.cfg.get("mc_dir", ""))
        log_path = cfgmod.config_dir() / "game.log"
        if not log_path.is_file():
            log_path = cfgmod.config_dir() / "launcher.log"
        text = crash._read_text_safe(log_path) if log_path.is_file() else "(Логов пока нет — запусти игру хотя бы раз!)"
        mf = self._last_manifest or {}
        self._open_log_window(
            text,
            mc_version=mf.get("mc_version", ""),
            loader=mf.get("loader", ""),
            exit_code=None,
            header_title=f"📄 Лог ({log_path.name})",
        )

    def _open_crash_dialog(self, report, full_log, manifest=None):
        mf = manifest or self._last_manifest or {}
        dlg = self._make_dialog("💥 Игра крашнулась!", width=640, height=500)
        card = self.frame(dlg, "panel", corner_radius=16)
        card.pack(fill="both", expand=True, padx=18, pady=18)

        self.label(card, "💥 Упс, игра крашнулась!", 22, True, color="danger").pack(
            anchor="w", padx=22, pady=(18, 4))
        code_txt = f"Код выхода: {report['exit_code']}" if report.get("exit_code") is not None else ""
        self.label(card, f"{report['title']}   {code_txt}", 15, True, color="text",
                   wraplength=580).pack(anchor="w", padx=22, pady=(0, 8))

        body = self.scroll_frame(card, "bg", height=250)
        body.pack(fill="both", expand=True, padx=22, pady=(0, 10))

        self.label(body, report["summary"], 13, color="text", wraplength=540).pack(
            anchor="w", padx=12, pady=(10, 8))

        if report.get("exception"):
            self.label(body, "Техническая причина:", 12, True, color="subtext").pack(anchor="w", padx=12)
            self.label(body, report["exception"], 12, color="danger", wraplength=540).pack(
                anchor="w", padx=12, pady=(2, 8))

        if report.get("suspected_mods"):
            self.label(body, "Подозрительные моды / файлы:", 12, True, color="subtext").pack(
                anchor="w", padx=12)
            self.label(body, "• " + ", ".join(report["suspected_mods"]), 13, color="accent",
                       wraplength=540).pack(anchor="w", padx=12, pady=(2, 8))

        self.label(body, "Что можно сделать:", 12, True, color="subtext").pack(anchor="w", padx=12)
        for tip in report.get("solutions", []):
            self.label(body, f"• {tip}", 13, color="text", wraplength=540).pack(
                anchor="w", padx=12, pady=2)

        bar = self.frame(card, "panel")
        bar.pack(side="bottom", fill="x", padx=22, pady=(6, 16))

        def open_full():
            self._open_log_window(
                full_log,
                mc_version=mf.get("mc_version", ""),
                loader=mf.get("loader", ""),
                exit_code=report.get("exit_code"),
                header_title=report["title"],
                parent_crash_dlg=dlg,
            )

        def restart():
            if dlg.winfo_exists():
                dlg.destroy()
            self.on_play()

        self.button(bar, "📄 Посмотреть полный лог", open_full, width=220, height=40).pack(side="left")
        self.button(bar, "Закрыть", dlg.destroy, primary=False, width=105, height=40).pack(side="right")
        self.button(bar, "🔄 Перезапуск", restart, primary=False, width=140, height=40).pack(
            side="right", padx=8)

    def _open_log_window(self, full_log, mc_version="", loader="", exit_code=None,
                         header_title="📄 Полный лог игры", parent_crash_dlg=None):
        dlg = self._make_dialog("Полный лог — botyaraMC", width=820, height=580)
        card = self.frame(dlg, "panel", corner_radius=16)
        card.pack(fill="both", expand=True, padx=16, pady=16)

        hdr = self.frame(card, "panel")
        hdr.pack(fill="x", padx=20, pady=(16, 6))
        lines_cnt = len((full_log or "").splitlines())
        self.label(hdr, header_title, 18, True).pack(side="left")
        self.label(hdr, f"{lines_cnt} строк", 12, color="subtext").pack(side="right")

        txt = ctk.CTkTextbox(
            card,
            corner_radius=10,
            font=ctk.CTkFont(family="Consolas" if sys.platform.startswith("win") else "monospace", size=12),
            wrap="none",
        )
        self.T(txt, fg_color="bg", text_color="text", border_color="border",
               scrollbar_button_color="surface_hover", scrollbar_button_hover_color="accent")
        txt.pack(fill="both", expand=True, padx=20, pady=(4, 8))
        txt.insert("1.0", full_log or "(Пусто)")
        txt.see("end")
        txt.configure(state="disabled")

        share_row = self.frame(card, "panel")
        share_row.pack(fill="x", padx=20, pady=(0, 4))
        info_lbl = self.label(share_row, "", 13, color="subtext")
        info_lbl.pack(side="left")
        last_url = [""]
        open_url_btn = self.button(
            share_row, "Открыть в браузере 🌐",
            command=lambda: webbrowser.open(last_url[0]) if last_url[0] else None,
            primary=False, width=170, height=28,
        )

        # Нижняя панель: Скопировать, Поделиться (mclo.gs), Перезапуск, Закрыть
        bar = self.frame(card, "panel")
        bar.pack(side="bottom", fill="x", padx=20, pady=(4, 16))

        def do_copy():
            self._copy_clipboard(full_log or "")
            self.msg(info_lbl, "Полный лог скопирован в буфер обмена 📋", "success")

        def do_share():
            share_btn.configure(state="disabled", text="Отправляем… ⏳")
            self.msg(info_lbl, "Загружаем лог на https://mclo.gs… 🌐", "subtext")

            def work():
                try:
                    res = crash.upload_to_mclogs(
                        full_log or "",
                        mc_version=mc_version,
                        loader=loader,
                        exit_code=exit_code,
                    )
                    self.post(done_ok, res)
                except Exception as e:
                    log.exception("ошибка отправки на mclo.gs")
                    self.post(done_err, str(e))

            def done_ok(res):
                if not dlg.winfo_exists():
                    return
                share_btn.configure(state="normal", text="🔗 Поделиться")
                url = res["url"]
                last_url[0] = url
                self._copy_clipboard(url)
                self.msg(info_lbl, f"Ссылка скопирована: {url} 🎉", "success")
                open_url_btn.pack(side="right")

            def done_err(err_msg):
                if not dlg.winfo_exists():
                    return
                share_btn.configure(state="normal", text="🔗 Поделиться")
                self.msg(info_lbl, f"Не вышло отправить: {err_msg}", "danger")

            threading.Thread(target=work, daemon=True).start()

        def do_restart():
            if parent_crash_dlg is not None and parent_crash_dlg.winfo_exists():
                parent_crash_dlg.destroy()
            if dlg.winfo_exists():
                dlg.destroy()
            self.on_play()

        self.button(bar, "📋 Скопировать", do_copy, primary=False, width=150, height=40).pack(
            side="left", padx=(0, 8))
        share_btn = self.button(bar, "🔗 Поделиться", do_share, primary=True, width=165, height=40)
        share_btn.pack(side="left")

        self.button(bar, "✖ Закрыть", dlg.destroy, primary=False, width=120, height=40).pack(
            side="right")
        self.button(bar, "🔄 Перезапуск", do_restart, primary=False, width=150, height=40).pack(
            side="right", padx=8)

    # ------------------------------------------------------------ редактор JVM-пресетов (#8)
    def _open_presets_editor(self, custom_presets_draft, current_preset_var, on_updated):
        dlg = self._make_dialog("⚙ Редактор JVM-пресетов", width=660, height=490)
        card = self.frame(dlg, "panel", corner_radius=16)
        card.pack(fill="both", expand=True, padx=16, pady=16)

        self.label(card, "⚙ JVM-пресеты", 20, True).pack(anchor="w", padx=20, pady=(16, 2))
        self.label(
            card,
            "Выбери готовый пресет для редактирования или создай собственный набор флагов.",
            12, color="subtext",
        ).pack(anchor="w", padx=20, pady=(0, 10))

        def merged():
            m = dict(jvm.BUILTIN_PRESETS)
            m.update(custom_presets_draft)
            return m

        top_row = self.frame(card, "panel")
        top_row.pack(fill="x", padx=20, pady=(0, 8))

        sel_var = tk.StringVar(value=current_preset_var.get())
        om = self.option_menu(top_row, values=list(merged().keys()), variable=sel_var, width=220)
        om.pack(side="left")

        e_new = self.entry(top_row, width=190, height=32, placeholder_text="Имя нового пресета…")
        e_new.pack(side="left", padx=(12, 6))

        desc_lbl = self.label(card, "", 12, color="subtext", wraplength=600)
        desc_lbl.pack(anchor="w", padx=20, pady=(0, 6))

        box = ctk.CTkTextbox(card, height=180, corner_radius=10, font=ctk.CTkFont(size=13))
        self.T(box, fg_color="bg", text_color="text", border_color="border")
        box.pack(fill="both", expand=True, padx=20, pady=(0, 8))

        status = self.label(card, "", 12, color="subtext")
        status.pack(anchor="w", padx=20)

        def load_selected(name=None):
            nm = name or sel_var.get()
            all_p = merged()
            if nm not in all_p:
                nm = "G1GC"
                sel_var.set(nm)
            desc = jvm.PRESET_DESCRIPTIONS.get(nm, "Пользовательский JVM-пресет")
            if nm in jvm.BUILTIN_PRESETS and nm in custom_presets_draft:
                desc += " (изменён тобой)"
            desc_lbl.configure(text=desc)
            box.delete("1.0", "end")
            box.insert("1.0", all_p.get(nm, ""))

        om.configure(command=load_selected)

        def add_new():
            nm = e_new.get().strip()
            if not nm:
                return self.msg(status, "Введи название для нового пресета 🙂", "danger")
            custom_presets_draft[nm] = box.get("1.0", "end").strip()
            e_new.delete(0, "end")
            vals = list(merged().keys())
            om.configure(values=vals)
            sel_var.set(nm)
            load_selected(nm)
            self.msg(status, f"Создан пресет «{nm}» ✨", "success")

        self.button(top_row, "+ Создать", add_new, primary=False, width=100, height=32).pack(side="left")

        bar = self.frame(card, "panel")
        bar.pack(side="bottom", fill="x", padx=20, pady=(8, 16))

        def save_current_and_close():
            nm = sel_var.get()
            flags_str = " ".join(box.get("1.0", "end").split())
            if nm in jvm.BUILTIN_PRESETS and flags_str == jvm.BUILTIN_PRESETS[nm]:
                custom_presets_draft.pop(nm, None)
            else:
                custom_presets_draft[nm] = flags_str
            on_updated(nm)
            dlg.destroy()

        def reset_or_delete():
            nm = sel_var.get()
            if nm in jvm.BUILTIN_PRESETS:
                custom_presets_draft.pop(nm, None)
                load_selected(nm)
                self.msg(status, f"Пресет «{nm}» сброшен к заводским флагам ↺", "success")
            else:
                custom_presets_draft.pop(nm, None)
                vals = list(merged().keys())
                om.configure(values=vals)
                sel_var.set("G1GC")
                load_selected("G1GC")
                self.msg(status, f"Пресет «{nm}» удалён 🗑", "subtext")

        self.button(bar, "↺ Сбросить / Удалить", reset_or_delete, primary=False,
                    width=175, height=38).pack(side="left")
        self.button(bar, "Применить ✓", save_current_and_close, width=155, height=38).pack(side="right")
        self.button(bar, "Отмена", dlg.destroy, primary=False, width=105, height=38).pack(
            side="right", padx=8)

        load_selected()

    # ------------------------------------------------------------ настройки
    def _view_settings(self):
        c = self.cfg
        custom_presets_draft = dict(c.get("custom_jvm_presets") or {})

        root = self.frame(self, "bg")
        card = self.frame(root, "panel", corner_radius=18)
        card.pack(fill="both", expand=True, padx=22, pady=20)

        hdr = self.frame(card, "panel")
        hdr.pack(fill="x", padx=24, pady=(16, 6))
        self.label(hdr, "⚙ Настройки", 24, True).pack(side="left")
        self.label(hdr, "Ctrl+S — сохранить • Esc — отмена", 12, color="subtext").pack(side="right")

        sf = self.scroll_frame(card, "panel")
        sf.pack(fill="both", expand=True, padx=16, pady=(0, 6))
        g = self.frame(sf, "panel")
        g.pack(fill="x", padx=8, pady=4)
        g.grid_columnconfigure(1, weight=1)

        def section(r, title):
            self.label(g, title, 15, True, color="accent").grid(
                row=r, column=0, columnspan=3, sticky="w", pady=(14 if r else 4, 6)
            )

        def row_lbl(r, text):
            self.label(g, text, color="subtext").grid(
                row=r, column=0, sticky="w", pady=6, padx=(0, 16)
            )

        # === Секция 1: Профиль и сеть ===
        section(0, "👤 Профиль и сервер синхронизации")

        row_lbl(1, "Ник")
        e_nick = self.entry(g, height=34)
        e_nick.insert(0, c["nickname"])
        e_nick.grid(row=1, column=1, columnspan=2, sticky="ew", pady=4)

        row_lbl(2, "Тема оформления")
        om_theme = self.option_menu(g, values=themes.THEME_NAMES, command=self.apply_theme, width=220)
        om_theme.set(c["theme"])
        om_theme.grid(row=2, column=1, columnspan=2, sticky="w", pady=4)

        row_lbl(3, "Сервер синхронизации")
        e_host = self.entry(g, height=34)
        e_host.insert(0, self._addr_text())
        e_host.grid(row=3, column=1, sticky="ew", pady=4)
        m_host = self.label(g, "", 12, color="subtext")
        find_btn = self.button(g, "🔍 Найти", primary=False, width=105, height=34)
        find_btn.configure(command=lambda: self._autofind(e_host, m_host, find_btn))
        find_btn.grid(row=3, column=2, padx=(8, 0))
        m_host.grid(row=4, column=1, columnspan=2, sticky="w")

        row_lbl(5, "Режим хоста")
        sw_host = ctk.CTkSwitch(g, text="я хост! 👑 (дублировать моды в папку сервера)")
        self.T(sw_host, fg_color="surface_hover", progress_color="accent", button_color="text",
               button_hover_color="accent_hover", text_color="text")
        sw_host.grid(row=5, column=1, columnspan=2, sticky="w", pady=4)

        row_lbl(6, "Папка модов сервера")
        e_srv = self.entry(g, height=34, placeholder_text="путь к mods у Minecraft-сервера")
        e_srv.insert(0, c["server_mods_dir"])
        e_srv.grid(row=6, column=1, sticky="ew", pady=4)
        b_srv = self.button(g, "Обзор…", lambda: self._browse_dir(e_srv), primary=False,
                            width=105, height=34)
        b_srv.grid(row=6, column=2, padx=(8, 0))

        def toggle_host():
            st = "normal" if sw_host.get() else "disabled"
            e_srv.configure(state=st)
            b_srv.configure(state=st)

        sw_host.configure(command=toggle_host)
        if c["is_host"]:
            sw_host.select()
        toggle_host()

        # === Секция 2: Память (RAM), Java и JVM-пресеты ===
        section(7, "☕ Память (RAM), Java и JVM-аргументы")

        sys_ram = cfgmod.system_ram_mb()
        rec_ram = cfgmod.recommended_ram_mb(sys_ram)
        max_ram = cfgmod.max_selectable_ram_mb()

        row_lbl(8, "Авто-RAM")
        sw_autoram = ctk.CTkSwitch(
            g,
            text=f"Автоподбор по системе ({rec_ram} МБ из {sys_ram} МБ ОЗУ)",
        )
        self.T(sw_autoram, fg_color="surface_hover", progress_color="accent", button_color="text",
               button_hover_color="accent_hover", text_color="text")
        sw_autoram.grid(row=8, column=1, columnspan=2, sticky="w", pady=4)

        row_lbl(9, "Память вручную")
        ram_box = self.frame(g, "panel")
        ram_box.grid(row=9, column=1, columnspan=2, sticky="ew", pady=4)
        e_ram = self.entry(ram_box, width=86, height=32)
        init_ram = min(max_ram, max(1024, int(c.get("ram_mb", rec_ram))))
        e_ram.insert(0, str(init_ram))
        e_ram.pack(side="right")
        self.label(ram_box, "МБ", 12, color="subtext").pack(side="right", padx=(6, 6))

        steps = max(1, (max_ram - 1024) // 256)
        sl_ram = ctk.CTkSlider(
            ram_box, from_=1024, to=max_ram, number_of_steps=steps,
            command=lambda v: (e_ram.delete(0, "end"), e_ram.insert(0, str(int(round(v))))),
        )
        self.T(sl_ram, fg_color="surface", progress_color="accent", button_color="accent",
               button_hover_color="accent_hover")
        sl_ram.set(init_ram)
        sl_ram.pack(side="left", fill="x", expand=True, padx=(0, 10))

        def toggle_autoram():
            manual = not bool(sw_autoram.get())
            sl_ram.configure(state="normal" if manual else "disabled")
            e_ram.configure(state="normal" if manual else "disabled")

        sw_autoram.configure(command=toggle_autoram)
        if c.get("auto_ram", True):
            sw_autoram.select()
        toggle_autoram()

        # Java: автодетект + ручной выбор (#7)
        row_lbl(10, "Режим Java")
        java_row = self.frame(g, "panel")
        java_row.grid(row=10, column=1, columnspan=2, sticky="ew", pady=4)
        java_mode_ui = "Вручную" if c.get("java_mode") == "manual" else "Авто (рекомендуется)"
        seg_java = self.segmented(java_row, values=["Авто (рекомендуется)", "Вручную"])
        seg_java.set(java_mode_ui)
        seg_java.pack(side="left")

        detected_map = {}  # label -> path
        om_detected = self.option_menu(java_row, values=["Нажми «Найти Java»…"], width=230)
        om_detected.pack(side="left", padx=(10, 6))
        btn_scan_java = self.button(java_row, "🔄 Найти Java", primary=False, width=115, height=32)
        btn_scan_java.pack(side="left")

        row_lbl(11, "Путь к Java")
        e_java = self.entry(g, height=34, placeholder_text="путь к bin/java (или оставь Авто)")
        e_java.insert(0, c.get("java_path", ""))
        e_java.grid(row=11, column=1, sticky="ew", pady=4)
        java_info_lbl = self.label(g, "", 12, color="subtext")
        java_info_lbl.grid(row=12, column=1, columnspan=2, sticky="w")

        def check_java_entry(*_a):
            if seg_java.get() != "Вручную":
                self.msg(
                    java_info_lbl,
                    "Авторежим сам выберет подходящую системную Java или докачает рантайм Mojang (с учётом требований сервера).",
                    "subtext",
                )
                return
            raw_p = e_java.get().strip()
            if not raw_p:
                self.msg(java_info_lbl, "Укажи путь к java или выбери из найденных выше", "subtext")
                return
            info = jvm.probe_java(raw_p)
            if info:
                self.msg(java_info_lbl, f"✓ Найдена {info['label']}", "success")
            else:
                self.msg(java_info_lbl, "✗ Не удалось запустить java -version по этому пути", "danger")

        b_java = self.button(
            g, "Обзор…",
            command=lambda: self._browse_file(e_java, on_change=check_java_entry),
            primary=False, width=105, height=34,
        )
        b_java.grid(row=11, column=2, padx=(8, 0))
        e_java.bind("<KeyRelease>", check_java_entry)

        def on_pick_detected(choice):
            path = detected_map.get(choice)
            if path:
                seg_java.set("Вручную")
                toggle_java_mode()
                e_java.delete(0, "end")
                e_java.insert(0, path)
                check_java_entry()

        om_detected.configure(command=on_pick_detected)

        def toggle_java_mode(*_a):
            manual = seg_java.get() == "Вручную"
            st = "normal" if manual else "disabled"
            e_java.configure(state=st)
            b_java.configure(state=st)
            check_java_entry()

        seg_java.configure(command=toggle_java_mode)
        toggle_java_mode()

        def run_java_scan():
            btn_scan_java.configure(state="disabled")
            self.msg(java_info_lbl, "Ищем установленные Java в системе… 🔍", "subtext")

            def work():
                mc_d = mc.find_minecraft_dir(e_mc.get().strip() or c.get("mc_dir", ""))
                self.post(done, jvm.detect_java_installations(mc_d))

            def done(found):
                try:
                    btn_scan_java.configure(state="normal")
                    detected_map.clear()
                    if not found:
                        om_detected.configure(values=["Java не найдена (скачается сама)"])
                        om_detected.set("Java не найдена (скачается сама)")
                        self.msg(java_info_lbl, "Системная Java не найдена — в Авто-режиме лаунчер сам скачает её от Mojang.", "subtext")
                        return
                    labels = []
                    for j in found:
                        short_lbl = f"{j['label']} — {Path(j['path']).parent.parent.name}"
                        detected_map[short_lbl] = j["path"]
                        labels.append(short_lbl)
                    om_detected.configure(values=labels)
                    om_detected.set(labels[0])
                    if seg_java.get() != "Вручную":
                        self.msg(java_info_lbl, f"Найдено Java: {len(found)} шт. (лучшая: {found[0]['label']})", "success")
                except Exception:
                    pass

            threading.Thread(target=work, daemon=True).start()

        btn_scan_java.configure(command=run_java_scan)

        # JVM-пресеты + доп. параметры (#8)
        row_lbl(13, "JVM-пресет")
        preset_row = self.frame(g, "panel")
        preset_row.grid(row=13, column=1, columnspan=2, sticky="ew", pady=4)

        def current_preset_names():
            m = dict(jvm.BUILTIN_PRESETS)
            m.update(custom_presets_draft)
            return list(m.keys())

        init_preset = c.get("jvm_preset", "G1GC")
        if init_preset not in current_preset_names():
            init_preset = "G1GC"
        preset_var = tk.StringVar(value=init_preset)
        om_preset = self.option_menu(preset_row, values=current_preset_names(), variable=preset_var, width=210)
        om_preset.pack(side="left")

        def refresh_presets(selected_name):
            vals = current_preset_names()
            om_preset.configure(values=vals)
            preset_var.set(selected_name if selected_name in vals else "G1GC")

        self.button(
            preset_row, "✏ Редактировать / Свой пресет…",
            command=lambda: self._open_presets_editor(custom_presets_draft, preset_var, refresh_presets),
            primary=False, width=230, height=32,
        ).pack(side="left", padx=(10, 0))

        row_lbl(14, "Доп. параметры JVM")
        e_extra_jvm = self.entry(
            g, height=34,
            placeholder_text="Дописать к пресету, например: -Dfile.encoding=UTF-8",
        )
        e_extra_jvm.insert(0, c.get("extra_jvm_args", ""))
        e_extra_jvm.grid(row=14, column=1, columnspan=2, sticky="ew", pady=4)

        # === Секция 3: Игра, разрешение окна и таймаут ===
        section(15, "🖥 Окно игры, папки и таймаут запуска")

        row_lbl(16, "Папка .minecraft")
        e_mc = self.entry(g, height=34)
        e_mc.insert(0, str(mc.find_minecraft_dir(c.get("mc_dir", ""))))
        e_mc.grid(row=16, column=1, sticky="ew", pady=4)
        self.button(g, "Обзор…", lambda: self._browse_dir(e_mc), primary=False,
                    width=105, height=34).grid(row=16, column=2, padx=(8, 0))

        row_lbl(17, "Режим окна игры")
        win_mode_label = WINDOW_MODES_REV.get(c.get("window_mode", "default"), "Обычное")
        seg_win = self.segmented(g, values=list(WINDOW_MODES_UI.keys()))
        seg_win.set(win_mode_label)
        seg_win.grid(row=17, column=1, columnspan=2, sticky="w", pady=4)

        row_lbl(18, "Размер окна (Ш × В)")
        res_row = self.frame(g, "panel")
        res_row.grid(row=18, column=1, columnspan=2, sticky="w", pady=4)
        e_w = self.entry(res_row, width=78, height=32)
        e_w.insert(0, str(c.get("window_width", 1280)))
        e_w.pack(side="left")
        self.label(res_row, "×", 14, color="subtext").pack(side="left", padx=6)
        e_h = self.entry(res_row, width=78, height=32)
        e_h.insert(0, str(c.get("window_height", 720)))
        e_h.pack(side="left", padx=(0, 10))

        res_preset_btns = []
        for rw, rh in ((1280, 720), (1600, 900), (1920, 1080), (2560, 1440)):
            def _set_wh(w=rw, h=rh):
                if seg_win.get() != "Свой размер":
                    seg_win.set("Свой размер")
                    toggle_win_mode()
                e_w.delete(0, "end")
                e_w.insert(0, str(w))
                e_h.delete(0, "end")
                e_h.insert(0, str(h))

            b = self.button(res_row, f"{rw}×{rh}", _set_wh, primary=False, width=76, height=28,
                            font=ctk.CTkFont(size=11))
            b.pack(side="left", padx=2)
            res_preset_btns.append(b)

        def toggle_win_mode(*_a):
            custom = seg_win.get() == "Свой размер"
            st = "normal" if custom else "disabled"
            e_w.configure(state=st)
            e_h.configure(state=st)

        seg_win.configure(command=toggle_win_mode)
        toggle_win_mode()

        row_lbl(19, "Таймаут запуска")
        to_row = self.frame(g, "panel")
        to_row.grid(row=19, column=1, columnspan=2, sticky="w", pady=4)
        e_timeout = self.entry(to_row, width=86, height=32)
        e_timeout.insert(0, str(c.get("launch_timeout", 120)))
        e_timeout.pack(side="left")
        self.label(to_row, "сек  (0 — отключить контроль зависания старта)", 12, color="subtext").pack(
            side="left", padx=10)

        # Запускаем автодетект Java фоном сразу при открытии настроек
        run_java_scan()

        err = self.label(card, "", 13, color="danger")
        err.pack(anchor="w", padx=26, pady=(4, 0))

        def cancel():
            self.apply_theme(self.cfg["theme"])
            self.show("main")

        def save():
            nick = e_nick.get().strip()
            parsed = parse_hostport(e_host.get())
            if not NICK_RE.match(nick):
                return self.msg(err, "Ник: 3–16 символов, только a-z, A-Z, 0-9 и _", "danger")
            if not parsed:
                return self.msg(err, "Адрес сервера не похож на IP (пример: 26.12.34.56)", "danger")
            srv_dir = e_srv.get().strip() if sw_host.get() else c["server_mods_dir"]
            if sw_host.get() and not Path(srv_dir).is_dir():
                return self.msg(err, "Для режима хоста укажи существующую папку модов сервера", "danger")

            auto_ram_val = bool(sw_autoram.get())
            try:
                ram_val = max(1024, int(e_ram.get().strip())) if not auto_ram_val else int(c.get("ram_mb", rec_ram))
            except ValueError:
                return self.msg(err, "Память (RAM) должна быть числом в мегабайтах (например 4096)", "danger")

            java_mode_val = "manual" if seg_java.get() == "Вручную" else "auto"
            java_path_val = e_java.get().strip() if java_mode_val == "manual" else c.get("java_path", "")
            if java_mode_val == "manual" and not jvm.probe_java(java_path_val):
                return self.msg(err, "Укажи рабочий путь к Java или переключись на «Авто»", "danger")

            win_mode_val = WINDOW_MODES_UI.get(seg_win.get(), "default")
            try:
                win_w = max(320, int(e_w.get().strip())) if win_mode_val == "custom" else int(c.get("window_width", 1280))
                win_h = max(240, int(e_h.get().strip())) if win_mode_val == "custom" else int(c.get("window_height", 720))
            except ValueError:
                return self.msg(err, "Ширина и высота окна должны быть числами (например 1920 и 1080)", "danger")

            try:
                timeout_val = max(0, int(e_timeout.get().strip()))
            except ValueError:
                return self.msg(err, "Таймаут запуска должен быть числом секунд (0 или больше)", "danger")

            c.update(
                nickname=nick,
                theme=om_theme.get(),
                sync_host=parsed[0],
                sync_port=parsed[1],
                is_host=bool(sw_host.get()),
                server_mods_dir=srv_dir,
                auto_ram=auto_ram_val,
                ram_mb=ram_val,
                java_mode=java_mode_val,
                java_path=java_path_val,
                jvm_preset=preset_var.get(),
                custom_jvm_presets=custom_presets_draft,
                extra_jvm_args=e_extra_jvm.get().strip(),
                mc_dir=e_mc.get().strip(),
                window_mode=win_mode_val,
                window_width=win_w,
                window_height=win_h,
                launch_timeout=timeout_val,
            )
            cfgmod.save(c)
            self.show("main")

        self._save_settings_fn = save
        self._cancel_settings_fn = cancel

        bar = self.frame(card, "panel")
        bar.pack(side="bottom", fill="x", padx=24, pady=(6, 16))
        self.button(bar, "Сохранить 💾", save, width=165, height=40).pack(side="right")
        self.button(bar, "Отмена", cancel, primary=False, width=110, height=40).pack(
            side="right", padx=10)
        return root
