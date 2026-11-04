import random

import pytest

from mitski.config import Settings
from mitski.paths import Paths
from mitski.testing.world import build_world, instant_sleep


@pytest.fixture
def paths(tmp_path):
    return Paths(tmp_path)


@pytest.fixture
def make_cfg(paths):
    def make(**values):
        return Settings.from_dict(values, paths)

    return make


@pytest.fixture
def fast_sleep():
    with instant_sleep():
        yield


@pytest.fixture
async def world(paths, fast_sleep):
    random.seed(1234)
    w = build_world(paths).script()
    yield w
    await w.app.tasks.cancel_all()
