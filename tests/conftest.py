import asyncio
import json
from pathlib import Path

import pytest


@pytest.fixture
def acceptance():
    return json.loads(Path('tests/fixtures/acceptance.json').read_text())


class FakeClock:
    def __init__(self):
        self.t = 0.0
        self.hook = None

    def now(self):
        return self.t

    async def sleep(self, seconds):
        assert seconds >= 0
        self.t += seconds
        if self.hook:
            self.hook(self)
        await asyncio.sleep(0)


@pytest.fixture
def clock():
    return FakeClock()
