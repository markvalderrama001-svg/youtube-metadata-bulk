"""In-memory mock of the YouTube Data API v3 resources ytbulk uses.

Mimics the googleapiclient call shape (`service.videos().list(...).execute()`)
and enforces the real API's rules, so a bug in ytbulk fails here the way it
would fail against YouTube:
  * videos.update(part=snippet) requires title and categoryId and replaces the snippet
  * titles: max 100 chars, no < or >; descriptions: max 5,000 bytes
  * its own 10,000-unit daily quota, returning a 403 quotaExceeded when blown
"""
from __future__ import annotations

import copy

COSTS = {"list": 1, "update": 50}


class MockHttpError(Exception):
    def __init__(self, status: int, reason: str):
        super().__init__(f"<HttpError {status}: {reason}>")
        self.status, self.reason = status, reason


class _Req:
    def __init__(self, api, op, fn):
        self.api, self.op, self.fn = api, op, fn

    def execute(self):
        api = self.api
        if api.units_used + COSTS[self.op] > api.daily_limit:
            api.quota_errors += 1
            raise MockHttpError(403, "quotaExceeded")
        api.units_used += COSTS[self.op]
        api.calls.append(self.op)
        return self.fn()


class _Resource:
    def __init__(self, api, kind):
        self.api, self.kind = api, kind

    def list(self, part, **kw):
        return _Req(self.api, "list", lambda: getattr(self.api, f"_list_{self.kind}")(part, **kw))

    def update(self, part, body):
        if self.kind != "videos":
            raise AttributeError("update")
        return _Req(self.api, "update", lambda: self.api._update_video(part, body))


class MockYouTube:
    def __init__(self, channel_title: str, channel_id: str, videos: list[dict],
                 daily_limit: int = 10_000, page_size: int = 50):
        self.channel_title = channel_title
        self.channel_id = channel_id
        self.uploads = "UU" + channel_id[2:]
        self.store = {v["id"]: copy.deepcopy(v["snippet"]) for v in videos}
        self.order = [v["id"] for v in videos]
        self.daily_limit = daily_limit
        self.page_size = page_size
        self.units_used = 0
        self.quota_errors = 0
        self.calls: list[str] = []
        self.updates: list[str] = []

    # googleapiclient-style entry points
    def channels(self):
        return _Resource(self, "channels")

    def playlistItems(self):  # noqa: N802 (API casing)
        return _Resource(self, "playlistItems")

    def videos(self):
        return _Resource(self, "videos")

    # helpers for the demo / tests
    def new_day(self):
        self.units_used = 0

    def edit_in_studio(self, video_id: str, **fields):
        """Simulate a human editing a video by hand (no quota, no log)."""
        self.store[video_id].update(fields)

    # handlers
    def _list_channels(self, part, mine=None, id=None):  # noqa: A002
        if not mine and id != self.channel_id:
            return {"items": []}
        return {"items": [{"id": self.channel_id, "snippet": {"title": self.channel_title},
                           "contentDetails": {"relatedPlaylists": {"uploads": self.uploads}}}]}

    def _list_playlistItems(self, part, playlistId, maxResults=50, pageToken=None):  # noqa: N802,N803
        if playlistId != self.uploads:
            raise MockHttpError(404, "playlistNotFound")
        size = min(maxResults, self.page_size)
        start = int(pageToken or 0)
        page = self.order[start:start + size]
        resp = {"items": [{"contentDetails": {"videoId": v}} for v in page]}
        if start + size < len(self.order):
            resp["nextPageToken"] = str(start + size)
        return resp

    def _list_videos(self, part, id):  # noqa: A002
        ids = [i for i in id.split(",") if i]
        if len(ids) > 50:
            raise MockHttpError(400, "tooManyIds")
        return {"items": [{"id": i, "snippet": copy.deepcopy(self.store[i])} for i in ids if i in self.store]}

    def _update_video(self, part, body):
        vid, sn = body.get("id"), body.get("snippet") or {}
        if vid not in self.store:
            raise MockHttpError(404, "videoNotFound")
        if part != "snippet" or not sn.get("title") or not sn.get("categoryId"):
            raise MockHttpError(400, "invalidSnippet (title and categoryId are required)")
        if len(sn["title"]) > 100 or "<" in sn["title"] or ">" in sn["title"]:
            raise MockHttpError(400, "invalidTitle")
        if len(sn.get("description", "").encode("utf-8")) > 5000:
            raise MockHttpError(400, "invalidDescription")
        self.store[vid] = copy.deepcopy(sn)  # replaces the whole snippet, like the real API
        self.updates.append(vid)
        return {"id": vid, "snippet": copy.deepcopy(sn)}
