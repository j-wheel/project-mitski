import argparse
import asyncio
import subprocess
import sys

RELOAD_EXIT = 3


def parse(argv=None):
    p = argparse.ArgumentParser(prog="mitski")
    p.add_argument(
        "--voice", choices=("voice", "typing", "off"), help="VOICE_MODE for this run, instead of the one in mitski.yaml"
    )
    p.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    return p.parse_args(argv)


def supervise(argv):
    cmd = [sys.executable, "-m", "mitski", "--child", *argv]
    while True:
        proc = subprocess.Popen(cmd)
        while True:
            try:
                code = proc.wait()
                break
            except KeyboardInterrupt:
                continue
        if code != RELOAD_EXIT:
            return code
        print("reloading mitski...", flush=True)


def run():
    import aiohttp
    import discord

    from mitski.app import App
    from mitski.config import ConfigError, Settings
    from mitski.core import logs
    from mitski.paths import Paths

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
    app = App(cfg)
    try:
        asyncio.run(app.run())
    except discord.LoginFailure:
        sys.exit(f"discord didn't accept the token in {paths.keys}, it may have changed (log in again and copy it)")
    except (aiohttp.ClientConnectionError, OSError) as e:
        sys.exit(f"couldn't reach discord ({e}), check your connection")
    except KeyboardInterrupt:
        pass
    if app.reload_requested:
        sys.exit(RELOAD_EXIT)


def main():
    args = parse()
    if not args.child:
        sys.exit(supervise(sys.argv[1:]))
    run()


if __name__ == "__main__":
    main()
