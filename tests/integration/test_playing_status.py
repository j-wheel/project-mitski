from datetime import timedelta

import discord

from mitski.social import routine as rt
from mitski.social import status


def routine_on(world, level=None, what="", game=""):
    routine = world.app.routine
    routine.on = True
    routine.days = {}
    routine.week = rt.Week(None, None, "", (), (0, 0), (), (0, 0))
    routine.forced = None
    if level:
        now = routine.now()
        routine.forced = rt.Spell(now, now + timedelta(hours=2), level, what, game)
    return routine


def playing(world):
    acts = world.client.presence["activities"]
    return [a.name for a in acts if a.type is discord.ActivityType.playing]


async def test_her_playing_status_is_the_game_her_routine_has_her_on(world):
    world.app.cfg.ROUTINE_GAMES = ["VALORANT", "Minecraft"]
    routine_on(world, rt.GAMING, "playing minecraft with friends", "Minecraft")
    await world.app.profiles.apply()
    assert playing(world) == ["Minecraft"]


async def test_an_older_plan_without_a_game_still_shows_the_right_one(world):
    world.app.cfg.ROUTINE_GAMES = ["Counter-Strike 2", "VALORANT"]
    routine_on(world, rt.GAMING, "in a ranked cs match")
    await world.app.profiles.apply()
    assert playing(world) == ["Counter-Strike 2"]


async def test_not_gaming_means_no_playing_status(world):
    world.app.cfg.ACTIVITY_TYPE, world.app.cfg.ACTIVITY_TEXT = "playing", "Roblox"
    routine_on(world, rt.BUSY, "at uni")
    await world.app.profiles.apply()
    assert playing(world) == []


async def test_without_a_routine_the_config_activity_is_used(world):
    world.app.cfg.ACTIVITY_TYPE, world.app.cfg.ACTIVITY_TEXT = "playing", "Roblox"
    world.app.routine.on = False
    await world.app.profiles.apply()
    assert playing(world) == ["Roblox"]


async def test_following_the_routine_can_be_turned_off(world):
    world.app.cfg.ACTIVITY_TYPE, world.app.cfg.ACTIVITY_TEXT = "playing", "Roblox"
    world.app.cfg.ACTIVITY_FROM_ROUTINE = False
    routine_on(world, rt.GAMING, "playing minecraft", "Minecraft")
    await world.app.profiles.apply()
    assert playing(world) == ["Roblox"]


async def test_she_knows_what_shes_playing(world):
    routine_on(world, rt.GAMING, "playing minecraft", "Minecraft")
    assert "playing Minecraft" in world.app.profiles.own_status()


async def test_there_are_plenty_of_kinds_of_status():
    assert len(status.ANGLES) >= 40 and len(set(status.ANGLES)) == len(status.ANGLES)
    assert set(status.ANGLES) >= status.GAME_ANGLES


async def test_a_game_status_knows_what_shes_playing(world):
    routine_on(world, rt.GAMING, "grinding valorant", "VALORANT")
    angle = next(iter(status.GAME_ANGLES))
    assert "you're playing VALORANT right now" in world.app.custom_status._prompt(angle)
