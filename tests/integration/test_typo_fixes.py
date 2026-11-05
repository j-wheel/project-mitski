from mitski.chat import typos


def typo_prone(world, fix=1.0, star=0.0):
    world.app.cfg.TYPO_CHANCE = 1.0
    world.app.cfg.TYPO_FIX_CHANCE = fix
    world.app.cfg.TYPO_STAR_CHANCE = star
    world.app.cfg.TYPO_FIX_DELAY = [0, 0]


async def test_sometimes_she_corrects_it_with_a_star_instead(world):
    typo_prone(world, star=1.0)
    line = "honestly the lecture was boring today"
    world.replies.append(line)
    await world.send(world.people["anna"], "mitski how was uni")
    first, correction = world.client.sent
    assert first.content != line and not getattr(first, "edits", [])
    word = correction.content.strip("*")
    assert correction.content in (f"*{word}", f"{word}*") and word in line.split()
    assert typos.fix(first.content, first.content.split()[line.split().index(word)], word) == line


async def test_no_star_for_an_older_message_she_edits_that_one(world, monkeypatch):
    typo_prone(world, star=1.0)
    sender = world.app.sender
    real = sender._fix_typo

    async def after_she_said_more(msg, typo, delay):
        sender.last_sent[msg.channel.id] = -1
        await real(msg, typo, delay)

    monkeypatch.setattr(sender, "_fix_typo", after_she_said_more)
    world.replies.append("honestly the lecture was boring today")
    await world.send(world.people["anna"], "mitski how was uni")
    [msg] = world.client.sent
    assert msg.content == "honestly the lecture was boring today" and len(msg.edits) == 1


async def test_no_correction_once_shes_gone_quiet(world, monkeypatch):
    typo_prone(world, star=1.0)
    monkeypatch.setattr(world.app.away, "is_quiet", lambda gid: True)
    world.replies.append("honestly the lecture was boring today")
    await world.send(world.people["anna"], "mitski how was uni")
    sent = world.client.sent
    assert len(sent) <= 1 and not any(getattr(m, "edits", []) for m in sent)


async def test_she_sometimes_typos_and_edits_it_right_after(world):
    typo_prone(world)
    world.replies.append("honestly the lecture was boring today")
    await world.send(world.people["anna"], "mitski how was uni")
    [msg] = world.client.sent
    assert msg.content == "honestly the lecture was boring today"
    assert len(msg.edits) == 1 and msg.edits[0] != msg.content
    assert len(msg.edits[0].split()) == len(msg.content.split())


async def test_sometimes_she_just_leaves_it(world):
    typo_prone(world, fix=0.0)
    world.replies.append("honestly the lecture was boring today")
    await world.send(world.people["anna"], "mitski how was uni")
    [msg] = world.client.sent
    assert msg.content != "honestly the lecture was boring today"
    assert not getattr(msg, "edits", [])


async def test_no_typos_when_its_off(world):
    world.replies.append("honestly the lecture was boring today")
    await world.send(world.people["anna"], "mitski how was uni")
    assert world.sent_text() == ["honestly the lecture was boring today"]


async def test_a_typo_never_lands_in_a_short_reply(world):
    typo_prone(world)
    world.replies.append("ya lol")
    await world.send(world.people["bob"], "mitski u there")
    assert world.sent_text() == ["ya lol"]
    assert typos.add_typo("ya lol", __import__("random").Random(1))[1] is None
