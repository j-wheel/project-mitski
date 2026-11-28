import io
import time
from types import SimpleNamespace as NS

import yaml
from PIL import Image, PngImagePlugin

from mitski import __main__ as entry
from mitski.testing.fakes import FakeChannel, FakeMessage, settle


def png(w=800, h=900, text=None):
    info = PngImagePlugin.PngInfo()
    for k, v in (text or {}).items():
        info.add_text(k, v)
    out = io.BytesIO()
    Image.new("RGB", (w, h), (90, 60, 120)).save(out, "PNG", pnginfo=info)
    return out.getvalue()


def setup(world, files, results=None):
    app = world.app
    app.cfg.AVATAR_CHARACTER_NAME = "onikata kayoko"
    app.cfg.AVATAR_CHARACTER_SOURCE = "blue archive"
    edits = []

    async def edit(**kwargs):
        edits.append(kwargs)
        world.her.avatar = NS(key=f"a{len(edits)}")
        return world.her

    async def images(query, n=40):
        app.queries = [*getattr(app, "queries", []), query]
        return (
            results
            if results is not None
            else [
                {
                    "url": f"https://i.pximg.net/{i}.png",
                    "page": f"https://www.pixiv.net/artworks/{i}",
                    "title": "kayoko",
                }
                for i in range(len(files))
            ]
        )

    async def download(url):
        return files[int(url.rsplit("/", 1)[1].split(".")[0])]

    world.her.edit = edit
    world.her.avatar = None
    app.search.images = images
    app.self_profile._download = download
    app.self_profile.load()
    return edits


async def test_she_changes_to_fan_art_of_her_character_and_knows_it(world):
    edits = setup(world, [png()])
    out = await world.app.self_profile.change("testing")
    assert out.startswith("changed it to onikata kayoko")
    assert len(edits) == 1 and Image.open(io.BytesIO(edits[0]["avatar"])).size == (512, 512)
    assert '"onikata kayoko" blue archive fanart -ai' in world.app.queries[0]
    data = world.app.self_profile.data
    assert data["avatar_character"] == "onikata kayoko" and data["next_at"] > time.time()
    note = world.app.self_profile.note() if data.get("read_at") else ""
    assert note == ""
    data["read_at"], data["name"], data["username"] = time.time(), "mitski", "mitski"
    assert "fan art of onikata kayoko from blue archive" in world.app.profiles.own_status()


async def test_ai_made_pictures_are_skipped_by_their_metadata(world):
    ai = png(text={"parameters": "1girl, kayoko, Steps: 30, Sampler: DPM++ 2M"})
    edits = setup(world, [ai, png()])
    await world.app.self_profile.change("testing")
    assert len(edits) == 1
    assert world.app.self_profile.data["avatar_url"].endswith("/1.png")


async def test_nothing_usable_tries_again_in_an_hour(world):
    edits = setup(world, [png(100, 100)])
    out = await world.app.self_profile.change("testing")
    assert "couldn't find" in out and not edits
    assert world.app.self_profile.data["next_at"] - time.time() < 3700


async def test_forcing_it_again_right_away_waits_for_discord(world):
    setup(world, [png(), png()])
    await world.app.self_profile.change("asked to", forced=True)
    out = await world.app.self_profile.change("asked to", forced=True)
    assert "try again in" in out


async def test_no_character_means_no_change(world):
    edits = setup(world, [png()])
    world.app.cfg.AVATAR_CHARACTER_NAME = ""
    out = await world.app.self_profile.change("testing")
    assert "no character set" in out and not edits


async def test_she_reads_her_own_profile(world):
    async def profile(**kwargs):
        return NS(bio="just a girl who loves roblox", metadata=NS(pronouns="she/her", banner=None))

    world.her.profile = profile
    world.her.avatar = None
    world.app.self_profile.load()
    await world.app.self_profile.refresh()
    note = world.app.self_profile.note()
    assert 'your bio says "just a girl who loves roblox"' in note
    assert "pronouns she/her" in note and "default profile picture" in note


async def command(world, text):
    channel = FakeChannel(world.client, world.guild, "her-log")
    msg = FakeMessage(channel, world.owner, text)
    await world.app.router.route(msg)
    await settle(world.app)
    return channel.messages[-1].content


def saved(world, key):
    return yaml.safe_load(world.app.cfg.paths.config.read_text(encoding="utf-8")).get(key)


async def test_pfp_commands_set_the_character_interval_and_switch(world):
    world.app.self_profile.load()
    out = await command(world, "!pfp char onikata kayoko | blue archive")
    assert "onikata kayoko from blue archive" in out
    assert saved(world, "AVATAR_CHARACTER_NAME") == "onikata kayoko"
    assert saved(world, "AVATAR_CHARACTER_SOURCE") == "blue archive"
    await command(world, "!pfp every 12 36")
    assert saved(world, "AVATAR_EVERY_H") == [12, 36]
    await command(world, "!pfp on")
    assert saved(world, "AVATAR_AUTO") is True and world.app.self_profile.data["next_at"] > time.time()
    out = await command(world, "!pfp")
    assert "every 12 to 36h" in out


async def test_pfp_now_changes_it(world):
    edits = setup(world, [png()])
    out = await command(world, "!pfp now")
    assert out.startswith("changed it to onikata kayoko") and len(edits) == 1


async def test_reload_restarts_her(world, monkeypatch):
    closed = []

    async def close():
        closed.append(1)

    world.client.close = close
    out = await command(world, "!reload")
    assert "reloading" in out and world.app.reload_requested
    world.app.reload_soon(0)


def test_the_supervisor_restarts_her_after_a_reload(monkeypatch):
    codes = iter([entry.RELOAD_EXIT, entry.RELOAD_EXIT, 0])
    runs = []

    class Proc:
        def __init__(self, cmd):
            runs.append(cmd)

        def wait(self):
            return next(codes)

    monkeypatch.setattr(entry.subprocess, "Popen", Proc)
    assert entry.supervise(["--voice=off"]) == 0
    assert len(runs) == 3 and runs[0][-2:] == ["--child", "--voice=off"]
