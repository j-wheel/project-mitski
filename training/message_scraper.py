import asyncio
import json
import os
import re
import sys
from collections import deque
from datetime import datetime, timedelta

import discord
import yaml
from discord.http import Route

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
CONFIG_DIR = os.path.join(SCRIPT_DIR, "config")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.yaml")

EMPTY_CFG = """TOKEN: "your-bot-token-here" # your bot token
TARGET_ID: 123456 # user id to index
GUILD_ID: 0 # only index this server, 0 for every server the bot is in
OUTPUT: "data/messages.jsonl" # output file, relative to the project folder
KEEP_URLS: false # keep links inside messages
CONTEXT_MSGS: 6 # previous messages saved as context, 0 to skip (1 extra request per message)
CONTEXT_MAX_MIN: 60 # ignore context older than this many minutes
REQUEST_DELAY: 0.5 # seconds to wait between api requests
"""

USER_MENTION = re.compile(r"<@!?\d+>")
ROLE_MENTION = re.compile(r"<@&\d+>")
CHANNEL_MENTION = re.compile(r"<#\d+>")
EVERYONE_MENTION = re.compile(r"@(everyone|here)\b")
CUSTOM_EMOJI = re.compile(r"<a?:(\w+):\d+>")
URL = re.compile(r"https?://\S+")

USEFUL_TYPES = (0, 19)
SEARCH_PATH = "/guilds/{guild_id}/messages/search"
HISTORY_PATH = "/channels/{channel_id}/messages"


def ensure_config():
    if not os.path.exists(CONFIG_PATH):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_PATH, "w") as f:
            f.write(EMPTY_CFG)
        print(f"Created {CONFIG_PATH}, default cfg")
        sys.exit(0)


def load_config():
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


ensure_config()
config = load_config()
TOKEN = config["TOKEN"]
TARGET_ID = int(config["TARGET_ID"])
GUILD_ID = int(config.get("GUILD_ID") or 0)
KEEP_URLS = bool(config.get("KEEP_URLS", False))
CONTEXT_MSGS = int(config.get("CONTEXT_MSGS", 6))
CONTEXT_MAX_AGE = timedelta(minutes=int(config.get("CONTEXT_MAX_MIN", 60)))
REQUEST_DELAY = float(config.get("REQUEST_DELAY", 0.5))
OUTPUT_PATH = os.path.join(PROJECT_DIR, config.get("OUTPUT", "data/messages.jsonl"))
PROGRESS_PATH = os.path.join(os.path.dirname(OUTPUT_PATH), "progress.json")
os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)

bot = discord.Client(self_bot=True)

saved_ids = set()
progress = {}
live_buffers = {}
guild_queue = asyncio.Queue()
queued = set()
worker_started = False
out_file = None


def clean(text):
    text = USER_MENTION.sub("", text)
    text = ROLE_MENTION.sub("", text)
    text = CHANNEL_MENTION.sub("", text)
    text = EVERYONE_MENTION.sub("", text)
    text = CUSTOM_EMOJI.sub(r":\1:", text)
    if not KEEP_URLS:
        text = URL.sub("", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"[ \t]+,", ",", text)
    text = re.sub(r"[ \t]*\n[ \t]*", "\n", text)
    text = text.strip()
    text = re.sub(r"^,\s*", "", text)
    text = re.sub(r"^:\s+", "", text)
    return text.strip()


def load_state():
    global progress
    if os.path.exists(OUTPUT_PATH):
        with open(OUTPUT_PATH, encoding="utf-8") as f:
            for line in f:
                try:
                    saved_ids.add(json.loads(line)["id"])
                except (json.JSONDecodeError, KeyError):
                    pass
    if os.path.exists(PROGRESS_PATH):
        with open(PROGRESS_PATH) as f:
            progress = json.load(f)


def save_progress():
    with open(PROGRESS_PATH, "w") as f:
        json.dump(progress, f, indent=2)


def speaker(author_id):
    return "target" if int(author_id) == TARGET_ID else "other"


def wanted_guild(guild):
    return guild is not None and (not GUILD_ID or guild.id == GUILD_ID)


def write_record(mid, created, guild, channel_name, content, context, reply_to, attachments, source):
    if mid in saved_ids:
        return False
    record = {
        "id": mid,
        "timestamp": created.isoformat(),
        "guild": guild.name,
        "guild_id": str(guild.id),
        "channel": channel_name,
        "content": content,
        "reply_to": reply_to,
        "context": [{"speaker": spk, "content": txt} for ts, spk, txt in context if created - ts <= CONTEXT_MAX_AGE],
        "has_attachments": attachments,
        "source": source,
    }
    out_file.write(json.dumps(record, ensure_ascii=False) + "\n")
    out_file.flush()
    saved_ids.add(mid)
    return True


async def api(path, params=None, **route_args):
    await asyncio.sleep(REQUEST_DELAY)
    return await bot.http.request(Route("GET", path, **route_args), params=params)


async def search_page(guild_id, min_id):
    params = [
        ("author_id", str(TARGET_ID)),
        ("sort_by", "timestamp"),
        ("sort_order", "asc"),
        ("limit", "25"),
        ("include_nsfw", "true"),
    ]
    if min_id:
        params.append(("min_id", str(min_id)))
    while True:
        data = await api(SEARCH_PATH, params=params, guild_id=guild_id)
        if "messages" in data:
            return data
        wait = max(float(data.get("retry_after") or 0), 5.0)
        print(f"search index not ready, retry in {wait}s")
        await asyncio.sleep(wait)


