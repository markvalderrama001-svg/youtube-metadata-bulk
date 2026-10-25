from pathlib import Path

import pytest

from ytbulk import demo_data
from ytbulk.client import YouTubeClient
from ytbulk.mock import MockYouTube
from ytbulk.quota import QuotaMeter
from ytbulk.rules import load_config

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def cfg():
    return load_config(ROOT / "config" / "rules.example.yaml")


@pytest.fixture
def api():
    return MockYouTube(demo_data.CHANNEL_TITLE, demo_data.CHANNEL_ID, demo_data.VIDEOS, page_size=10)


@pytest.fixture
def make_client(api):
    def _make(used: int = 0, limit: int = 10_000):
        api.units_used = used
        api.daily_limit = limit
        return YouTubeClient(api, QuotaMeter(daily_limit=limit, used=used))
    return _make
