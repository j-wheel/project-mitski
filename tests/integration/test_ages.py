import time

from mitski.social.ages import AgeGuard
from mitski.testing.fakes import FakeProfile, FakeRole


def remembered_age(world, user):
    d = world.app.memory.people.get(str(user.id))
    return world.app.memory.current_age(d) if d else None


async def test_an_age_role_makes_her_treat_them_as_a_minor(world):
    world.app.cfg.MEMORY = True
    world.app.memory.enabled = True
    anna = world.people["anna"]
    anna.roles = [FakeRole("@everyone", default=True), FakeRole("15")]
    world.channel.nsfw = True
    world.replies.extend(["hehe send nudes", "anyway hi"])
    await world.send(anna, "mitski hiii")
    assert world.app.ages.is_minor(anna)
    assert remembered_age(world, anna) == 15
    assert world.app.memory.people[str(anna.id)]["slots"]["age"]["src"] == "said"
    assert "a minor" in world.prompts[0]
    assert world.sent_text() == ["anyway hi"]


async def test_a_bio_is_read_once_when_she_replies(world):
    bob = world.people["bob"]
    lookups = []

    async def profile():
        lookups.append(1)
        return FakeProfile(bio="he/him | 16 | val")

    bob.profile = profile
    world.replies.extend(["yo", "sup"])
    await world.send(bob, "mitski yo")
    await world.send(bob, "mitski again")
    assert lookups == [1]
    assert world.app.ages.is_minor(bob)
    assert world.app.ages.describe(bob) == "16"


async def test_bio_lookups_respect_the_hourly_limit(world):
    world.app.cfg.AGE_CHECK_BIOS_PER_HOUR = 0
    bob = world.people["bob"]
    calls = []

    async def profile():
        calls.append(1)
        return FakeProfile()

    bob.profile = profile
    world.replies.append("yo")
    await world.send(bob, "mitski yo")
    assert calls == []


async def test_removing_the_role_clears_that_flag(world):
    anna = world.people["anna"]
    anna.roles = [FakeRole("minor")]
    world.app.ages.check_member(anna)
    assert world.app.ages.is_minor(anna)
    anna.roles = [FakeRole("member")]
    world.app.ages.check_member(anna)
    assert not world.app.ages.is_minor(anna)


async def test_a_stated_adult_age_does_not_override_a_minor_flag(world):
    world.app.cfg.MEMORY = True
    world.app.memory.enabled = True
    anna = world.people["anna"]
    memory = world.app.memory
    memory.touch(anna, "hi")
    memory.people[str(anna.id)]["slots"]["age"] = {"v": 22, "t": time.time(), "src": "said"}
    anna.roles = [FakeRole("14")]
    world.app.ages.check_member(anna)
    assert world.app.ages.is_minor(anna)


async def test_flags_persist_and_work_without_memory(world):
    anna = world.people["anna"]
    anna.display_name = "anna [15]"
    world.app.ages.check_member(anna)
    again = AgeGuard(world.app)
    again.load()
    assert again.is_minor(anna)
    assert world.app.memory.people == {}


async def test_known_minors_in_the_channel_block_explicit_lines_in_any_message(world):
    anna = world.people["anna"]
    anna.roles = [FakeRole("13-15")]
    world.channel.nsfw = True
    await world.app.router.route(world.say(anna, "lol", to_her=False))
    sent = await world.app.sender.send(world.channel, ["send nudes", "ok"])
    assert [m.content for m in sent] == ["ok"]
