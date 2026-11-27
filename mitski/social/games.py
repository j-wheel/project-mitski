import re

from mitski.core.texts import fill, wording

SESSIONS = wording("life.game_sessions")
SHORT = {
    "cs": "counter-strike",
    "cs2": "counter-strike",
    "csgo": "counter-strike",
    "val": "valorant",
    "valo": "valorant",
    "lol": "league of legends",
    "league": "league of legends",
    "mc": "minecraft",
    "ow": "overwatch",
    "ow2": "overwatch",
    "rl": "rocket league",
    "genshin": "genshin impact",
    "hsr": "honkai: star rail",
    "sims": "the sims",
    "fn": "fortnite",
    "apex": "apex legends",
}
GENERIC = {"the", "of", "and", "a", "an", "game", "games", "online", "edition", "remastered", "simulator", "world"}


def words(text):
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def match(text, games):
    said = words(text)
    if not said:
        return ""
    short = {alias: " ".join(words(full)) for alias, full in SHORT.items()}
    low = " ".join(said)
    expanded = " ".join(short.get(w, w) for w in said)
    for game in games:
        name = " ".join(words(game))
        if name and (f" {name} " in f" {low} " or f" {name} " in f" {expanded} "):
            return game
    for game in games:
        name = " ".join(words(game))
        if any(w in short and name.startswith(short[w]) for w in said):
            return game
        distinct = [w for w in words(game) if len(w) >= 4 and w not in GENERIC]
        if distinct and any(w in said for w in distinct):
            return game
    return ""


def session(game, rng):
    return fill(rng.choice(SESSIONS), game=game)
