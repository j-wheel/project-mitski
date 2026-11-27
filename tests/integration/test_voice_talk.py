import struct
import time
from types import SimpleNamespace as NS

import discord

from mitski.testing.fakes import settle
from mitski.voice.receive import ListeningVoiceClient

TALKING = struct.pack("<2h", 5000, 5000) * 960
SILENT = bytes(3840)


class FakeEars:
    def __init__(self, channel, sounds=None):
        self.channel = channel
        self.connected = True
        self.callback = None
        self.played = []
        self.sounds = sounds
        self.held_while_playing = None

    def listen(self, callback):
        self.callback = callback

    def stop_listening(self):
        self.callback = None

    def is_connected(self):
        return self.connected

    def is_playing(self):
        return False

    def play(self, source, after=None):
        self.played.append(source)
        if self.sounds is not None:
            self.held_while_playing = self.sounds.held
        if after is not None:
            after(None)

    def stop(self):
        pass

    async def disconnect(self, force=False):
        self.connected = False


def in_vc(world, *people, heard="", spoken=None):
    app = world.app
    app.cfg.VOICE_MODE = "voice"
    app.cfg.VOICE_SPEAK_CHIME = 0.0
    channel = NS(id=555, name="hangout", guild=world.guild, voice_states={p.id: object() for p in (world.her, *people)})
    ears = FakeEars(channel, app.voice.sounds)
    app.voice.vc = ears
    app.voice.talk.attach(ears)
    app.voice.talk.ticker.cancel()
    calls = NS(heard=[], spoken=spoken if spoken is not None else [])

    async def transcribe(audio):
        calls.heard.append(len(audio))
        return heard() if callable(heard) else heard

    async def synth(payload):
        calls.spoken.append(payload)
        return bytes(48000 * 4)

    app.voice.talk._transcribe = transcribe
    app.voice.talk._synth = synth
    return ears, calls


async def speak(world, user, seconds=0.8):
    talk = world.app.voice.talk
    for _ in range(int(seconds / 0.02)):
        talk._frame(user.id, TALKING)
    talk._frame(user.id, SILENT)
    talk.flush(time.monotonic() + 5)
    await settle(world.app)


async def test_she_answers_what_she_hears_out_loud(world):
    anna = world.people["anna"]
    ears, calls = in_vc(world, anna, heard="mitski how was class")
    world.replies.append("so long ngl lol")
    await speak(world, anna)
    assert calls.heard and calls.spoken[0]["text"] == "so long not gonna lie"
    assert len(ears.played) == 1 and isinstance(ears.played[0], discord.PCMAudio)
    assert "anna: mitski how was class" in world.prompts[-1]
    assert "voice call" in world.prompts[-1]
    said = [line for who, _, line, _ in world.app.voice.talk.transcript if who is None]
    assert said == ["so long not gonna lie"]


async def test_typing_sounds_hold_off_while_she_talks(world):
    anna = world.people["anna"]
    ears, _ = in_vc(world, anna, heard="mitski u there")
    world.replies.append("yeah im here")
    await speak(world, anna)
    assert ears.held_while_playing is True
    assert world.app.voice.sounds.held is False


async def test_people_she_ignores_arent_listened_to(world):
    anna = world.people["anna"]
    _, calls = in_vc(world, anna, heard="mitski hi")
    world.app.cfg.ignored.add(anna.id)
    await speak(world, anna)
    assert calls.heard == [] and world.prompts == []


async def test_a_short_noise_isnt_sent_off_to_be_heard(world):
    anna = world.people["anna"]
    _, calls = in_vc(world, anna, heard="mitski hi")
    await speak(world, anna, seconds=0.1)
    assert calls.heard == []


async def test_whisper_junk_from_silence_is_dropped(world):
    anna = world.people["anna"]
    _, calls = in_vc(world, anna, heard="Thank you.")
    await speak(world, anna)
    assert calls.heard and world.prompts == [] and calls.spoken == []


