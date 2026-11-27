from mitski.config import ConfigError
from mitski.core import logs
from mitski.core.component import Component
from mitski.core.texts import fill, wording

log = logs.get("privacy")

FORGOT = wording("chat.privacy_forgot")
REMEMBERING = wording("chat.privacy_remembering")
ALREADY_REMEMBERING = wording("chat.privacy_already")


class PrivacyCommands(Component):
    async def forget_me(self, uid):
        self.cfg.memory_optout.add(uid)
        self.memory.forget(uid)
        self.state.forget_user(uid)
        await self._save()
        log.info("%s used forgetme", uid)
        return fill(FORGOT, prefix=self.cfg.COMMAND_PREFIX)

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
