from dataclasses import dataclass, field


@dataclass(frozen=True)
class Option:
    key: str
    default: object
    doc: str = ""
    choices: tuple = ()


@dataclass(frozen=True)
class Section:
    title: str
    options: tuple = field(default_factory=tuple)


SECTIONS = (
    Section(
        "basics",
        (
            Option(
                "CHANNELS", [], "channel ids she talks in (!addchannel / !delchannel / !listchannels change this live)"
            ),
            Option("LOG_CHANNEL", 0, "channel id for the relay log and the ! commands, 0 = off"),
            Option(
                "PERSONA",
                "You're hanging out in a discord server with your friends. You're friendly, easygoing and a bit funny, you have your own opinions, and you're happy to talk about almost anything. You type like a real person in chat: short, casual messages, often a few quick ones in a row, and you usually don't end messages with a period. Always stay in character.",
                "who she is: her personality, background and how she talks. rewrite this to make her your own",
            ),
            Option(
                "IDENTITY_NOTE",
                "",
                "who she always is, added to the persona every time (stay in character, no assistant talk, no owner talk). empty = the built-in one, {name} = her name",
            ),
            Option("LLM_URL", "http://127.0.0.1:5111", "llama-server running qwen3.8 27b"),
            Option(
                "PROMPT_FORMAT",
                "qwen",
                '"qwen" for qwen3.8 27b, "v7" for cydonia 24b, "v3" for rocinante-x 12b (must match the training)',
            ),
            Option(
                "LORA_SCALE",
                1.0,
                "how strongly her lora is applied, when llama-server loads it separately (--lora mitski-lora-f16.gguf --lora-init-without-apply): her replies use it, and her helper jobs (memory notes, planning, searching, looking at images) get the plain qwen, which is much better at those. ignored if the server has no lora loaded (a merged model)",
            ),
            Option(
                "ANSWER_RETRY_LORA",
                0.6,
                "when her reply dodged a question she'd worked out the answer to, the retry runs her lora at this part of its strength, so she follows the answer better while still sounding like her",
            ),
        ),
    ),
    Section(
        "presence",
        (
            Option("ACTIVITY_TYPE", "", "playing, watching, listening, competing, or empty for none"),
            Option("ACTIVITY_TEXT", "", 'activity text, e.g. "Minecraft"'),
            Option("STATUS", "online", "online, idle, dnd, invisible"),
        ),
    ),
    Section(
        "her owner: the one person she listens to. she treats them like a close friend and never calls them her owner",
        (
            Option(
                "OWNER_ID",
                0,
                'discord user id: she does what they ask, follows their standing orders ("stop pinging sam"), and they can tell her to be quiet, change her status or dm someone',
            ),
            Option(
                "OWNER_NOTE",
                "",
                'who they are to her, e.g. "your best friend, you bicker a lot but you adore them". empty = a default',
            ),
            Option("OWNER_CAN_DM", True, "her owner can tell her to dm people"),
            Option("OWNER_ORDERS_MAX", 15, "standing orders she keeps (data/owner.json), oldest go first"),
        ),
    ),
    Section(
        "away: quiet mode (her owner tells her to be quiet and she goes completely silent in that server) and sleep mode "
        "(now and then she goes offline in a server for a couple of hours)",
        (
            Option(
                "SLEEP_MODE",
                True,
                "she sometimes goes away in a server for a while (!sleep / !wake / !sleepexclude / !listsleep)",
            ),
            Option("SLEEP_CHANCE", 0.06, "chance per hour per server that she heads off"),
            Option(
                "SLEEP_NIGHT_BOOST",
                4,
                "that chance times this late at night (1-7 in TIMEZONE), and she stays away longer",
            ),
            Option("SLEEP_HOURS", [1.5, 4], "how long she's away"),
            Option("SLEEP_MAX_PER_DAY", 1, "per server"),
            Option("SLEEP_BYE_CHANCE", 0.6, "chance she says a quick bye first, if she was just talking there"),
            Option("SLEEP_EXCLUDE", [], "server ids where she never goes to sleep by herself"),
        ),
    ),
    Section(
        "routine: her day (sleep, a long busy block on weekdays, errands, gaming). while she's busy she only looks at "
        "her phone now and then, so dms and pings can wait a while. !routine shows today's plan, !busy and !free change it",
        (
            Option("ROUTINE", False, "she has a daily routine. false = she's always available"),
            Option(
                "ROUTINE_SLEEP", ["02:00", "10:00"], "when she's asleep. dms wait until morning, old pings are let go"
            ),
            Option(
                "ROUTINE_BUSY", ["11:00", "16:00"], "her long busy block on most weekdays, with a break in the middle"
            ),
            Option("ROUTINE_BUSY_WHAT", "at work", "what she's doing then, she's told \"right now you're at work\""),
            Option(
                "ROUTINE_ERRANDS",
                ["out running errands", "out with a friend", "helping out at home", "out with family"],
                "shorter things she's busy with, 25 to 120 minutes each, done by 21:30, nothing twice in a day",
            ),
            Option("ROUTINE_ERRANDS_PER_DAY", [0, 2], "how many of those a day"),
            Option(
                "ROUTINE_GAMES",
                ["in a ranked match", "playing games with friends"],
                "gaming sessions, she checks her phone more often than when she's busy but doesn't join in by herself",
            ),
            Option("ROUTINE_GAMES_PER_DAY", [0, 2], "how many of those a day"),
            Option("ROUTINE_LOOK_BUSY", [300, 1500], "seconds between looking at her phone while busy"),
            Option("ROUTINE_LOOK_GAMING", [60, 300], "seconds between looking at her phone while gaming"),
            Option("ROUTINE_STAY", [120, 480], "seconds she stays once she looks, and answers what's waiting"),
            Option("ROUTINE_PRESENCE", True, "her discord status follows it: invisible asleep, idle busy"),
        ),
    ),
    Section(
        'reminders ("remind me in 2h to drink water", "remind sam at 8 to start the raid")',
        (
            Option("REMINDERS", True, ""),
            Option("REMINDERS_MAX_PER_USER", 10, "pending reminders one person can ask for"),
            Option("REMINDERS_MAX_DAYS", 30, "how far ahead"),
        ),
    ),
    Section(
        "conversations",
        (
            Option(
                "NAME_TRIGGERS",
                ["mitski"],
                "saying any of these counts as talking to her, change it if you give her another name",
            ),
            Option(
                "IGNORE_USERS",
                [],
                "user ids she ignores completely (!ignoreuser / !unignoreuser / !listusers change this live)",
            ),
            Option(
                "ENGAGE_SEC",
                150,
                "after talking with someone, their next messages count as talking to her for this long..",
            ),
            Option("FOLLOWUP_BUDGET", 4, "..for up to this many replies without them pinging/replying again"),
            Option("GROUP_NAMES", True, "show who said what when several people are in what she reads"),
            Option(
                "CHIME_IN_CHANCE",
                0.35,
                'when someone she\'s chatting with says something to someone else ("gm sam"), the chance she chimes in anyway, like a friend in the group chat would. 0 = never, 1 = always',
            ),
            Option(
                "ADDRESSEE_CHECK",
                True,
                "in group chats, before sending, check that her reply fits the message she's answering. if it answers someone else's message instead, she rewrites it for the right person (or, when she joined in by herself, it goes to the message it really answers). one quick helper-model call",
            ),
            Option(
                "REPLY_BACK_CHANCE",
                0.7,
                "someone pinged/replied to her and nobody else talked since: chance she uses discord's reply back anyway (else a plain message, like people do when it's obvious who they mean)",
            ),
            Option(
                "MULTI_ANSWER",
                True,
                "someone asks a few different things, in one message or a few: she's told to answer each one, and it goes out as quick messages, one longer message, or a reply to each question, whatever fits. false = no special handling, she just replies to all of it",
            ),
            Option(
                "PINGS",
                True,
                'she can @ping people: sometimes instead of a discord reply, and when she writes "@name" herself',
            ),
            Option(
                "PING_CHANCE",
                0.25,
                "when others talked in between and she has to make clear who she means: chance of an @ping instead of a discord reply (a bit more when their message is far up and they've gone quiet)",
            ),
        ),
    ),
    Section(
        "voice chats: she never talks in vc, she just hangs out there and types in chat. needs "
        'pip install -U "discord.py-self[voice]" (2.1.0+) and ffmpeg on PATH',
        (
            Option("VOICE", True, "she sometimes joins voice channels on the servers she chats in"),
            Option(
                "VOICE_JOIN_CHANCE",
                0.1,
                "chance per hour she hops into a vc with people in it (more with people she knows or her owner in it, or right after the chat talked about vc, less late at night)",
            ),
            Option("VOICE_TALK_CHANCE", 0.03, 'chance per message that talks about vc ("hop in vc") that she joins'),
            Option("VOICE_ASKED_CHANCE", 0.35, "someone asks her to join (or leave) vc. her owner: always"),
            Option(
                "VOICE_SOLO_CHANCE",
                0.02,
                "chance per hour she joins an empty vc by herself while the chat is active, and waits for people",
            ),
            Option("VOICE_MIN_PEOPLE", 2, "people in a vc before she'd join it by herself"),
            Option("VOICE_STAY_MIN", [15, 75], "how long she feels like staying, in minutes (shorter late at night)"),
            Option("VOICE_COOLDOWN_MIN", 60, "after leaving, at least this long before she joins by herself again"),
            Option("VOICE_MAX_PER_DAY", 3, "times a day she joins by herself"),
            Option(
                "VOICE_ASMR_FILE",
                "asmr.mp3",
                "in the mp3/ folder: a random part of it plays in vc while she's typing on that server",
            ),
            Option("VOICE_ASMR_VOLUME", 0.5, ""),
        ),
    ),
    Section(
        "joining in by herself (scales automatically with how busy a channel is)",
        (
            Option("ACTIVE_MIN", 10, "in a normal-paced channel she speaks up after ACTIVE_MIN.."),
            Option("ACTIVE_MAX", 30, "..ACTIVE_MAX messages from other people"),
            Option("ACTIVE_COOLDOWN", 120, "base seconds between joining in by herself"),
            Option(
                "ACTIVE_REPLY_CHANCE",
                0.3,
                "chance she uses discord's reply when the person she answers is the last one talking",
            ),
            Option(
                "LATE_GAP",
                12,
                "joining in by herself: if this many messages came in while she was typing, she doesn't send it. 0 = off",
            ),
            Option("BUSY_RATE", 6, "messages per minute that counts as a busy channel, she holds back more there"),
            Option("MAX_AMBIENT_PER_HOUR", 6, "max times per channel per hour she joins in by herself"),
        ),
    ),
    Section(
        "context",
        (
            Option("CONTEXT_MSGS", 30, "max messages she reads when someone talks to her (pings, replies, dms)"),
            Option("AMBIENT_MSGS", 15, "messages she reads when joining in on the general chat"),
            Option("CHAIN_DEPTH", 6, "how far back she follows a chain of replies"),
            Option("CONTEXT_GAP_MIN", 30, "ignore messages from before a silence longer than this"),
            Option(
                "NOTES_PLACEMENT",
                "end",
                'where her notes for a reply go (who she\'s answering, memories, search results, ...): "end" = just before the newest messages (best), "inline" = inside the newest message, "after" = after it (she may start repeating people), "start" = in the system prompt',
            ),
            Option(
                "SHOW_NOTES",
                False,
                "print the notes she got for each reply in the console, to see what she knew when she answered",
            ),
            Option(
                "MEANWHILE_MSGS",
                6,
                "what's been said in the channel since the message she answers, shown to her, 0 = off",
            ),
            Option(
                "CHANNEL_CONTEXT_MSGS",
                10,
                "in a conversation, she also reads this many of the channel's messages before it (the rest of the chat, not just her thread with them), so she doesn't lose what's going on",
            ),
            Option(
                "TIMEZONE",
                "",
                'for knowing what time of day it is, e.g. "Europe/London". empty = this computer\'s clock',
            ),
            Option("STALE_SEC", 180, "skip messages that waited in the queue longer than this"),
        ),
    ),
    Section(
        "memory",
        (
            Option("MEMORY", True, "remember people between conversations (data/memory.db)"),
            Option("MEMORY_NOTES", True, "a model reads chats and updates what she knows about people"),
            Option(
                "NOTES_URL",
                "",
                'helper model: writes memory notes, plans her replies, decides what to google, sums up search results. empty = the same llama-server as her chat (the plain qwen when her lora is loaded separately, best). or a separate server, e.g. "http://127.0.0.1:11434" (ollama) with NOTES_MODEL: "gemma3:4b" (faster)',
            ),
            Option("NOTES_MODEL", "", "model name for NOTES_URL (ollama / cloud)"),
            Option("NOTES_EVERY", 6, "messages to her from someone between regular memory updates.."),
            Option(
                "NOTES_MIN_GAP",
                60,
                '..but at most once per this many seconds per person. personal stuff ("im 19", "call me..") updates sooner',
            ),
            Option(
                "NOTES_IDLE_MIN",
                8,
                "when a chat goes quiet for this long, whatever's left gets noted (so short chats aren't lost)",
            ),
            Option(
                "NOTES_OVERHEAR", True, "she also learns from people she knows talking in the channel, not just to her"
            ),
            Option("NOTES_OVERHEAR_EVERY", 15, "their channel messages between those updates"),
            Option("NOTES_MAX_PER_HOUR", 40, "max memory updates per hour, all people together"),
            Option("FACTS_MAX", 40, "facts kept per person, the least important get merged or dropped first"),
            Option(
                "FACTS_IN_PROMPT",
                12,
                "how many facts she's reminded of per reply (the most relevant to what's being said)",
            ),
            Option(
                "MEMORY_THINK",
                True,
                "qwen thinks it through before writing memory notes (who said what, what's new, what changed). runs in the background and pauses whenever someone's waiting on her reply",
            ),
            Option("MEMORY_THINK_TOKENS", 800, "how long it may think per memory update"),
            Option(
                "EPISODES_MAX",
                30,
                "past conversations she remembers in detail per person, older ones get folded into a short history",
            ),
            Option(
                "REFLECT_EVERY",
                8,
                "after this many new things about someone she rethinks who they are to her (portrait, how she is with them, inside jokes, what to avoid) and tidies their facts. 0 = never",
            ),
            Option(
                "BACKGROUND_QUIET_SEC",
                20,
                "memory work waits until she's had nothing more important to do for this long (max 3 min)",
            ),
            Option(
                "MEMORY_EMBED_URL",
                "",
                'optional: an embedding model so she finds memories by meaning ("my dog" -> "has a golden retriever"), not just shared words. a second llama-server with Qwen3-Embedding-0.6B: llama-server -m Qwen3-Embedding-0.6B-Q8_0.gguf --embedding --pooling last -ngl 99 -c 8192 -ub 8192 --port 5112 then "http://127.0.0.1:5112". empty = keywords + tags',
            ),
            Option("MEMORY_EMBED_MODEL", "", "model name, only for ollama/cloud"),
            Option(
                "MEMORY_EMBED_DIMS",
                512,
                "qwen3-embedding vectors can be cut down to this (smaller cache, same quality). 0 = keep all",
            ),
            Option(
                "SELF_NOTES",
                True,
                "remember what she says about herself, so her backstory stays consistent (data/memory.db)",
            ),
            Option("SELF_MAX", 30, "facts kept about herself"),
            Option(
                "MEMORY_ADMINS",
                [],
                "user ids allowed to use the ! commands in the log channel (besides her owner), empty = anyone there",
            ),
        ),
    ),
    Section(
        "profiles (what people are playing, listening to and doing, from their discord presence)",
        (
            Option(
                "PROFILES", True, "she sees what people are playing/listening to, their custom status, roles, join date"
            ),
            Option(
                "PROFILE_TRACK",
                True,
                "remember what people play (and how long), listen to, watch and their statuses (only people she's talked to)",
            ),
        ),
    ),
    Section(
        "reactions & stickers",
        (
            Option("REACTIONS", True, "she adds reactions to messages"),
            Option("REACT_CHANCE", 0.2, "chance she also reacts to a message she's answering"),
            Option(
                "REACT_INSTEAD_CHANCE",
                0.5,
                'chance she only reacts to short stuff like "lol", "ty", "gn" instead of replying',
            ),
            Option("AMBIENT_REACT_CHANCE", 0.2, "chance she reacts to a random message in chat"),
            Option("MAX_REACTIONS_PER_HOUR", 30, "per channel"),
            Option("STICKER_CHANCE", 0.08, "chance she sends one of the server's stickers after a reply, 0 = never"),
            Option("EMOJI_HINT_MAX", 25, "how many of the server's emojis she's told about (most used first)"),
        ),
    ),
    Section(
        "looking stuff up",
        (
            Option(
                "SEARCH_PROVIDER", "ddg", 'ddg (free, no key, pip install ddgs), searxng, brave, google, or "" for off'
            ),
            Option(
                "SEARXNG_URL",
                "http://127.0.0.1:8888",
                "your searxng instance (enable the json format in its settings.yml)",
            ),
            Option("SEARCH_MAX_PER_HOUR", 30, "max searches per hour"),
            Option(
                "THINKING",
                True,
                "before answering questions/requests she works out what they want and checks things first (search, weather, time, math, a closer look at a picture, what she knows about someone)",
            ),
            Option(
                "THINK_ALWAYS",
                True,
                'think about every real message to her (false = only questions/requests). tiny ones like "hi mitski" or "lol" are skipped either way, and follow-ups are always checked for who they\'re for',
            ),
            Option("WEATHER", True, "weather + time anywhere, from open-meteo.com (free, no key)"),
            Option("WEATHER_UNITS", "metric", "metric or imperial"),
            Option("YOUTUBE", True, "read titles of youtube links people send, and summarize the newest one"),
            Option(
                "YT_TRANSCRIPT_CHARS",
                6000,
                "how much of a transcript she reads (pip install youtube-transcript-api), 0 = titles only",
            ),
        ),
    ),
    Section(
        "seeing images, gifs, stickers and videos (pip install pillow, ffmpeg on PATH is optional for videos)",
        (
            Option("VISION", True, "look at what people send and describe it to her"),
            Option(
                "VISION_URL",
                "",
                'vision model server, empty = same as LLM_URL (qwen3.8 sees images itself: start llama-server with --mmproj mmproj-F16.gguf). or a separate one, e.g. "http://127.0.0.1:11434" with VISION_MODEL: "gemma3:4b"',
            ),
            Option(
                "VISION_MODEL", "", 'model name, needed for ollama/cloud apis (e.g. "gemma3:4b"), not for llama-server'
            ),
            Option("VISION_MAX_PER_MSG", 3, "max images/gifs/stickers she looks at per message"),
            Option(
                "VISION_MAX_PER_HOUR",
                0,
                "max images/gifs/stickers she looks at in chat per hour, 0 = no limit (fine when self-hosted)",
            ),
            Option(
                "VISION_INDEX_PER_HOUR",
                30,
                "the background sticker scan has its own limit, and waits while she's chatting",
            ),
            Option("VISION_MAX_MB", 10, "skip files bigger than this"),
            Option(
                "VISION_MAX_SIDE", 896, "images get shrunk to this many pixels on the longest side before she looks"
            ),
            Option("VISION_FRAMES", 4, "frames sampled from gifs, animated stickers and videos"),
            Option("VISION_CONTEXT_MSGS", 8, "how many of the newest messages she reads get looked at"),
            Option(
                "VISION_INDEX_STICKERS",
                True,
                "slowly look at the stickers of servers she talks in, so she picks better ones",
            ),
        ),
    ),
    Section(
        "generation (qwen's recommended settings with thinking off)",
        (
            Option("TEMPERATURE", 0.7, ""),
            Option("TOP_P", 0.8, ""),
            Option("TOP_K", 20, ""),
            Option("MIN_P", 0.0, ""),
            Option("PRESENCE_PENALTY", 1.5, "stops her repeating herself. if her wording gets odd, try 0.5-1.0"),
            Option("REPEAT_PENALTY", 1.0, ""),
            Option("MAX_TOKENS", 1000, "max tokens per reply"),
            Option("MAX_LINES", 5, "max separate messages per reply"),
            Option("STRIP_PERIODS", True, 'remove a single "." at the end of messages (keeps "...")'),
            Option("DROP_UNKNOWN_EMOJIS", True, "remove :emoji_names: she can't actually use"),
            Option(
                "NITRO",
                False,
                "does her account have nitro? true: she uses emojis (animated too) and stickers from every server she's in, anywhere, in her messages and reactions (where the server allows external emojis/stickers). false: only the emojis and stickers of the server she's in, no animated emojis",
                choices=("auto",),
            ),
            Option(
                "REPLY_PING",
                True,
                'ping people when she uses discord\'s reply. "auto" = only when others talked in between',
                choices=("auto",),
            ),
        ),
    ),
    Section(
        "how she types (applied to every message right before it's sent)",
        (
            Option(
                "SLANG",
                0.3,
                "how much she abbreviates (you -> u, because -> bc, i don't know -> idk, right now -> rn, ...). 0 = off, 1 = max",
            ),
            Option(
                "LOWERCASE", True, "everything lowercase, except words she writes in CAPS for emphasis (LMAO, WHAT)"
            ),
            Option("NO_APOSTROPHES", 0.3, "chance a reply skips apostrophes (im, dont, thats)"),
            Option("SPLIT_CHANCE", 0.5, "chance a long line with a few sentences becomes a few quick messages"),
            Option("STRETCH_CHANCE", 0.05, 'chance she stretches the last word of a message ("sooo", "pleaseee")'),
            Option("FLAIR_CHANCE", 0.0, "chance she ends a lighthearted reply with ~ >.< :3 or hehe"),
            Option(
                "STYLE_NOTE",
                "Type like a regular person on discord: short, casual messages, some slang and abbreviations are fine, not uptight.",
                'reminder in her notes for every reply, "" = off',
            ),
        ),
    ),
    Section(
        "realism",
        (
            Option("READ_DELAY", [1.0, 4.0], "base seconds before she starts typing"),
            Option("READ_CPS", 25, 'reading speed, longer messages take longer to "read"'),
            Option("TYPING_CPS", 9, "typing speed, characters per second"),
            Option("DEBOUNCE_SEC", 4, "wait until someone stops sending/typing before answering them"),
            Option("DISTRACTED_CHANCE", 0.15, "sometimes she takes a while (dms and joining in only)"),
            Option("DISTRACTED_DELAY", [15, 60], "seconds"),
        ),
    ),
    Section(
        "gifs (giphy, tenor's api was shut down in june 2026)",
        (
            Option("GIF_CHANCE", 0.1, "chance she sends a gif after a reply"),
            Option("GIF_RATING", "pg-13", "g, pg, pg-13, r"),
            Option("GIF_STYLE", "", 'added to every gif search, e.g. "anime". empty = nothing added'),
            Option(
                "GIF_UPLOAD",
                True,
                'where she can\'t embed links (no "embed links" permission) but can attach files, she uploads the gif as a file instead. false = no gifs there. without either permission she never sends gifs there',
            ),
        ),
    ),
    Section(
        "dms she starts herself",
        (
            Option("DM_ENABLED", False, "she starts dms by herself with anyone she's been chatting with"),
            Option("DM_ENABLED_FRIEND", False, "she starts dms by herself, but only with people on her friends list"),
            Option("DM_MIN_EXCHANGES", 4, "replies between her and someone in a server.."),
            Option("DM_WINDOW_MIN", 20, "..within this many minutes before she might dm them"),
            Option("DM_CHANCE", 0.25, "chance she dms them once they qualify"),
            Option("DM_DELAY", [60, 300], "seconds she waits before sending the dm"),
            Option("DM_COOLDOWN_H", 24, "min hours between dms she starts with the same person"),
            Option(
                "DM_KEEP_PROMISES", False, 'if she says she\'ll dm someone (or agrees to "dm me"), she actually does'
            ),
            Option("DM_PROMISE_DELAY", [20, 90], "seconds before she follows through"),
            Option("DM_PROMISE_COOLDOWN_MIN", 30, "min minutes between kept promises to the same person"),
        ),
    ),
    Section(
        "safety and privacy",
        (
            Option(
                "ADULT_CONTENT",
                "nsfw_channels",
                'where flirting may get explicit: "nsfw_channels" = only in channels Discord marks age-restricted '
                '(18+), "all_channels" = any server channel regardless of NSFW status, '
                '"never" = nowhere. DMs never count, and detected minors are always excluded',
                choices=("never", "nsfw_channels", "all_channels"),
            ),
            Option(
                "AGE_CHECK",
                True,
                'she reads people\'s roles and names for signs they\'re under 18 (an age, a range, "minor", "-18") '
                "and never gets explicit with them, anywhere",
            ),
            Option("AGE_CHECK_BIOS", True, "also read the bio of people she talks to (one profile lookup a day each)"),
            Option("AGE_CHECK_BIOS_PER_HOUR", 20, "most profile lookups she does in an hour"),
            Option(
                "MEMORY_OPTOUT",
                [],
                "user ids she keeps no memory about (!forgetme / !rememberme change this live, anyone can use them)",
            ),
            Option(
                "MEMORY_RETENTION_DAYS",
                180,
                "she forgets people she hasn't talked to in this many days, 0 = never",
            ),
        ),
    ),
    Section(
        "advanced",
        (
            Option("VOICE_CHECK_SEC", 45, "seconds between her checks of whether to join or leave a vc"),
            Option("SLEEP_CHECK_SEC", 300, "seconds between her checks of whether to head off in a server"),
            Option(
                "MEMORY_EMBED_QUERY_PREFIX",
                None,
                "instruction put before memory searches, null = the one qwen3-embedding expects",
            ),
            Option("LLM_TIMEOUT_SEC", 60.0, "longest a single model call may take before it's given up on"),
            Option("LLM_PAUSE_AFTER", 3, "failed model calls in a row before she stops trying for a while"),
            Option("LLM_PAUSE_SEC", 60.0, "how long she waits before trying the model again after that"),
            Option("LOG_LEVEL", "INFO", "console log level: DEBUG, INFO, WARNING"),
            Option("METRICS_WINDOW", 200, "replies kept for the latency numbers in !stats"),
        ),
    ),
)

SECRETS = (
    Option("TOKEN", "", "your discord token"),
    Option("GIPHY_KEY", "", "free key from developers.giphy.com, empty = no gifs"),
    Option("SEARCH_KEY", "", "api key for brave / google search"),
    Option("SEARCH_CX", "", "google programmable search engine id"),
    Option("YOUTUBE_KEY", "", "optional youtube data api key"),
    Option("NOTES_KEY", "", "api key for NOTES_URL, only for cloud apis"),
    Option("VISION_KEY", "", "api key for VISION_URL, only for cloud apis"),
    Option("MEMORY_EMBED_KEY", "", "api key for MEMORY_EMBED_URL, only for cloud apis"),
)

OPTIONS = {o.key: o for s in SECTIONS for o in s.options}
SECRET_KEYS = tuple(o.key for o in SECRETS)
