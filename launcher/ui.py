"""Интерфейс botyaraMC (RU/EN): мастер 4 шага, мульти-серверы, автосохранение настроек, краш-парсер."""
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
import i18n
import jvm
import mc
import sync
import themes

log = logging.getLogger("botyaraMC.ui")
DEFAULT_PORT = 25456
GREETING_ROTATE_MS = 10 * 60 * 1000  # 10 минут


def parse_hostport(text):
    t = (text or "").strip().rstrip("/")
    for prefix in ("http://", "https://"):
        if t.startswith(prefix):
            t = t[len(prefix):]
    if not t or " " in t:
        return None
    host, port = t, DEFAULT_PORT
    if ":" in t:
        host, _, p = t.rpartition(":")
        if not p.isdigit() or not 0 < int(p) < 65536:
            return None
        port = int(p)
    if not host:
        return None
    if re.fullmatch(r"[0-9.]+", host):
        parts = host.split(".")
        if len(parts) != 4 or any(not x.isdigit() or not 0 <= int(x) <= 255 for x in parts):
            return None
        return host, port
    if len(host) < 2 or not re.fullmatch(r"[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*", host):
        return None
    if host.startswith("-") or host.endswith("-"):
        return None
    return host, port


def _hex_to_rgb(h):
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _lerp_hex(c1, c2, t):
    t = max(0.0, min(1.0, float(t)))
    r1, g1, b1 = _hex_to_rgb(c1)
    r2, g2, b2 = _hex_to_rgb(c2)
    r = round(r1 + (r2 - r1) * t)
    g = round(g1 + (g2 - g1) * t)
    b = round(b1 + (b2 - b1) * t)
    return f"#{r:02x}{g:02x}{b:02x}"


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
        self.geometry("920x680")
        self.minsize(860, 620)
        self.configure(fg_color=self.theme["bg"])
        self._ico_path, self._icon_img = None, None
        self._apply_window_icon()

        self._reg = {}            # виджет -> {опция: ключ палитры}
        self._q = queue.Queue()   # сообщения из потоков в UI
        self.view = None
        self.view_name = ""
        self.playing = False
        self._status, self._prog = "", 0.0
        self._play_hover_t = 0.0
        self._play_hover_job = None
        self._greeting = ""
        self._greeting_job = None
        self._server_badge_text = ""
        self._last_manifest = cfgmod.load_cache(self.cfg.get("active_server_id") or None)
        self._close_settings_fn = None
        self._active_dialogs = []
        self._force = False
        self.draft = {
            "lang": self._lang(),
            "nick": self.cfg["nickname"],
            "theme": self.cfg["theme"],
            "host": self._addr_text(),
            "server_name": "",
        }
        self._play_btn_text = self._tr("play_btn")

        self._bind_hotkeys()
        self.after(60, self._pump)
        self._schedule_greeting_rotation()
        self.show("main" if self.cfg["setup_done"] else "wizard")

    def _lang(self):
        return "en" if self.cfg.get("language") == "en" else "ru"

    def _tr(self, key, **kwargs):
        return i18n.tr(self._lang(), key, **kwargs)

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
        self._paint_play_button_color()

    # ------------------------------------------------------------ автосмена приветствий каждые 10 минут
    def _schedule_greeting_rotation(self):
        if self._greeting_job is not None:
            try:
                self.after_cancel(self._greeting_job)
            except Exception:
                pass
        self._greeting_job = self.after(GREETING_ROTATE_MS, self._rotate_greeting)

    def _rotate_greeting(self):
        self._greeting_job = None
        try:
            if not self.winfo_exists():
                return
            self._greeting = i18n.random_greeting(
                self.cfg.get("nickname") or "",
                lang=self._lang(),
                prev=self._greeting,
            )
            lbl = getattr(self, "greeting_lbl", None)
            if lbl is not None and lbl.winfo_exists():
                lbl.configure(text=self._greeting)
        except Exception:
            pass
        self._schedule_greeting_rotation()

    # ------------------------------------------------------------ плавный hover кнопки ИГРАТЬ (#22)
    def _paint_play_button_color(self):
        btn = getattr(self, "play_btn", None)
        if btn is None:
            return
        try:
            if not btn.winfo_exists():
                return
            col = _lerp_hex(self.theme["accent"], self.theme["accent_hover"], self._play_hover_t)
            btn._fg_color = col
            btn._hover_color = col
            if hasattr(btn, "_canvas"):
                btn._canvas.itemconfig("inner_parts", outline=col, fill=col)
            if getattr(btn, "_text_label", None) is not None:
                btn._text_label.configure(bg=col)
            if getattr(btn, "_image_label", None) is not None:
                btn._image_label.configure(bg=col)
        except Exception:
            pass

    def _animate_play_hover(self, target):
        if self._play_hover_job is not None:
            try:
                self.after_cancel(self._play_hover_job)
            except Exception:
                pass
            self._play_hover_job = None

        def step():
            self._play_hover_job = None
            btn = getattr(self, "play_btn", None)
            if btn is None or not btn.winfo_exists():
                return
            if self.playing:
                self._play_hover_t = 0.0
                self._paint_play_button_color()
                return
            diff = target - self._play_hover_t
            if abs(diff) <= 0.04:
                self._play_hover_t = target
                self._paint_play_button_color()
                return
            self._play_hover_t += diff * 0.28 + (0.04 if diff > 0 else -0.04)
            self._play_hover_t = max(0.0, min(1.0, self._play_hover_t))
            self._paint_play_button_color()
            self._play_hover_job = self.after(16, step)

        step()

    def _bind_play_hover(self, btn):
        self._play_hover_t = 0.0
        self._paint_play_button_color()

        def _on_enter(_e=None):
            self._animate_play_hover(1.0)

        def _on_leave(_e=None):
            try:
                if btn.winfo_exists():
                    x = btn.winfo_pointerx() - btn.winfo_rootx()
                    y = btn.winfo_pointery() - btn.winfo_rooty()
                    if 0 <= x < btn.winfo_width() and 0 <= y < btn.winfo_height():
                        return  # курсор всё ещё внутри кнопки (например над текстом)
            except Exception:
                pass
            self._animate_play_hover(0.0)

        btn.bind("<Enter>", _on_enter, add="+")
        btn.bind("<Leave>", _on_leave, add="+")

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

    def _on_hotkey_escape(self):
        self._clean_dialogs()
        if self._active_dialogs:
            top = self._active_dialogs.pop()
            try:
                top.destroy()
            except Exception:
                pass
            return
        if self.view_name == "settings" and self._close_settings_fn:
            self._close_settings_fn()

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
        self._close_settings_fn = None
        if self._play_hover_job is not None:
            try:
                self.after_cancel(self._play_hover_job)
            except Exception:
                pass
            self._play_hover_job = None
        if self.view is not None:
            self.view.destroy()
        self.view_name = name
        if name == "main":
            # Генерируем новое живое приветствие по времени суток при заходе на главный экран
            self._greeting = i18n.random_greeting(
                self.cfg.get("nickname") or "",
                lang=self._lang(),
                prev=self._greeting,
            )
            self._schedule_greeting_rotation()
            if not self.playing:
                self._play_btn_text = self._tr("play_btn")
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
        kw.setdefault("dynamic_resizing", False)
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

    def _make_dialog(self, title, width=560, height=460, min_w=None, min_h=None):
        dlg = ctk.CTkToplevel(self)
        dlg.title(title)
        dlg.geometry(f"{width}x{height}")
        dlg.minsize(min_w or min(500, width), min_h or min(380, height))
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

    def _addr_text(self, host=None, port=None):
        h = self.cfg.get("sync_host", "") if host is None else host
        p = self.cfg.get("sync_port", DEFAULT_PORT) if port is None else port
        return "" if not h else (h if p == DEFAULT_PORT else f"{h}:{p}")

    def _server_label(self, srv):
        addr = self._addr_text(srv.get("host", ""), srv.get("port", DEFAULT_PORT))
        nm = (srv.get("name") or "").strip()
        if nm:
            return f"{nm} ({addr})"
        return addr

    def _browse_dir(self, entry, on_change=None):
        path = filedialog.askdirectory()
        if path:
            entry.configure(state="normal")
            entry.delete(0, "end")
            entry.insert(0, path)
            if on_change:
                on_change()

    def _browse_file(self, entry, on_change=None):
        all_lbl = "All files" if self._lang() == "en" else "Все файлы"
        filetypes = [("Java executable", "java.exe javaw.exe java"), (all_lbl, "*.*")] \
            if sys.platform.startswith("win") else [(all_lbl, "*")]
        path = filedialog.askopenfilename(filetypes=filetypes)
        if path:
            entry.configure(state="normal")
            entry.delete(0, "end")
            entry.insert(0, path)
            if on_change:
                on_change()

    def _autofind(self, entry, lbl, btn, on_found=None):
        btn.configure(state="disabled")
        self.msg(lbl, self._tr("wiz_searching"))

        def work():
            self.post(done, discovery.discover_full(3.0))

        def done(res):
            try:
                btn.configure(state="normal")
                if res:
                    host, port, sname = res
                    addr = host if port == DEFAULT_PORT else f"{host}:{port}"
                    entry.delete(0, "end")
                    entry.insert(0, addr)
                    disp = f"{sname} ({addr})" if sname else addr
                    self.msg(lbl, self._tr("wiz_found", host=disp), "success")
                    if on_found:
                        on_found(host, port, sname)
                else:
                    self.msg(lbl, self._tr("wiz_not_found"), "danger")
            except Exception:
                pass

        threading.Thread(target=work, daemon=True).start()

    # ============================================================ МАСТЕР ПЕРВОГО ЗАПУСКА (4 шага)
    def _view_wizard(self, step=1):
        root = self.frame(self, "bg")
        card = self.frame(root, "panel", corner_radius=18)
        card.pack(fill="both", expand=True, padx=28, pady=28)
        self.label(
            card,
            self._tr("wizard_step", step=step, total=4),
            12, color="subtext",
        ).pack(anchor="w", padx=28, pady=(22, 0))
        getattr(self, f"_step{step}")(card)
        return root

    def _nav(self, card, back, next_text, next_cmd):
        bar = self.frame(card, "panel")
        bar.pack(side="bottom", fill="x", padx=28, pady=22)
        nxt = self.button(bar, next_text, next_cmd, width=180, height=42)
        nxt.pack(side="right")
        if back:
            self.button(bar, self._tr("btn_back"), back, primary=False, width=120, height=42).pack(side="left")
        return nxt

    # Шаг 1 из 4 — Выбор языка (до выбора ника!)
    def _step1(self, card):
        self.label(card, self._tr("wiz_lang_title"), 26, True).pack(
            anchor="w", padx=28, pady=(8, 4))
        self.label(card, self._tr("wiz_lang_sub"), color="subtext").pack(
            anchor="w", padx=28)

        row = self.frame(card, "panel")
        row.pack(anchor="w", padx=28, pady=28)

        cur_lang = self._lang()
        for code, title_txt, sub_txt in (
            ("ru", "🇷🇺  Русский", "Интерфейс, приветствия и диагностика на русском"),
            ("en", "🇬🇧  English", "Interface, greetings, and crash diagnostics in English"),
        ):
            selected = (cur_lang == code)
            box = self.frame(
                row, "bg" if selected else "surface",
                corner_radius=14, border_width=2,
            )
            self.T(box, border_color="accent" if selected else "border")
            box.pack(side="left", padx=(0, 18), ipadx=18, ipady=14)

            lbl_t = self.label(box, title_txt, 20, True, color="accent" if selected else "text")
            lbl_t.pack(anchor="w", padx=18, pady=(12, 4))
            lbl_s = self.label(box, sub_txt, 12, color="subtext", wraplength=260)
            lbl_s.pack(anchor="w", padx=18, pady=(0, 12))

            def pick_lang(_e=None, c_code=code):
                self.draft["lang"] = c_code
                self.cfg["language"] = c_code
                cfgmod.save(self.cfg)
                self.show("wizard", 1)

            for w in (box, lbl_t, lbl_s):
                try:
                    w.configure(cursor="hand2")
                except Exception:
                    pass
                w.bind("<Button-1>", pick_lang)

        self._nav(card, None, self._tr("btn_next"), lambda: self.show("wizard", 2))

    # Шаг 2 из 4 — Выбор ника (строгая валидация a-zA-Z0-9_)
    def _step2(self, card):
        self.label(card, self._tr("wiz_nick_title"), 26, True).pack(
            anchor="w", padx=28, pady=(6, 4))
        self.label(card, self._tr("wiz_nick_sub"), color="subtext").pack(
            anchor="w", padx=28)
        e = self.entry(card, height=44, width=360, placeholder_text=self._tr("wiz_nick_placeholder"))
        e.pack(anchor="w", padx=28, pady=(20, 6))
        e.insert(0, self.draft["nick"])
        err = self.label(card, self._tr("wiz_nick_hint"), 12, color="subtext", wraplength=680)
        err.pack(anchor="w", padx=28)

        def nxt():
            raw_nick = e.get()
            ok, msg_err = i18n.validate_nickname(raw_nick, lang=self._lang())
            if not ok:
                self.msg(err, msg_err, "danger")
                return
            self.draft["nick"] = raw_nick
            self.show("wizard", 3)

        e.bind("<Return>", lambda _e: nxt())
        self._nav(card, lambda: self.show("wizard", 1), self._tr("btn_next"), nxt)

    # Шаг 3 из 4 — Тема оформления
    def _step3(self, card):
        self.label(card, self._tr("wiz_theme_title"), 26, True).pack(anchor="w", padx=28, pady=(6, 4))
        self.label(card, self._tr("wiz_theme_sub"), color="subtext").pack(anchor="w", padx=28)
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
        self._nav(card, lambda: self.show("wizard", 2), self._tr("btn_next"), lambda: self.show("wizard", 4))

    def _mock(self, parent):
        m = self.frame(parent, "bg", corner_radius=16, border_width=2)
        self.T(m, border_color="border")
        m.pack(fill="both", expand=True)
        self.label(m, "botyaraMC", 30, True, "accent").pack(pady=(28, 4))
        sample_nick = self.draft["nick"] or ("player" if self._lang() == "en" else "игрок")
        greet_sample = i18n.random_greeting(sample_nick, lang=self._lang())
        self.label(m, greet_sample, color="subtext").pack(pady=(0, 18))
        self.button(m, self._tr("play_btn"), None, width=220, height=44,
                    font=ctk.CTkFont(size=16, weight="bold")).pack()
        row = self.frame(m, "bg")
        row.pack(pady=24)
        for key in ("accent", "success", "danger", "surface", "text"):
            self.frame(row, key, corner_radius=10, width=26, height=26).pack(side="left", padx=4)

    # Шаг 4 из 4 — Сервер синхронизации
    def _step4(self, card):
        self.label(card, self._tr("wiz_srv_title"), 26, True).pack(
            anchor="w", padx=28, pady=(6, 4))
        self.label(card, self._tr("wiz_srv_sub"), color="subtext").pack(anchor="w", padx=28)
        row = self.frame(card, "panel")
        row.pack(anchor="w", padx=28, pady=(20, 6))
        e = self.entry(row, height=44, width=300, placeholder_text="26.12.34.56")
        e.pack(side="left")
        e.insert(0, self.draft["host"])
        m = self.label(card, "", 13, color="subtext", wraplength=660)

        def on_discovered(_h, _p, sname):
            self.draft["server_name"] = sname or ""

        find = self.button(row, self._tr("wiz_find_auto"), primary=False, height=44, width=210)
        find.configure(command=lambda: self._autofind(e, m, find, on_found=on_discovered))
        find.pack(side="left", padx=12)
        m.pack(anchor="w", padx=28, pady=4)
        self._force = False

        def reset(_e=None):
            if self._force:
                self._force = False
                fin.configure(text=self._tr("btn_finish"))

        e.bind("<KeyRelease>", reset)

        def finish():
            parsed = parse_hostport(e.get())
            if not parsed:
                self.msg(m, self._tr("wiz_bad_addr"), "danger")
                return
            host, port = parsed
            self.draft["host"] = e.get().strip()
            if self._force:
                return self._finish_setup(host, port, self.draft.get("server_name", ""))
            fin.configure(state="disabled")
            self.msg(m, self._tr("wiz_checking"))

            def work():
                try:
                    mf = sync.fetch_manifest(host, port)
                    self.post(done, True, mf)
                except Exception:
                    log.exception("проверка сервера не прошла")
                    self.post(done, False, None)

            def done(ok, mf):
                try:
                    fin.configure(state="normal")
                    if ok:
                        sname = (mf or {}).get("server_name") or self.draft.get("server_name", "")
                        self._finish_setup(host, port, sname, manifest=mf)
                    else:
                        self._force = True
                        fin.configure(text=self._tr("btn_save_anyway"))
                        self.msg(m, self._tr("wiz_offline_warn"), "danger")
                except Exception:
                    pass

            threading.Thread(target=work, daemon=True).start()

        fin = self._nav(card, lambda: self.show("wizard", 3), self._tr("btn_finish"), finish)

    def _finish_setup(self, host, port, server_name="", manifest=None):
        c = self.cfg
        c["language"] = self.draft.get("lang", self._lang())
        c["nickname"] = self.draft["nick"]
        c["theme"] = self.draft["theme"]
        c["setup_done"] = True
        c["mc_dir"] = str(mc.find_minecraft_dir(c.get("mc_dir", "")))
        entry = cfgmod.add_or_select_server(c, host, port, name=server_name)
        cfgmod.save(c)
        if manifest is not None:
            cfgmod.save_cache(manifest, server_id=entry["id"])
            self._last_manifest = manifest
        self.show("main")

    # ============================================================ ГЛАВНОЕ ОКНО
    def _view_main(self):
        root = self.frame(self, "bg")
        root.grid_rowconfigure(0, weight=1)
        root.grid_columnconfigure(0, weight=1)

        # ── Top bar (34px height, aligned with buttons) ──
        top = self.frame(root, "bg", height=34)
        top.grid(row=0, column=0, sticky="ew", padx=22, pady=(16, 0))
        top.grid_propagate(False)
        top.grid_columnconfigure(0, weight=0)
        top.grid_columnconfigure(1, weight=1)
        top.grid_columnconfigure(2, weight=0)

        # Left: Host badge + Auto-RAM + Server name
        left_info = self.frame(top, "bg")
        left_info.grid(row=0, column=0, sticky="w")

        if self.cfg.get("is_host"):
            self.label(left_info, self._tr("host_badge"), 13, True, color="accent").pack(
                side="left", padx=(0, 10))
        ram_now = cfgmod.effective_ram_mb(self.cfg)
        ram_tag = self._tr("auto_ram_tag") if self.cfg.get("auto_ram", True) else self._tr("ram_tag")
        active_s = cfgmod.active_server(self.cfg)
        srv_name = ((active_s or {}).get("name") or "").strip()
        srv_display = f" 🌐 {srv_name}" if srv_name else ""
        self.label(
            left_info,
            f"{ram_tag}: {ram_now} {self._tr('mb_unit')}{srv_display}",
            12, color="subtext",
        ).pack(side="left")

        # Right: Top buttons (34px height)
        btns = self.frame(top, "bg")
        btns.grid(row=0, column=2, sticky="e")
        self.button(btns, self._tr("top_settings"), lambda: self.show("settings"), primary=False,
                    width=136, height=34).pack(side="right")
        self.button(btns, self._tr("top_folders"), self._open_folders_dialog, primary=False,
                    width=116, height=34).pack(side="right", padx=(0, 8))
        self.button(btns, self._tr("top_log"), self._open_latest_game_log, primary=False,
                    width=90, height=34).pack(side="right", padx=(0, 8))
        self.button(btns, "⌨", self._open_hotkeys_dialog, primary=False,
                    width=38, height=34).pack(side="right", padx=(0, 8))

        # ── Center hero block (vertically anchored at true center) ──
        hero = self.frame(root, "bg")
        hero.place(relx=0.5, rely=0.5, anchor="center")

        self.label(hero, "botyaraMC", 56, True, "accent").pack()
        self.greeting_lbl = self.label(hero, self._greeting, 18, color="subtext")
        self.greeting_lbl.pack(pady=(2, 10))

        # Quick server switch (if multiple servers)
        self.server_title_lbl = None
        self._main_srv_om = None
        self._main_srv_map = {}
        servers = self.cfg.get("servers") or []
        if len(servers) > 1:
            srv_row = self.frame(hero, "bg")
            srv_row.pack(pady=(0, 6))

            def _on_switch_main_srv(chosen):
                if self.playing:
                    return
                s = self._main_srv_map.get(chosen)
                if not s:
                    return
                cfgmod.add_or_select_server(self.cfg, s["host"], s["port"])
                cfgmod.save(self.cfg)
                self._last_manifest = cfgmod.load_cache(s["id"])
                self._status = ""
                self.refresh_download_plan(manual=True)

            self._main_srv_om = self.option_menu(srv_row, values=["—"], command=_on_switch_main_srv, width=320)
            self._main_srv_om.pack()
            self._refresh_main_server_header()
        else:
            init_srv_title = f"🌐 {srv_name}" if srv_name else ""
            self.server_title_lbl = self.label(hero, init_srv_title, 14, True, color="text")
            if init_srv_title:
                self.server_title_lbl.pack(pady=(0, 4))

        # Badge (mods count, etc.)
        self.badge_lbl = self.label(hero, self._server_badge_text, 13, color="subtext")
        self.badge_lbl.pack(pady=(0, 10))

        # Live MC server ping badge
        self.mc_ping_lbl = self.label(hero, "", 13, color="subtext")
        self.mc_ping_lbl.pack(pady=(0, 20))
        self._start_mc_ping_loop()

        # Play button
        self.play_btn = self.button(
            hero, self._play_btn_text, self.on_play,
            width=390, height=68,
            font=ctk.CTkFont(size=20, weight="bold"),
        )
        self.play_btn.pack()
        self._bind_play_hover(self.play_btn)
        if self.playing:
            self.play_btn.configure(state="disabled")
            self._play_hover_t = 1.0
            self._paint_play_button_color()

        # ── Lower container: progress bar (hidden by default) + status ──
        lower = self.frame(root, "bg")
        lower.place(relx=0.5, rely=0.5, anchor="center", y=220)

        self.progress_holder = self.frame(lower, "bg")
        self.progress_holder.pack(pady=(0, 8))
        self.progress = ctk.CTkProgressBar(self.progress_holder, width=400)
        self.T(self.progress, fg_color="surface", progress_color="accent")
        self.progress.set(self._prog)
        if self.playing:
            self.progress.pack(pady=(6, 8))

        self.status_lbl = self.label(lower, self._status, 14, color="subtext", wraplength=700)
        self.status_lbl.pack(pady=(6, 0))

        # Bind R key (and Cyrillic К) for random greeting
        self.bind_all("<Key-r>", lambda e: self._randomize_greeting(e))
        self.bind_all("<Key-R>", lambda e: self._randomize_greeting(e))
        # Cyrillic 'к' — пробуем разные варианты, не все Tk их понимают
        for seq in ("<Key-0x6B>", "<Key-к>", "<Key-Cyrillic_ka>", "<Key-KCyrillic>"):
            try:
                self.bind_all(seq, lambda e: self._randomize_greeting(e))
            except Exception:
                pass

        return root

    def _start_mc_ping_loop(self):
        """Background ping of the Minecraft server shown in manifest.server (host/port)."""
        if getattr(self, "_mc_ping_job", None):
            try:
                self.after_cancel(self._mc_ping_job)
            except Exception:
                pass
        self._mc_ping_job = self.after(5000, self._update_mc_ping)

    def _update_mc_ping(self):
        self._mc_ping_job = None
        try:
            if not self.winfo_exists():
                return
            manifest = self._last_manifest or cfgmod.load_cache(self.cfg.get("active_server_id") or None)
            if manifest:
                srv = manifest.get("server") or {}
                mchost = srv.get("host")
                mcport = srv.get("port") or 25565
                if mchost:
                    # Use sync_host as fallback for "auto"
                    result = mc.ping_mc_server(mchost, mcport, sync_host=self.cfg.get("sync_host", ""), timeout=1.5)
                    lang = self._lang()
                    if result.get("online"):
                        txt = self._tr("mc_ping_online", on=result["players_online"], mx=result["players_max"], ms=result["latency_ms"])
                    else:
                        txt = self._tr("mc_ping_offline")
                    self.mc_ping_lbl.configure(text=txt)
        except Exception:
            pass
        self._mc_ping_job = self.after(10000, self._update_mc_ping)

    def _randomize_greeting(self, event=None):
        """Switch greeting to a new random phrase (bound to R key)."""
        # Ignore if focus is in an Entry/Text widget
        w = self.focus_get()
        if w is not None:
            cls = w.winfo_class().lower()
            if any(t in cls for t in ("entry", "text")):
                return
        # Ignore if modifier keys held (Ctrl/Alt/Shift)
        try:
            state = event.state if event else 0
            if state & (0x4 | 0x8 | 0x1):  # Control | Alt | Shift (bitmask)
                return
        except Exception:
            pass
        self._greeting = i18n.random_greeting(
            self.cfg.get("nickname") or "",
            lang=self._lang(),
            prev=self._greeting,
        )
        if hasattr(self, "greeting_lbl") and self.greeting_lbl.winfo_exists():
            self.greeting_lbl.configure(text=self._greeting)

    def _show_progress_bar(self, visible):
        try:
            if not hasattr(self, "progress") or not self.progress.winfo_exists():
                return
            if visible:
                if not self.progress.winfo_manager():
                    self.progress.pack(pady=(6, 8))
            else:
                if self.progress.winfo_manager():
                    self.progress.pack_forget()
        except Exception:
            pass

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

    def _refresh_main_server_header(self, fallback_name=""):
        servers = self.cfg.get("servers") or []
        om = getattr(self, "_main_srv_om", None)
        if om is not None and om.winfo_exists() and len(servers) > 1:
            self._main_srv_map.clear()
            labels = []
            cur_lbl = None
            for s in servers:
                lb = self._server_label(s)
                if lb in self._main_srv_map:
                    lb = f"{lb} [{s['id'][-4:]}]"
                self._main_srv_map[lb] = s
                labels.append(lb)
                if s.get("id") == self.cfg.get("active_server_id"):
                    cur_lbl = lb
            om.configure(values=labels)
            if cur_lbl:
                om.set(cur_lbl)
            return

        lbl = getattr(self, "server_title_lbl", None)
        if lbl is not None and lbl.winfo_exists():
            active_s = cfgmod.active_server(self.cfg)
            sname = ((active_s or {}).get("name") or fallback_name or "").strip()
            if sname:
                lbl.configure(text=f"🌐 {sname}")
                if not lbl.winfo_manager():
                    lbl.pack(pady=(0, 4), before=self.badge_lbl)
            else:
                if lbl.winfo_manager():
                    lbl.pack_forget()

    def _set_badge(self, text):
        self._server_badge_text = text
        try:
            self.badge_lbl.configure(text=text)
        except Exception:
            pass

    def _show_progress_bar(self, visible):
        try:
            if not hasattr(self, "progress") or not self.progress.winfo_exists():
                return
            if visible:
                if not self.progress.winfo_manager():
                    self.progress.pack(pady=(6, 8))
            else:
                if self.progress.winfo_manager():
                    self.progress.pack_forget()
        except Exception:
            pass

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

    def _refresh_main_server_header(self, fallback_name=""):
        servers = self.cfg.get("servers") or []
        om = getattr(self, "_main_srv_om", None)
        if om is not None and om.winfo_exists() and len(servers) > 1:
            self._main_srv_map.clear()
            labels = []
            cur_lbl = None
            for s in servers:
                lb = self._server_label(s)
                if lb in self._main_srv_map:
                    lb = f"{lb} [{s['id'][-4:]}]"
                self._main_srv_map[lb] = s
                labels.append(lb)
                if s.get("id") == self.cfg.get("active_server_id"):
                    cur_lbl = lb
            om.configure(values=labels)
            if cur_lbl:
                om.set(cur_lbl)
            return

        lbl = getattr(self, "server_title_lbl", None)
        if lbl is not None and lbl.winfo_exists():
            active_s = cfgmod.active_server(self.cfg)
            sname = ((active_s or {}).get("name") or fallback_name or "").strip()
            if sname:
                lbl.configure(text=f"🌐 {sname}")
                if not lbl.winfo_manager():
                    lbl.pack(pady=(0, 4), before=self.badge_lbl)
            else:
                if lbl.winfo_manager():
                    lbl.pack_forget()

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
            self._set_status(self._tr("status_refreshing"))

        def work():
            cfg = self.cfg
            host, port = cfg.get("sync_host", ""), cfg.get("sync_port", DEFAULT_PORT)
            srv_id = cfg.get("active_server_id") or None
            if not host:
                return
            try:
                mf = sync.fetch_manifest(host, port)
                if mf.get("server_name"):
                    if cfgmod.update_server_name(cfg, mf["server_name"], server_id=srv_id):
                        cfgmod.save(cfg)
                cfgmod.save_cache(mf, server_id=srv_id)
                self._last_manifest = mf
                mc_dir = mc.find_minecraft_dir(cfg.get("mc_dir", ""))
                plan = sync.plan_sync(
                    mf, mc_dir,
                    is_host=cfg.get("is_host", False),
                    server_mods_dir=cfg.get("server_mods_dir", ""),
                )
                self.post(_apply_plan, mf, plan, True)
            except Exception:
                cached = cfgmod.load_cache(server_id=srv_id)
                self._last_manifest = cached
                self.post(_apply_plan, cached, None, False)

        def _apply_plan(mf, plan, online):
            if self.playing:
                return
            lang = self._lang()
            if mf:
                self._refresh_main_server_header(fallback_name=mf.get("server_name", ""))
                parts = [f"Minecraft {mf['mc_version']}", mf["loader"]]
                if mf.get("java_version"):
                    parts.append(f"Java {mf['java_version']}")
                parts.append(self._tr("badge_mods", n=len(mf.get("mods", []))))
                if mf.get("resourcepacks"):
                    parts.append(self._tr("badge_rp", n=len(mf["resourcepacks"])))
                if mf.get("mods_hidden"):
                    parts.append(self._tr("badge_hidden"))
                self._set_badge("  •  ".join(parts))
            else:
                self._refresh_main_server_header()
                self._set_badge("")

            if online and plan is not None:
                tb = plan["total_bytes"]
                if tb > 0:
                    sz = sync.format_size(tb, lang=lang)
                    self._set_play_text(self._tr("play_btn_dl", size=sz))
                    if manual or not self._status:
                        self._set_status(self._tr(
                            "status_need_dl",
                            size=sz,
                            mods=plan["mods_count"],
                            rp=plan["rp_count"],
                        ))
                elif plan["total_files"] > 0:
                    self._set_play_text(self._tr("play_btn_update"))
                else:
                    self._set_play_text(self._tr("play_btn"))
                    if manual:
                        self._set_status(self._tr("status_up_to_date"))
            else:
                self._set_play_text(self._tr("play_btn"))
                if manual:
                    self._set_status(self._tr("status_offline_cache"))

        threading.Thread(target=work, daemon=True).start()

    def _play_done(self):
        self.playing = False
        self._show_progress_bar(False)
        try:
            self.play_btn.configure(state="normal")
            self._paint_play_button_color()
        except Exception:
            pass
        self.refresh_download_plan(manual=False)

    def on_play(self):
        if self.playing:
            return
        self.playing = True
        self._prog = 0.0
        self._show_progress_bar(True)
        self._set_progress(0.02)
        try:
            self.play_btn.configure(state="disabled")
        except Exception:
            pass
        threading.Thread(target=self._play_worker, daemon=True).start()

    def _play_worker(self):
        P = self.post
        lang = self._lang()
        try:
            cfg = self.cfg
            host, port = cfg.get("sync_host", ""), cfg.get("sync_port", DEFAULT_PORT)
            srv_id = cfg.get("active_server_id") or None
            P(self._set_status, i18n.tr(lang, "status_connecting"))
            P(self._set_progress, 0.04)
            manifest = None
            if host:
                try:
                    manifest = sync.fetch_manifest(host, port)
                except Exception:
                    log.warning("sync-сервер недоступен по %s:%s, ищем заново", host, port)
            if manifest is None:
                # Smart discovery: discover_all + match_discovered_server
                candidates = discovery.discover_all(2.2)
                matched = cfgmod.match_discovered_server(cfg, candidates)
                if matched:
                    fh, fp, fname, entry = matched
                    try:
                        manifest = sync.fetch_manifest(fh, fp)
                        host, port = fh, fp
                        srv_id = entry["id"]
                        cfgmod.save(cfg)
                    except Exception:
                        log.exception("найденный сервер не ответил")
            live = manifest is not None
            if live:
                if manifest.get("server_name"):
                    if cfgmod.update_server_name(cfg, manifest["server_name"], server_id=srv_id):
                        cfgmod.save(cfg)
                cfgmod.save_cache(manifest, server_id=srv_id)
                self._last_manifest = manifest
            else:
                manifest = cfgmod.load_cache(server_id=srv_id)
            if manifest is None:
                P(self._set_status, i18n.tr(lang, "status_unreachable"))
                return

            mc_dir = mc.find_minecraft_dir(cfg.get("mc_dir", ""))
            if live:
                plan = sync.plan_sync(
                    manifest, mc_dir,
                    is_host=cfg.get("is_host", False),
                    server_mods_dir=cfg.get("server_mods_dir", ""),
                    cfg=cfg,
                )
                if plan["total_bytes"] > 0:
                    P(self._set_status, i18n.tr(
                        lang, "status_downloading",
                        size=sync.format_size(plan["total_bytes"], lang=lang),
                    ))
                else:
                    P(self._set_status, i18n.tr(lang, "status_checking_mods"))

                ok = sync.sync_all(
                    host, port, manifest, mc_dir,
                    is_host=cfg.get("is_host", False),
                    server_mods_dir=cfg.get("server_mods_dir", ""),
                    on_progress=lambda f: P(self._set_progress, 0.05 + f * 0.40),
                    on_status=lambda s: P(self._set_status, s),
                    lang=lang,
                    cfg=cfg,
                )
                if not ok:
                    log.warning("синхронизация прошла не полностью")

            P(self._set_status, i18n.tr(
                lang, "status_preparing_mc",
                ver=manifest["mc_version"], loader=manifest["loader"],
            ))
            vid = mc.ensure_version(
                mc_dir, manifest["mc_version"], manifest["loader"],
                on_frac=lambda f: P(self._set_progress, 0.45 + f * 0.45),
                cfg=cfg,
                server_java_version=manifest.get("java_version"),
            )

            P(self._set_status, i18n.tr(lang, "status_launching"))
            P(self._set_progress, 0.95)
            srv = manifest.get("server") or {}
            client_folder = manifest.get("client_folder", "")
            game_dir = cfgmod.resolve_game_dir(mc_dir, client_folder, cfg=cfg, manifest=manifest)
            log_path = cfgmod.config_dir() / "game.log"
            start_time = time.time()
            ram_mb = cfgmod.effective_ram_mb(cfg)

            proc = mc.launch(
                mc_dir, vid, cfg["nickname"],
                srv.get("host"), srv.get("port"),
                ram_mb, log_path,
                cfg=cfg,
                server_java_version=manifest.get("java_version"),
                auto_join=bool(srv.get("auto_join", True)),
                client_folder=client_folder,
                manifest=manifest,
            )

            def _on_game_ready():
                P(self._set_progress, 1.0)
                P(self._set_status, i18n.tr(lang, "status_game_ready"))
                # Update play button to show running state
                P(self._on_game_started)

            rc, timed_out = mc.monitor_launch(
                proc, log_path,
                timeout_sec=cfg.get("launch_timeout", 120),
                on_ready=_on_game_ready,
            )

            full_log, has_cr, _ = crash.collect_session_log(game_dir, log_path, start_time, lang=lang)
            if crash.is_crash(rc, full_log, has_crash_file=has_cr, timed_out=timed_out):
                report = crash.parse_crash(full_log, exit_code=rc, timed_out=timed_out, lang=lang)
                P(self._set_status, i18n.tr(lang, "status_crash_prefix", title=report["title"]))
                P(self._set_progress, 0.0)
                P(self._open_crash_dialog, report, full_log, manifest)
            else:
                P(self._set_status, i18n.tr(lang, "status_game_closed"))
                P(self._set_progress, 0.0)
        except Exception as e:
            log.exception("запуск не удался")
            P(self._set_status, i18n.tr(lang, "status_launch_err", err=e))
            P(self._set_progress, 0.0)
        finally:
            P(self._play_done)

    def _on_game_started(self):
        """Called when game window is detected - update UI for running state."""
        try:
            # Keep button in hover color (accent_hover)
            self._play_hover_t = 1.0
            self._paint_play_button_color()
            # Change button text to "GAME RUNNING"
            self.play_btn.configure(text=self._tr("play_btn_running"), state="disabled")
            # Hide progress bar
            self._show_progress_bar(False)
            # Show running status
            self._set_status(self._tr("status_game_ready"))
            # Apply on_launch_action
            action = self.cfg.get("on_launch_action", "keep")
            if action == "minimize":
                self.iconify()
            elif action == "hide":
                self.withdraw()
        except Exception:
            pass

    def _restore_window_if_hidden(self):
        """Restore window if it was hidden/minimized per on_launch_action."""
        try:
            action = self.cfg.get("on_launch_action", "keep")
            if action in ("minimize", "hide"):
                self.deiconify()
                self.lift()
                self.focus_force()
        except Exception:
            pass

    def _play_done(self):
        self.playing = False
        self._show_progress_bar(False)
        self._restore_window_if_hidden()
        try:
            self.play_btn.configure(state="normal")
            self._play_hover_t = 0.0
            self._paint_play_button_color()
            self._set_play_text(self._tr("play_btn"))
        except Exception:
            pass
        self.refresh_download_plan(manual=False)

    # ============================================================ БЫСТРОЕ ОТКРЫТИЕ ПАПОК (#16)
    def _open_folders_dialog(self):
        mc_dir = mc.find_minecraft_dir(self.cfg.get("mc_dir", ""))
        client_folder = (self._last_manifest or {}).get("client_folder", "")
        game_dir = cfgmod.resolve_game_dir(mc_dir, client_folder)

        has_host = bool(self.cfg.get("is_host") and self.cfg.get("server_mods_dir"))
        dlg_h = 560 if has_host else 520
        dlg = self._make_dialog(
            self._tr("folders_title"),
            width=540, height=dlg_h,
            min_w=500, min_h=dlg_h - 20,
        )
        card = self.frame(dlg, "panel", corner_radius=16)
        card.pack(fill="both", expand=True, padx=18, pady=18)

        # Сначала упаковываем кнопку «Закрыть» снизу, чтобы она НИКОГДА не обрезалась!
        bottom_bar = self.frame(card, "panel")
        bottom_bar.pack(side="bottom", fill="x", padx=20, pady=(10, 16))
        self.button(
            bottom_bar, self._tr("folders_close"), dlg.destroy,
            primary=False, width=150, height=38,
        ).pack()

        self.label(card, self._tr("folders_heading"), 20, True).pack(anchor="w", padx=20, pady=(16, 2))
        self.label(card, self._tr("folders_sub"), 12, color="subtext").pack(
            anchor="w", padx=20, pady=(0, 12))

        items = [
            ("1", self._tr("folder_mc", name=game_dir.name), game_dir),
            ("2", self._tr("folder_mods"), game_dir / "mods"),
            ("3", self._tr("folder_rp"), game_dir / "resourcepacks"),
            ("4", self._tr("folder_screens"), game_dir / "screenshots"),
            ("5", self._tr("folder_crashes"), game_dir / "crash-reports"),
            ("6", self._tr("folder_cfg"), cfgmod.config_dir()),
        ]
        if has_host:
            items.append(("7", self._tr("folder_srv_mods"), Path(self.cfg["server_mods_dir"])))

        list_box = self.frame(card, "panel")
        list_box.pack(fill="both", expand=True, padx=20)

        def go(target_path):
            try:
                cfgmod.open_folder(target_path)
            except Exception:
                log.exception("не удалось открыть папку %s", target_path)
            if dlg.winfo_exists():
                dlg.destroy()

        for key_num, title_str, p in items:
            btn = self.button(
                list_box, f"[{key_num}]   {title_str}",
                command=partial(go, p),
                primary=False, height=38, anchor="w",
            )
            btn.pack(fill="x", pady=4)
            dlg.bind(key_num, lambda _e, path=p: go(path))

    # ============================================================ ШПАРГАЛКА ХОТКЕЕВ
    def _open_hotkeys_dialog(self):
        dlg = self._make_dialog(self._tr("hk_title"), width=540, height=440, min_w=500, min_h=410)
        card = self.frame(dlg, "panel", corner_radius=16)
        card.pack(fill="both", expand=True, padx=18, pady=18)

        self.button(card, self._tr("hk_ok"), dlg.destroy, width=160, height=38).pack(
            side="bottom", pady=(8, 16))

        self.label(card, self._tr("hk_heading"), 20, True).pack(anchor="w", padx=22, pady=(16, 12))
        shortcuts = [
            ("Enter / Ctrl + P", self._tr("hk_play")),
            ("R / К", self._tr("hk_random_greet")),
            ("F5 / Ctrl + R", self._tr("hk_refresh")),
            ("Ctrl + O", self._tr("hk_folders")),
            ("Ctrl + L", self._tr("hk_log")),
            ("Ctrl + ,", self._tr("hk_settings")),
            ("Esc", self._tr("hk_esc")),
            ("F1", self._tr("hk_f1")),
        ]
        grid = self.frame(card, "panel")
        grid.pack(fill="both", expand=True, padx=22)
        for idx, (keys, desc) in enumerate(shortcuts):
            k_lbl = self.label(grid, keys, 13, True, color="accent")
            k_lbl.grid(row=idx, column=0, sticky="w", pady=5, padx=(0, 18))
            self.label(grid, desc, 13, color="text").grid(row=idx, column=1, sticky="w", pady=5)

    # ============================================================ КРАШ-РЕПОРТ И ЛОГИ
    def _open_latest_game_log(self):
        log_path = cfgmod.config_dir() / "game.log"
        if not log_path.is_file():
            log_path = cfgmod.config_dir() / "launcher.log"
        text = crash._read_text_safe(log_path) if log_path.is_file() else self._tr("log_empty_yet")
        mf = self._last_manifest or {}
        self._open_log_window(
            text,
            mc_version=mf.get("mc_version", ""),
            loader=mf.get("loader", ""),
            exit_code=None,
            header_title=f"{self._tr('top_log')} ({log_path.name})",
        )

    def _open_crash_dialog(self, report, full_log, manifest=None):
        mf = manifest or self._last_manifest or {}
        dlg = self._make_dialog(self._tr("crash_win_title"), width=660, height=520, min_w=580, min_h=460)
        card = self.frame(dlg, "panel", corner_radius=16)
        card.pack(fill="both", expand=True, padx=18, pady=18)

        bar = self.frame(card, "panel")
        bar.pack(side="bottom", fill="x", padx=22, pady=(8, 16))

        self.label(card, self._tr("crash_heading"), 22, True, color="danger").pack(
            anchor="w", padx=22, pady=(18, 4))
        code_txt = self._tr("crash_exit_code", code=report["exit_code"]) if report.get("exit_code") is not None else ""
        self.label(card, f"{report['title']}   {code_txt}", 15, True, color="text",
                   wraplength=600).pack(anchor="w", padx=22, pady=(0, 8))

        body = self.scroll_frame(card, "bg", height=250)
        body.pack(fill="both", expand=True, padx=22, pady=(0, 8))

        self.label(body, report["summary"], 13, color="text", wraplength=560).pack(
            anchor="w", padx=12, pady=(10, 8))

        if report.get("exception"):
            self.label(body, self._tr("crash_tech_reason"), 12, True, color="subtext").pack(anchor="w", padx=12)
            self.label(body, report["exception"], 12, color="danger", wraplength=560).pack(
                anchor="w", padx=12, pady=(2, 8))

        if report.get("suspected_mods"):
            self.label(body, self._tr("crash_suspects"), 12, True, color="subtext").pack(
                anchor="w", padx=12)
            self.label(body, "• " + ", ".join(report["suspected_mods"]), 13, color="accent",
                       wraplength=560).pack(anchor="w", padx=12, pady=(2, 8))

        self.label(body, self._tr("crash_what_to_do"), 12, True, color="subtext").pack(anchor="w", padx=12)
        for tip in report.get("solutions", []):
            self.label(body, f"• {tip}", 13, color="text", wraplength=560).pack(
                anchor="w", padx=12, pady=2)

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

        self.button(bar, self._tr("crash_view_full"), open_full, width=220, height=40).pack(side="left")
        self.button(bar, self._tr("crash_close"), dlg.destroy, primary=False, width=110, height=40).pack(side="right")
        self.button(bar, self._tr("crash_restart"), restart, primary=False, width=145, height=40).pack(
            side="right", padx=8)

    def _open_log_window(self, full_log, mc_version="", loader="", exit_code=None,
                         header_title=None, parent_crash_dlg=None):
        dlg = self._make_dialog(self._tr("log_win_title"), width=840, height=580, min_w=680, min_h=480)
        card = self.frame(dlg, "panel", corner_radius=16)
        card.pack(fill="both", expand=True, padx=16, pady=16)

        bar = self.frame(card, "panel")
        bar.pack(side="bottom", fill="x", padx=20, pady=(4, 16))

        share_row = self.frame(card, "panel")
        share_row.pack(side="bottom", fill="x", padx=20, pady=(0, 4))
        info_lbl = self.label(share_row, "", 13, color="subtext")
        info_lbl.pack(side="left")
        last_url = [""]
        open_url_btn = self.button(
            share_row, self._tr("log_open_browser"),
            command=lambda: webbrowser.open(last_url[0]) if last_url[0] else None,
            primary=False, width=175, height=28,
        )

        hdr = self.frame(card, "panel")
        hdr.pack(fill="x", padx=20, pady=(16, 6))
        lines_cnt = len((full_log or "").splitlines())
        self.label(hdr, header_title or self._tr("log_default_hdr"), 18, True).pack(side="left")
        self.label(hdr, self._tr("log_lines", n=lines_cnt), 12, color="subtext").pack(side="right")

        txt = ctk.CTkTextbox(
            card,
            corner_radius=10,
            font=ctk.CTkFont(family="Consolas" if sys.platform.startswith("win") else "monospace", size=12),
            wrap="none",
        )
        self.T(txt, fg_color="bg", text_color="text", border_color="border",
               scrollbar_button_color="surface_hover", scrollbar_button_hover_color="accent")
        txt.pack(fill="both", expand=True, padx=20, pady=(4, 8))
        txt.insert("1.0", full_log or self._tr("log_empty"))
        txt.see("end")
        txt.configure(state="disabled")

        def do_copy():
            self._copy_clipboard(full_log or "")
            self.msg(info_lbl, self._tr("log_copied"), "success")

        def do_share():
            share_btn.configure(state="disabled", text=self._tr("log_sharing"))
            self.msg(info_lbl, self._tr("log_uploading"), "subtext")

            def work():
                try:
                    res = crash.upload_to_mclogs(
                        full_log or "",
                        mc_version=mc_version,
                        loader=loader,
                        exit_code=exit_code,
                        lang=self._lang(),
                    )
                    self.post(done_ok, res)
                except Exception as e:
                    log.exception("ошибка отправки на mclo.gs")
                    self.post(done_err, str(e))

            def done_ok(res):
                if not dlg.winfo_exists():
                    return
                share_btn.configure(state="normal", text=self._tr("log_share_btn"))
                url = res["url"]
                last_url[0] = url
                self._copy_clipboard(url)
                self.msg(info_lbl, self._tr("log_shared_ok", url=url), "success")
                open_url_btn.pack(side="right")

            def done_err(err_msg):
                if not dlg.winfo_exists():
                    return
                share_btn.configure(state="normal", text=self._tr("log_share_btn"))
                self.msg(info_lbl, self._tr("log_shared_err", err=err_msg), "danger")

            threading.Thread(target=work, daemon=True).start()

        def do_restart():
            if parent_crash_dlg is not None and parent_crash_dlg.winfo_exists():
                parent_crash_dlg.destroy()
            if dlg.winfo_exists():
                dlg.destroy()
            self.on_play()

        self.button(bar, self._tr("log_copy_btn"), do_copy, primary=False, width=155, height=40).pack(
            side="left", padx=(0, 8))
        share_btn = self.button(bar, self._tr("log_share_btn"), do_share, primary=True, width=190, height=40)
        share_btn.pack(side="left")

        self.button(bar, self._tr("log_close_btn"), dlg.destroy, primary=False, width=120, height=40).pack(
            side="right")
        self.button(bar, self._tr("crash_restart"), do_restart, primary=False, width=150, height=40).pack(
            side="right", padx=8)

    # ============================================================ РЕДАКТОР JVM-ПРЕСЕТОВ
    def _open_presets_editor(self, custom_presets_draft, current_preset_var, on_updated):
        dlg = self._make_dialog(self._tr("pe_title"), width=680, height=500, min_w=600, min_h=450)
        card = self.frame(dlg, "panel", corner_radius=16)
        card.pack(fill="both", expand=True, padx=16, pady=16)

        bar = self.frame(card, "panel")
        bar.pack(side="bottom", fill="x", padx=20, pady=(8, 16))

        self.label(card, self._tr("pe_heading"), 20, True).pack(anchor="w", padx=20, pady=(16, 2))
        self.label(card, self._tr("pe_sub"), 12, color="subtext").pack(anchor="w", padx=20, pady=(0, 10))

        def merged():
            m = dict(jvm.BUILTIN_PRESETS)
            m.update(custom_presets_draft)
            return m

        top_row = self.frame(card, "panel")
        top_row.pack(fill="x", padx=20, pady=(0, 8))

        sel_var = tk.StringVar(value=current_preset_var.get())
        om = self.option_menu(top_row, values=list(merged().keys()), variable=sel_var, width=220)
        om.pack(side="left")

        e_new = self.entry(top_row, width=200, height=32, placeholder_text=self._tr("pe_new_placeholder"))
        e_new.pack(side="left", padx=(12, 6))

        desc_lbl = self.label(card, "", 12, color="subtext", wraplength=620)
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
            desc = jvm.preset_description(nm, lang=self._lang())
            if nm in jvm.BUILTIN_PRESETS and nm in custom_presets_draft:
                desc += self._tr("pe_modified")
            desc_lbl.configure(text=desc)
            box.delete("1.0", "end")
            box.insert("1.0", all_p.get(nm, ""))

        om.configure(command=load_selected)

        def add_new():
            nm = e_new.get().strip()
            if not nm:
                return self.msg(status, self._tr("pe_enter_name"), "danger")
            custom_presets_draft[nm] = box.get("1.0", "end").strip()
            e_new.delete(0, "end")
            vals = list(merged().keys())
            om.configure(values=vals)
            sel_var.set(nm)
            load_selected(nm)
            self.msg(status, self._tr("pe_created", name=nm), "success")

        self.button(top_row, self._tr("pe_create_btn"), add_new, primary=False, width=110, height=32).pack(side="left")

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
                self.msg(status, self._tr("pe_reset_ok", name=nm), "success")
            else:
                custom_presets_draft.pop(nm, None)
                vals = list(merged().keys())
                om.configure(values=vals)
                sel_var.set("G1GC")
                load_selected("G1GC")
                self.msg(status, self._tr("pe_deleted", name=nm), "subtext")

        self.button(bar, self._tr("pe_reset_btn"), reset_or_delete, primary=False,
                    width=180, height=38).pack(side="left")
        self.button(bar, self._tr("pe_apply_btn"), save_current_and_close, width=155, height=38).pack(side="right")
        self.button(bar, self._tr("pe_cancel_btn"), dlg.destroy, primary=False, width=110, height=38).pack(
            side="right", padx=8)

        load_selected()

    # ============================================================ ДОБАВЛЕНИЕ СЕРВЕРА (#12)
    def _open_add_server_dialog(self, on_added):
        dlg = self._make_dialog(self._tr("add_srv_win_title"), width=540, height=340, min_w=500, min_h=320)
        card = self.frame(dlg, "panel", corner_radius=16)
        card.pack(fill="both", expand=True, padx=18, pady=18)

        bar = self.frame(card, "panel")
        bar.pack(side="bottom", fill="x", padx=22, pady=(10, 18))

        self.label(card, self._tr("add_srv_heading"), 20, True).pack(anchor="w", padx=22, pady=(18, 4))
        self.label(card, self._tr("add_srv_sub"), 12, color="subtext", wraplength=480).pack(
            anchor="w", padx=22, pady=(0, 14))

        row = self.frame(card, "panel")
        row.pack(fill="x", padx=22, pady=(0, 8))
        e_addr = self.entry(row, height=38, placeholder_text="26.12.34.56")
        e_addr.pack(side="left", fill="x", expand=True)

        e_name = self.entry(card, height=36, placeholder_text=self._tr("add_srv_name_ph"))
        e_name.pack(fill="x", padx=22, pady=(0, 6))

        msg_lbl = self.label(card, "", 12, color="subtext", wraplength=480)
        msg_lbl.pack(anchor="w", padx=22)

        def on_disc(_h, _p, sname):
            if sname and not e_name.get().strip():
                e_name.insert(0, sname)

        btn_find = self.button(row, self._tr("st_find_btn"), primary=False, width=120, height=38)
        btn_find.configure(command=lambda: self._autofind(e_addr, msg_lbl, btn_find, on_found=on_disc))
        btn_find.pack(side="left", padx=(8, 0))

        def do_add():
            parsed = parse_hostport(e_addr.get())
            if not parsed:
                self.msg(msg_lbl, self._tr("st_err_addr"), "danger")
                return
            host, port = parsed
            custom_name = e_name.get().strip()
            btn_ok.configure(state="disabled")
            self.msg(msg_lbl, self._tr("wiz_checking"), "subtext")

            def work():
                try:
                    mf = sync.fetch_manifest(host, port)
                    self.post(done, mf)
                except Exception:
                    self.post(done, None)

            def done(mf):
                if not dlg.winfo_exists():
                    return
                sname = custom_name or ((mf or {}).get("server_name") or "")
                entry = cfgmod.add_or_select_server(self.cfg, host, port, name=sname)
                cfgmod.save(self.cfg)
                if mf is not None:
                    cfgmod.save_cache(mf, server_id=entry["id"])
                    self._last_manifest = mf
                else:
                    self._last_manifest = cfgmod.load_cache(server_id=entry["id"])
                dlg.destroy()
                on_added()

            threading.Thread(target=work, daemon=True).start()

        e_addr.bind("<Return>", lambda _e: do_add())
        e_name.bind("<Return>", lambda _e: do_add())
        btn_ok = self.button(bar, self._tr("add_srv_confirm"), do_add, width=165, height=38)
        btn_ok.pack(side="right")
        self.button(bar, self._tr("pe_cancel_btn"), dlg.destroy, primary=False, width=115, height=38).pack(
            side="right", padx=10)
        dlg.after(100, e_addr.focus_set)

    # ============================================================ ПОДТВЕРЖДЕНИЕ ВЫХОДА (#13)
    def _confirm_signout_dialog(self):
        dlg = self._make_dialog(self._tr("st_signout_confirm_title"), width=520, height=270, min_w=480, min_h=250)
        card = self.frame(dlg, "panel", corner_radius=16)
        card.pack(fill="both", expand=True, padx=18, pady=18)

        bar = self.frame(card, "panel")
        bar.pack(side="bottom", fill="x", padx=22, pady=(10, 18))

        self.label(card, self._tr("st_signout_confirm_title"), 20, True, color="danger").pack(
            anchor="w", padx=22, pady=(18, 8))
        self.label(card, self._tr("st_signout_confirm_body"), 13, color="text", wraplength=440).pack(
            anchor="w", padx=22)

        def do_reset():
            if dlg.winfo_exists():
                dlg.destroy()
            cfgmod.reset_account_and_servers(self.cfg)
            self._last_manifest = None
            self._server_badge_text = ""
            self._status = ""
            self.draft = {
                "lang": self._lang(),
                "nick": "",
                "theme": self.cfg["theme"],
                "host": "",
                "server_name": "",
            }
            self.show("wizard", 1)

        self.danger_button(bar, self._tr("st_signout_yes"), do_reset, width=190, height=38).pack(side="right")
        self.button(bar, self._tr("st_signout_no"), dlg.destroy, primary=False, width=120, height=38).pack(
            side="right", padx=10)

    # ============================================================ НАСТРОЙКИ (#8, #12, #13, #17, #19, #20, #21)
    def _view_settings(self):
        c = self.cfg
        custom_presets_draft = dict(c.get("custom_jvm_presets") or {})

        root = self.frame(self, "bg")
        card = self.frame(root, "panel", corner_radius=18)
        card.pack(fill="both", expand=True, padx=22, pady=20)

        # #19: Шапка настроек с кнопкой «✕ Закрыть» справа вместо подсказок хоткеев
        hdr = self.frame(card, "panel")
        hdr.pack(fill="x", padx=24, pady=(16, 8))
        self.label(hdr, self._tr("st_title"), 24, True).pack(side="left")

        autosave_lbl = self.label(hdr, self._tr("st_autosave_hint"), 12, color="subtext")

        def close_settings():
            autosave_now()
            self.show("main")

        self._close_settings_fn = close_settings
        self.button(
            hdr, self._tr("st_close"), close_settings,
            primary=False, width=122, height=34,
        ).pack(side="right")
        autosave_lbl.pack(side="right", padx=(0, 14))

        # #17: Без нижней панели Сохранить/Отмена — скролл-область занимает всё пространство карточки!
        sf = self.scroll_frame(card, "panel")
        sf.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        g = self.frame(sf, "panel")
        g.pack(fill="x", padx=8, pady=4)
        g.grid_columnconfigure(1, weight=1)

        def section(r, title):
            self.label(g, title, 15, True, color="accent").grid(
                row=r, column=0, columnspan=3, sticky="w", pady=(16 if r else 4, 6)
            )

        def row_lbl(r, text):
            self.label(g, text, color="subtext").grid(
                row=r, column=0, sticky="w", pady=6, padx=(0, 16)
            )

        def _disable_scroll_on_slider(sl):
            """Disable mouse wheel scrolling on CTkSlider."""
            try:
                canvas = getattr(sl, "_canvas", None)
                if canvas:
                    canvas.unbind("<MouseWheel>")
                    canvas.unbind("<Button-4>")
                    canvas.unbind("<Button-5>")
                    sl._mouse_scroll_event = lambda *_a, **_kw: None
            except Exception:
                pass

        def _disable_scroll_on_option_menu(om):
            """Disable mouse wheel scrolling on CTkOptionMenu."""
            try:
                canvas = getattr(om, "_canvas", None)
                if canvas:
                    canvas.unbind("<MouseWheel>")
                    canvas.unbind("<Button-4>")
                    canvas.unbind("<Button-5>")
                    om._mouse_scroll_event = lambda *_a, **_kw: None
            except Exception:
                pass

        # --- Секция 1: Язык, профиль и мульти-серверы ---
        section(0, self._tr("st_sec_profile"))

        # Язык (#6)
        row_lbl(1, self._tr("st_lang"))
        lang_labels = {"ru": "Русский", "en": "English"}
        lang_rev = {v: k for k, v in lang_labels.items()}
        om_lang = self.option_menu(g, values=["Русский", "English"], width=230)
        om_lang.set(lang_labels[self._lang()])
        om_lang.grid(row=1, column=1, sticky="w", pady=4)
        _disable_scroll_on_option_menu(om_lang)

        # Ник (#14)
        row_lbl(2, self._tr("st_nick"))
        e_nick = self.entry(g, height=34)
        e_nick.insert(0, c["nickname"])
        e_nick.grid(row=2, column=1, columnspan=2, sticky="ew", pady=4)

        # Тема
        row_lbl(3, self._tr("st_theme"))
        om_theme = self.option_menu(g, values=themes.THEME_NAMES, width=230)
        om_theme.set(c["theme"])
        om_theme.grid(row=3, column=1, sticky="w", pady=4)
        _disable_scroll_on_option_menu(om_theme)

        # Мульти-серверы (#12)
        row_lbl(4, self._tr("st_active_server"))
        srv_bar = self.frame(g, "panel")
        srv_bar.grid(row=4, column=1, columnspan=2, sticky="ew", pady=4)

        srv_label_map = {}  # display_label -> server_dict
        om_servers = self.option_menu(srv_bar, values=["—"], width=300)
        om_servers.pack(side="left")
        _disable_scroll_on_option_menu(om_servers)

        btn_add_srv = self.button(srv_bar, self._tr("st_srv_add"), primary=False, width=120, height=32)
        btn_add_srv.pack(side="left", padx=(8, 6))
        btn_del_srv = self.button(srv_bar, self._tr("st_srv_remove"), primary=False, width=115, height=32)
        btn_del_srv.pack(side="left")

        row_lbl(5, self._tr("st_srv_addr"))
        e_host = self.entry(g, height=34, placeholder_text="26.12.34.56 или play.host.ru")
        e_host.insert(0, self._addr_text())
        e_host.grid(row=5, column=1, sticky="ew", pady=4)
        m_host = self.label(g, "", 12, color="subtext")
        find_btn = self.button(g, self._tr("st_find_btn"), primary=False, width=125, height=34)
        find_btn.grid(row=5, column=2, padx=(8, 0))
        m_host.grid(row=6, column=1, columnspan=2, sticky="w")

        def rebuild_servers_dropdown():
            srv_label_map.clear()
            servers = c.get("servers") or []
            if not servers:
                empty_lbl = "—"
                om_servers.configure(values=[empty_lbl])
                om_servers.set(empty_lbl)
                btn_del_srv.configure(state="disabled")
                return
            labels = []
            cur_lbl = None
            for s in servers:
                lb = self._server_label(s)
                if lb in srv_label_map:
                    lb = f"{lb} [{s['id'][-4:]}]"
                srv_label_map[lb] = s
                labels.append(lb)
                if s.get("id") == c.get("active_server_id"):
                    cur_lbl = lb
            om_servers.configure(values=labels)
            om_servers.set(cur_lbl or labels[0])
            btn_del_srv.configure(state="normal" if len(servers) > 0 else "disabled")

        def on_select_server(chosen_lbl):
            s = srv_label_map.get(chosen_lbl)
            if not s:
                return
            cfgmod.add_or_select_server(c, s["host"], s["port"])
            e_host.delete(0, "end")
            e_host.insert(0, self._addr_text(s["host"], s["port"]))
            self._last_manifest = cfgmod.load_cache(s["id"])
            cfgmod.save(c)
            self.msg(err, "", "subtext")
            self.msg(autosave_lbl, self._tr("st_saved_ok"), "success")

        om_servers.configure(command=on_select_server)

        def on_added_from_dialog():
            e_host.delete(0, "end")
            e_host.insert(0, self._addr_text())
            rebuild_servers_dropdown()
            self.msg(err, "", "subtext")
            self.msg(autosave_lbl, self._tr("st_saved_ok"), "success")

        def on_click_add_server():
            self._open_add_server_dialog(on_added_from_dialog)

        def on_click_remove_server():
            cur_id = c.get("active_server_id")
            if not cur_id:
                return
            cfgmod.remove_server(c, cur_id)
            cfgmod.save(c)
            e_host.delete(0, "end")
            e_host.insert(0, self._addr_text())
            self._last_manifest = cfgmod.load_cache(c.get("active_server_id") or None)
            rebuild_servers_dropdown()
            self.msg(autosave_lbl, self._tr("st_saved_ok"), "success")

        btn_add_srv.configure(command=on_click_add_server)
        btn_del_srv.configure(command=on_click_remove_server)
        rebuild_servers_dropdown()

        def on_found_in_settings(fh, fp, sname):
            cfgmod.add_or_select_server(c, fh, fp, name=sname or "")
            cfgmod.save(c)
            rebuild_servers_dropdown()
            self.msg(autosave_lbl, self._tr("st_saved_ok"), "success")

        find_btn.configure(command=lambda: self._autofind(e_host, m_host, find_btn, on_found=on_found_in_settings))

        # Режим хоста + папка модов сервера (с валидацией уникальности)
        row_lbl(7, self._tr("st_host_mode"))
        sw_host = ctk.CTkSwitch(g, text=self._tr("st_host_switch"))
        self.T(sw_host, fg_color="surface_hover", progress_color="accent", button_color="text",
               button_hover_color="accent_hover", text_color="text")
        sw_host.grid(row=7, column=1, columnspan=2, sticky="w", pady=4)

        # Папка сборки сервера (переименование/сброс)
        row_lbl(8, self._tr("st_srv_folder"))
        srv_folder_box = self.frame(g, "panel")
        srv_folder_box.grid(row=8, column=1, columnspan=2, sticky="ew", pady=4)
        active_s = cfgmod.active_server(c)
        client_folder = (active_s or {}).get("client_folder", "")
        if client_folder:
            e_srv_folder = self.entry(srv_folder_box, height=34)
            e_srv_folder.insert(0, client_folder)
            e_srv_folder.pack(side="left", fill="x", expand=True, padx=(0, 8))
            btn_rename = self.button(srv_folder_box, self._tr("st_srv_folder_rename"), primary=False, width=120, height=34)
            btn_rename.pack(side="left", padx=(0, 4))
            btn_reset = self.button(srv_folder_box, self._tr("st_srv_folder_reset"), primary=False, width=80, height=34)
            btn_reset.pack(side="left")
        else:
            self.label(srv_folder_box, self._tr("st_srv_folder_root"), 13, color="subtext").pack(side="left")

        row_lbl(9, self._tr("st_srv_mods_dir"))
        e_srv = self.entry(g, height=34, placeholder_text=self._tr("st_srv_mods_ph"))
        e_srv.insert(0, c["server_mods_dir"])
        e_srv.grid(row=9, column=1, sticky="ew", pady=4)
        b_srv = self.button(
            g, self._tr("st_browse"),
            lambda: self._browse_dir(e_srv, on_change=autosave_now),
            primary=False, width=125, height=34,
        )
        b_srv.grid(row=9, column=2, padx=(8, 0))

        # --- Секция 2: Память (RAM), Java и JVM-аргументы ---
        section(10, self._tr("st_sec_java"))

        sys_ram = cfgmod.system_ram_mb()
        rec_ram = cfgmod.recommended_ram_mb(sys_ram)
        max_ram = cfgmod.max_selectable_ram_mb()

        row_lbl(11, self._tr("st_autoram"))
        sw_autoram = ctk.CTkSwitch(
            g, text=self._tr("st_autoram_switch", rec=rec_ram, total=sys_ram),
        )
        self.T(sw_autoram, fg_color="surface_hover", progress_color="accent", button_color="text",
               button_hover_color="accent_hover", text_color="text")
        sw_autoram.grid(row=11, column=1, columnspan=2, sticky="w", pady=4)

        row_lbl(12, self._tr("st_manual_ram"))
        ram_box = self.frame(g, "panel")
        ram_box.grid(row=12, column=1, columnspan=2, sticky="ew", pady=4)
        e_ram = self.entry(ram_box, width=86, height=32)
        init_ram = min(max_ram, max(1024, int(c.get("ram_mb", rec_ram))))
        e_ram.insert(0, str(init_ram))
        e_ram.pack(side="right")
        self.label(ram_box, self._tr("mb_unit"), 12, color="subtext").pack(side="right", padx=(6, 6))

        steps = max(1, (max_ram - 1024) // 256)

        def on_ram_slider(v):
            e_ram.delete(0, "end")
            e_ram.insert(0, str(int(round(v))))
            autosave_now()

        sl_ram = ctk.CTkSlider(
            ram_box, from_=1024, to=max_ram, number_of_steps=steps,
            command=on_ram_slider,
        )
        self.T(sl_ram, fg_color="surface", progress_color="accent", button_color="accent",
               button_hover_color="accent_hover")
        sl_ram.set(init_ram)
        sl_ram.pack(side="left", fill="x", expand=True, padx=(0, 10))
        _disable_scroll_on_slider(sl_ram)

        # Java режим
        row_lbl(13, self._tr("st_java_mode"))
        lbl_java_auto = self._tr("java_mode_auto")
        lbl_java_manual = self._tr("java_mode_manual")
        om_java_mode = self.option_menu(g, values=[lbl_java_auto, lbl_java_manual], width=250)
        om_java_mode.set(lbl_java_manual if c.get("java_mode") == "manual" else lbl_java_auto)
        om_java_mode.grid(row=13, column=1, sticky="w", pady=4)
        _disable_scroll_on_option_menu(om_java_mode)

        row_lbl(14, self._tr("st_java_detected"))
        detected_map = {}
        om_detected = self.option_menu(g, values=[self._tr("java_detect_placeholder")])
        om_detected.grid(row=14, column=1, sticky="ew", pady=4)
        _disable_scroll_on_option_menu(om_detected)
        btn_scan_java = self.button(g, self._tr("st_detect_java_btn"), primary=False, width=125, height=34)
        btn_scan_java.grid(row=14, column=2, padx=(8, 0))

        row_lbl(15, self._tr("st_java_path"))
        e_java = self.entry(g, height=34, placeholder_text=self._tr("st_java_path_ph"))
        e_java.insert(0, c.get("java_path", ""))
        e_java.grid(row=15, column=1, sticky="ew", pady=4)
        b_java = self.button(
            g, self._tr("st_browse"),
            command=lambda: self._browse_file(e_java, on_change=lambda: (check_java_entry(), autosave_now())),
            primary=False, width=125, height=34,
        )
        b_java.grid(row=15, column=2, padx=(8, 0))

        java_info_lbl = self.label(g, "", 12, color="subtext", wraplength=540)
        java_info_lbl.grid(row=16, column=1, columnspan=2, sticky="w")

        def check_java_entry(*_a):
            if om_java_mode.get() != lbl_java_manual:
                self.msg(java_info_lbl, self._tr("java_auto_hint"), "subtext")
                return True
            raw_p = e_java.get().strip()
            if not raw_p:
                self.msg(java_info_lbl, self._tr("java_manual_empty"), "subtext")
                return False
            info = jvm.probe_java(raw_p)
            if info:
                self.msg(java_info_lbl, self._tr("java_probe_ok", label=info["label"]), "success")
                return True
            self.msg(java_info_lbl, self._tr("java_probe_bad"), "danger")
            return False

        def on_pick_detected(choice):
            path = detected_map.get(choice)
            if path:
                om_java_mode.set(lbl_java_manual)
                toggle_java_mode(save_after=False)
                e_java.delete(0, "end")
                e_java.insert(0, path)
                check_java_entry()
                autosave_now()

        om_detected.configure(command=on_pick_detected)

        def run_java_scan():
            btn_scan_java.configure(state="disabled")
            self.msg(java_info_lbl, self._tr("java_scanning"), "subtext")
            mc_dir_hint = e_mc.get().strip() or c.get("mc_dir", "")

            def work():
                mc_d = mc.find_minecraft_dir(mc_dir_hint)
                self.post(done, jvm.detect_java_installations(mc_d))

            def done(found):
                try:
                    if not btn_scan_java.winfo_exists():
                        return
                    btn_scan_java.configure(state="normal")
                    detected_map.clear()
                    if not found:
                        none_txt = self._tr("java_none_found")
                        om_detected.configure(values=[none_txt])
                        om_detected.set(none_txt)
                        self.msg(java_info_lbl, self._tr("java_none_hint"), "subtext")
                        return
                    labels = []
                    for idx_j, j in enumerate(found, 1):
                        folder_hint = Path(j["path"]).parent.parent.name
                        if len(folder_hint) > 22:
                            folder_hint = folder_hint[:20] + "…"
                        disp = f"{j['label']}  [{folder_hint}]"
                        if disp in detected_map:
                            disp = f"{disp} #{idx_j}"
                        detected_map[disp] = j["path"]
                        labels.append(disp)
                    om_detected.configure(values=labels)
                    om_detected.set(labels[0])
                    if om_java_mode.get() != lbl_java_manual:
                        self.msg(
                            java_info_lbl,
                            self._tr("java_found_summary", n=len(found), best=found[0]["label"]),
                            "success",
                        )
                except Exception:
                    pass

            threading.Thread(target=work, daemon=True).start()

        btn_scan_java.configure(command=run_java_scan)

        # JVM-пресеты
        row_lbl(17, self._tr("st_jvm_preset"))
        preset_row = self.frame(g, "panel")
        preset_row.grid(row=17, column=1, columnspan=2, sticky="ew", pady=4)

        def current_preset_names():
            m = dict(jvm.BUILTIN_PRESETS)
            m.update(custom_presets_draft)
            return list(m.keys())

        init_preset = c.get("jvm_preset", "G1GC")
        if init_preset not in current_preset_names():
            init_preset = "G1GC"
        preset_var = tk.StringVar(value=init_preset)
        om_preset = self.option_menu(
            preset_row, values=current_preset_names(), variable=preset_var, width=220,
            command=lambda _v: autosave_now(),
        )
        om_preset.pack(side="left")
        _disable_scroll_on_option_menu(om_preset)

        def refresh_presets(selected_name):
            vals = current_preset_names()
            om_preset.configure(values=vals)
            preset_var.set(selected_name if selected_name in vals else "G1GC")
            autosave_now()

        self.button(
            preset_row, self._tr("st_edit_presets"),
            command=lambda: self._open_presets_editor(custom_presets_draft, preset_var, refresh_presets),
            primary=False, width=230, height=32,
        ).pack(side="left", padx=(10, 0))

        row_lbl(18, self._tr("st_extra_jvm"))
        e_extra_jvm = self.entry(g, height=34, placeholder_text=self._tr("st_extra_jvm_ph"))
        e_extra_jvm.insert(0, c.get("extra_jvm_args", ""))
        e_extra_jvm.grid(row=18, column=1, columnspan=2, sticky="ew", pady=4)

        # --- Секция 3: Папки версий, окно игры и поведение ---
        section(19, self._tr("st_sec_window"))

        row_lbl(20, self._tr("st_mc_dir"))
        e_mc = self.entry(g, height=34)
        e_mc.insert(0, str(mc.find_minecraft_dir(c.get("mc_dir", ""))))
        e_mc.grid(row=20, column=1, sticky="ew", pady=4)
        self.button(
            g, self._tr("st_browse"),
            lambda: self._browse_dir(e_mc, on_change=autosave_now),
            primary=False, width=125, height=34,
        ).grid(row=20, column=2, padx=(8, 0))

        # Режим разделения версий (isolation_mode)
        row_lbl(21, self._tr("st_isolation"))
        iso_labels = {
            "none": self._tr("iso_none"),
            "family": self._tr("iso_family"),
            "version": self._tr("iso_version"),
        }
        iso_rev = {v: k for k, v in iso_labels.items()}
        om_iso = self.option_menu(g, values=list(iso_labels.values()), width=280)
        om_iso.set(iso_labels.get(c.get("isolation_mode", "family"), iso_labels["family"]))
        om_iso.grid(row=21, column=1, sticky="w", pady=4)
        _disable_scroll_on_option_menu(om_iso)

        # on_launch_action
        row_lbl(22, self._tr("st_on_launch"))
        launch_labels = {
            "keep": self._tr("launch_keep"),
            "minimize": self._tr("launch_minimize"),
            "hide": self._tr("launch_hide"),
        }
        launch_rev = {v: k for k, v in launch_labels.items()}
        om_launch = self.option_menu(g, values=list(launch_labels.values()), width=280)
        om_launch.set(launch_labels.get(c.get("on_launch_action", "keep"), launch_labels["keep"]))
        om_launch.grid(row=22, column=1, sticky="w", pady=4)
        _disable_scroll_on_option_menu(om_launch)

        # Server background toggle
        row_lbl(23, self._tr("st_server_bg"))
        use_bg = c.get("use_server_bg", True)
        sw_bg = ctk.CTkSwitch(g, text=self._tr("st_server_bg_switch"))
        self.T(sw_bg, fg_color="surface_hover", progress_color="accent", button_color="text",
               button_hover_color="accent_hover", text_color="text")
        if use_bg:
            sw_bg.select()
        sw_bg.grid(row=23, column=1, columnspan=2, sticky="w", pady=4)

        # --- Linux: GameMode & MangoHud ---
        import platform
        if platform.system().lower() == "linux":
            section(24, self._tr("st_sec_linux"))

            # GameMode
            row_lbl(25, self._tr("st_gamemode"))
            has_gm = mc.has_gamemode()
            sw_gm = ctk.CTkSwitch(g, text=self._tr("st_gamemode_on" if has_gm else "st_gamemode_off"))
            self.T(sw_gm, fg_color="surface_hover", progress_color="accent", button_color="text",
                   button_hover_color="accent_hover", text_color="text")
            if not has_gm:
                sw_gm.configure(state="disabled")
            if c.get("use_gamemode", False) and has_gm:
                sw_gm.select()
            sw_gm.grid(row=25, column=1, columnspan=2, sticky="w", pady=4)

            # MangoHud
            row_lbl(26, self._tr("st_mangohud"))
            has_mh = mc.has_mangohud()
            sw_mh = ctk.CTkSwitch(g, text=self._tr("st_mangohud_on" if has_mh else "st_mangohud_off"))
            self.T(sw_mh, fg_color="surface_hover", progress_color="accent", button_color="text",
                   button_hover_color="accent_hover", text_color="text")
            if not has_mh:
                sw_mh.configure(state="disabled")
            if c.get("use_mangohud", False) and has_mh:
                sw_mh.select()
            sw_mh.grid(row=26, column=1, columnspan=2, sticky="w", pady=4)

            linux_section_end = 26
        else:
            linux_section_end = 23

        # Режим окна игры
        row_lbl(linux_section_end + 1, self._tr("st_win_mode"))
        wm_labels = {
            "default": self._tr("win_default"),
            "fullscreen": self._tr("win_fullscreen"),
            "custom": self._tr("win_custom"),
        }
        wm_rev = {v: k for k, v in wm_labels.items()}
        om_win = self.option_menu(g, values=list(wm_labels.values()), width=230)
        om_win.set(wm_labels.get(c.get("window_mode", "default"), wm_labels["default"]))
        om_win.grid(row=linux_section_end + 1, column=1, sticky="w", pady=4)
        _disable_scroll_on_option_menu(om_win)

        row_lbl(linux_section_end + 2, self._tr("st_win_size"))
        res_row = self.frame(g, "panel")
        res_row.grid(row=linux_section_end + 2, column=1, columnspan=2, sticky="w", pady=4)
        e_w = self.entry(res_row, width=78, height=32)
        e_w.insert(0, str(c.get("window_width", 1280)))
        e_w.pack(side="left")
        self.label(res_row, "×", 14, color="subtext").pack(side="left", padx=6)
        e_h = self.entry(res_row, width=78, height=32)
        e_h.insert(0, str(c.get("window_height", 720)))
        e_h.pack(side="left", padx=(0, 10))

        for rw, rh in ((1280, 720), (1600, 900), (1920, 1080), (2560, 1440)):
            def _set_wh(w=rw, h=rh):
                if om_win.get() != wm_labels["custom"]:
                    om_win.set(wm_labels["custom"])
                    toggle_win_mode(save_after=False)
                e_w.delete(0, "end")
                e_w.insert(0, str(w))
                e_h.delete(0, "end")
                e_h.insert(0, str(h))
                autosave_now()

            self.button(
                res_row, f"{rw}×{rh}", _set_wh,
                primary=False, width=76, height=28,
                font=ctk.CTkFont(size=11),
            ).pack(side="left", padx=2)

        row_lbl(linux_section_end + 3, self._tr("st_timeout"))
        to_row = self.frame(g, "panel")
        to_row.grid(row=linux_section_end + 3, column=1, columnspan=2, sticky="w", pady=4)
        e_timeout = self.entry(to_row, width=86, height=32)
        e_timeout.insert(0, str(c.get("launch_timeout", 120)))
        e_timeout.pack(side="left")
        self.label(to_row, self._tr("st_timeout_hint"), 12, color="subtext").pack(
            side="left", padx=10)

        # --- Секция 4: Выход из аккаунта и удаление конфигов ---
        section(linux_section_end + 4, self._tr("st_sec_account"))
        acc_box = self.frame(g, "panel")
        acc_box.grid(row=linux_section_end + 5, column=0, columnspan=3, sticky="ew", pady=(2, 8))
        self.label(acc_box, self._tr("st_signout_desc"), 12, color="subtext", wraplength=620).pack(
            anchor="w", pady=(0, 8))
        self.danger_button(
            acc_box, self._tr("st_signout_btn"),
            command=self._confirm_signout_dialog,
            width=340, height=38,
        ).pack(anchor="w")

        err = self.label(g, "", 13, color="danger", wraplength=680)
        err.grid(row=linux_section_end + 6, column=0, columnspan=3, sticky="w", pady=(6, 4))

        # --- Логика переключателей и автосохранения ---
        ready_for_autosave = [False]

        # Server folder rename/reset callbacks
        def _on_rename_server_folder():
            srv = cfgmod.active_server(c)
            if not srv:
                return
            dlg = self._make_dialog(self._tr("ren_win_title"), width=520, height=280, min_w=480, min_h=260)
            card_d = self.frame(dlg, "panel", corner_radius=16)
            card_d.pack(fill="both", expand=True, padx=18, pady=18)
            bar = self.frame(card_d, "panel")
            bar.pack(side="bottom", fill="x", padx=22, pady=(10, 18))
            self.label(card_d, self._tr("ren_heading"), 20, True).pack(anchor="w", padx=22, pady=(18, 4))
            self.label(card_d, self._tr("ren_sub"), 12, color="subtext", wraplength=460).pack(anchor="w", padx=22, pady=(0, 14))
            e_new = self.entry(card_d, height=36, placeholder_text=self._tr("ren_ph"))
            e_new.insert(0, srv.get("client_folder", ""))
            e_new.pack(fill="x", padx=22, pady=(0, 6))
            msg_lbl = self.label(card_d, "", 12, color="subtext", wraplength=460)
            msg_lbl.pack(anchor="w", padx=22)

            def do_rename():
                new_name = e_new.get().strip()
                if not new_name:
                    self.msg(msg_lbl, self._tr("ren_err_bad"), "danger")
                    return
                try:
                    new_folder = cfgmod.rename_server_folder(c, srv["id"], new_name)
                    cfgmod.save(c)
                    # Refresh server list and manifest
                    rebuild_servers_dropdown()
                    self._last_manifest = cfgmod.load_cache(srv["id"])
                    self.msg(autosave_lbl, self._tr("st_saved_ok"), "success")
                    dlg.destroy()
                except ValueError as ve:
                    self.msg(msg_lbl, str(ve), "danger")
                except Exception as ex:
                    log.exception("rename failed")
                    self.msg(msg_lbl, self._tr("ren_err_io"), "danger")

            btn_ok = self.button(bar, self._tr("ren_confirm"), do_rename, width=165, height=38)
            btn_ok.pack(side="right")
            self.button(bar, self._tr("pe_cancel_btn"), dlg.destroy, primary=False, width=115, height=38).pack(side="right", padx=10)
            dlg.after(100, e_new.focus_set)
            e_new.bind("<Return>", lambda _e: do_rename())

        def _on_reset_server_folder():
            srv = cfgmod.active_server(c)
            if not srv:
                return
            try:
                new_folder = cfgmod.reset_server_folder(c, srv["id"])
                cfgmod.save(c)
                rebuild_servers_dropdown()
                self._last_manifest = cfgmod.load_cache(srv["id"])
                self.msg(autosave_lbl, self._tr("st_saved_ok"), "success")
            except Exception as ex:
                log.exception("reset folder failed")
                self.msg(err, self._tr("ren_err_io"), "danger")

        if 'btn_rename' in dir() and 'btn_reset' in dir():
            pass  # handled inline above

        def toggle_host(save_after=True):
            st = "normal" if sw_host.get() else "disabled"
            e_srv.configure(state=st)
            b_srv.configure(state=st)
            if save_after:
                autosave_now()

        def toggle_autoram(save_after=True):
            manual = not bool(sw_autoram.get())
            sl_ram.configure(state="normal" if manual else "disabled")
            e_ram.configure(state="normal" if manual else "disabled")
            if save_after:
                autosave_now()

        def toggle_java_mode(_v=None, save_after=True):
            manual = om_java_mode.get() == lbl_java_manual
            st = "normal" if manual else "disabled"
            e_java.configure(state=st)
            b_java.configure(state=st)
            check_java_entry()
            if save_after:
                autosave_now()

        def toggle_win_mode(_v=None, save_after=True):
            custom = om_win.get() == wm_labels["custom"]
            st = "normal" if custom else "disabled"
            e_w.configure(state=st)
            e_h.configure(state=st)
            if save_after:
                autosave_now()

        def on_theme_change(theme_name):
            self.apply_theme(theme_name)
            autosave_now()

        def on_lang_change(chosen_lang_lbl):
            new_lang = lang_rev.get(chosen_lang_lbl, "ru")
            if new_lang != self._lang():
                autosave_now()
                c["language"] = new_lang
                cfgmod.save(c)
                self.show("settings")

        def autosave_now(*_a):
            if not ready_for_autosave[0]:
                return
            first_error = None

            # 1. Ник (#14: строгая валидация без пробелов и спецсимволов)
            raw_nick = e_nick.get()
            ok_nick, nick_err = i18n.validate_nickname(raw_nick, lang=self._lang())
            if ok_nick:
                c["nickname"] = raw_nick
            else:
                first_error = first_error or nick_err

            # 2. Тема
            c["theme"] = om_theme.get()

            # 3. Сервер / список серверов (#12)
            raw_addr = e_host.get().strip()
            if raw_addr:
                parsed = parse_hostport(raw_addr)
                if parsed:
                    # Use update_active_server_address to preserve server ID
                    cfgmod.update_active_server_address(c, parsed[0], parsed[1])
                    cfgmod.save(c)
                    e_host.delete(0, "end")
                    e_host.insert(0, self._addr_text(parsed[0], parsed[1]))
                    rebuild_servers_dropdown()
                else:
                    first_error = first_error or self._tr("st_err_addr")

            # 4. Хост-режим + уникальность папки
            host_on = bool(sw_host.get())
            srv_dir = e_srv.get().strip()
            if host_on:
                if srv_dir and Path(srv_dir).is_dir():
                    # Validate uniqueness against other servers
                    active_id = c.get("active_server_id")
                    ok, dup_name = cfgmod.validate_unique_host_dir(c, srv_dir, exclude_server_id=active_id)
                    if not ok:
                        first_error = first_error or self._tr("st_err_host_dup", srv=dup_name)
                    else:
                        # Check if this is the sync server's own folder
                        if cfgmod.is_sync_server_own_mods_dir(c, srv_dir):
                            first_error = first_error or self._tr("st_err_host_sync_own")
                        else:
                            c["is_host"] = True
                            c["server_mods_dir"] = srv_dir
                else:
                    first_error = first_error or self._tr("st_err_host_dir")
            else:
                c["is_host"] = False
                if srv_dir:
                    c["server_mods_dir"] = srv_dir

            # 5. RAM
            auto_ram_val = bool(sw_autoram.get())
            c["auto_ram"] = auto_ram_val
            if not auto_ram_val:
                try:
                    c["ram_mb"] = max(1024, int(e_ram.get().strip()))
                except ValueError:
                    first_error = first_error or self._tr("st_err_ram")

            # 6. Java
            java_mode_val = "manual" if om_java_mode.get() == lbl_java_manual else "auto"
            if java_mode_val == "auto":
                c["java_mode"] = "auto"
            else:
                jp = e_java.get().strip()
                if jp and jvm.probe_java(jp):
                    c["java_mode"] = "manual"
                    c["java_path"] = jp
                else:
                    first_error = first_error or self._tr("st_err_java")

            # 7. JVM-пресеты и флаги
            c["jvm_preset"] = preset_var.get()
            c["custom_jvm_presets"] = dict(custom_presets_draft)
            c["extra_jvm_args"] = e_extra_jvm.get().strip()

            # 8. Папка .minecraft
            if e_mc.get().strip():
                c["mc_dir"] = e_mc.get().strip()

            # 9. isolation_mode
            c["isolation_mode"] = iso_rev.get(om_iso.get(), "family")

            # 10. on_launch_action
            c["on_launch_action"] = launch_rev.get(om_launch.get(), "keep")

            # 11. use_server_bg
            c["use_server_bg"] = bool(sw_bg.get())

            # 12. Linux: GameMode / MangoHud
            if platform.system().lower() == "linux":
                c["use_gamemode"] = bool(sw_gm.get()) if has_gm else False
                c["use_mangohud"] = bool(sw_mh.get()) if has_mh else False

            # 13. Режим окна и таймаут
            win_mode_val = wm_rev.get(om_win.get(), "default")
            c["window_mode"] = win_mode_val
            if win_mode_val == "custom":
                try:
                    c["window_width"] = max(320, int(e_w.get().strip()))
                    c["window_height"] = max(240, int(e_h.get().strip()))
                except ValueError:
                    first_error = first_error or self._tr("st_err_res")

            try:
                c["launch_timeout"] = max(0, int(e_timeout.get().strip()))
            except ValueError:
                first_error = first_error or self._tr("st_err_timeout")

            cfgmod.save(c)
            if first_error:
                self.msg(err, first_error, "danger")
                self.msg(autosave_lbl, self._tr("st_autosave_hint"), "subtext")
            else:
                self.msg(err, "", "subtext")
                self.msg(autosave_lbl, self._tr("st_saved_ok"), "success")

        # Инициализируем состояния переключателей и вешаем слушатели автосохранения
        if c["is_host"]:
            sw_host.select()
        toggle_host(save_after=False)
        sw_host.configure(command=toggle_host)

        if c.get("auto_ram", True):
            sw_autoram.select()
        toggle_autoram(save_after=False)
        sw_autoram.configure(command=toggle_autoram)

        toggle_java_mode(save_after=False)
        om_java_mode.configure(command=toggle_java_mode)

        toggle_win_mode(save_after=False)
        om_win.configure(command=toggle_win_mode)

        if platform.system().lower() == "linux":
            pass  # toggles already initialized

        om_theme.configure(command=on_theme_change)
        om_lang.configure(command=on_lang_change)

        # Bind rename/reset buttons
        if client_folder:
            btn_rename.configure(command=_on_rename_server_folder)
            btn_reset.configure(command=_on_reset_server_folder)

        for ent in (e_nick, e_host, e_srv, e_ram, e_java, e_extra_jvm, e_mc, e_w, e_h, e_timeout):
            ent.bind("<KeyRelease>", autosave_now, add="+")
            ent.bind("<FocusOut>", autosave_now, add="+")
        e_java.bind("<KeyRelease>", check_java_entry, add="+")

        ready_for_autosave[0] = True
        run_java_scan()
        return root
