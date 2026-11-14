"""botyaraMC - точка входа. GUI: python main.py | CLI: python main.py --play --nick Steve"""
import logging
import logging.handlers
import sys

import config


def _setup_logging():
    """Ротация launcher.log (иначе растёт бесконечно) + безопасный фолбэк,
    если папка конфигов недоступна для записи."""
    try:
        cfg_dir = config.config_dir()
        handler = logging.handlers.RotatingFileHandler(
            cfg_dir / "launcher.log",
            maxBytes=2 * 1024 * 1024,  # 2 МБ достаточно для диагностики
            backupCount=2,
            encoding="utf-8",
        )
    except OSError:
        handler = logging.StreamHandler(sys.stderr)
    logging.basicConfig(
        handlers=[handler],
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def main():
    _setup_logging()

    if len(sys.argv) > 1:
        import cli
        args = cli.build_parser().parse_args()
        if args.play or args.sync_only or args.detect_java:
            raise SystemExit(cli.run_cli(args))
        if args.lang:
            print("botyaraMC: --lang applies to CLI mode; "
                  "for headless use add --play / --sync-only / --detect-java. Opening GUI…")

    # Встроенные шрифты (Inter / JetBrains Mono) — строго до создания Tk,
    # чтобы fontconfig на Linux увидел их при первой инициализации.
    import fonts
    fonts.ensure_loaded()

    from ui import App
    App().mainloop()


if __name__ == "__main__":
    main()
