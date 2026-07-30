from __future__ import annotations

import argparse
import logging
import multiprocessing as mp
from pathlib import Path

from .config import CONFIG_NAME, ConfigError, StartupConfig
from .watcher import watch


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="doc2md-watch",
        description="Recursively watch folders and create revisioned document conversions.",
    )
    parser.add_argument(
        "folders",
        nargs="*",
        type=Path,
        help="root folders to watch (the GUI prompts when omitted)",
    )
    parser.add_argument(
        "--initial",
        action="store_true",
        help="convert supported files already present before watching",
    )
    parser.add_argument(
        "--settle-seconds",
        type=float,
        default=1.0,
        metavar="SECONDS",
        help="wait after the last file event before converting (default: 1.0)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="enable debug logging")
    parser.add_argument(
        "--gui",
        action="store_true",
        help="show a compact always-on-top status dashboard",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config_path = Path.cwd() / CONFIG_NAME
    config_exists = config_path.is_file()
    if config_exists:
        try:
            startup = StartupConfig.load(config_path)
        except ConfigError as exc:
            raise SystemExit(str(exc)) from exc
    else:
        if args.settle_seconds < 0:
            raise SystemExit("--settle-seconds must be zero or greater")
        startup = StartupConfig(
            folders=args.folders,
            initial=args.initial,
            settle_seconds=args.settle_seconds,
            gui=args.gui,
            verbose=args.verbose,
        )

    if not startup.folders and not startup.gui:
        raise SystemExit("at least one folder is required unless GUI mode is enabled")
    logging.basicConfig(
        level=logging.DEBUG if startup.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    if startup.gui:
        from .dashboard import choose_watch_folder, run_dashboard

        if not startup.folders:
            selected = choose_watch_folder()
            if selected is None:
                return 0
            startup.folders = [selected]
        if not config_exists:
            startup.save(config_path)
        run_dashboard(startup.folders, startup.settle_seconds, startup.initial)
    else:
        if not config_exists:
            startup.save(config_path)
        watch(startup.folders, startup.settle_seconds, startup.initial)
    return 0


if __name__ == "__main__":
    mp.freeze_support()
    raise SystemExit(main())
