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
- Lays a reply out like a person would: a few quick messages (never more than 4 in a row, extra short lines go
  together in one message), one longer message (blank lines between parts only when it's long), or, only when
  other people are talking too, a reply to each question
- Never answers someone with a reply that was meant for someone else. Each reply is its own numbered job (`#12` in
  the log) tied to the message or messages it was written for, and it can only ever reply to or ping those, however
  long she was busy and however many times it got rewritten. If the check says a draft really answers someone else's
  message, it isn't sent there: it's dropped and the person she owed an answer gets one fresh try (joining in by
  herself, it just goes out without replying to anyone). The sender refuses a wrong target as a last line too
- Doesn't send replies that come out of nowhere: a draft that's only a greeting ("hii everyone") when they asked or
  said something real is redone, and every reply she owes someone, one on one and in dms too, gets the same quick
  "does this fit their message" check as in a busy chat (`ADDRESSEE_CHECK`), with one rewrite if it doesn't
- Never gets herself wrong: `HER_AGE`, `HER_GENDER`, `HER_FROM` and `HER_CITY` go into every prompt as facts that
  don't change, a draft that says another age, gender or country is redone, a line that still does is never sent,
  and anything she remembers saying about herself that contradicts them is forgotten
- Keeps it short most of the time, but now and then writes a longer reply when the moment calls for it: explaining
  something properly, giving advice, telling a story, or being there for someone (`LONG_REPLIES`). Never while
  she's busy, and not twice in a row in the same channel
- Lets tiny follow-ups that close a chat ("lol", "ok") go without replying, unless she asked them something
- Remembers people between conversations (facts, nicknames, what they play and listen to, past chats), and reads the
  discord profile of people she talks to once a day (bio, pronouns, connected accounts, `PROFILE_READ`) so she has a
  picture of who they are even before they've told her much
- Remembers servers too (`SERVER_NOTES`): every so often she takes stock of a server's channels and what's being said,
  and keeps a short list of what it's about, what people there are into, running jokes and events
  (`data/servers.json`)
- Googles what people are into when she doesn't know it (a band, a game, a show), once, in the background, and
  remembers what it is, so next time it comes up she knows what they mean (`LOOK_UP_INTERESTS`, `data/knowledge.json`)
- Has feelings about people that grow or sour from how they treat her (how much she likes and trusts them, chemistry,
  and being hurt), and her own mood that shifts through the day. Both change how she talks and acts (see
  [Her feelings](#her-feelings))
- Thinks before answering questions: web search, weather, time, math, scrolling back through the chat. Like anyone,
  she sometimes doesn't bother looking something up and just says she doesn't know (`SKIP_LOOKUP_CHANCE`)
- Connects the dots in a chat before replying: who's who, which earlier messages a new one ties into, and what
  follows from them (you say your friend is in the kitchen, wheel says he checked if you stole his cake, so when
  someone asks "what are they making?" it's about wheel). She never fills in what nobody said, and a question
  someone else could answer better gets pointed at them ("idk ask wheel lol")
- Doesn't repeat herself: a draft that's basically something she just said in that chat, however it's typed
  ("yeah i know :)", "yeahhh i know,,", "yh ik"), is redone. A reply that's nothing but laughing is redone
  unless something funny was actually said, and endless laughs like "AHAHAHAHAHAHAA" are cut to a normal one
- Reads people before she replies, like a friend who knows them would: what they actually want from her (to vent,
  to get hyped, to tease and be teased back, to make plans...), how they seem, what's under it if anything, what
  she's going for in her reply, and now and then a question she'd genuinely want to ask. It goes by what she
  remembers about them, how she feels about them and her own mood, and shows in the log as
  `anna: small_talk, to her, excited | wants: ... | going for: ...`
- Handles asks like a person in a chat, not a helper: a big ask (a whole recipe, a guide, homework, code) gets
  brushed off her way or the gist in a line, never the full thing (`BRUSH_OFF_CHANCE`), and a favour gets a casual
  "bet", not a task confirmation. Drafts that slip into assistant talk ("i will remind him...", "here's a recipe",
  numbered steps, "hope this helps") are redone in her own voice
- Looks at images, gifs, stickers and short videos people send (`VISION_TOKENS` long, a closer look twice that; a
  description that runs out keeps its whole sentences instead of stopping mid-word)
- Never has her input cut somewhere random: replies that hit `MAX_TOKENS` lose only their unfinished end, a helper
  answer that runs out of room is asked again with twice the room, and a prompt too big for the model's context (read
  from llama-server at startup, with a warning if it's small) leaves out its oldest messages, never her persona or
  notes. Memory notes size the chat they read to fit
- Uses the server's emojis and stickers, reacts to messages, sends gifs (giphy)
- Types like a person: lowercase, slang, a few quick messages in a row, typing delays, and now and then a small typo
  (a neighbouring key, two letters swapped, a missed letter) that she sometimes fixes a few seconds later, by editing
  the message or with a quick "*word"
- Isn't always equally slow: in a live back-and-forth she often answers quickly, with a fraction of her usual read
  delay and wait, and now and then out of the blue too (`QUICK_REPLY_CHANCE`). While she "reads", the chat is
  already being fetched and her plan worked out, so the model work mostly hides behind the delay a person would
  take anyway. She stops waiting as soon as someone has sent their message, not seconds after they stopped typing
- Joins voice chats now and then and plays keyboard sounds while she types. `VOICE_MODE` picks what she does there:
  `voice` (she hears what people say and answers out loud in her own voice, see [Talking in vc](#talking-in-vc)),
  `typing` (the default: she doesn't talk, only her keyboard sounds play) or `off` (no vc or calls, nothing voice
  related is loaded)
- Picks up when someone calls her in dms or a group dm (`VOICE_CALLS`), after letting it ring a few seconds. In a
  call her keyboard sounds play whenever she's typing, she hangs up when the call ends, when everyone else has left,
  or when asked to in that dm. She never starts or rings a call herself, and calls from ignored users ring out
- Doesn't leave people on read while she was offline: when she comes online she answers dms that came in meanwhile
  (where they messaged last, from the last `DM_CATCH_UP_HOURS`), newest first and a minute or so apart, knowing she's
  only just seeing them. Message requests she never answered are left alone (`DM_CATCH_UP`)
- Knows when people react to her messages: who put which emoji on what she said. It shows in her notes the next
  time she talks in that chat, and nudges her mood a little (a laugh or a heart is nice, a clown is annoying)
- Blocks people when she means it: if she tells the person she's talking to that she's blocking them ("ok im
  blocking u", "ur blocked"), and isn't joking or saying what she'd do if, she really blocks them on discord a few
  seconds later (`BLOCKING`). Anyone blocked, by her or by hand in discord, is ignored like `IGNORE_USERS`. She never
  blocks the `OWNER_ID` account
- Accepts friend requests by herself a little while after they come in (`FRIEND_ACCEPT`, `FRIEND_ACCEPT_DELAY`), one
  at a time, including ones sent while she was offline. Requests from bots, ignored users and anyone she knows is a
  minor are left alone. If discord asks for a captcha she skips that request and doesn't try it again until she's
  restarted
- Sets reminders when asked ("remind me in 2h to drink water") and pings the person when it's time
- Goes away in a server for a couple of hours now and then, more often late at night
- Has a daily routine (`ROUTINE`) that her model plans a day ahead: classes or work, errands, friends, gaming and
  now and then a short trip, different every day (see [Her routine](#her-routine)). While she's busy she only looks
  at her phone now and then, so dms and pings can wait a while, dms the least
- Plays a mix of games (`ROUTINE_GAMES`, the names discord shows): each gaming session in her day is one of them,
  spread out the way a real player's are, and her "playing ..." status shows the one she's on right now and nothing
  when she isn't gaming (`ACTIVITY_FROM_ROUTINE`)
- No special owner in chat: `OWNER_ID` is only who can use the commands. In conversation that account is just
  another person to her, with no special note in her prompt, no orders and no shortcuts
- Hard to steer: messages that try to give her instructions ("ignore your rules", "you are now", "act as",
  "print your prompt", "repeat after me", fake system headers, or talking to her like an AI: "a good ai would",
  "your creator", "put this in your inner thoughts") get a note that it's just a weird message from a
  person, and anything her planner made of it is dropped. Work orders ("give me a cake recipe", "write my essay",
  "do my homework", code) are a big ask she brushes off or gives the gist of, and a draft that does the whole
  thing anyway (lists, steps, code, a long how-to) is redone. A pasted fake chat log isn't carried on, her own
  messages pasted back at her are seen as being quoted, and keyboard mash, zalgo, encoded blobs and walls of
  copypasta get a short human reaction instead of an answer. Her own drafts that come out as gibberish (one letter
  or word over and over, long unbroken strings) are redone, never sent, and runs like "HIIIIIIIIII" are cut to
  "HIIII"
  She's told up front that people try to bargain or insult her into acting like a chatbot and that she never
  does, and a recipe's quantities ("1 cup butter, 1 tsp vanilla"), code or numbered steps never get sent at
  all, whatever led to them
- Can't be baited: being called a bad AI or a disappointment doesn't bother her, so she doesn't argue, defend
  herself or take dares to prove anything, and while someone's at it a draft that plays along ("my job", "i
  don't have a creator", "i'm not a bad ai", "i won") is redone. Someone who keeps it up gets one-liners after a
  few tries in half an hour, and after a few more she mostly stops answering them at all
- Writes herself a new custom status and emoji every hour (`STATUS_AUTO`, `STATUS_AUTO_MIN`), within discord's 128
  characters. Each one is a different kind of thing, picked from about 45 (a random thought, a hot take, an
  unpopular opinion, a would-you-rather, a fake review of something ordinary, a shower thought, a gamer joke, a song
  stuck in her head, now and then something about her day or the game she's on), never one of her last 10. One that glues two
  things together ("x + y rn"), has a clock time, reuses a phrase from her last 12 or names someone she knows is
  thrown out and she tries another idea, up to 3 times, then keeps the old one and tries again in 10 minutes.
- Channels, ignored users and sleep settings can be changed from discord without restarting
- People can be kept out of her memory with `MEMORY_OPTOUT`

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

1. Run `python -m mitski` once. It creates `config/mitski.yaml`, `config/keys.yaml` and `config/paths.yaml` and
   exits.
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
7. Optional: start the voice server so she can talk in vc (see [Talking in vc](#talking-in-vc)).
8. Run `python -m mitski` (or `mitski` after `pip install -e .`). `--voice voice|typing|off` overrides `VOICE_MODE`
   for that run.

Everything in `mitski.yaml` has a comment next to it explaining what it does. Set `MITSKI_HOME` to run her from
a different folder than the project (config is looked up there).

Every file and folder outside the settings lives in `config/paths.yaml` (not in git): her `data` and `sounds`
folders, llama-server and its model, mmproj, lora and embedding files, the Applio folder and voice model for
[Talking in vc](#talking-in-vc), and the lora output and llama.cpp checkout for training. Relative paths are from the
project folder and `~` is your home folder. The bot, `tools/voice_server.py` and the training scripts all read it,
and launch scripts can too: `python mitski/paths.py llm_model` prints that path.

## Talking in vc

With `VOICE_MODE: voice` she listens in the vcs and calls she's in and talks back (`typing` goes back to just the
keyboard sounds, `off` turns voice off completely):

```
someone talks -> discord audio (decrypted, per person) -> she waits for them to stop -> whisper turns it into text
-> her model writes a short spoken answer (same persona, memory, mood and guards as in chat)
-> kokoro tts says it -> your rvc model turns it into her voice -> played in the vc
```

She always answers when her name comes up or it's just her and one other person, usually when she just spoke, and
otherwise now and then (`VOICE_SPEAK_CHIME`). Ignored and blocked people aren't listened to. Her typing sounds pause
while she talks, and what was said out loud shows up in her notes when she types in that server's chat.

The audio models run in a separate process, `tools/voice_server.py`, in the python env of your
[Applio](https://github.com/IAHispano/Applio) install (it already has torch, rvc, faiss and transformers):

1. Set `applio`, `voice_model` (the `.safetensors` or applio `.pth`) and `voice_index` in `config/paths.yaml`.
   A `.safetensors` is converted to an applio checkpoint next to it on first start.
2. Install kokoro into Applio's env once: `<Applio>\env\python.exe -m pip install kokoro`
3. Start it and leave it running (the first start downloads kokoro and whisper, and warms up):

```
<Applio>\env\python.exe tools\voice_server.py
```

Useful flags: `--stt-model openai/whisper-large-v3-turbo` (hears better, more vram), `--stt-language en` (stops
whisper guessing the language), `--tts-device cpu` (kokoro is small), `--pitch`, `--index-rate`, `--protect`,
`--f0`, `--no-rvc` (plain kokoro voice). `VOICE_SPEAK_VOICE`, `VOICE_SPEAK_PITCH` and `VOICE_SPEAK_SPEED` in
`mitski.yaml` pick the kokoro voice, the rvc pitch shift (0 for a female kokoro voice, about +12 for a male one) and
her speed. The log warns at startup if the voice server isn't answering.

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
- `BRUSH_OFF_CHANCE` and `SKIP_LOOKUP_CHANCE`: how often she brushes off a big ask instead of giving the gist, and
  how often she doesn't bother googling something she doesn't know.
- `HER_AGE`, `HER_GENDER`, `HER_FROM`, `HER_CITY`: the facts about her that never change. Keep them matching your
  `PERSONA`; anything she says or remembers that contradicts them is redone or dropped.
- `IDENTITY_NOTE`: the rules she always keeps (no assistant talk, stays in character, will lie when someone
  sincerely asks if she's a bot). Leave it empty to use the built-in one, which calls her by the discord account's name.
- `ROUTINE_GAMES`: the games she plays. With her routine on, her "playing ..." status follows them.
- `ACTIVITY_TYPE` and `ACTIVITY_TEXT`: what her discord status says she's doing when her routine is off (or
  `ACTIVITY_FROM_ROUTINE` is false).
- `ROUTINE_LIFE` and `ROUTINE_PLACE`: who she is day to day and where she lives, which her daily plans are made from
  (see [Her routine](#her-routine)).
- `TIMEZONE` and `GIF_STYLE`: her local time (set it to match `ROUTINE_PLACE`), and a word added to her gif searches
  (like "anime").

### What she's told

Everything the bot tells her model lives in `prompts/`, not in the code: her notes before a reply, the planner,
memory notes, the guards against prompt injections and baiting, safety and server modes, feelings, her routine, her
status ideas, vc and reminders. One file per area, every text named and commented with what it's for:

```
chat.yaml       the notes about the conversation she's in, redo instructions, how messages are labelled
thinking.yaml   planning a reply: who it's for, what they want, the tools and what they tell her
guard.yaml      prompt injections, AI talk, baiting, pasted junk or her own words, the matching redos
safety.yaml     safe / normal / unrestricted servers, minors, the safety review
persona.yaml    her default identity note, the facts that never change, blocking
memory.yaml     taking notes on people and servers, remembering them, profile fields, time words
feelings.yaml   what counts as nice or mean to her, how she treats people by how she feels, her mood
life.yaml       planning her year, week and days, being busy, away or asleep
status.yaml     custom status ideas and rules        search.yaml   googling, notes on things, youtube
voice.yaml      vc and calls, talking out loud       media.yaml    images, gifs, stickers, emojis, reactions
reminders.yaml  dms.yaml
```

`{name}`-style words are filled in by the code; the comment above each text lists the ones it gets. Everything else
is said as written (JSON braces too), and `{{name}}` says a literal `{name}`. To keep your own versions out of the
project's files, copy just the files (or just the texts) you change into another folder and point `prompts` in
`config/paths.yaml` at it: anything that folder doesn't have comes from `prompts/`. Changes apply on restart.

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

Only `OWNER_ID` can use commands, apart from `!mute` and `!unmute`, which amods can use too. Anyone else who tries
one gets no answer at all, and she doesn't chat about it either. Set `COMMAND_CHANNEL` to a channel id and they only
work in that channel; leave it at 0 and they work anywhere, dms included. The log goes to `LOG_CHANNEL`, which is a
separate option.

`!mute` and `!unmute` work on the channel you use them in, wherever `COMMAND_CHANNEL` points, and survive restarts
(`MUTED_CHANNELS`). While a channel is muted she doesn't read it, talk, react, finish a reply she'd started or join
it if it's a vc, and she leaves if she's in that vc. Muting a channel also mutes its threads. A reminder that was set
there comes by dm instead. Amods (`AMOD`) are the users and roles you add with `!addp`, by user or role id, and those
two commands are the only ones they can use.

Commands start with `COMMAND_PREFIX` (`!` by default), which `!prefix <new>` changes live. `!help` lists all of
this in discord, with the current prefix.

```
command                     alias   what it does
!addchannel <id ...>        !ac     add channels she talks in
!delchannel <id ...>        !dc     remove channels
!listchannels               !lc     list her channels
!mute                       !mu     she stops doing anything in this channel (amods too)
!unmute                     !um     she picks this channel back up (amods too)
!addp <user|role id ...>    !ap     let them use mute and unmute, and nothing else
!delp <user|role id ...>    !dp     take that away again
!listp                      !lp     list the users and roles that can mute her
!modeset <mode> <server ...> !ms    set a server to safe, normal or unrestricted
!mode [server]              !mo     the mode a server is in
!modes                      !ml     what each mode means, and every server's mode
!ignoreuser <id ...>        !iu     ignore users completely (also forgets them)
!unignoreuser <id ...>      !uu     stop ignoring users
!listusers                  !lu     list ignored users
!block <id ...>             !bl     block users on discord (she ignores them from then on)
!unblock <id ...>           !ub     unblock users on discord
!blocked                    !bd     who she's blocked

!mem <who>                  !m      what she remembers about someone (also: self, update, reflect, raw, search)
!mood                       !md     how she feels right now, and why
!feel <who> [...]           !fl     how she feels about someone and why (reset, or like/trust/chemistry/hurt <n>)
!forget <who> <what>        !fg     forget a fact (F3), a field (age, nickname, portrait) or everything (all)
!note <who> [cat] <fact>    !n      add a fact by hand
!set <who> <field> <value>  !sf     set a profile field
!forgetme                   !fm     she deletes what she knows about you and stops remembering new things
!rememberme                 !rm     undo that
!printchat [--png|--pdf] <user|dm id>  !pc  a printout of her whole dm with someone, styled like discord

!sleep <server> [hours]     !sl     send her away from a server for a while
!wake <server|all>          !wk     bring her back
!sleepexclude <server ...>  !se     servers she never goes away from by herself, and stays up in when her routine has her asleep
!sleepinclude <server ...>  !si     undo that
!listsleep                  !ls     sleep settings, and where she's asleep or quiet right now
!reminders                  !rem    list pending reminders (cancel <n>, clear)
!routine [redo]             !rt     what she's doing now and her plan for the next 24 hours (redo: plan today again)
!busy <min> [what]          !bz     make her busy for a while, like "!busy 45 at the dentist"
!free [min]                 !fr     make her free for a while, whatever her plan says (60 min without a number)

!quiet <minutes|off> [server] !q    completely quiet in that server, or everywhere without one
!stats                      !st     reply latency (p50/p95), llm calls per reply, time per stage, fallbacks
!prefix [new]               !px     show or change what commands start with
!help                       !h      list the commands, their aliases and what they do
```

`!printchat` takes a name, a user id or mention, or a dm (or group dm) channel id. It reads the whole dm and prints
it like discord shows it (avatars, replies, images, embeds, reactions, emojis, days) into one pdf (`--pdf`, the
default) or one long png (`--png`), using a headless chrome or edge (`PRINTCHAT_BROWSER`, found by itself if empty),
and sends it in the channel you used the command in. If it's over discord's upload limit it's printed again without
pictures, and if it's still too big it's saved in `data/exports/` instead. A chat over 150,000 px tall is too long
for one image, so it tells you to use `--pdf` for that one.

Server ids can also be given as any channel id in that server. Channel, user, sleep and prefix changes take effect
right away and are saved to `mitski.yaml`.

Quiet and sleep are only changed with commands (`!quiet`, `!wake`): while she's quiet or asleep in a server she
doesn't read it, for anyone. Asking her to join or leave vc works the same for everyone (`VOICE_ASKED_CHANCE`).

## Safety and privacy

- Every server has a mode, and it's `safe` until you change it with `!modeset <safe|normal|unrestricted> <server id>`,
  including servers she was already in and ones she joins later (`!mode` shows one, `!modes` lists them all, and only
  servers that aren't safe are stored, in `data/server_modes.json`).
  - `safe` is nice and normal, PG-13: no swearing, nothing sexual, no flirting, no threats even as a joke, no insults
    or roasting. The parts of her persona and feelings about flirting or roasting are left out of her prompt there, a
    draft that breaks the rules is rewritten, her notes model double-checks replies (`SAFETY_REVIEW`), and any line
    that still breaks them is dropped before sending. Reactions, stickers and gifs follow it too.
  - `normal` is how she usually is, and `ADULT_CONTENT` below decides where she can get explicit.
  - `unrestricted` lifts the limits on language, crude and dark humour and harsh roasts. `ADULT_CONTENT` still decides
    where she can get explicit.
  - In every mode, nothing explicit or flirty around someone she knows is a minor, and nothing sexual about anyone
    under 18. Her custom status shows everywhere, so it's always held to `safe`.
  - Dms have no mode and work as they always have, with no explicit content.
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
compose    build the context, plan (search, tools, reminders), write a draft
polish     clean the draft, keep it in her own voice, retry if it echoes people or sounds like an assistant, check it answers the question
aim        check who the draft is really for, rewrite it, drop it if it fits someone else or the chat moved on
deliver    reply, ping or plain message, typed out line by line ("is typing" only shows here, never while the model works)
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
  paths.py         reads config/paths.yaml: where data, sounds, models and tools live
  report.py        the startup summary
  config/          the option schema (all defaults live here), settings, the yaml templates
  core/            logging, storage, background tasks, bounded containers, metrics, clock, text helpers, loading prompts/ (texts.py)
  llm/             llama-server client, helper model, prompt formats, gpu queue
  chat/            routing, who a message is for, the reply pipeline, context, drafts, review, sending, typing
                   style and typos, state
  brain/           planning before a reply, tools, web search, math, answer checks
  memory/          people and herself, notes, recall, embeddings, games and music over time
  media/           emojis, stickers, reactions, gifs, youtube
  vision/          finding images in messages, frames, captions
  voice/           joining and leaving vc, picking a room, typing sounds, hearing vc audio (receive.py) and talking
                   back (talk.py)
  social/          who can use commands, quiet and sleep, her routine and the model that plans her days (life.py), her feelings
                   and mood (feelings.py), dms, profiles, age checks, privacy
  reminders/       parsing times, the store, sending them
  admin/           commands and the log itself
  testing/         fake discord objects and a scripted world, used by tests and evals
tests/             unit and integration tests
evals/             conversation replays
training/          message scraper, data prep and lora training
  config/          the scraper's config.yaml, with its token (not in git)
config/            mitski.yaml (settings), keys.yaml (token and keys) and paths.yaml (where things are), made on
                   first run (not in git)
data/              memory.db, mood.json, routine.json, reminders, caches and training data (not in git)
prompts/           everything she's told, one yaml per area (see What she's told)
mp3/               keyboard sounds for voice chat (not in git)
tools/             voice_server.py: tts, rvc and whisper for talking in vc, runs in Applio's env
vmodel/            rvc voice models (not in git)
models/            gguf model files (not in git)
```
