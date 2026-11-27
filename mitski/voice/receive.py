import contextlib
import struct

import discord
import nacl.secret
from discord.voice_state import VoiceConnectionState

from mitski.core import logs

try:
    import davey
except ImportError:
    davey = None

log = logs.get("voice")

SPEAKING = 5
CLIENT_DISCONNECT = 13
OPUS = 120
SILENCE = b"\xf8\xff\xfe"
RTPSIZE = ("aead_xchacha20_poly1305_rtpsize",)


class ListeningVoiceClient(discord.VoiceClient):
    def __init__(self, client, channel):
        self.ssrcs = {}
        self.on_audio = None
        self.decoders = {}
        self.listening = False
        self.failures = 0
        super().__init__(client, channel)

    def create_connection_state(self):
        return VoiceConnectionState(self, hook=self._voice_event)

    async def _voice_event(self, ws, msg):
        op, data = msg.get("op"), msg.get("d") or {}
        if op == SPEAKING and "ssrc" in data and "user_id" in data:
            self.ssrcs[int(data["ssrc"])] = int(data["user_id"])
        elif op == CLIENT_DISCONNECT and "user_id" in data:
            gone = int(data["user_id"])
            for ssrc in [s for s, u in self.ssrcs.items() if u == gone]:
                self.ssrcs.pop(ssrc, None)
                self.decoders.pop(ssrc, None)

    def listen(self, callback):
        self.on_audio = callback
        if not self.listening:
            self._connection.add_socket_listener(self._packet)
            self.listening = True

    def stop_listening(self):
        if self.listening:
            with contextlib.suppress(Exception):
                self._connection.remove_socket_listener(self._packet)
        self.listening = False
        self.on_audio = None

    def _packet(self, data):
        callback = self.on_audio
        if callback is None:
            return
        try:
            got = self.decode(data)
        except Exception as e:
            self.failures += 1
            if self.failures in (1, 50, 500):
                log.info("couldn't read a voice packet (%s), %d so far", e, self.failures)
            return
        if got is not None:
            callback(*got)

    def decode(self, data):
        if len(data) < 16 or data[0] >> 6 != 2 or 200 <= data[1] <= 204 or data[1] & 0x7F != OPUS:
            return None
        ssrc = struct.unpack_from(">I", data, 8)[0]
        user_id = self.ssrcs.get(ssrc)
        if user_id is None:
            return None
        opus = self._open(data)
        if opus is None:
            return None
        opus = self._undave(user_id, opus)
        if opus is None or opus == SILENCE:
            return None
        decoder = self.decoders.get(ssrc)
        if decoder is None:
            decoder = self.decoders[ssrc] = discord.opus.Decoder()
        return user_id, decoder.decode(opus, fec=False)

    def _open(self, data):
        key, mode = bytes(self.secret_key), self.mode
        extended, csrcs = data[0] & 0x10, data[0] & 0x0F
        start = 12 + 4 * csrcs
        if mode in RTPSIZE:
            head = start + (4 if extended else 0)
            nonce = data[-4:] + bytes(20)
            plain = nacl.secret.Aead(key).decrypt(bytes(data[head:-4]), bytes(data[:head]), nonce)
            if extended:
                words = struct.unpack_from(">H", data, head - 2)[0]
                plain = plain[4 * words :]
            return plain
        box = nacl.secret.SecretBox(key)
        if mode == "xsalsa20_poly1305_lite":
            plain = box.decrypt(bytes(data[12:-4]), data[-4:] + bytes(20))
        elif mode == "xsalsa20_poly1305_suffix":
            plain = box.decrypt(bytes(data[12:-24]), bytes(data[-24:]))
        elif mode == "xsalsa20_poly1305":
            plain = box.decrypt(bytes(data[12:]), bytes(data[:12]) + bytes(12))
        else:
            return None
        if extended and len(plain) >= 4:
            words = struct.unpack_from(">H", plain, 2)[0]
            plain = plain[4 + 4 * words :]
        return plain

    def _undave(self, user_id, opus):
        state = self._connection
        session = getattr(state, "dave_session", None)
        if davey is None or session is None or not getattr(state, "dave_protocol_version", 0) or not session.ready:
            return opus
        try:
            return session.decrypt(user_id, davey.MediaType.audio, opus)
        except Exception:
            try:
                return opus if session.can_passthrough(user_id) else None
            except Exception:
                return None
