from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
import arrow

@dataclass
class Media:
    filename: Optional[str] = None  # local file path if downloaded
    url: Optional[str] = None       # remote URL if not downloaded yet
    alt: str = ""
    kind: str = "image"            # image | video | external

@dataclass
class Post:
    # Stable id per source (cid for Bluesky, media id for Instagram)
    id: str
    source: str                   # 'bluesky' | 'instagram'
    text: str
    created_at: Any               # arrow.Arrow for now
    link: str = ""
    reply_to_id: str = ""
    quoted_id: str = ""
    quote_url: str = ""
    media: List[Media] = field(default_factory=list)
    visibility: str = "public"
    allowed_reply: str = "All"
    repost: bool = False
    
    # per-destination toggles
    post_to: Dict[str, bool] = field(default_factory=lambda: {
        "twitter": True,
        "mastodon": True,
        "discord": True,
        "tumblr": True,
        "bsky": False,
    })
