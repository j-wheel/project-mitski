from types import SimpleNamespace

import discord

from mitski.testing.fakes import FakeRelationship, FakeUser, settle


async def arrives(world, relationship):
    await world.client.handlers["on_relationship_add"](relationship)
    await settle(world.app)


async def test_she_accepts_a_friend_request(world):
    request = FakeRelationship(world.client, world.people["anna"])
    await arrives(world, request)
    assert request.accepted == 1


async def test_a_request_from_someone_she_already_knew_of_comes_as_an_update(world):
    request = FakeRelationship(world.client, world.people["anna"])
    await world.client.handlers["on_relationship_update"](None, request)
    await settle(world.app)
    assert request.accepted == 1


async def test_requests_sent_while_she_was_offline(world):
    one = FakeRelationship(world.client, world.people["anna"])
    two = FakeRelationship(world.client, world.people["bob"])
    world.app.dms.accept_pending()
    await settle(world.app)
    assert one.accepted == two.accepted == 1


async def test_only_incoming_requests(world):
    friend = FakeRelationship(world.client, world.people["anna"], discord.RelationshipType.friend)
    blocked = FakeRelationship(world.client, world.people["bob"], discord.RelationshipType.blocked)
    world.app.dms.accept_pending()
    await settle(world.app)
    assert friend.accepted == blocked.accepted == 0


async def test_ignored_users_and_bots_are_left_alone(world):
    anna = world.people["anna"]
    world.app.cfg.ignored.add(anna.id)
    ignored = FakeRelationship(world.client, anna)
    bot = FakeRelationship(world.client, FakeUser("somebot", bot=True))
    world.app.dms.accept_pending()
    await settle(world.app)
    assert ignored.accepted == bot.accepted == 0


async def test_someone_she_knows_is_a_minor_is_left_alone(world, monkeypatch):
    anna = world.people["anna"]
    monkeypatch.setattr(world.app.ages, "is_minor", lambda user: user.id == anna.id)
    minor = FakeRelationship(world.client, anna)
    await arrives(world, minor)
    assert minor.accepted == 0


async def test_it_can_be_turned_off(world):
    world.app.cfg.FRIEND_ACCEPT = False
    request = FakeRelationship(world.client, world.people["anna"])
    await arrives(world, request)
    assert request.accepted == 0


async def test_the_same_request_is_only_accepted_once(world):
    request = FakeRelationship(world.client, world.people["anna"])
    world.app.dms.friend_request(request)
    world.app.dms.friend_request(request)
    await settle(world.app)
    assert request.accepted == 1


async def test_a_request_cancelled_before_she_gets_to_it(world):
    request = FakeRelationship(world.client, world.people["anna"])
    world.app.dms.friend_request(request)
    world.client.relationships.remove(request)
    await settle(world.app)
    assert request.accepted == 0


def captcha():
    data = {"captcha_key": ["captcha-required"], "captcha_service": "hcaptcha", "captcha_sitekey": "key"}
    return discord.CaptchaRequired(SimpleNamespace(status=400, reason="Bad Request"), data)


async def test_a_captcha_skips_that_request_until_she_restarts(world):
    bad = FakeRelationship(world.client, world.people["anna"], fails=captcha())
    good = FakeRelationship(world.client, world.people["bob"])
    world.app.dms.accept_pending()
    await settle(world.app)
    assert bad.accepted == 0 and good.accepted == 1

    bad.fails = None
    world.app.dms.accept_pending()
    await world.client.handlers["on_relationship_update"](None, bad)
    await settle(world.app)
    assert bad.accepted == 0


async def test_another_kind_of_failure_is_tried_again_next_time_she_connects(world):
    error = discord.HTTPException(SimpleNamespace(status=500, reason="oops"), "server error")
    request = FakeRelationship(world.client, world.people["anna"], fails=error)
    world.app.dms.accept_pending()
    await settle(world.app)
    request.fails = None
    world.app.dms.accept_pending()
    await settle(world.app)
    assert request.accepted == 1


async def test_a_failed_accept_does_not_hold_up_the_next_one(world):
    error = discord.HTTPException(SimpleNamespace(status=400, reason="captcha"), "captcha required")
    bad = FakeRelationship(world.client, world.people["anna"], fails=error)
    good = FakeRelationship(world.client, world.people["bob"])
    world.app.dms.accept_pending()
    await settle(world.app)
    assert bad.accepted == 0 and good.accepted == 1
    assert world.people["anna"].id not in world.app.dms.friend_requests
