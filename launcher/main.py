"""botyaraMC - точка входа. GUI: python main.py | CLI: python main.py --play --nick Steve"""
import logging
import sys

import config


def main():
    logging.basicConfig(
        filename=str(config.config_dir() / "launcher.log"),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        encoding="utf-8",
    )

    if len(sys.argv) > 1:
        import cli
        args = cli.build_parser().parse_args()
        if args.play or args.sync_only or args.detect_java:
            raise SystemExit(cli.run_cli(args))

    from ui import App
    App().mainloop()


if __name__ == "__main__":
    main()
