from mitski.config import ConfigError
from mitski.core import logs
from mitski.core.component import Component

log = logs.get("privacy")

FORGOT = "done, i forgot what i knew about u and i won't remember new stuff. `{prefix}rememberme` if u change ur mind"
REMEMBERING = "ok, i'll remember stuff about u again"
ALREADY_REMEMBERING = "i wasn't forgetting u, nothing changed"


class PrivacyCommands(Component):
    async def forget_me(self, uid):
        self.cfg.memory_optout.add(uid)
        self.memory.forget(uid)
        self.state.forget_user(uid)
        await self._save()
        log.info("%s used forgetme", uid)
        return FORGOT.format(prefix=self.cfg.COMMAND_PREFIX)

    async def remember_me(self, uid):
        known = uid in self.cfg.memory_optout
        self.cfg.memory_optout.discard(uid)
        await self._save()
        log.info("%s used rememberme", uid)
        return REMEMBERING if known else ALREADY_REMEMBERING

    async def _save(self):
        try:
            self.cfg.save_list("MEMORY_OPTOUT", sorted(self.cfg.memory_optout))
        except (OSError, ValueError, ConfigError):
            log.warning("couldn't save MEMORY_OPTOUT to the config", exc_info=True)
        await self.memory.flush()
