from types import SimpleNamespace as NS

import discord

from mitski.social.blocking import means_block
from mitski.testing.fakes import FakeDM, FakeMessage, FakeRelationship, settle


def emoji(text, custom=False):
    return NS(name=text, id=1, is_custom_emoji=lambda: custom, __str__=lambda self=None: text)


def reaction(world, msg, user, text):
    return NS(
        message_id=msg.id,
        user_id=user.id,
        channel_id=msg.channel.id,
        guild_id=getattr(msg.channel.guild, "id", None),
        emoji=emoji(text),
        message_author_id=world.her.id,
    )


async def her_message(world, text="i just failed my exam lmao"):
    world.replies.append(text)
    await world.send(world.people["anna"], "mitski how did it go")
    return next(m for m in reversed(world.client.sent) if m.content == text)


# reactions


async def test_she_knows_who_reacted_to_what(world):
    mine = await her_message(world)
    await world.app.client.handlers["on_raw_reaction_add"](reaction(world, mine, world.people["bob"], "😭"))
    world.replies.append("bob stop laughing")
    await world.send(world.people["anna"], "mitski u ok?")
    assert 'bob 😭 on "i just failed my exam lmao"' in world.prompts[-1]


async def test_a_taken_back_reaction_is_forgotten(world):
    mine = await her_message(world)
    payload = reaction(world, mine, world.people["bob"], "😭")
    await world.app.client.handlers["on_raw_reaction_add"](payload)
    await world.app.client.handlers["on_raw_reaction_remove"](payload)
    assert world.app.reacted.note(world.channel.id) == ""


async def test_reactions_change_her_mood_a_little(world):
    mine = await her_message(world)
    feelings = world.app.feelings
    before = feelings.mood.level("amused")
    await world.app.client.handlers["on_raw_reaction_add"](reaction(world, mine, world.people["bob"], "💀"))
    assert feelings.mood.level("amused") > before
    irritated = feelings.mood.level("irritated")
    await world.app.client.handlers["on_raw_reaction_add"](reaction(world, mine, world.people["bob"], "🤡"))
    assert feelings.mood.level("irritated") > irritated


async def test_ignored_people_and_her_own_reactions_dont_count(world):
    mine = await her_message(world)
    world.app.cfg.ignored.add(world.people["bob"].id)
    assert not world.app.reacted.added(reaction(world, mine, world.people["bob"], "😭"))
    assert not world.app.reacted.added(reaction(world, mine, world.her, "😭"))


async def test_reactions_to_other_peoples_messages_arent_hers(world):
    theirs = FakeMessage(world.channel, world.people["anna"], "lol")
    assert not world.app.reacted.added(reaction(world, theirs, world.people["bob"], "😭"))


# blocking


def test_what_counts_as_meaning_it():
    for line in ["ok im blocking u", "ur blocked", "blocked.", "ima block you now", "bye ur so blocked"]:
        assert means_block([line]), line
    for line in [
        "if u say that again im blocking u",
        "i would block u lol",
        "jk im not blocking u",
        "dont make me block u",
        "i blocked my ex lol",
    ]:
        assert not means_block([line]), line


async def test_saying_shes_blocking_someone_blocks_them(world):
    bob = world.people["bob"]
    world.replies.append("ok im blocking u")
    await world.send(bob, "mitski ur so ugly and annoying")
    await settle(world.app)
    assert getattr(bob, "blocked", False) and bob.id in world.app.cfg.ignored
    before = len(world.client.sent)
    world.replies.append("should not be sent")
    await world.send(bob, "mitski hello??")
    assert len(world.client.sent) == before


async def test_a_conditional_threat_isnt_a_block(world):
    bob = world.people["bob"]
    world.replies.append("if u say that again im blocking u")
    await world.send(bob, "mitski ur annoying")
    await settle(world.app)
    assert not getattr(bob, "blocked", False) and bob.id not in world.app.cfg.ignored


async def test_her_owner_is_never_blocked(world):
    world.replies.append("ur blocked lol")
    await world.send(world.owner, "mitski hi")
    await settle(world.app)
    assert not getattr(world.owner, "blocked", False) and world.owner.id not in world.app.cfg.ignored


async def test_it_can_be_turned_off(world):
    world.app.cfg.BLOCKING = False
    bob = world.people["bob"]
    world.replies.append("ok im blocking u")
    await world.send(bob, "mitski ur annoying")
    await settle(world.app)
    assert not getattr(bob, "blocked", False)


async def test_people_blocked_by_hand_are_ignored_too(world):
    anna = world.people["anna"]
    FakeRelationship(world.client, anna, discord.RelationshipType.blocked)
    world.app.blocking.sync()
    assert anna.id in world.app.cfg.ignored
    before = len(world.client.sent)
    await world.send(anna, "mitski hey")
    assert len(world.client.sent) == before


async def test_unblocked_by_hand_shes_back(world):
    anna = world.people["anna"]
    rel = FakeRelationship(world.client, anna, discord.RelationshipType.blocked)
    world.app.blocking.relationship(rel)
    await world.app.client.handlers["on_relationship_remove"](rel)
    assert anna.id not in world.app.cfg.ignored


async def test_block_commands(world):
    bob = world.people["bob"]
    prefix = world.app.cfg.COMMAND_PREFIX
    await world.app.router.route(FakeMessage(world.channel, world.owner, f"{prefix}block {bob.id}"))
    await settle(world.app)
    assert bob.blocked and bob.id in world.app.cfg.ignored
    await world.app.router.route(FakeMessage(world.channel, world.owner, f"{prefix}blocked"))
    await settle(world.app)
    assert str(bob.id) in world.client.sent[-1].content
    await world.app.router.route(FakeMessage(world.channel, world.owner, f"{prefix}unblock {bob.id}"))
    await settle(world.app)
    assert not bob.blocked and bob.id not in world.app.cfg.ignored


async def test_blocked_in_dms_too(world):
    bob = world.people["bob"]
    dm = FakeDM(world.client, bob)
    world.replies.append("blocked")
    await world.app.router.route(FakeMessage(dm, bob, "send me ur pics"))
    await settle(world.app)
    assert getattr(bob, "blocked", False)