async def fetch_context(channel_id, before_id):
    try:
        raw = await api(HISTORY_PATH, params={"before": before_id, "limit": CONTEXT_MSGS}, channel_id=channel_id)
    except discord.HTTPException:
        return []
    context = []
    for m in reversed(raw):
        if m.get("type", 0) not in USEFUL_TYPES or m["author"].get("bot"):
            continue
        text = clean(m.get("content", ""))
        if text:
            context.append((datetime.fromisoformat(m["timestamp"]), speaker(m["author"]["id"]), text))
    return context


def raw_reply(ref):
    if not ref:
        return None
    text = clean(ref.get("content", ""))
    if not text:
        return None
    return {"speaker": speaker(ref["author"]["id"]), "content": text}


async def save_search_hit(guild, m, thread_names):
    if m["id"] in saved_ids or m.get("type", 0) not in USEFUL_TYPES:
        return False
    content = clean(m.get("content", ""))
    if not content:
        return False
    context = await fetch_context(m["channel_id"], m["id"]) if CONTEXT_MSGS else []
    channel = bot.get_channel(int(m["channel_id"]))
    channel_name = thread_names.get(m["channel_id"]) or getattr(channel, "name", m["channel_id"])
    return write_record(
        m["id"],
        datetime.fromisoformat(m["timestamp"]),
        guild,
        channel_name,
        content,
        context,
        raw_reply(m.get("referenced_message")),
        bool(m.get("attachments")),
        "backfill",
    )


async def backfill_guild(guild):
    gid = str(guild.id)
    state = progress.get(gid, {})
    last_id = 0 if state.get("rescan") else int(state.get("last_id", 0))
    deep_index = False
    total = 0
    print(f"scraping: {guild.name} (from id {last_id})")

    while True:
        data = await search_page(guild.id, last_id)
        deep_index = deep_index or bool(data.get("doing_deep_historical_index"))
        thread_names = {t["id"]: t.get("name") for t in data.get("threads") or []}

        hits = []
        for group in data.get("messages") or []:
            for m in group if isinstance(group, list) else [group]:
                if int(m["author"]["id"]) == TARGET_ID:
                    hits.append(m)
        hits.sort(key=lambda m: int(m["id"]))
        if not hits or int(hits[-1]["id"]) <= last_id:
            break

        for m in hits:
            if await save_search_hit(guild, m, thread_names):
                total += 1
            last_id = max(last_id, int(m["id"]))

        progress[gid] = {"last_id": last_id, "rescan": deep_index}
        save_progress()
        print(f"{guild.name}: +{total} (up to {hits[-1]['timestamp'][:10]}, ~{data.get('total_results', '?')} left)")

    progress[gid] = {"last_id": last_id, "rescan": deep_index}
    save_progress()
    print(f"backfill done: {guild.name} +{total} ({len(saved_ids)} total)")
    if deep_index:
        print(f"discord was still indexing old messages in {guild.name}, restart later to pick up any it missed")


async def backfill_worker():
    while True:
        guild = await guild_queue.get()
        try:
            await backfill_guild(guild)
        except discord.Forbidden:
            print(f"no access to search {guild.name} (needs read message history)")
        except discord.HTTPException as e:
            print(f"backfill fail {guild.name}: {e.status} {e.text}")
        except Exception as e:
            print(f"backfill fail {guild.name}: {e}")
        finally:
            guild_queue.task_done()


def queue_guild(guild):
    if wanted_guild(guild) and guild.id not in queued:
        queued.add(guild.id)
        guild_queue.put_nowait(guild)


@bot.event
async def on_ready():
    global worker_started
    print(f"--> {bot.user} (id: {bot.user.id})")
    print(f"target {TARGET_ID}, {len(saved_ids)} already saved")
    for guild in bot.guilds:
        queue_guild(guild)
    if not worker_started:
        worker_started = True
        asyncio.create_task(backfill_worker())


@bot.event
async def on_guild_join(guild):
    print(f"joined {guild.name}")
    queue_guild(guild)


@bot.event
async def on_message(msg):
    if not wanted_guild(msg.guild) or msg.author.bot:
        return
    if msg.type not in (discord.MessageType.default, discord.MessageType.reply):
        return
    content = clean(msg.content)
    if not content:
        return

    buf = live_buffers.setdefault(msg.channel.id, deque(maxlen=CONTEXT_MSGS or 1))

    if msg.author.id == TARGET_ID:
        reply_to = None
        ref = msg.reference.resolved if msg.reference else None
        if isinstance(ref, discord.Message):
            text = clean(ref.content)
            if text:
                reply_to = {"speaker": speaker(ref.author.id), "content": text}
        context = list(buf) if CONTEXT_MSGS else []
        if write_record(
            str(msg.id),
            msg.created_at,
            msg.guild,
            getattr(msg.channel, "name", str(msg.channel.id)),
            content,
            context,
            reply_to,
            bool(msg.attachments),
            "live",
        ):
            print(f"live #{msg.channel}: {content[:60]}")

    buf.append((msg.created_at, speaker(msg.author.id), content))


load_state()
out_file = open(OUTPUT_PATH, "a", encoding="utf-8")
bot.run(TOKEN, reconnect=True)
