from atproto import Client
from settings.auth import BSKY_HANDLE, BSKY_PASSWORD
from settings.paths import *
from settings import settings
from local.functions import write_log, lang_toggle
import arrow
import os
import subprocess
import random
import string
from settings.paths import image_path
import time
from typing import Any, Dict
from models.post import Post, Media

# Date format adjustment
date_in_format = 'YYYY-MM-DDTHH:mm:ssZ'

_bsky_client: Client | None = None


def load_session_string():
    """Read a stored session string from session.txt, if present."""
    try:
        with open("session.txt", "r") as file:
            contents = file.read().strip()
            if contents:
                return contents
            return None
    except FileNotFoundError:
        return None


def save_session_string(session_string: str):
    with open("session.txt", "w") as file:
        file.write(session_string)


def _on_session_changed(new_session_string: str):
    save_session_string(new_session_string)


def get_bsky_session() -> Client:
    """Return the initialized and authenticated Bluesky client (lazy)."""
    global _bsky_client
    if _bsky_client is not None and getattr(_bsky_client, "_session", None) is not None:
        return _bsky_client

    client = Client()
    session_string = load_session_string()
    try:
        if session_string:
            client.login(session_string=session_string)
        else:
            raise ValueError("No stored session string")
    except Exception:
        client.login(BSKY_HANDLE, BSKY_PASSWORD)
        session_string = client.export_session_string()
        save_session_string(session_string)

    try:
        if hasattr(client, "_session") and client._session is not None and hasattr(client._session, "on_session_changed"):
            client._session.on_session_changed = _on_session_changed  # type: ignore[attr-defined]
    except Exception:
        pass

    _bsky_client = client
    return _bsky_client

