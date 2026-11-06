def _on(flag, detail=""):
    return (f"on{detail}" if detail else "on") if flag else "off"


def startup_report(app):
    cfg, client = app.cfg, app.client
    guilds = client.guilds
    away, reminders, owner, memory = app.away, app.reminders, app.owner, app.memory
    emojis = sum(len(g.emojis) for g in guilds)
    stickers = sum(len(g.stickers) for g in guilds)
    youtube = ", titles only"
    if app.youtube.transcripts:
        youtube = " + transcripts"
    lines = [
        f"logged in as {app.user} ({app.user.id})",
        f"channels: {sorted(cfg.channels) or 'none set'}",
        f"log channel: {cfg.LOG_CHANNEL or 'off'} | commands: "
        + (f"{cfg.COMMAND_PREFIX} in {cfg.COMMAND_CHANNEL or 'any channel'}" if owner.active else "off, no OWNER_ID")
        + f" | gifs: {_on(cfg.GIPHY_KEY)} | "
        f"dms: {'on' if cfg.DM_ENABLED else 'friends only' if cfg.DM_ENABLED_FRIEND else 'off'} | "
        f"routine: {_on(cfg.ROUTINE, ', planned by her model' if cfg.ROUTINE_PLANNER else '')} | memory: {f'{len(memory.people)} people' if cfg.MEMORY else 'off'}",
        f"feelings: {_on(cfg.FEELINGS, ' about people')}"
        + (f", mood {_on(cfg.MOOD)}" if cfg.FEELINGS else f" | mood: {_on(cfg.MOOD)}"),
        f"profiles: {_on(cfg.PROFILES)} | reactions: {_on(cfg.REACTIONS)} | {emojis} emojis, {stickers} stickers | "
        f"search: {app.search.provider or 'off'} | youtube: {_on(cfg.YOUTUBE, youtube)}",
        f"vision: {app.vision.status()}" + (f" | ignoring {len(cfg.ignored)} user(s)" if cfg.ignored else ""),
        f"voice: {app.voice.status()}",
        f"sleep mode: {_on(away.sleep_on)}"
        + (f", never in {len(away.exclude)} server(s)" if away.exclude else "")
        + (f" | asleep in {len(away.data['sleep'])} server(s)" if away.data["sleep"] else "")
        + f" | reminders: {_on(reminders.on)}, {len(reminders.items)} pending",
        "emojis: "
        + (
            f"nitro, {len(client.emojis)} emojis and {stickers} stickers from {len(guilds)} servers"
            if app.emojis.has_nitro()
            else "no nitro, each server's own (not animated)"
        ),
    ]
    if owner.active:
        lines.append(
            f"owner: {owner.id} ({owner.name}) | {len(owner.data['orders'])} standing orders"
            + (f" | quiet in {len(away.data['quiet'])} place(s)" if away.data["quiet"] else "")
        )
    if cfg.MEMORY:
        lines.append(
            f"memory: notes {'with qwen thinking' if app.helper.think_on else 'without thinking'} | recall by "
            f"{memory.embed.status()} | reflect every {memory.reflect_every} new things"
        )
    return lines
