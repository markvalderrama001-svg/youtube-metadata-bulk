"""Thin adapter over the YouTube Data API v3 resource object.

The same adapter drives the real `googleapiclient` service and the in-memory
mock (ytbulk.mock), so the demo and the tests exercise the production code
path. Every call is charged to the QuotaMeter before it is sent.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .quota import QuotaExceeded, QuotaMeter

SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]
# videos.update(part=snippet) REPLACES the whole snippet: any writable field we
# don't send back is wiped. Round-trip all of them, change only title/description.
WRITABLE_SNIPPET = ("title", "description", "categoryId", "tags", "defaultLanguage", "defaultAudioLanguage")


class ApiError(RuntimeError):
    pass


@dataclass
class Video:
    id: str
    snippet: dict

    @property
    def title(self) -> str:
        return self.snippet.get("title", "")

    @property
    def description(self) -> str:
        return self.snippet.get("description", "")


class YouTubeClient:
    def __init__(self, service, meter: QuotaMeter):
        self.service = service
        self.meter = meter

    def _exec(self, op: str, request):
        self.meter.charge(op)  # raises QuotaExceeded *before* the call
        try:
            return request.execute()
        except QuotaExceeded:
            raise
        except Exception as e:  # googleapiclient.errors.HttpError or mock error
            raise ApiError(str(e)) from e

    def channel(self, channel_id: str | None = None) -> tuple[str, str]:
        """Return (channel title, uploads playlist id) for the authorized channel."""
        kw = {"id": channel_id} if channel_id else {"mine": True}
        resp = self._exec("list", self.service.channels().list(part="snippet,contentDetails", **kw))
        items = resp.get("items") or []
        if not items:
            raise ApiError("channel not found for these credentials")
        ch = items[0]
        return ch["snippet"]["title"], ch["contentDetails"]["relatedPlaylists"]["uploads"]

    def video_ids(self, playlist_id: str) -> list[str]:
        ids, token = [], None
        while True:
            resp = self._exec("list", self.service.playlistItems().list(
                part="contentDetails", playlistId=playlist_id, maxResults=50, pageToken=token))
            ids += [it["contentDetails"]["videoId"] for it in resp.get("items", [])]
            token = resp.get("nextPageToken")
            if not token:
                return ids

    def videos(self, ids: list[str]) -> list[Video]:
        out = []
        for i in range(0, len(ids), 50):
            resp = self._exec("list", self.service.videos().list(part="snippet", id=",".join(ids[i:i + 50])))
            out += [Video(it["id"], it["snippet"]) for it in resp.get("items", [])]
        return out

    def scan(self, channel_id: str | None = None) -> tuple[str, list[Video]]:
        title, uploads = self.channel(channel_id)
        return title, self.videos(self.video_ids(uploads))

    def update_snippet(self, video: Video, title: str, description: str) -> None:
        snippet = {k: video.snippet[k] for k in WRITABLE_SNIPPET if k in video.snippet}
        snippet["title"] = title
        snippet["description"] = description
        snippet.setdefault("categoryId", "22")  # required by the API on update
        self._exec("update", self.service.videos().update(part="snippet", body={"id": video.id, "snippet": snippet}))


def real_service():
    """Build an authorized googleapiclient service from environment variables.

    YT_CLIENT_SECRETS_FILE  OAuth "Desktop app" client JSON from Google Cloud Console
    YT_TOKEN_FILE           where the user token is cached (default .secrets/yt_token.json)
    """
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    secrets = os.environ.get("YT_CLIENT_SECRETS_FILE")
    token_path = Path(os.environ.get("YT_TOKEN_FILE", ".secrets/yt_token.json"))
    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not secrets or not Path(secrets).exists():
                raise SystemExit(
                    "Set YT_CLIENT_SECRETS_FILE to your OAuth client JSON "
                    "(Google Cloud Console > Credentials > OAuth client ID > Desktop app). "
                    "Or try the offline demo: python -m ytbulk --demo")
            creds = InstalledAppFlow.from_client_secrets_file(secrets, SCOPES).run_local_server(port=0)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json(), encoding="utf-8")
    return build("youtube", "v3", credentials=creds, cache_discovery=False)
