from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS

import discord
import pytest

from mitski.admin import printchat
from mitski.admin.printchat import Row, build_html, find_browser, markdown, rows_from

ANNA, HER = 222222222222222222, 111111111111111111
T = datetime(2026, 11, 7, 21, 40, tzinfo=UTC)


def row(i, who, minutes, text="", **kw):
    return Row(
        id=i,
        author_id=who,
        name="anna" if who == ANNA else "mitski",
        avatar="a.png",
        when=T + timedelta(minutes=minutes),
        text=text,
        **kw,
    )


@pytest.mark.parametrize(
    "text",
    ["<script>alert(1)</script>", '<img src=x onerror="alert(1)">', "</div><style>body{display:none}</style>"],
)
def test_nothing_in_a_message_can_become_markup(text):
    out, _ = markdown(text, {})
    assert "<script" not in out and "<img src=x" not in out and "<style" not in out and "&lt;" in out


@pytest.mark.parametrize(
    ("text", "expect"),
    [
        ("**bold** and *it*", "<b>bold</b> and <i>it</i>"),
        ("`code` here", "<code>code</code> here"),
        ("||secret||", '<span class="spoiler">secret</span>'),
        ("> quoted\nnot", "<blockquote>quoted</blockquote>not"),
        ("see <https://example.com/x>", '<a href="https://example.com/x">https://example.com/x</a>&gt;'),
        ("ok https://example.com/a_b_c.", '<a href="https://example.com/a_b_c">https://example.com/a_b_c</a>.'),
        (f"hey <@{ANNA}>", '<span class="mention">@anna</span>'),
        ("<:pepe:123456789012345678>", "emojis/123456789012345678.png"),
        ("snake_case_word stays", "snake_case_word stays"),
    ],
)
def test_discord_formatting(text, expect):
    assert expect in markdown(text, {ANNA: "anna"})[0]


def test_only_emoji_messages_are_big_like_on_discord():
    assert markdown("😭😭", {})[1] is True
    assert markdown("<:pepe:123456789012345678>", {})[1] is True
    assert markdown("lol 😭", {})[1] is False


def test_messages_close_together_from_one_person_share_a_header():
    page = build_html(
        [row(1, ANNA, 0, "hi"), row(2, ANNA, 2, "u up"), row(3, ANNA, 20, "hello??"), row(4, HER, 21, "ya")],
        "t",
        "s",
        HER,
    )
    assert page.count("class='name") == 3
    assert page.count("class='name her'") == 1


def test_a_new_day_gets_a_separator_and_replies_show_what_they_answer():
    page = build_html(
        [
            row(1, ANNA, 0, "be honest"),
            row(2, HER, 1, "its cute", reply=("anna", "a.png", "be honest")),
            row(3, ANNA, 60 * 24, "gm"),
            row(4, ANNA, 60 * 24 + 1, "", system="started a call that lasted 3 minutes."),
        ],
        "t",
        "s",
        HER,
    )
    assert page.count("class='day'") == 2
    assert "<span class='rname'>@anna</span>" in page
    assert "class='system call'" in page and "started a call" in page


def test_without_pictures_images_become_file_boxes():
    r = row(1, ANNA, 0, "look", attachments=[{"kind": "image", "name": "a.png", "url": "https://x/a.png", "size": 9}])
    assert "class='pic'" in build_html([r], "t", "s", HER)
    page = build_html([r], "t", "s", HER, images=False)
    assert "class='pic'" not in page and "a.png" in page and "class='avatar'" not in page


def fake_message(i, author, text="", minutes=0, **kw):
    return NS(
        id=i,
        author=author,
        content=text,
        created_at=T + timedelta(minutes=minutes),
        edited_at=None,
        type=kw.pop("type", discord.MessageType.default),
        reference=kw.pop("reference", None),
        attachments=kw.pop("attachments", []),
        embeds=[],
        stickers=[],
        reactions=kw.pop("reactions", []),
        mentions=[],
        **kw,
    )


def test_rows_from_messages():
    anna = NS(id=ANNA, name="anna", display_name="anna", display_avatar=NS(url="anna.png"))
    her = NS(id=HER, name="mitski", display_name="mitski", display_avatar=NS(url="her.png"))
    first = fake_message(1, anna, "be honest")
    msgs = [
        first,
        fake_message(2, her, "cute", 1, type=discord.MessageType.reply, reference=NS(message_id=1, resolved=None)),
        fake_message(3, her, "what", 2, reference=NS(message_id=99, resolved=None)),
        fake_message(
            4,
            anna,
            "",
            3,
            attachments=[
                NS(filename="pic.jpg", url="https://x/pic.jpg", content_type="image/jpeg", size=10),
                NS(filename="notes.pdf", url="https://x/notes.pdf", content_type="application/pdf", size=10),
            ],
            reactions=[NS(emoji="😭", count=2)],
        ),
    ]
    rows = rows_from(msgs, UTC)
    assert rows[1].reply == ("anna", "anna.png", "be honest")
    assert rows[2].reply == (None, None, "Original message was deleted")
    assert [a["kind"] for a in rows[3].attachments] == ["image", "file"]
    assert rows[3].reactions == [{"emoji": "😭", "url": "", "count": 2}]


def test_finding_a_browser(tmp_path):
    fake = tmp_path / "chrome.exe"
    fake.write_text("x")
    assert find_browser(str(fake)) == str(fake)
    assert find_browser(str(tmp_path / "missing.exe")) is None
    assert printchat.FREE_UPLOAD < 10 * 1024 * 1024