# Getting posts from Bluesky
def get_posts(timelimit=arrow.utcnow().shift(hours=-1)) -> Dict[str, Post]:  # Adjust `hours` to your desired time window
    write_log("Gathering posts")
    
    # In Test Mode, we want to grab the most recent post regardless of time to test the pipeline
    if settings.TEST_MODE:
        write_log("[DRY RUN] Expanding time limit to find latest post for testing.")
        timelimit = arrow.get(2020, 1, 1)

    posts = {}
    try:
        bsky = get_bsky_session()
    except Exception as e:
        write_log(f"Failed to get Bluesky session: {e}", "error")
        return {}

    actor = BSKY_HANDLE
    if not actor:
        try:
            sess = bsky.com.atproto.server.get_session()
            actor = getattr(sess, 'handle', None) or getattr(sess, 'did', None)
        except Exception:
            actor = None
    if not actor:
        write_log("BSKY_HANDLE is not configured; cannot fetch author feed.", "error")
        return {}
    
    try:
        profile_feed: Any = bsky.app.bsky.feed.get_author_feed({'actor': actor})  # type: ignore[arg-type]
    except Exception as e:
        write_log(f"Failed to fetch author feed: {e}", "error")
        return {}

    visibility = settings.visibility

    for feed_view in profile_feed.feed:
        try:
            if feed_view.post.author.handle != BSKY_HANDLE:
                continue

            # Get and parse created_at date
            created_at_str = feed_view.post.record.created_at.split(".")[0]
            if not created_at_str.endswith('Z'):
                created_at_str += 'Z'
            created_at = arrow.get(created_at_str, 'YYYY-MM-DDTHH:mm:ssZ')

            # Skip posts older than the timelimit
            if created_at < timelimit:
                continue

            repost = False
            if hasattr(feed_view.reason, "indexed_at"):
                repost = True
                created_at = arrow.get(feed_view.reason.indexed_at.split(".")[0], 'YYYY-MM-DDTHH:mm:ssZ')

            langs = feed_view.post.record.langs
            mastodon_post = (lang_toggle(langs, "mastodon") and settings.Mastodon)
            twitter_post = (lang_toggle(langs, "twitter") and settings.Twitter)
            
            # Note: We aren't filtering hard here anymore, we let the Post object carry the intent
            # via post_to dict, but preserving existing logic to skip processing if both are false 
            # might be desired? Actually, with the new unified system, we should probably validly
            # create the Post object and let the global settings manager enforce the final toggles.
            # But adhering to existing logic:
            if not mastodon_post and not twitter_post:
                # If these are purely language-based toggles, we should probably keep them.
                pass 
            reply_to_user = BSKY_HANDLE
            cid = feed_view.post.cid
            
            # Check if post is effectively a mention (starts with @user that is not us)
            text = feed_view.post.record.text
            created_at = arrow.get(feed_view.post.record.created_at)
            send_mention = True
            if feed_view.post.record.facets:
                text = restore_urls(feed_view.post.record)
                if settings.mentions != "ignore":
                    text, send_mention = parse_mentioned_username(feed_view.post.record, text)
            if not send_mention:
                continue
            if reply_to_user != BSKY_HANDLE:
                continue
            reply_to_post = ""
            quoted_post = ""
            quote_url = ""
            allowed_reply = get_allowed_reply(feed_view.post)
            
            if feed_view.post.embed and hasattr(feed_view.post.embed, "record"):
                try:
                    quoted_user, quoted_post, quote_url, open_quote = get_quote_post(feed_view.post.embed.record)
                except Exception as e:
                    write_log(f"Post {cid} contains a quote type structure not currently supported. Skipping quote processing.", "warning")
                    continue
                if quoted_user != BSKY_HANDLE and (not settings.quote_posts or not open_quote):
                    continue
                elif quoted_user == BSKY_HANDLE:
                    text = text.replace(quote_url, "")
            
            if feed_view.post.record.reply:
                reply_to_post = feed_view.post.record.reply.parent.cid
                try:
                    reply_to_user = feed_view.reply.parent.author.handle
                except:
                    reply_to_user = get_reply_to_user(feed_view.post.record.reply.parent)
            
            if not reply_to_user:
                write_log(f"Unable to find the user that post {cid} replies to or quotes - parent post may be deleted.", "warning")
                continue

            if created_at > timelimit and reply_to_user == BSKY_HANDLE:
                image_data = ""
                images = []
                if feed_view.post.embed and hasattr(feed_view.post.embed, "images"):
                    image_data = feed_view.post.embed.images
                elif feed_view.post.embed and hasattr(feed_view.post.embed, "playlist"):
                    m3u8_url = feed_view.post.embed.playlist
                    output_mp4 = download_bsky_video(m3u8_url)
                    if output_mp4:
                        images.append(Media(filename=output_mp4, alt=feed_view.post.embed.alt, kind="video"))
                    else:
                        write_log(f"Failed to download or convert {m3u8_url} to mp4.", "error")
                elif feed_view.post.embed and hasattr(feed_view.post.embed, "media") and hasattr(feed_view.post.embed.media, "images"):
                    image_data = feed_view.post.embed.media.images
                if feed_view.post.embed and hasattr(feed_view.post.embed, "external") and hasattr(feed_view.post.embed.external, "uri"):
                    if feed_view.post.embed.external.uri not in text:
                        text += '\n' + feed_view.post.embed.external.uri
                
                if image_data:
                    for image in image_data:
                        images.append(Media(url=image.fullsize, alt=image.alt, kind="image"))
                
                if visibility == "hybrid" and reply_to_post:
                    visibility = "unlisted"
                elif visibility == "hybrid":
                    visibility = "public"
                
                link = f"https://bsky.app/profile/{BSKY_HANDLE}/post/{feed_view.post.uri.split('/')[-1]}"
                
                p = Post(
                    id=cid,
                    source="bluesky",
                    text=text,
                    created_at=created_at,
                    link=link,
                    reply_to_id=reply_to_post,
                    quoted_id=quoted_post,
                    quote_url=quote_url,
                    media=images, # Assuming 'media' in the instruction meant 'images' from the original context
                    visibility=visibility,
                    allowed_reply=allowed_reply,
                    repost=repost, # Assuming 'repost_post' in the instruction meant 'repost' from the original context
                    post_to={"twitter": twitter_post, "mastodon": mastodon_post, "discord": settings.Discord, "tumblr": settings.Tumblr} # Reverted to original logic for post_to
                )
                
                posts[cid] = p

        except Exception as e:
            write_log(f"An error occurred while processing post {feed_view.post.cid}: {e}", "error")

    if not posts and settings.TEST_MODE:
        write_log("[DRY RUN] Generating Mock BlueSky Post")
        mock_cid = "mock_bsky_post_123"
        posts[mock_cid] = Post(
            id=mock_cid,
            source="bluesky",
            text="This is a test post for Dry Run Mode! 🧪 #Test",
            created_at=arrow.utcnow(),
            link="http://mock.blue.sky/post/123",
            reply_to_id=None,
            quoted_id=None,
            quote_url=None,
            media=[Media(url="http://mock.site/img.jpg", alt="Mock Image", kind="image")],
            visibility="public",
            allowed_reply="all",
            repost=False,
            post_to={"twitter": True, "mastodon": True, "discord": True, "tumblr": True}
        )

    if settings.TEST_MODE and posts:
         # Find the single most recent post
         latest_cid = max(posts, key=lambda k: posts[k].created_at)
         entry = posts[latest_cid]
         write_log(f"[DRY RUN] Selected most recent post: {entry.text[:30]}... ({entry.created_at})")
         return {latest_cid: entry}

    return posts

