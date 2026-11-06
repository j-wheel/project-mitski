import asyncio
from types import SimpleNamespace as NS

from mitski.vision.service import sticker_description


class MessageSticker:
    """Like discord's StickerItem: no description until it's fetched."""

    def __init__(self, description):
        self.fetched = 0
        self._description = description

    async def fetch(self):
        self.fetched += 1
        return NS(description=self._description)


def test_a_server_sticker_already_has_its_description():
    guild_sticker = NS(description="  disgusted blob  ")
    assert asyncio.run(sticker_description(guild_sticker)) == "disgusted blob"


def test_a_sticker_from_a_message_is_fetched_first():
    stub = MessageSticker("happy cat")
    assert asyncio.run(sticker_description(stub)) == "happy cat"
    assert stub.fetched == 1


def test_a_missing_description_is_empty_and_long_ones_are_cut():
    assert asyncio.run(sticker_description(NS(description=None))) == ""
    assert len(asyncio.run(sticker_description(NS(description="x" * 300)))) == 100
