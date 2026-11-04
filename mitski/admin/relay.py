import discord

from mitski.chat.patterns import NO_PINGS
from mitski.core import logs
from mitski.core.component import Component
from mitski.core.text import cut

log = logs.get("relay")


MODE_STYLE = {
    "direct": ("replied", 0x5865F2),
    "dm": ("dm reply", 0xA970FF),
    "ambient": ("organic chat", 0x57F287),
    "dm_open": ("slid into dm", 0xFF73C6),
    "dm_promise": ("kept her dm promise", 0xFF73C6),
}


class RelayLog(Component):
    async def post(self, content):
        if not self.cfg.LOG_CHANNEL:
            return
        try:
            log = self.app.get_channel(self.cfg.LOG_CHANNEL) or await self.app.fetch_channel(self.cfg.LOG_CHANNEL)
            await log.send(content=cut(content, 2000), allowed_mentions=NO_PINGS)
        except Exception:
            log.warning("log failed", exc_info=True)

    async def interaction(self, mode, channel, person, their_msg, lines, extra=None, turns=0, label=None):
        if not self.cfg.LOG_CHANNEL:
            return
        title, _ = MODE_STYLE[mode]
        parts = [f"**{title}**"]
        if person is not None:
            parts.append(f"**User:** {person.display_name} (@{person.name})")
        if their_msg is not None:
            seen = " ".join(self.app.vision.tags(their_msg))
            text = " ".join(t for t in (their_msg.clean_content, seen) if t) or "*(no text)*"
            name = label or ("Latest in chat" if mode == "ambient" else "They said")
            parts.append(f"**{name}:**\n{cut(text, 900)}\n[Jump to message]({their_msg.jump_url})")
        response = "\n".join(lines) or "*(no response text)*"
        parts.append(f"**{self.me.display_name} said:**\n{cut(response, 1024)}")
        if extra:
            parts.append(f"**{'GIF' if extra.startswith('http') else 'Extra'}:** {extra}")
        if isinstance(channel, discord.DMChannel):
            where = f"DM with {person}" if person else "DM"
        else:
            where = f"{channel.guild.name} • #{channel.name}"
        parts.append(f"-# {where} • {turns} turns of context")
        await self.post("\n\n".join(parts))
