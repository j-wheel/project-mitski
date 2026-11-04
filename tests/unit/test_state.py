import asyncio
import time

from mitski.chat.state import ChatState, Engagement
from mitski.social.away import ALL, Away


def test_sweep_drops_only_stale_entries(make_cfg):
    state = ChatState(make_cfg())
    now = time.monotonic()
    state.engaged[(1, 2)] = Engagement(now - 1)
    state.engaged[(1, 3)] = Engagement(now + 100)
    state.last_typing[(1, 2)] = now - 120
    state.last_typing[(1, 3)] = now
    state.last_msg_time[(1, 2)] = now - 7200
    state.channel_locks[1] = asyncio.Lock()
    state.dm_opened[9] = now - 10**7
    removed = state.sweep(now)
    assert removed == 5
    assert list(state.engaged) == [(1, 3)]
    assert list(state.last_typing) == [(1, 3)]
    assert not state.channel_locks and not state.dm_opened


def test_busy_channels_keep_their_lock(make_cfg):
    state = ChatState(make_cfg())
    state.channel_locks[1] = asyncio.Lock()
    state.waiting[(1, 5)] = object()
    state.sweep()
    assert 1 in state.channel_locks
    assert state.channel_busy(1)


def test_forget_user_and_channel(make_cfg):
    state = ChatState(make_cfg())
    state.waiting[(1, 5)] = state.waiting[(2, 6)] = object()
    state.engaged[(1, 5)] = Engagement(time.monotonic() + 60)
    state.dm_unanswered.add(5)
    state.msg_count[2] = 4
    state.forget_user(5)
    assert list(state.waiting) == [(2, 6)] and not state.engaged and 5 not in state.dm_unanswered
    state.forget_channel(2)
    assert not state.waiting and 2 not in state.msg_count


def test_addressed_is_bounded(make_cfg):
    state = ChatState(make_cfg())
    for i in range(6000):
        state.addressed[i] = 1
    assert len(state.addressed) == 5000 and 0 not in state.addressed


def test_quiet_and_sleep(make_cfg):
    away = Away(make_cfg())
    away.quiet(10, 30)
    assert away.state(10) == "quiet" and away.state(11) is None
    assert 29 <= away.quiet_left(10) <= 31
    away.quiet(ALL, 5)
    assert away.is_quiet(11)
    away.unquiet_everywhere()
    away.sleep(11, 2, "nap")
    assert away.state(11) == "asleep" and away.naps_today(11) == 1
    assert away.wake(11) and not away.wake(11)
    assert away.just_woke(11)


def test_quiet_overrides_sleep_and_persists(make_cfg):
    cfg = make_cfg()
    away = Away(cfg)
    away.sleep(3, 1)
    away.quiet(3, 10)
    assert away.state(3) == "quiet"
    again = Away(cfg)
    again.load()
    assert again.asleep(3) and again.is_quiet(3)


def test_excluded_servers_never_nap(make_cfg):
    cfg = make_cfg(SLEEP_MODE=True, SLEEP_CHANCE=0.95, SLEEP_EXCLUDE=[4])
    away = Away(cfg, exclude=cfg.sleep_exclude)
    assert not any(away.wants_nap(4, late=True) for _ in range(50))


def test_expired_sleep_is_reported_once(make_cfg):
    away = Away(make_cfg())
    away.sleep(5, 1)
    away.data["sleep"]["5"]["until"] = time.time() - 1
    assert away.ended() == [5]
    assert away.ended() == []
