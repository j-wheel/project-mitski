import argparse
import asyncio
import sys

import aiohttp
import discord

from mitski.app import App
from mitski.config import ConfigError, Settings
from mitski.core import logs
from mitski.paths import Paths


def parse(argv=None):
    p = argparse.ArgumentParser(prog="mitski")
    p.add_argument(
        "--voice", choices=("voice", "typing", "off"), help="VOICE_MODE for this run, instead of the one in mitski.yaml"
    )
    return p.parse_args(argv)


def main():
    args = parse()
    paths = Paths.discover()
    try:
        cfg = Settings.load(paths)
    except ConfigError as e:
        sys.exit(str(e))
    if not cfg.TOKEN:
        sys.exit(f"TOKEN is empty, put your discord token in {paths.keys}")
    logs.setup(cfg.LOG_LEVEL)
    if args.voice:
        cfg.VOICE_MODE = args.voice
        logs.get("mitski").info("VOICE_MODE %s for this run (--voice)", args.voice)
    try:
        asyncio.run(App(cfg).run())
    except discord.LoginFailure:
        sys.exit(f"discord didn't accept the token in {paths.keys}, it may have changed (log in again and copy it)")
    except (aiohttp.ClientConnectionError, OSError) as e:
        sys.exit(f"couldn't reach discord ({e}), check your connection")
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
