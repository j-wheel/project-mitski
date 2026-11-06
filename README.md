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
- Answers several messages from one person together: each question when they ask a few different things, and one
  reaction to the whole thing when it's a few remarks in a row, without repeating their words back
- Lays a reply out like a person would: a few quick messages, one longer message, or a reply to each question
- Keeps it short most of the time, but now and then writes a longer reply when the moment calls for it: explaining
  something properly, giving advice, telling a story, or being there for someone (`LONG_REPLIES`). Never while
  she's busy, and not twice in a row in the same channel
- Lets tiny follow-ups that close a chat ("lol", "ok") go without replying, unless she asked them something
- Remembers people between conversations (facts, nicknames, what they play and listen to, past chats)
- Has feelings about people that grow or sour from how they treat her (how much she likes and trusts them, chemistry,
  and being hurt), and her own mood that shifts through the day. Both change how she talks and acts (see
  [Her feelings](#her-feelings))
- Thinks before answering questions: web search, weather, time, math, scrolling back through the chat
- Looks at images, gifs, stickers and short videos people send
- Uses the server's emojis and stickers, reacts to messages, sends gifs (giphy)
- Types like a person: lowercase, slang, a few quick messages in a row, typing delays, and now and then a small typo
  (a neighbouring key, two letters swapped, a missed letter) that she sometimes fixes a few seconds later, by editing
  the message or with a quick "*word"
- Joins voice chats now and then and plays keyboard sounds while she types (she never talks in vc)
- Sets reminders when asked ("remind me in 2h to drink water") and pings the person when it's time
- Goes away in a server for a couple of hours now and then, more often late at night
- Has a daily routine (`ROUTINE`) that her model plans a day ahead: classes or work, errands, friends, gaming and
  now and then a short trip, different every day (see [Her routine](#her-routine)). While she's busy she only looks
  at her phone now and then, so dms and pings can wait a while, dms the least
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
- `TYPO_CHANCE`, `TYPO_FIX_CHANCE`, `TYPO_STAR_CHANCE`, `TYPO_FIX_DELAY`: how often a message gets a small typo
  (about 1 in 25 by default, a bit more in long ones), how often she fixes it, how often that's a quick "*word"
  instead of an edit, and how many seconds later.
- `MAX_LINES`, `LONG_REPLIES`, `LONG_REPLY_COOLDOWN_MIN`: how many messages a reply can be, and whether she
  sometimes writes a longer one when it's called for.
- `IDENTITY_NOTE`: the rules she always keeps (no assistant talk, stays in character, will lie when someone
  sincerely asks if she's a bot). Leave it empty to use the built-in one, which calls her by the discord account's name.
- `ACTIVITY_TYPE` and `ACTIVITY_TEXT`: what her discord status says she's doing.
- `ROUTINE_LIFE` and `ROUTINE_PLACE`: who she is day to day and where she lives, which her daily plans are made from
  (see [Her routine](#her-routine)).
- `TIMEZONE` and `GIF_STYLE`: her local time (set it to match `ROUTINE_PLACE`), and a word added to her gif searches
  (like "anime").

## Her routine

With `ROUTINE: true` she has a life outside discord. While she's in a lecture, at work or asleep she only checks her
phone now and then, and when she's gaming she checks it more often. With `ROUTINE_PLANNER` on (the default), her
model plans it from `ROUTINE_LIFE` in four layers, each one feeding the next:

1. **Her year.** About once a week she googles the academic calendar and public holidays for `ROUTINE_PLACE`, and
   works out whether it's a normal term, exams or a break, and until when.
2. **Her weekly timetable.** Once a semester her model writes the classes (or shifts) she has at the same time every
   week, so her Monday lectures are always on Mondays.
3. **Her week.** Each week it picks a few things that make the week hers, like a project deadline, dinner with
   friends or a gig it found by googling what's on.
4. **Her day.** Each evening it plans tomorrow in detail, from that week's plans, what she did yesterday, the weather
   forecast and what she's already told people about herself, so her days differ and stay consistent.

The code keeps it in bounds. Plans with anything life-changing are thrown out (pregnancy, weddings, new
relationships, expensive things like a Ferrari, hospitals, police, moving, dropping out). She only travels on trips
the code decides on: `ROUTINE_TRIP_CHANCE` a week, never during exams, at least `ROUTINE_TRIP_GAP_WEEKS` apart. Her
model only picks where she goes. Times, overlaps and sleep length are checked too.

Planning runs in the background and gives way to her replies. Plans are kept in `data/routine.json`, so a restart
doesn't change them. Until a day is planned, or if her model can't be reached, she falls back to the simple plan from
`ROUTINE_SLEEP`, `ROUTINE_BUSY`, `ROUTINE_ERRANDS` and `ROUTINE_GAMES`. `!routine` shows what she's doing, her plan for
the next 24 hours and any upcoming trip, and `!routine redo` throws away today's plan and makes a new one.

Servers in `SLEEP_EXCLUDE` (`!sleepexclude`) don't follow her routine's sleep: while she's asleep everywhere else,
she's still up and chatting there. Only sleep is overridden, so a lecture or work still keeps her busy there too.
Her discord status is the same everywhere, so with `ROUTINE_PRESENCE` on it still shows invisible while she sleeps.

## Her feelings

With `FEELINGS` and `MOOD` on (the default), she reacts to people the way a person would, a bit at a time.

**How she feels about each person** is four things, kept with her memory of them:

- **like** (-100 to 100): how fond of them she is, from "can't stand" through neutral to "adore"
- **trust** (0 to 100): builds slowly (being consistent, keeping their word, opening up to her) and drops fast (lying,
  broken promises, fake sweet talk)
- **chemistry** (0 to 100): whether flirting feels natural with them. Always 0 with minors, and pushiness kills it
- **hurt** (0 to 100): being upset with them right now. It fades (halfway in `GRUDGE_HOURS`), faster if they apologize

It changes in two ways. When someone says something to her, she has a gut reaction straight away (an insult
stings, a compliment lifts her mood), which only touches her mood and how hurt she is. Then her memory notes
judge what actually happened, from a fixed list of 28 kinds of moment (shared interests, caring about her,
opening up, making her laugh, keeping a promise, insults, mocking her, fake affection, pushiness, lying, going after
her close friends, ...). Every moment has to quote their real message or it's thrown away, and the numbers come from
the code, not the model.

Only messages that were really said TO her count, for both the gut reaction and the judgment. The code decides
that, not the model: a dm to her, a ping or a reply to her message, her name used to talk to her ("mitski ur
annoying", "hey mitski", not "mitski is annoying"), or an answer straight after something she said to them with
nobody talking in between. Anything that replies to, pings or names someone else never counts, even mid-chat with
her or when she chimes in on it. The one exception is going after someone she's close to, which needs a message
said to that friend. The code also makes it human: bad moments count more than good ones, the same compliment
wears off, a friend's roast stings less, sweet talk from someone she doesn't like counts for less, too much
affection too soon makes her suspicious, it gets harder to move the closer it is to an extreme, and nobody can
move it more than `LIKE_DAILY_MAX` in a day. People she stops talking to slowly drift back to neutral.

What it changes: every reply comes with a note on how she feels about that person and why ("you really like
anna... lately: they loves laufey like you do"). She's warmer and more playful with people she likes, cooler and
curt with people she doesn't, flirts back only where there's chemistry, chimes in more with people she likes,
only starts dms with people she likes, and sometimes leaves small talk on read from people she can't stand
(`LEAVE_ON_READ`). Even when she dislikes someone she never uses slurs or threats or goes after their looks or
identity, and if they're genuinely going through something she drops the attitude.

**Her mood** is a handful of emotions (happy, amused, excited, affectionate, flustered, proud, content, down, lonely,
irritated, stressed, embarrassed, bored, tired). People move them, and so does her day: exams make her stressed,
late nights tired, trips excited, a quiet few hours lonely, and some days are just a bit better or worse. Each one
fades back at its own pace (amused in minutes, stressed over hours), and only the strongest one or two show, gently,
in how she talks. `MOOD_SWING` makes her steadier or moodier.

`!mood` shows her mood and why. `!feel <who>` shows how she feels about someone and the moments behind it, and
`!feel <who> like 40`, `trust`, `chemistry`, `hurt` or `reset` sets it by hand. Her mood is kept in `data/mood.json`.

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
!mood                       !md     how she feels right now, and why
!feel <who> [...]           !fl     how she feels about someone and why (reset, or like/trust/chemistry/hurt <n>)
!forget <who> <what>        !fg     forget a fact (F3), a field (age, nickname, portrait) or everything (all)
!note <who> [cat] <fact>    !n      add a fact by hand
!set <who> <field> <value>  !sf     set a profile field
!forgetme                   !fm     she deletes what she knows about you and stops remembering new things
!rememberme                 !rm     undo that

!sleep <server> [hours]     !sl     send her away from a server for a while
!wake <server|all>          !wk     bring her back
!sleepexclude <server ...>  !se     servers she never goes away from by herself, and stays up in when her routine has her asleep
!sleepinclude <server ...>  !si     undo that
!listsleep                  !ls     sleep settings, and where she's asleep or quiet right now
!reminders                  !rem    list pending reminders (cancel <n>, clear)
!routine [redo]             !rt     what she's doing now and her plan for the next 24 hours (redo: plan today again)
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
  busy. With `FEELINGS` on she also only starts one with people she likes (kept promises still go out). Unprompted
  dms from a user account are also the quickest way to get it flagged.
- If someone sincerely asks whether she's a bot, she will lie about it.
- When someone asks what she knows about another person, she only shares harmless things (games, music, what they
  like). Age, location, relationships, job, school and private facts stay between her and that person.
- People she hasn't talked to in `MEMORY_RETENTION_DAYS` (180) are forgotten.
- How she feels about someone is part of her memory of them, so `!forgetme` deletes it too. For anyone in
  `MEMORY_OPTOUT` it's never used or changed (adding someone to that list by hand doesn't delete what was already
  saved). Only messages said to her can change it. She never builds chemistry with or flirts
  with someone she knows is a minor, and disliking someone never lets her use slurs, threats or attacks on who
  they are.
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
  chat/            routing, who a message is for, the reply pipeline, context, drafts, review, sending, typing
                   style and typos, state
  brain/           planning before a reply, tools, web search, math, answer checks
  memory/          people and herself, notes, recall, embeddings, games and music over time
  media/           emojis, stickers, reactions, gifs, youtube
  vision/          finding images in messages, frames, captions
  voice/           joining and leaving vc, picking a room, typing sounds
  social/          owner, quiet and sleep, her routine and the model that plans her days (life.py), her feelings
                   and mood (feelings.py), dms, profiles, age checks, privacy
  reminders/       parsing times, the store, sending them
  admin/           commands and the log itself
  testing/         fake discord objects and a scripted world, used by tests and evals
tests/             unit and integration tests
evals/             conversation replays
training/          message scraper, data prep and lora training
  config/          the scraper's config.yaml, with its token (not in git)
config/            mitski.yaml (settings) and keys.yaml (token and keys), made on first run (not in git)
data/              memory.db, mood.json, routine.json, reminders, caches and training data (not in git)
mp3/               keyboard sounds for voice chat (not in git)
models/            gguf model files (not in git)
```
