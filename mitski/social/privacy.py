from mitski.chat.patterns import NO_PINGS
from mitski.config import ConfigError
from mitski.core import logs
from mitski.core.component import Component

log = logs.get("privacy")

FORGET = {"!forgetme", "!forget me"}
REMEMBER = {"!rememberme", "!remember me"}
FORGOT = "done, i forgot what i knew about u and i won't remember new stuff. `!rememberme` if u change ur mind"
REMEMBERING = "ok, i'll remember stuff about u again"
ALREADY_REMEMBERING = "i wasn't forgetting u, nothing changed"


class PrivacyCommands(Component):
    def wants(self, msg):
        text = (msg.content or "").strip().lower()
        return text in FORGET or text in REMEMBER

    async def handle(self, msg):
        text = msg.content.strip().lower()
        uid = msg.author.id
        reply = self.forget_me(uid) if text in FORGET else self.remember_me(uid)
        try:
            self.cfg.save_list("MEMORY_OPTOUT", sorted(self.cfg.memory_optout))
        except (OSError, ValueError, ConfigError):
            log.warning("couldn't save MEMORY_OPTOUT to the config", exc_info=True)
        await self.memory.flush()
        await msg.reply(reply, mention_author=False, allowed_mentions=NO_PINGS)
        log.info("%s used %s", msg.author, text)

    def forget_me(self, uid):
        self.cfg.memory_optout.add(uid)
        self.memory.forget(uid)
        self.state.forget_user(uid)
        return FORGOT

    def remember_me(self, uid):
        if uid not in self.cfg.memory_optout:
            return ALREADY_REMEMBERING
        self.cfg.memory_optout.discard(uid)
        return REMEMBERING
