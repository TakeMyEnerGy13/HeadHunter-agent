from dataclasses import dataclass


@dataclass(frozen=True)
class JobPost:
    source: str
    channel: str
    message_id: int
    posted_at: str
    text: str
    url: str
    title: str
    text_hash: str


@dataclass(frozen=True)
class ChannelFetchStats:
    channel: str
    scanned: int
    saved: int
    duplicates: int
    filtered: int


@dataclass(frozen=True)
class SavedPostPreview:
    channel: str
    message_id: int
    posted_at: str
    title: str
    url: str