async def test_her_own_voice_coming_back_through_a_mic_is_ignored(world):
    anna = world.people["anna"]
    _, calls = in_vc(world, anna, heard="i was literally just at the library all day")
    world.app.voice.talk.transcript.append((None, "mitski", "i was literally just at the library all day", time.time()))
    await speak(world, anna)
    assert world.prompts == [] and calls.spoken == []


async def test_with_a_few_people_she_only_answers_when_its_for_her(world):
    anna, bob = world.people["anna"], world.people["bob"]
    lines = iter(["did u see the game last night", "mitski did u see it"])
    _, calls = in_vc(world, anna, bob, heard=lambda: next(lines))
    world.replies.append("no i missed it")
    await speak(world, bob)
    assert world.prompts == []
    await speak(world, anna)
    assert len(world.prompts) == 1 and "bob: did u see the game last night" in world.prompts[0]
    assert calls.spoken[0]["text"] == "no i missed it"


async def test_one_on_one_she_answers_without_being_named(world):
    anna = world.people["anna"]
    _, calls = in_vc(world, anna, heard="what are you up to")
    world.replies.append("just doing homework")
    await speak(world, anna)
    assert calls.spoken[0]["text"] == "just doing homework"


async def test_she_doesnt_do_the_work_out_loud_either(world):
    anna = world.people["anna"]
    _, calls = in_vc(world, anna, heard="mitski give me a cake recipe")
    world.replies.extend(["1 cup butter, 2 cups sugar, 3 eggs", "1 cup butter, 2 cups sugar, 3 eggs"])
    await speak(world, anna)
    assert calls.spoken == []


async def test_the_text_chat_knows_shes_talking_and_what_was_said(world):
    anna = world.people["anna"]
    in_vc(world, anna, heard="mitski the exam got moved to friday")
    world.replies.append("wait fr")
    world.app.voice.session = NS(call=False, guild=world.guild.id, minutes=3)
    await speak(world, anna)
    note = world.app.voice.note(world.guild, lambda u: u.name)
    assert "with your voice" in note and "anna: mitski the exam got moved to friday" in note
    world.app.voice.talk.detach()
    note = world.app.voice.note(world.guild, lambda u: u.name)
    assert "You don't talk in vc" in note


async def test_she_connects_with_ears_only_when_speaking_is_on(world):
    talk = world.app.voice.talk
    world.app.cfg.VOICE_MODE = "typing"
    assert talk.client_class() is discord.VoiceClient
    world.app.cfg.VOICE_MODE = "voice"
    assert talk.client_class() is ListeningVoiceClient


async def test_leaving_stops_listening(world):
    anna = world.people["anna"]
    ears, _ = in_vc(world, anna)
    world.app.voice.session = NS(call=False, guild=world.guild.id, minutes=3)
    await world.app.voice.leave("test")
    assert ears.callback is None and world.app.voice.talk.vc is None


async def test_decision_note_matches_whether_she_talks(world):
    voice = world.app.voice
    voice.decisions[1] = "join"
    world.app.cfg.VOICE_MODE = "typing"
    assert "You don't talk in vc" in voice.decision_note(1)
    world.app.cfg.VOICE_MODE = "voice"
    assert "You talk in vc" in voice.decision_note(1)


async def test_off_loads_nothing_and_never_joins(world, monkeypatch):
    voice = world.app.voice
    world.app.cfg.VOICE_MODE = "off"
    loaded = []
    monkeypatch.setattr(voice.sounds, "load", lambda: loaded.append(1))
    voice.check()
    assert loaded == [] and not voice.active and not voice.can_join() and voice.status() == "off"
    assert not voice.talk.on


async def test_typing_mode_joins_without_ears(world):
    world.app.cfg.VOICE_MODE = "typing"
    assert world.app.voice.on and not world.app.voice.talk.on
    assert world.app.voice.talk.client_class() is discord.VoiceClient
