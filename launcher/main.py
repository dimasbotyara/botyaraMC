"""botyaraMC - точка входа. Запуск: python main.py"""
import logging

import config


def main():
    logging.basicConfig(
        filename=str(config.config_dir() / "launcher.log"),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        encoding="utf-8",
    )
    from ui import App
    App().mainloop()


if __name__ == "__main__":
    main()
