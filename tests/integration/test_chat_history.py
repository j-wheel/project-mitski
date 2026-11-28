from datetime import UTC, datetime, timedelta

from mitski.memory.rerank import Reranker
from mitski.testing.fakes import FakeChannel, FakeMessage


def history(world):
    app = world.app
    app.cfg.MEMORY = True
    app.cfg.CHAT_HISTORY = True
    app.chatlog.open()
    return app.chatlog


async def said(world, author, text, ago_min, channel=None):
    msg = FakeMessage(channel or world.channel, author, text)
    msg.created_at = datetime.now(UTC) - timedelta(minutes=ago_min)
    await world.app.router.route(msg)
    return msg


async def test_she_finds_what_was_actually_said_even_without_notes(world):
    log = history(world)
    anna, bob = world.people["anna"], world.people["bob"]
    await said(world, anna, "my dog is called biscuit, hes a golden retriever", 3000, None)
    await said(world, world.her, "omg biscuit is the cutest name", 2999)
    await said(world, bob, "anyone up for ranked later", 2990)
    hits = await log.search(anna, "what is my dogs name")
    assert len(hits) == 1
    assert "biscuit, hes a golden retriever" in hits[0] and "you: omg biscuit is the cutest name" in hits[0]
    out = await world.app.memory.remember(anna, "my dog")
    assert "From your old chats with anna" in out and "biscuit" in out
    assert "found nothing" not in out


async def test_what_was_just_said_isnt_dug_up_as_an_old_memory(world):
    log = history(world)
    anna = world.people["anna"]
    await said(world, anna, "my dog is called biscuit", 2)
    assert await log.search(anna, "dog name") == []


async def test_forgetting_someone_deletes_their_messages_too(world):
    log = history(world)
    anna = world.people["anna"]
    await said(world, anna, "my dog is called biscuit", 3000)
    world.app.memory.forget(anna.id)
    assert await log.search(anna, "dog") == []


async def test_opted_out_ignored_and_log_channel_messages_are_never_kept(world):
    log = history(world)
    anna, bob = world.people["anna"], world.people["bob"]
    world.app.cfg.memory_optout.add(anna.id)
    world.app.cfg.ignored.add(bob.id)
    relay = FakeChannel(world.client, world.guild, "her-log")
    world.app.cfg.LOG_CHANNEL = relay.id
    await said(world, anna, "my dog is called biscuit", 3000)
    await said(world, bob, "my cat is called mochi", 3000)
    await said(world, world.owner, "my fish is called bubbles", 3000, relay)
    assert log.count() == 0


async def test_embeddings_find_it_by_meaning(world):
    log = history(world)
    embed = world.app.memory.embed
    embed.url = "http://embed.test"

    async def call(texts):
        return [[1.0, 0.0] if any(w in t for w in ("dog", "puppy", "pet")) else [0.0, 1.0] for t in texts]

    embed._call = call
    anna = world.people["anna"]
    await said(world, anna, "just got a new puppy!!", 3000)
    await said(world, anna, "ranked later?", 2000)
    hits = await log.search(anna, "how is your pet doing")
    assert hits and "new puppy" in hits[0]


async def test_the_reranker_reorders_what_she_remembers(world):
    log = history(world)
    anna = world.people["anna"]
    await said(world, anna, "my dog is called biscuit", 5000)
    await said(world, anna, "my dog likes the beach", 4000)
    reranker = world.app.memory.rerank
    reranker.url = "http://rerank.test"

    async def rank(query, docs, top_n=None):
        return sorted(((i, 1.0 if "beach" in d else 0.1) for i, d in enumerate(docs)), key=lambda x: -x[1])

    reranker.rank = rank
    hits = await log.search(anna, "my dog", k=1)
    assert len(hits) == 1 and "beach" in hits[0]


async def test_a_reranker_that_scores_everything_the_same_is_turned_off(world, monkeypatch):
    reranker = Reranker(world.app.cfg, lambda: None)
    reranker.url = "http://rerank.test"

    class Resp:
        status = 200

        async def json(self, content_type=None):
            return {"results": [{"index": 0, "relevance_score": 0.0}, {"index": 1, "relevance_score": 0.0}]}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class Http:
        def post(self, *a, **k):
            return Resp()

    reranker.get_http = lambda: Http()
    assert await reranker.rank("q", ["a", "b"]) is None and not reranker.active
