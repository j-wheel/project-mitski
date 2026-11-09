from pathlib import Path

from mitski.admin import printchat
from mitski.testing.fakes import FakeDM, FakeMessage, settle


def setup(world, monkeypatch, pdf_bytes=b"%PDF-1.4 fake", too_big=False):
    anna, owner = world.people["anna"], world.owner
    anna_dm = FakeDM(world.client, anna)
    owner.dm_channel = FakeDM(world.client, owner)
    world.client.private_channels.extend([anna_dm, owner.dm_channel])
    FakeMessage(anna_dm, anna, "heyyy")
    FakeMessage(anna_dm, world.client.user, "hiii")
    printed = []

    async def render(browser, page, workdir):
        printed.append(page)
        pdf = Path(workdir) / "chat.pdf"
        pdf.write_bytes(pdf_bytes)
        return pdf

    async def render_image(browser, page, workdir):
        printed.append(page)
        png = Path(workdir) / "chat.png"
        png.write_bytes(b"\x89PNG fake")
        return png

    monkeypatch.setattr(printchat, "render_pdf", render)
    monkeypatch.setattr(printchat, "render_png", render_image)
    monkeypatch.setattr(printchat, "find_browser", lambda configured="": "chrome")
    if too_big:
        monkeypatch.setattr(printchat, "FREE_UPLOAD", 1)
    return anna_dm, owner.dm_channel, printed


async def command(world, channel, text):
    await world.app.router.route(FakeMessage(channel, world.owner, f"{world.app.cfg.COMMAND_PREFIX}{text}"))
    await settle(world.app)


def files_in(world, channel):
    return [m for m in world.client.sent if m.channel is channel and getattr(m, "file", None) is not None]


async def test_printchat_sends_her_owner_the_dm_as_a_pdf(world, monkeypatch):
    _anna_dm, owner_dm, printed = setup(world, monkeypatch)
    await command(world, owner_dm, "pc anna")
    [sent] = files_in(world, owner_dm)
    assert sent.file.filename.startswith("dm-anna-") and sent.file.filename.endswith(".pdf")
    assert "2 messages" in sent.content
    assert "heyyy" in printed[0] and "hiii" in printed[0]


async def test_it_works_with_a_dm_channel_id_too(world, monkeypatch):
    anna_dm, owner_dm, _ = setup(world, monkeypatch)
    await command(world, owner_dm, f"printchat {anna_dm.id}")
    assert files_in(world, owner_dm)


async def test_the_pdf_goes_to_the_channel_the_command_was_used_in(world, monkeypatch):
    _anna_dm, owner_dm, _ = setup(world, monkeypatch)
    await command(world, world.channel, "pc anna")
    assert files_in(world, world.channel) and not files_in(world, owner_dm)


async def test_png_flag_sends_one_long_image(world, monkeypatch):
    _anna_dm, owner_dm, printed = setup(world, monkeypatch)
    await command(world, owner_dm, "pc --png anna")
    [sent] = files_in(world, owner_dm)
    assert sent.file.filename.startswith("dm-anna-") and sent.file.filename.endswith(".png")
    assert "heyyy" in printed[0]


async def test_pdf_flag_is_the_same_as_no_flag(world, monkeypatch):
    _anna_dm, owner_dm, _ = setup(world, monkeypatch)
    await command(world, owner_dm, "pc --pdf anna")
    await command(world, owner_dm, "pc anna")
    assert [m.file.filename[-4:] for m in files_in(world, owner_dm)] == [".pdf", ".pdf"]


async def test_the_flag_can_come_after_the_id(world, monkeypatch):
    anna_dm, owner_dm, _ = setup(world, monkeypatch)
    await command(world, owner_dm, f"pc {anna_dm.id} --PNG")
    [sent] = files_in(world, owner_dm)
    assert sent.file.filename.endswith(".png")


async def test_a_flag_with_nobody_to_print_gets_the_usage(world, monkeypatch):
    _anna_dm, owner_dm, printed = setup(world, monkeypatch)
    await command(world, owner_dm, "pc --png")
    assert printed == [] and not files_in(world, owner_dm)
    assert any("usage:" in m.content and "--png" in m.content for m in world.client.sent)


async def test_a_chat_too_long_for_one_image_says_to_use_pdf(world, monkeypatch):
    _anna_dm, owner_dm, _ = setup(world, monkeypatch)

    async def too_tall(browser, page, workdir):
        raise printchat.TooTall("that chat is too long for one image (200000 px tall), use --pdf instead")

    monkeypatch.setattr(printchat, "render_png", too_tall)
    await command(world, owner_dm, "pc --png anna")
    assert not files_in(world, owner_dm)
    assert any("couldn't print it" in m.content and "use --pdf instead" in m.content for m in world.client.sent)


async def test_a_png_too_big_for_discord_is_saved_as_a_png(world, monkeypatch):
    _anna_dm, owner_dm, printed = setup(world, monkeypatch, too_big=True)
    await command(world, owner_dm, "pc --png anna")
    assert not files_in(world, owner_dm) and len(printed) == 2
    assert list((world.app.cfg.paths.data / "exports").glob("dm-anna-*.png"))


async def test_someone_she_has_no_dm_with(world, monkeypatch):
    _anna_dm, owner_dm, _ = setup(world, monkeypatch)
    await command(world, owner_dm, "pc nobody")
    assert not files_in(world, owner_dm)
    assert any("doesn't have a dm with" in m.content for m in world.client.sent)


async def test_too_big_even_without_pictures_is_saved_instead(world, monkeypatch):
    _anna_dm, owner_dm, printed = setup(world, monkeypatch, too_big=True)
    await command(world, owner_dm, "pc anna")
    assert not files_in(world, owner_dm) and len(printed) == 2
    saved = list((world.app.cfg.paths.data / "exports").glob("dm-anna-*.pdf"))
    assert saved and any("too big for discord" in m.content for m in world.client.sent)


async def test_no_browser_to_print_with(world, monkeypatch):
    _anna_dm, owner_dm, _ = setup(world, monkeypatch)
    monkeypatch.setattr(printchat, "find_browser", lambda configured="": None)
    await command(world, owner_dm, "pc anna")
    assert any("no chrome or edge found" in m.content for m in world.client.sent)


async def test_only_her_owner_can_use_it(world, monkeypatch):
    _anna_dm, _owner_dm, printed = setup(world, monkeypatch)
    bob_dm = FakeDM(world.client, world.people["bob"])
    world.replies.append("huh")
    await world.app.router.route(FakeMessage(bob_dm, world.people["bob"], f"{world.app.cfg.COMMAND_PREFIX}pc anna"))
    await settle(world.app)
    assert printed == [] and not any(getattr(m, "file", None) for m in world.client.sent)
