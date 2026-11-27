from types import SimpleNamespace as NS

from mitski.testing.fakes import FakeDM, FakeMessage, settle
from mitski.voice import service
from mitski.voice.session import Session


class FakeVoiceClient:
    def __init__(self, channel):
        self.channel = channel
        self.connected = True
        self.played = 0

    def is_connected(self):
        return self.connected

    def is_playing(self):
        return False

    def play(self, source, after=None):
        self.played += 1

    def stop(self):
        pass

    async def disconnect(self, force=False):
        self.connected = False


class FakeCall:
    def __init__(self, channel, ringing, people, initiator):
        self.channel = channel
        self.ringing = list(ringing)
        self.voice_states = {u.id: object() for u in people}
        self.initiator = initiator
        self.vc = None

    async def connect(self, timeout=30, reconnect=True, cls=None):
        self.vc = FakeVoiceClient(self.channel)
        return self.vc

    async def ring(self, *who):
        raise AssertionError("she must never ring anyone")


def calling(world, caller, ringing_her=True, name=None):
    world.app.cfg.VOICE_MODE = "typing"
    dm = FakeDM(world.client, caller)
    channel = NS(id=dm.id, name=name, recipient=caller)
    call = FakeCall(channel, [world.client.user] if ringing_her else [], [caller], caller)
    channel.call = call
    return dm, call


async def test_she_picks_up_when_someone_calls_her(world):
    anna = world.people["anna"]
    dm, call = calling(world, anna)
    world.app.voice.call_changed(call)
    await settle(world.app)
    voice = world.app.voice
    assert call.vc is not None and voice.vc is call.vc and voice.session.call
    assert voice.sounds.guild == dm.id and voice.sounds.everywhere


async def test_a_call_that_isnt_ringing_her_is_left_alone(world):
    _dm, call = calling(world, world.people["anna"], ringing_her=False)
    world.app.voice.call_changed(call)
    await settle(world.app)
    assert call.vc is None and world.app.voice.vc is None


async def test_calls_from_people_she_ignores_ring_out(world):
    anna = world.people["anna"]
    world.app.cfg.ignored.add(anna.id)
    _dm, call = calling(world, anna)
    world.app.voice.call_changed(call)
    await settle(world.app)
    assert call.vc is None


async def test_calls_off_means_she_never_picks_up(world):
    _dm, call = calling(world, world.people["anna"])
    world.app.cfg.VOICE_CALLS = False
    world.app.voice.call_changed(call)
    await settle(world.app)
    assert call.vc is None


async def test_if_it_stops_ringing_before_she_gets_there_she_doesnt_join(world):
    anna = world.people["anna"]
    _dm, call = calling(world, anna)
    call.channel.call = FakeCall(call.channel, [], [anna], anna)
    world.app.voice.call_changed(call)
    await settle(world.app)
    assert call.vc is None and world.app.voice.vc is None


async def test_she_hangs_up_when_the_call_ends(world):
    _dm, call = calling(world, world.people["anna"])
    voice = world.app.voice
    voice.call_changed(call)
    await settle(world.app)
    vc = voice.vc
    voice.call_ended(call)
    await settle(world.app)
    assert not vc.connected and voice.vc is None


async def test_she_hangs_up_once_everyone_else_has(world, monkeypatch):
    monkeypatch.setattr(service, "CALL_ALONE_WAIT", (0, 0))
    _dm, call = calling(world, world.people["anna"])
    voice = world.app.voice
    voice.call_changed(call)
    await settle(world.app)
    vc = voice.vc
    call.voice_states = {}
    await voice._maybe_leave()
    await settle(world.app)
    assert not vc.connected and voice.vc is None


async def test_someone_still_in_the_call_keeps_her_there(world, monkeypatch):
    monkeypatch.setattr(service, "CALL_ALONE_WAIT", (0, 0))
    _dm, call = calling(world, world.people["anna"])
    voice = world.app.voice
    voice.call_changed(call)
    await settle(world.app)
    await voice._maybe_leave()
    assert voice.vc is not None


async def test_she_leaves_a_server_vc_to_take_a_call(world):
    voice = world.app.voice
    server_vc = FakeVoiceClient(NS(name="general vc", guild=world.guild))
    voice.vc = server_vc
    voice.session = Session(world.guild.id, 0, "x", False, 1)
    _dm, call = calling(world, world.people["anna"])
    voice.call_changed(call)
    await settle(world.app)
    assert not server_vc.connected and voice.vc is call.vc and voice.session.call


async def test_in_a_call_her_typing_sounds_play_whenever_she_types(world, monkeypatch):
    dm, call = calling(world, world.people["anna"])
    voice = world.app.voice
    voice.call_changed(call)
    await settle(world.app)
    played = []
    monkeypatch.setattr(voice.sounds, "_play", lambda: played.append(1))
    async with voice.typing_in(world.channel):
        pass
    async with voice.typing_in(dm):
        pass
    assert len(played) == 2


async def test_anyone_in_the_call_can_ask_her_to_hang_up(world):
    world.app.cfg.VOICE_ASKED_CHANCE = 1.0
    owner = world.people["anna"]
    dm, call = calling(world, owner)
    voice = world.app.voice
    voice.call_changed(call)
    await settle(world.app)
    vc = voice.vc
    world.replies.append("ok byee")
    await world.app.router.route(FakeMessage(dm, owner, "ok u can hang up now"))
    await settle(world.app)
    assert not vc.connected and voice.vc is None


async def test_in_the_call_dm_she_knows_shes_in_the_call(world):
    anna = world.people["anna"]
    dm, call = calling(world, anna)
    world.app.voice.call_changed(call)
    await settle(world.app)
    world.replies.append("hii")
    await world.app.router.route(FakeMessage(dm, anna, "hiii can u hear me"))
    await settle(world.app)
    assert "You're in a call with anna here" in world.prompts[-1]
