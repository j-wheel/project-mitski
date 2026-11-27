import asyncio
import struct
from types import SimpleNamespace as NS

import nacl.secret
import nacl.utils

from mitski.voice.receive import ListeningVoiceClient
from mitski.voice.talk import loud, mono, spoken

KEY = nacl.utils.random(32)
OPUS = b"\x78\x01\x02\x03opus frame"


def client(mode="aead_xchacha20_poly1305_rtpsize", dave=None):
    vc = object.__new__(ListeningVoiceClient)
    vc.ssrcs, vc.decoders, vc.listening, vc.on_audio, vc.failures = {}, {}, False, None, 0
    vc._connection = NS(mode=mode, secret_key=list(KEY), dave_session=dave, dave_protocol_version=1 if dave else 0)
    return vc


def header(ssrc=7, extended=False, payload=120):
    head = bytearray(12)
    head[0] = 0x90 if extended else 0x80
    head[1] = payload
    struct.pack_into(">H", head, 2, 1)
    struct.pack_into(">I", head, 4, 960)
    struct.pack_into(">I", head, 8, ssrc)
    return bytes(head)


def rtpsize_packet(opus=OPUS, extended=False, ssrc=7):
    head = header(ssrc, extended)
    body = opus
    if extended:
        head += b"\xbe\xde" + struct.pack(">H", 1)
        body = b"\x10\xaa\x00\x00" + opus
    nonce = struct.pack(">I", 5) + bytes(20)
    sealed = nacl.secret.Aead(KEY).encrypt(body, head, nonce).ciphertext
    return head + sealed + nonce[:4]


def test_rtpsize_packets_open_to_the_opus_frame():
    assert client()._open(rtpsize_packet()) == OPUS


def test_the_header_extension_is_stripped_after_opening():
    assert client()._open(rtpsize_packet(extended=True)) == OPUS


def test_xsalsa_lite_packets_open_too():
    vc = client("xsalsa20_poly1305_lite")
    nonce = struct.pack(">I", 3) + bytes(20)
    packet = header() + nacl.secret.SecretBox(KEY).encrypt(OPUS, nonce).ciphertext + nonce[:4]
    assert vc._open(packet) == OPUS


def test_packets_from_unknown_speakers_and_rtcp_are_skipped():
    vc = client()
    assert vc.decode(rtpsize_packet(ssrc=99)) is None
    rtcp = bytearray(rtpsize_packet())
    rtcp[1] = 200
    assert vc.decode(bytes(rtcp)) is None


def test_speaking_events_map_ssrcs_to_people_and_disconnects_forget_them():
    vc = client()
    asyncio.run(vc._voice_event(None, {"op": 5, "d": {"ssrc": 7, "user_id": "42", "speaking": 1}}))
    assert vc.ssrcs == {7: 42}
    asyncio.run(vc._voice_event(None, {"op": 13, "d": {"user_id": "42"}}))
    assert vc.ssrcs == {}


def test_dave_frames_are_decrypted_per_person():
    seen = []

    class Session:
        ready = True

        def decrypt(self, user_id, media, frame):
            seen.append(user_id)
            return b"plain"

        def can_passthrough(self, user_id):
            return False

    assert client(dave=Session())._undave(42, b"sealed") == b"plain"
    assert seen == [42]


def test_without_dave_frames_pass_straight_through():
    assert client()._undave(42, OPUS) == OPUS


def test_a_bad_packet_is_counted_not_raised():
    vc = client()
    vc.ssrcs[7] = 42
    got = []
    vc.on_audio = lambda *a: got.append(a)
    vc._packet(rtpsize_packet()[:-6] + b"broken")
    assert vc.failures == 1 and got == []


def test_stereo_is_folded_to_mono_and_loudness_is_measured():
    quiet = struct.pack("<4h", 10, 10, -10, -10)
    talking = struct.pack("<4h", 4000, 2000, -4000, -2000)
    assert struct.unpack("<2h", mono(talking)) == (3000, -3000)
    assert not loud(quiet) and loud(talking)


def test_what_she_says_is_cleaned_up_for_speaking():
    assert spoken(["idk tbh lol", "ur so funny 😭"]) == "i don't know to be honest your so funny"
    assert spoken(["AHAHAHAHA no way"]) == "haha no way"
    assert spoken(["noooooo <:pepe:123> https://x.com/a"]) == "noo"
    assert spoken(["lol"]) == ""


def test_voice_mode_reads_yaml_off_as_off(make_cfg):
    assert make_cfg(VOICE_MODE=False).VOICE_MODE == "off"
    assert make_cfg(VOICE_MODE="Voice").VOICE_MODE == "voice"
    assert make_cfg(VOICE_MODE="loud").VOICE_MODE == "typing"
    assert make_cfg().VOICE_MODE == "typing"
