# mitski

mitski is a discord chatbot that runs on a user account and tries to act like a regular person in a server.
She hangs out in a few channels, talks to people, joins in on conversations by herself, remembers who people are
and sometimes sits in voice chat. Out of the box she has a plain, friendly personality, and who she is from there
is up to you (see [Make her your own](#make-her-your-own)).

She runs on a local model through llama-server, so nothing goes to an outside api unless you set one up. The model
is 0bserverx's Qwen3.8 27B ([`0bserverx/Qwen3.8-27B-Heretic-Abliterated-Uncensored`](https://huggingface.co/0bserverx/Qwen3.8-27B-Heretic-Abliterated-Uncensored)),
optionally with a LoRA trained on your own chat logs.

Note: this uses discord.py-self, which runs on a user account. That's against discord's terms of service, so use
a throwaway account and don't be surprised if it gets banned.

## Features

- Answers when she's pinged, replied to or named, and keeps talking with people for a bit after that
- Joins in on conversations by herself, less often in busy channels
- Works out who a message is for and replies, pings or just sends a message so it's clear who she's talking to
- Answers several messages from one person together, and answers each question when they ask a few different things
- Lays a reply out like a person would: a few quick messages, one longer message, or a reply to each question
- Lets tiny follow-ups that close a chat ("lol", "ok") go without replying, unless she asked them something
- Remembers people between conversations (facts, nicknames, what they play and listen to, past chats)
- Thinks before answering questions: web search, weather, time, math, scrolling back through the chat
- Looks at images, gifs, stickers and short videos people send
- Uses the server's emojis and stickers, reacts to messages, sends gifs (giphy)
- Types like a person: lowercase, slang, a few quick messages in a row, typing delays
- Joins voice chats now and then and plays keyboard sounds while she types (she never talks in vc)
- Sets reminders when asked ("remind me in 2h to drink water") and pings the person when it's time
- Goes away in a server for a couple of hours now and then, more often late at night
- Has a daily routine (`ROUTINE`): she sleeps, has a long busy block on most weekdays, errands and gaming sessions.
  While she's busy she only looks at her phone now and then, so dms and pings can wait a while, dms the least
- An owner account she listens to, with standing orders, quiet mode, status changes and dms
- Channels, ignored users and sleep settings can be changed from discord without restarting
- Her owner can keep people out of her memory with `MEMORY_OPTOUT`

## Requirements

- Python 3.11 or newer
- llama.cpp (llama-server) and a GPU that fits a 27B Q4 model, a 24GB card works
- ffmpeg on PATH (for voice and videos, optional otherwise)

```
pip install -r requirements.txt
```

`pillow`, `emoji`, `ddgs`, `youtube-transcript-api` and `mutagen` are optional. Without them she can't see
images, look up emoji names, search for free, read youtube transcripts or tell how long the typing sound is.

## Setup

1. Run `python -m mitski` once. It creates `config/mitski.yaml` and `config/keys.yaml` and exits.
2. Put your discord token in `config/keys.yaml`. Any api keys (giphy, search, etc.) go there too.
3. In `config/mitski.yaml` set at least `CHANNELS` (channel ids she talks in), `LOG_CHANNEL`, `COMMAND_CHANNEL` and `OWNER_ID`, and
   give her a personality (see [Make her your own](#make-her-your-own)).
4. Download the model and start llama-server:

```
hf download 0bserverx/Qwen3.8-27B-Heretic-Abliterated-Uncensored-GGUF RVN-Q4_K_M-multilingual.gguf --local-dir models
hf download unsloth/Qwen3.8-27B-GGUF mmproj-F16.gguf --local-dir models
llama-server -m models/RVN-Q4_K_M-multilingual.gguf --mmproj models/mmproj-F16.gguf -ngl 99 -c 32768 -np 2 --jinja --host 127.0.0.1 --port 5111
```

   If you trained a lora (see [Training her lora](#training-her-lora)), also pass
   `--lora out_mitski2/mitski-lora-f16.gguf --lora-init-without-apply`.

5. Optional: a small embedding model so memory search works by meaning (set `MEMORY_EMBED_URL` to port 5112):

```
llama-server -m Qwen3-Embedding-0.6B-Q8_0.gguf --embedding --pooling last -ngl 99 -c 8192 -ub 8192 --port 5112
```

6. Optional: put an `asmr.mp3` with keyboard sounds in `mp3/` for voice chat.
7. Run `python -m mitski` (or `mitski` after `pip install -e .`).

Everything in `mitski.yaml` has a comment next to it explaining what it does. Set `MITSKI_HOME` to run her from
a different folder than the project (config, data and mp3 are looked up there).

## Make her your own

The generated config is deliberately generic. These are the options that decide who she is, all in `mitski.yaml`:

- `PERSONA`: her personality, background and how she talks. This is the main one to rewrite.
- `NAME_TRIGGERS`: names that count as talking to her. Change it if you call her something other than mitski.
- `STYLE_NOTE`: a short reminder of how she types, given to her with every reply.
- `SLANG`, `LOWERCASE`, `NO_APOSTROPHES`, `STRETCH_CHANCE`, `FLAIR_CHANCE`: how much her messages get roughed up
  right before they're sent.
- `IDENTITY_NOTE`: the rules she always keeps (no assistant talk, stays in character, doesn't lie when someone
  sincerely asks if she's a bot). Leave it empty to use the built-in one, which calls her by the discord account's name.
- `ACTIVITY_TYPE` and `ACTIVITY_TEXT`: what her discord status says she's doing.
- `ROUTINE` and the `ROUTINE_*` options: her daily schedule, what keeps her busy and what she plays.
- `TIMEZONE` and `GIF_STYLE`: where she lives, and a word added to her gif searches (like "anime").

## Commands

Only `OWNER_ID` can use commands. Anyone else who tries one gets no answer at all, and she doesn't chat about it
either. Set `COMMAND_CHANNEL` to a channel id and they only work in that channel; leave it at 0 and they work
anywhere, dms included. The log goes to `LOG_CHANNEL`, which is a separate option.

Commands start with `COMMAND_PREFIX` (`!` by default), which `!prefix <new>` changes live. `!help` lists all of
this in discord, with the current prefix.

```
command                     alias   what it does
!addchannel <id ...>        !ac     add channels she talks in
!delchannel <id ...>        !dc     remove channels
!listchannels               !lc     list her channels
!ignoreuser <id ...>        !iu     ignore users completely (also forgets them)
!unignoreuser <id ...>      !uu     stop ignoring users
!listusers                  !lu     list ignored users

!mem <who>                  !m      what she remembers about someone (also: self, update, reflect, raw, search)
!forget <who> <what>        !fg     forget a fact (F3), a field (age, nickname, portrait) or everything (all)
!note <who> [cat] <fact>    !n      add a fact by hand
!set <who> <field> <value>  !sf     set a profile field
!forgetme                   !fm     she deletes what she knows about you and stops remembering new things
!rememberme                 !rm     undo that

!sleep <server> [hours]     !sl     send her away from a server for a while
!wake <server|all>          !wk     bring her back
!sleepexclude <server ...>  !se     servers she never goes away from by herself
!sleepinclude <server ...>  !si     undo that
!listsleep                  !ls     sleep settings, and where she's asleep or quiet right now
!reminders                  !rem    list pending reminders (cancel <n>, clear)
!routine                    !rt     what she's doing now and her plan for the next 24 hours
!busy <min> [what]          !bz     make her busy for a while, like "!busy 45 at the dentist"
!free [min]                 !fr     make her free for a while, whatever her plan says (60 min without a number)

!orders                     !ord    list standing orders (add <rule>, forget <n>, clear)
!quiet <minutes|off> [server] !q    completely quiet in that server, or everywhere without one
!stats                      !st     reply latency (p50/p95), llm calls per reply, time per stage, fallbacks
!prefix [new]               !px     show or change what commands start with
!help                       !h      list the commands, their aliases and what they do
```

Server ids can also be given as any channel id in that server. Channel, user, sleep and prefix changes take effect
right away and are saved to `mitski.yaml`.

The owner can also just tell her things in chat: "be quiet for an hour" makes her go silent in that server
(no replies, not even to pings) until the time's up or the owner says she can talk again. Pinging her while
she's asleep in a server wakes her up. "join vc" makes her join the vc of whoever is named, or the busiest one,
or an empty one that looks fine if nobody's in voice.

## Safety and privacy

- By default, flirting only gets explicit in channels discord marks as age-restricted
  (`ADULT_CONTENT: nsfw_channels`), never in dms and never when someone in the chat is a minor. Everywhere else she's
  told to keep it PG-13, and anything explicit that still comes out is held back before it's sent.
  `ADULT_CONTENT: never` turns it off everywhere, and `all_channels` allows it in any server channel (dms and minors
  stay excluded).
- She reads people's roles and names, and the bio of people she talks to, for signs they're under 18: an age
  ("15", "16 y/o", "13-15", "she/her | 16"), or words like "minor", "-18", "under 18". When she finds one she treats
  them as a minor everywhere, including age-restricted channels, and an age goes into her memory as if they'd told
  her. The flags are kept in `data/age_flags.json` (also with memory off or after `!forgetme`) and clear when the
  role or bio changes. Bios cost one profile lookup per person a day, at most `AGE_CHECK_BIOS_PER_HOUR`.
- She doesn't start dms by herself unless you turn on `DM_ENABLED` (anyone), `DM_ENABLED_FRIEND` (only people on her
  friends list) or `DM_KEEP_PROMISES`. She never starts one with someone she knows is a minor, and not while she's
  busy. Unprompted dms from a user account are also the quickest way to get it flagged.
- If someone sincerely asks whether she's a bot, she doesn't lie about it. Teasing ("ur such a bot") is still just
  banter.
- When someone asks what she knows about another person, she only shares harmless things (games, music, what they
  like). Age, location, relationships, job, school and private facts stay between her and that person.
- People she hasn't talked to in `MEMORY_RETENTION_DAYS` (180) are forgotten.
- Memory lives in `data/memory.db` (sqlite). An existing `memory.json` and `self.json` are moved into it on the
  first start and renamed to `.migrated`.

## How a reply happens

Every message goes through `chat/router.py`, which decides whether it's for her, a follow-up, something to
overhear or nothing. Replies then run through `chat/pipeline.py` in fixed stages, each one timed:

```
admit      is she allowed to answer (channel, quiet/asleep, too old)
settle     wait for them to stop typing, read delay
compose    build the context, plan (search, tools, owner requests, reminders), write a draft
polish     clean the draft, keep it in her own voice, retry if it echoes people or sounds like an assistant, check it answers the question
aim        check who the draft is really for, rewrite or redirect it, drop it if the chat moved on
deliver    reply, ping or plain message, typed out line by line
aftercare  memory, reactions, dm follow-ups, the log channel
```

`!stats` shows how long each stage takes on average, how many llm calls a reply costs, and how often each
fallback fires (a redone draft, an answer retry, the rewrite in her style, a refocus, an explicit line held back, a
line fixed because she talked about herself in third person). Her memory is written to her as "you", and older
memories that use her name are rewritten once on startup, after saving a copy as `data/memory.before-voice-fix.db`.
A model call that takes longer than `LLM_TIMEOUT_SEC` is given up on, and after `LLM_PAUSE_AFTER` failures in a row
she stops calling the model for `LLM_PAUSE_SEC` instead of piling up requests on a stuck server.

## Development

```
pip install -r requirements-dev.txt
python -m pytest
ruff check . && ruff format --check .
```

The tests run the real app against fake discord objects (`mitski/testing/`) with the model scripted, so they
need no token, gpu or network.

`evals/` replays conversations through her and checks what she says:

```
python -m evals.replay                                  scripted replies, checks the bot's own logic
python -m evals.replay --live http://127.0.0.1:5111     her real model through llama-server
python -m evals.replay -k greeting --json results.json  only some cases, results saved
```

Cases are one json object per line in `evals/cases/*.jsonl`: who says what, optional config overrides and
setup (`quiet_minutes`, `asleep_hours`, `ignored`), and what to expect (`reply`, `silent`, `contains`,
`not_contains`, `matches`, `max_messages`). The report ends with time and llm calls at p50 and p95, and how
often each fallback fired. With `--live`, that fallback rate is the number to compare when you train a new lora.

## Training her lora

1. Get her old messages into `data/messages.jsonl` (see [Scraping messages](#scraping-messages)), and set `PERSONA`,
   `STYLE_NOTE` and `NAME_TRIGGERS` in `mitski.yaml` first. Training reads them from there, along with `TIMEZONE`.
2. `python -m training.prep_data` makes `data/train.jsonl`, `data/val.jsonl`, `data/preview.txt` and
   `data/persona.yaml`, a copy of the text she's trained with. The bot has to use that same text, so if you change
   `PERSONA` or `STYLE_NOTE` afterwards, her lora should be trained again.
3. `python -m training.train_qwen` trains the lora on the 0bserverx model (`BASE_MODEL`) and writes
   `out_mitski2/mitski-lora-f16.gguf`.

Examples longer than `MAX_SEQ_LEN` lose their oldest messages until they fit instead of being skipped, and every
example's masking is checked before training starts. Some examples where she answered a question get the same
`What to tell them: ...` note the bot gives her at runtime, so the lora learns to use it.

Both scripts build prompts with `mitski/llm/prompt_format.py`, the same code the bot uses, so what she's
trained on looks exactly like what she sees when she runs. Run them from the project folder.

### Scraping messages

`training/message_scraper.py` collects one person's discord messages into the jsonl file `prep_data` reads.

1. Run `python training/message_scraper.py` once. It creates `training/config/config.yaml` and exits.
2. In that file set `TOKEN` (a user account token), `TARGET_ID` (whose messages to collect) and, to stick to one
   server, `GUILD_ID`. Messages are saved to `data/messages.jsonl`, where `prep_data` reads them. `OUTPUT` changes
   that path, relative to the project folder.
3. Run it again. It searches every server the account is in (or just `GUILD_ID`), age-restricted channels included,
   oldest messages first. After that it keeps running and saves new messages as they're sent, until you stop it.

It remembers where it got to in `progress.json` next to the output file, so you can stop and restart it without
getting duplicates. If discord is still indexing a server's old messages it tells you, and a later restart picks up
what it missed.

Each line has the message, its server, channel and time, the message it replied to, and up to `CONTEXT_MSGS` messages
before it. Those are marked `target` or `other`, without names. Mentions are removed, links too unless `KEEP_URLS` is
on, and messages with only an attachment are skipped. Context takes one extra request per message, and
`REQUEST_DELAY` sets the pace.

The output includes other people's messages, so scrape your own account or someone who's agreed to it, and keep the
file private. The scraper runs on a user account like the bot does, so the warning at the top of this page applies
here too.

## Layout

```
mitski/
  __main__.py      entry point
  app.py           builds every service and wires the discord events
  paths.py         where config, data and mp3 live (MITSKI_HOME)
  report.py        the startup summary
  config/          the option schema (all defaults live here), settings, the yaml templates
  core/            logging, storage, background tasks, bounded containers, metrics, clock, text helpers
  llm/             llama-server client, helper model, prompt formats, gpu queue
  chat/            routing, the reply pipeline, context, drafts, review, sending, typing style, state
  brain/           planning before a reply, tools, web search, math, answer checks
  memory/          people and herself, notes, recall, embeddings, games and music over time
  media/           emojis, stickers, reactions, gifs, youtube
  vision/          finding images in messages, frames, captions
  voice/           joining and leaving vc, picking a room, typing sounds
  social/          owner, quiet and sleep, routine, dms, profiles
  reminders/       parsing times, the store, sending them
  admin/           commands and the log itself
  testing/         fake discord objects and a scripted world, used by tests and evals
tests/             unit and integration tests
evals/             conversation replays
training/          message scraper, data prep and lora training
config/            mitski.yaml (settings) and keys.yaml (token and keys), made on first run (not in git)
data/              memory.db, caches and training data (not in git)
mp3/               keyboard sounds for voice chat (not in git)
models/            gguf model files (not in git)
```