def get_quote_post(post):
    try:
        if isinstance(post, dict):
            user = post["record"]["author"]["handle"]
            cid = post["record"]["cid"]
            uri = post["record"]["uri"]
            labels = post["record"]["author"].get("labels", [])
        elif hasattr(post, "author"):
            user = post.author.handle
            cid = post.cid
            uri = post.uri
            labels = getattr(post.author, "labels", [])
        elif hasattr(post, "record") and hasattr(post.record, "author"):
            user = post.record.author.handle
            cid = post.record.cid
            uri = post.record.uri
            labels = getattr(post.record.author, "labels", [])
        else:
            raise AttributeError("Post object structure is not recognized")

        open = True
        if labels and labels[0].val == "!no-unauthenticated":
            open = False

        url = "https://bsky.app/profile/" + user + "/post/" + uri.split("/")[-1]
        return user, cid, url, open
    except Exception as e:
        write_log(f"Error in get_quote_post: {e}", "error")
        return None, None, None, False

def get_reply_to_user(reply):
    uri = reply.uri
    username = ""
    try:
        client = get_bsky_session()
        response: Any = client.app.bsky.feed.get_post_thread(params={"uri": uri})
        username = response.thread.post.author.handle
    except Exception as e:
        write_log(f"Unable to retrieve reply_to-user of post (parent post likely deleted). Error: {e}", "warning")
    return username

def restore_urls(record):
    text = record.text
    encoded_text = text.encode("UTF-8")
    for facet in record.facets:
        if facet.features[0].py_type != "app.bsky.richtext.facet#link":
            continue
        url = facet.features[0].uri
        start = facet.index.byte_start
        end = facet.index.byte_end
        section = encoded_text[start:end]
        shortened = section.decode("UTF-8")
        text = text.replace(shortened, url)
    return text

def parse_mentioned_username(record, text):
    send_mention = True
    encoded_text = text.encode("UTF-8")
    for facet in record.facets:
        if facet.features[0].py_type != "app.bsky.richtext.facet#mention":
            continue
        start = facet.index.byte_start
        end = facet.index.byte_end
        username = encoded_text[start:end].decode("UTF-8")
        
        if settings.mentions == "skip":
            send_mention = False
        elif settings.mentions == "strip":
            text = text.replace(username, username.replace("@", ""))
        elif settings.mentions == "url":
            base_url = "https://bsky.app/profile/"
            did = facet.features[0].did
            url = base_url + did
            text = text.replace(username, url)
    return text, send_mention

def get_allowed_reply(post):
    reply_restriction = post.threadgate
    if reply_restriction is None:
        return "All"
    if len(reply_restriction.record.allow) == 0:
        return "None"
    if reply_restriction.record.allow[0].py_type == "app.bsky.feed.threadgate#followingRule":
        return "Following"
    if reply_restriction.record.allow[0].py_type == "app.bsky.feed.threadgate#mentionRule":
        return "Mentioned"
    return "Unknown"

def download_bsky_video(m3u8_url):
    """Download and convert an .m3u8 stream to .mp4 format."""
    output_filename = ''.join(random.choice(string.ascii_lowercase) for i in range(10)) + ".mp4"
    output_path = image_path + output_filename
    try:
        ffmpeg_command = ["ffmpeg", "-y", "-i", m3u8_url, "-c", "copy", output_path]
        subprocess.run(ffmpeg_command, check=True)
        if os.path.exists(output_path):
            write_log(f"Successfully downloaded and converted {m3u8_url} to {output_path}.")
            return output_path
        else:
            write_log(f"Failed to create output file {output_path}.")
            return None
    except subprocess.CalledProcessError as e:
        write_log(f"Error during ffmpeg conversion: {e}", "error")
        return None
    except FileNotFoundError:
        write_log("FFmpeg not found. Video processing skipped. Install ffmpeg to enable video support.", "warning")
        return None
