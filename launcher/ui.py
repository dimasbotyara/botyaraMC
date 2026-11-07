"""Интерфейс botyaraMC: мастер первого запуска, главное окно, настройки."""
import logging
import queue
import re
import threading
import tkinter as tk
from functools import partial
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

import config as cfgmod
import discovery
import mc
import sync
import themes

log = logging.getLogger("botyaraMC.ui")
NICK_RE = re.compile(r"^[A-Za-z0-9_]{3,16}$")
DEFAULT_PORT = 25456


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
        self.cfg = cfgmod.load()
        if self.cfg["theme"] not in themes.THEMES:
            self.cfg["theme"] = themes.DEFAULT
        self.theme = themes.THEMES[self.cfg["theme"]]
        ctk.set_appearance_mode(self.theme["mode"])
        super().__init__()
        self.title("botyaraMC")
        self.geometry("800x620")
        self.minsize(740, 580)
        self.configure(fg_color=self.theme["bg"])

        self._reg = {}            # виджет -> {опция: ключ палитры}
        self._q = queue.Queue()   # сообщения из потоков в UI
        self.view = None
        self.playing = False
        self._status, self._prog = "", 0.0
        self._force = False
        self.draft = {"nick": self.cfg["nickname"], "theme": self.cfg["theme"],
                      "host": self._addr_text()}
        self.after(60, self._pump)
        self.show("main" if self.cfg["setup_done"] else "wizard")

    # ------------------------------------------------------------ темы
    def T(self, w, **opts):
        """Регистрирует виджет: opts = {опция_ctk: ключ_палитры}. Перекрашивается вживую."""
        self._reg.setdefault(w, {}).update(opts)
        w.configure(**{k: self.theme[v] for k, v in opts.items()})
        return w

    def apply_theme(self, name):
        self.theme = themes.THEMES[name]
        ctk.set_appearance_mode(self.theme["mode"])
        self.configure(fg_color=self.theme["bg"])
        for w, opts in list(self._reg.items()):
            try:
                w.configure(**{k: self.theme[v] for k, v in opts.items()})
            except Exception:
                self._reg.pop(w, None)

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
        if self.view is not None:
            self.view.destroy()
        self.view = getattr(self, "_view_" + name)(*a)
        self.view.pack(fill="both", expand=True)

    def frame(self, parent, key="bg", **kw):
        kw.setdefault("corner_radius", 0)
        return self.T(ctk.CTkFrame(parent, **kw), fg_color=key)

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

    def entry(self, parent, **kw):
        return self.T(ctk.CTkEntry(parent, corner_radius=8, **kw), fg_color="surface",
                      border_color="border", text_color="text",
                      placeholder_text_color="subtext")

    def _addr_text(self):
        h, p = self.cfg.get("sync_host", ""), self.cfg.get("sync_port", DEFAULT_PORT)
        return "" if not h else (h if p == DEFAULT_PORT else f"{h}:{p}")

    def _browse(self, entry):
        path = filedialog.askdirectory()
        if path:
            entry.configure(state="normal")
            entry.delete(0, "end")
            entry.insert(0, path)

    def _autofind(self, entry, lbl, btn):
        btn.configure(state="disabled")
        self.msg(lbl, "Ищем сервер в сети… 🔍")

        def work():
            self.post(done, discovery.discover(3.0))

        def done(res):
            btn.configure(state="normal")
            if res:
                host, port = res
                entry.delete(0, "end")
                entry.insert(0, host if port == DEFAULT_PORT else f"{host}:{port}")
                self.msg(lbl, f"Нашли сервер: {host} 🎉", "success")
            else:
                self.msg(lbl, "Не нашли 😕 Включён Radmin VPN? Можно вписать IP руками.", "danger")

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
                    sync.fetch_manifest(host, port)
                    self.post(done, True)
                except Exception:
                    log.exception("проверка сервера не прошла")
                    self.post(done, False)

            def done(ok):
                fin.configure(state="normal")
                if ok:
                    self._finish_setup(host, port)
                else:
                    self._force = True
                    fin.configure(text="Сохранить так 💾")
                    self.msg(m, "Сервер не отвечает 😕 Проверь IP и Radmin VPN. "
                                "Можно сохранить как есть и поправить позже.", "danger")

            threading.Thread(target=work, daemon=True).start()

        fin = self._nav(card, lambda: self.show("wizard", 2), "Готово 🚀", finish)

    def _finish_setup(self, host, port):
        c = self.cfg
        c.update(nickname=self.draft["nick"], theme=self.draft["theme"], sync_host=host,
                 sync_port=port, setup_done=True,
                 mc_dir=str(mc.find_minecraft_dir(c.get("mc_dir", ""))))
        cfgmod.save(c)
        self.show("main")

    # ------------------------------------------------------------ главное окно
    def _view_main(self):
        root = self.frame(self, "bg")
        top = self.frame(root, "bg")
        top.pack(fill="x", padx=20, pady=(16, 0))
        self.button(top, "⚙ Настройки", lambda: self.show("settings"), primary=False,
                    width=130, height=34).pack(side="right")
        if self.cfg["is_host"]:
            self.label(top, "👑 режим хоста", 13, color="subtext").pack(side="left")
        center = self.frame(root, "bg")
        center.pack(expand=True)
        self.label(center, "botyaraMC", 56, True, "accent").pack()
        self.label(center, f"Привет, {self.cfg['nickname']}! 👋", 18, color="subtext").pack(
            pady=(0, 28))
        self.play_btn = self.button(center, "▶  ИГРАТЬ", self.on_play, width=320, height=66,
                                    font=ctk.CTkFont(size=22, weight="bold"))
        self.play_btn.pack()
        if self.playing:
            self.play_btn.configure(state="disabled")
        self.progress = ctk.CTkProgressBar(center, width=380)
        self.T(self.progress, fg_color="surface", progress_color="accent")
        self.progress.set(self._prog)
        self.progress.pack(pady=(26, 8))
        self.status_lbl = self.label(center, self._status, 14, color="subtext")
        self.status_lbl.pack()
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

    def _play_done(self):
        self.playing = False
        try:
            self.play_btn.configure(state="normal")
        except Exception:
            pass

    def on_play(self):
        if self.playing:
            return
        self.playing = True
        self.play_btn.configure(state="disabled")
        threading.Thread(target=self._play_worker, daemon=True).start()

    def _play_worker(self):
        P = self.post
        try:
            cfg = self.cfg
            host, port = cfg["sync_host"], cfg["sync_port"]
            P(self._set_status, "Подключаемся… 🔌")
            P(self._set_progress, 0.02)
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
            else:
                manifest = cfgmod.load_cache()
            if manifest is None:
                P(self._set_status, "Сервер недоступен 😕 Проверь Radmin VPN и адрес в настройках.")
                return

            mc_dir = mc.find_minecraft_dir(cfg.get("mc_dir", ""))
            P(self._set_status, "Готовим игру… ✨")
            if live:
                targets = [mc_dir / "mods"]
                if cfg["is_host"] and cfg["server_mods_dir"]:
                    targets.append(Path(cfg["server_mods_dir"]))
                ok = sync.sync(host, port, manifest["mods"], targets,
                               lambda f: P(self._set_progress, 0.05 + f * 0.35))
                if not ok:
                    log.warning("синхронизация прошла не полностью")
            vid = mc.ensure_version(mc_dir, manifest["mc_version"], manifest["loader"],
                                    lambda f: P(self._set_progress, 0.4 + f * 0.5))
            P(self._set_status, "Запускаем… 🚀")
            P(self._set_progress, 0.95)
            srv = manifest.get("server") or {}
            proc = mc.launch(mc_dir, vid, cfg["nickname"], srv.get("host"), srv.get("port"),
                             cfg["ram_mb"], cfgmod.config_dir() / "game.log")
            P(self._set_progress, 1.0)
            P(self._set_status, "Игра запущена! Удачного геймплея 🎮")
            proc.wait()
            P(self._set_status, "Игра закрыта. Заходи ещё! 😊")
            P(self._set_progress, 0.0)
        except Exception:
            log.exception("запуск не удался")
            P(self._set_status, "Что-то пошло не так 😕 (подробности в launcher.log)")
        finally:
            P(self._play_done)

    # ------------------------------------------------------------ настройки
    def _view_settings(self):
        c = self.cfg
        root = self.frame(self, "bg")
        card = self.frame(root, "panel", corner_radius=18)
        card.pack(fill="both", expand=True, padx=24, pady=24)
        self.label(card, "⚙ Настройки", 26, True).pack(anchor="w", padx=26, pady=(20, 8))
        g = self.frame(card, "panel")
        g.pack(fill="x", padx=26)
        g.grid_columnconfigure(1, weight=1)

        def row(r, text):
            self.label(g, text, color="subtext").grid(row=r, column=0, sticky="w",
                                                      pady=8, padx=(0, 18))

        row(0, "Ник")
        e_nick = self.entry(g, height=34)
        e_nick.insert(0, c["nickname"])
        e_nick.grid(row=0, column=1, columnspan=2, sticky="ew")

        row(1, "Тема")
        om = ctk.CTkOptionMenu(g, values=themes.THEME_NAMES, command=self.apply_theme)
        self.T(om, fg_color="surface", button_color="surface_hover",
               button_hover_color="border", text_color="text", dropdown_fg_color="surface",
               dropdown_hover_color="surface_hover", dropdown_text_color="text")
        om.set(c["theme"])
        om.grid(row=1, column=1, columnspan=2, sticky="w")

        row(2, "Сервер синхронизации")
        e_host = self.entry(g, height=34)
        e_host.insert(0, self._addr_text())
        e_host.grid(row=2, column=1, sticky="ew")
        m_host = self.label(g, "", 12, color="subtext")
        find = self.button(g, "🔍 Найти", primary=False, width=90, height=34)
        find.configure(command=lambda: self._autofind(e_host, m_host, find))
        find.grid(row=2, column=2, padx=(8, 0))
        m_host.grid(row=3, column=1, columnspan=2, sticky="w")

        row(4, "Память (RAM)")
        ram_lbl = self.label(g, f"{c['ram_mb']} МБ", color="text")
        sl = ctk.CTkSlider(g, from_=1024, to=16384, number_of_steps=30,
                           command=lambda v: ram_lbl.configure(text=f"{int(v)} МБ"))
        self.T(sl, fg_color="surface", progress_color="accent", button_color="accent",
               button_hover_color="accent_hover")
        sl.set(c["ram_mb"])
        sl.grid(row=4, column=1, sticky="ew")
        ram_lbl.grid(row=4, column=2, padx=(8, 0))

        row(5, "Папка .minecraft")
        e_mc = self.entry(g, height=34)
        e_mc.insert(0, str(mc.find_minecraft_dir(c.get("mc_dir", ""))))
        e_mc.grid(row=5, column=1, sticky="ew")
        self.button(g, "Обзор…", lambda: self._browse(e_mc), primary=False,
                    width=90, height=34).grid(row=5, column=2, padx=(8, 0))

        row(6, "Режим хоста")
        sw = ctk.CTkSwitch(g, text="я хост! 👑")
        self.T(sw, fg_color="surface_hover", progress_color="accent", button_color="text",
               button_hover_color="accent_hover", text_color="text")
        sw.grid(row=6, column=1, sticky="w")

        row(7, "Папка модов сервера")
        e_srv = self.entry(g, height=34, placeholder_text="путь к mods у Minecraft-сервера")
        e_srv.insert(0, c["server_mods_dir"])
        e_srv.grid(row=7, column=1, sticky="ew")
        b_srv = self.button(g, "Обзор…", lambda: self._browse(e_srv), primary=False,
                            width=90, height=34)
        b_srv.grid(row=7, column=2, padx=(8, 0))

        def toggle():
            state = "normal" if sw.get() else "disabled"
            e_srv.configure(state=state)
            b_srv.configure(state=state)

        sw.configure(command=toggle)
        if c["is_host"]:
            sw.select()
        toggle()

        err = self.label(card, "", 13, color="danger")
        err.pack(anchor="w", padx=26, pady=(10, 0))

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
            srv_dir = e_srv.get().strip() if sw.get() else c["server_mods_dir"]
            if sw.get() and not Path(srv_dir).is_dir():
                return self.msg(err, "Для режима хоста укажи существующую папку модов сервера", "danger")
            c.update(nickname=nick, theme=om.get(), sync_host=parsed[0], sync_port=parsed[1],
                     ram_mb=int(sl.get()), mc_dir=e_mc.get().strip(), is_host=bool(sw.get()),
                     server_mods_dir=srv_dir)
            cfgmod.save(c)
            self.show("main")

        bar = self.frame(card, "panel")
        bar.pack(side="bottom", fill="x", padx=26, pady=20)
        self.button(bar, "Сохранить 💾", save, width=160, height=40).pack(side="right")
        self.button(bar, "Отмена", cancel, primary=False, width=110, height=40).pack(side="right",
                                                                                    padx=10)
        return root
