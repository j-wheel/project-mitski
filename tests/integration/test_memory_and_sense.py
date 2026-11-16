from types import SimpleNamespace

from mitski.llm.helper import HelperModel
from mitski.testing.fakes import FakeMessage, settle


def remembering(world):
    world.app.cfg.MEMORY = True
    world.app.memory.enabled = True


def herself(world):
    cfg = world.app.cfg
    cfg.HER_AGE, cfg.HER_GENDER, cfg.HER_FROM, cfg.HER_CITY = 20, "girl", "Portugal", "Lisbon"
    from mitski.core.identity import Identity

    world.app.identity = Identity(cfg)


# her own facts


async def test_getting_her_own_age_wrong_is_redone(world):
    herself(world)
    world.replies += ["im 21 lol", "im 20 lol"]
    await world.send(world.people["anna"], "mitski how old are u")
    assert world.sent_text() == ["im 20 lol"]
    assert "you're 20" in world.prompts[0] and "You got something about yourself wrong" in world.prompts[-1]


async def test_saying_shes_from_somewhere_else_never_goes_out(world):
    herself(world)
    sent = await world.app.sender.send(world.channel, ["im from spain actually", "anyway hi"])
    assert [m.content for m in sent] == ["anyway hi"]


async def test_wrong_things_she_remembers_about_herself_are_forgotten(world):
    herself(world)
    remembering(world)
    own = world.app.memory.own
    own["facts"] = [
        {"id": 1, "text": "is 21 years old", "cat": "life", "t": 0},
        {"id": 2, "text": "plays cs2 a lot", "cat": "games", "t": 0},
    ]
    world.app.memory.fix_own_voice()
    assert [f["text"] for f in own["facts"]] == ["plays cs2 a lot"]


# random replies


async def test_just_saying_hi_to_a_question_is_redone(world):
    world.replies += ["hii everyone", "it was good, kinda long tho"]
    await world.send(world.people["anna"], "mitski how was class")
    assert world.sent_text() == ["it was good, kinda long tho"]
    assert "you just said hi out of nowhere" in world.prompts[-1]


async def test_saying_hi_back_to_a_hi_is_fine(world):
    world.replies.append("heyyy")
    await world.send(world.people["anna"], "mitski hiii")
    assert world.sent_text() == ["heyyy"]


async def test_the_fit_check_runs_one_on_one_too(world):
    checked = []

    async def ask_json(system, user, schema, max_tokens=400, think=False):
        if "mixed_up" in (schema or {}).get("properties", {}):
            checked.append(user)
            return {"fits": True, "to": 1, "mixed_up": False}
        return None

    world.app.cfg.ADDRESSEE_CHECK = True
    world.app.helper.ask_json = ask_json
    world.replies.append("ya i finished it")
    await world.send(world.people["anna"], "mitski did u finish the project")
    assert checked and world.sent_text() == ["ya i finished it"]


# limits


async def test_a_reply_cut_off_by_max_tokens_loses_the_unfinished_end(world, monkeypatch):
    async def generate(prompt, *args, raw=False, **kwargs):
        world.prompts.append(prompt)
        data = {"content": "ok so basically\nthe thing is that the whole proj", "stop_type": "limit"}
        return data if raw else data["content"]

    monkeypatch.setattr(world.app.llm, "generate", generate)
    await world.send(world.people["anna"], "mitski explain")
    assert world.sent_text() == ["ok so basically"]


async def test_a_helper_answer_that_ran_out_of_room_gets_more(world, monkeypatch):
    sizes = []

    async def generate(prompt, *args, n_predict=None, raw=False, **kwargs):
        sizes.append(n_predict)
        if len(sizes) == 1:
            return {"content": '{"say": "half', "stop_type": "limit"}
        return {"content": '{"say": "whole answer"}', "stop_type": "eos"}

    monkeypatch.setattr(world.app.llm, "generate", generate)
    out = await HelperModel.ask_json(world.app.helper, "sys", "user", {"type": "object"}, 100)
    assert out == {"say": "whole answer"} and sizes == [100, 200]


async def test_a_prompt_too_big_for_the_context_leaves_out_the_oldest_messages(world):
    llm = world.app.llm
    turns = [["user", f"message number {i} " * 20] for i in range(60)]
    llm.info.n_ctx = 2000
    text = llm.prompt(turns, "persona", "notes")
    assert "message number 59" in text and "message number 0 " not in text
    llm.info.n_ctx = 0
    assert "message number 0 " in llm.prompt(turns, "persona", "notes")


# memory


async def test_she_reads_their_discord_profile(world):
    remembering(world)
    anna = world.people["anna"]
    world.app.memory.touch(anna, "hi")
    profile = SimpleNamespace(
        bio="cs2 addict | lisbon",
        metadata=SimpleNamespace(pronouns="she/her"),
        connections=[SimpleNamespace(type=SimpleNamespace(value="spotify")), SimpleNamespace(type="steam")],
    )
    world.app.memory.saw_profile(anna, profile)
    blurb = world.app.memory.blurb(anna)
    assert 'bio "cs2 addict | lisbon"' in blurb and "she/her" in blurb and "spotify, steam" in blurb


async def test_she_googles_what_people_are_into_once(world, monkeypatch):
    knowledge = world.app.knowledge
    world.app.search.provider = "ddg"
    searched = []

    async def search(query):
        searched.append(query)
        return "- Laufey: Icelandic jazz-pop singer-songwriter"

    async def ask_json(system, user, schema, max_tokens=400, think=False):
        return {"known": True, "what": "an Icelandic jazz-pop singer-songwriter"}

    monkeypatch.setattr(world.app.search, "search", search)
    world.app.helper.ask_json = ask_json
    knowledge.want(["laufey (singer)"], "anna")
    await settle(world.app)
    knowledge.want(["Laufey (singer)"], "anna")
    await settle(world.app)
    assert searched == ["laufey (singer)"]
    assert "Icelandic jazz-pop" in knowledge.note("omg do u like laufey??")
    assert knowledge.note("what game do u play") == ""


async def test_she_keeps_notes_about_the_server(world):
    servers = world.app.servers

    async def ask_json(system, user, schema, max_tokens=400, think=False):
        if "new_facts" in (schema or {}).get("properties", {}) and "wrong" in schema["properties"]:
            return {"new_facts": ["people here mostly play cs2", "friday movie nights"], "wrong": []}
        return None

    world.app.helper.ask_json = ask_json
    for i in range(25):
        msg = FakeMessage(world.channel, world.people["anna"], f"gg that round {i}")
        servers.heard_in(msg)
    await settle(world.app)
    blurb = servers.blurb(world.guild)
    assert "mostly play cs2" in blurb and "friday movie nights" in blurb
    world.replies.append("lol")
    await world.send(world.people["bob"], "mitski hey whats up")
    assert "mostly play cs2" in world.prompts[0]
