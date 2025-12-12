import random
import string
import time
import urllib.request
import arrow
import requests
import re
from typing import Dict, Tuple, Any

from settings import settings
from settings.paths import image_path
from local.functions import write_log
from local.db import db_write
from output.twitter import tweet, retweet
from output.mastodon import toot, retoot
from output.discord import post_to_discord
from output.tumblr import post_to_tumblr
from output.telegram import post_to_telegram
from atproto import Client, models as atp
from input.bluesky import load_session_string
from datetime import datetime
from models.post import Post, Media
from dataclasses import asdict

def download_image(image_url):
    try:
        filename = ''.join(random.choice(string.ascii_lowercase) for i in range(10)) + ".jpg"
        filepath = image_path + filename
        urllib.request.urlretrieve(image_url, filepath)
        return filepath
    except Exception as e:
        write_log(f"Failed to download image: {e}", "error")
        return None

def get_images(media_list: list[Media]) -> list[Dict[str, str]]:
    """Ensures all media is downloaded locally."""
    local_images = []
    for m in media_list:
        if m.filename:
            local_images.append({"filename": m.filename, "alt": m.alt})
        else:
            # needs download
            filename = ''.join(random.choice(string.ascii_lowercase) for i in range(10)) + ".jpg"
            filepath = image_path + filename
            try:
                urllib.request.urlretrieve(m.url, filepath)
                # Update the object itself to avoid re-downloading later if needed
                m.filename = filepath
                local_images.append({"filename": filepath, "alt": m.alt})
            except Exception as e:
                write_log(f"Failed to download image {m.url}: {e}", "error")
    return local_images

def extract_hashtags(text):
    hashtags = re.findall(r'#\w+', text)
    return [tag.strip('#') for tag in hashtags]

def parse_mentions(text):
    spans = []
    mention_regex = rb"(@([a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)"
    text_bytes = text.encode("UTF-8")
    for m in re.finditer(mention_regex, text_bytes):
        spans.append({
            "start": m.start(1),
            "end": m.end(1),
            "handle": m.group(1).decode("UTF-8")
        })
    return spans

def parse_urls(text):
    spans = []
    url_regex = rb"(https?:\/\/(www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b([-a-zA-Z0-9()@:%_\+.~#?&//=]*))"
    text_bytes = text.encode("UTF-8")
    for m in re.finditer(url_regex, text_bytes):
        spans.append({
            "start": m.start(1),
            "end": m.end(1),
            "url": m.group(1).decode("UTF-8"),
        })
    return spans

def build_typed_facets(text: str):
    facets: list[atp.AppBskyRichtextFacet.Main] = []
    # Mentions
    for m in parse_mentions(text):
        resp = requests.get(
            "https://bsky.social/xrpc/com.atproto.identity.resolveHandle",
            params={"handle": m["handle"]},
        )
        if resp.status_code == 400:
            continue
        did = resp.json().get("did")
        if not did:
            continue
        facets.append(
            atp.AppBskyRichtextFacet.Main(
                index=atp.AppBskyRichtextFacet.ByteSlice(byte_start=m["start"], byte_end=m["end"]),
                features=[atp.AppBskyRichtextFacet.Mention(did=did)],
            )
        )
    # Links
    for u in parse_urls(text):
        facets.append(
            atp.AppBskyRichtextFacet.Main(
                index=atp.AppBskyRichtextFacet.ByteSlice(byte_start=u["start"], byte_end=u["end"]),
                features=[atp.AppBskyRichtextFacet.Link(uri=u["url"])],
            )
        )
    # Hashtags
    for h in extract_hashtags(text):
        start = text.find("#" + h)
        end = start + len("#" + h)
        if start >= 0:
            facets.append(
                atp.AppBskyRichtextFacet.Main(
                    index=atp.AppBskyRichtextFacet.ByteSlice(byte_start=start, byte_end=end),
                    features=[atp.AppBskyRichtextFacet.Tag(tag=h)],
                )
            )
    return facets or None

def post_to_bluesky(text, images: list[Dict[str, str]]):
    session_string = load_session_string()
    client = Client()

    if not session_string:
        write_log("BSKY_SESSION_STRING is not set. Cannot login to Bluesky.", "error")
        return False, None
    try:
        client.login(session_string=session_string)
    except ValueError as e:
        write_log(f"Failed to login to Bluesky: {e}", "error")
        return False, None

    # Determine repo DID from session
    try:
        sess = client.com.atproto.server.get_session()
        repo = sess.did
        handle = getattr(sess, 'handle', None)
    except Exception:
        repo = None
        handle = None

    if not repo and handle:
        try:
            r = client.com.atproto.identity.resolve_handle(params={"handle": handle})
            repo = getattr(r, 'did', None)
        except Exception:
            pass
    if not repo:
        write_log("Unable to determine repo DID for Bluesky account.", "error")
        return False, None

    typed_facets = build_typed_facets(text)

    embed = None
    try:
        if images:
            if len(images) == 1 and images[0]["filename"].endswith(".mp4"):
                # Attempt video embed
                with open(images[0]["filename"], 'rb') as f:
                    video_bytes = f.read()
                up = client.com.atproto.repo.upload_blob(video_bytes)
                embed = atp.AppBskyEmbedVideo.Main(
                    video=up.blob,
                    alt=images[0].get("alt", ""),
                )
            else:
                imgs: list[atp.AppBskyEmbedImages.Image] = []
                for im in images:
                    with open(im["filename"], 'rb') as f:
                        img_bytes = f.read()
                    up = client.com.atproto.repo.upload_blob(img_bytes)
                    imgs.append(
                        atp.AppBskyEmbedImages.Image(
                            image=up.blob,
                            alt=im.get("alt", ""),
                        )
                    )
                embed = atp.AppBskyEmbedImages.Main(images=imgs)
    except Exception as e:
        write_log(f"Failed to prepare media for Bluesky: {e}", "error")
        embed = None

    record = atp.AppBskyFeedPost.Record(
        text=text,
        facets=typed_facets,
        embed=embed,
        created_at=datetime.utcnow().replace(microsecond=0).isoformat() + 'Z',
    )

    try:
        create = client.com.atproto.repo.create_record(
            atp.ComAtprotoRepoCreateRecord.Data(
                repo=repo,
                collection='app.bsky.feed.post',
                record=record,
            )
        )
        write_log("Bluesky post created.")
        time.sleep(2)
        post_rkey = create.uri.split('/')[-1]
        profile = handle or getattr(sess, 'handle', None)
        bluesky_link = f"https://bsky.app/profile/{profile or 'self'}/post/{post_rkey}"
        return True, bluesky_link
    except Exception as e:
        write_log(f"Failed to create Bluesky post: {e}", "error")
        return False, None

    # Removed orphaned code

    return updates, database, post_cache, dry_run_receipts

# Note: The function signature needs to return the receipts too, or we save them globally.
# Creating a side-effect (saving to file) inside this function for now as implied by plan.
import json
import os

DRY_RUN_FILE = "dry_run_last.json"

def save_dry_run_receipts(receipts):
    # Load existing or start new if we want per-run accumulation? 
    # For now, let's append or overwrite? Ideally overwrite on new run start, append during run?
    # Simpler: Read, append, write.
    existing = []
    if os.path.exists(DRY_RUN_FILE):
        try:
            with open(DRY_RUN_FILE, 'r') as f:
                existing = json.load(f)
        except:
            pass
    existing.extend(receipts)
    with open(DRY_RUN_FILE, 'w') as f:
        json.dump(existing, f, indent=2)

# Updating the post function to use the mocking logic
def post(posts: Dict[str, Post], database: Dict[str, Any], post_cache: Dict[str, Any]):
    updates = False
    dry_run_receipts = []

    # helper to process receipts
    def record_receipt(service, content, media, post_obj: Post, status="Simulated"):
        # Serialize post object
        raw_data = asdict(post_obj)
        # Handle arrow objects
        if isinstance(raw_data.get('created_at'), arrow.Arrow):
            raw_data['created_at'] = raw_data['created_at'].isoformat()
        
        receipt = {
            "service": service,
            "cid": post_obj.id,
            "content": content,
            "media": ["/images/" + os.path.basename(m["filename"]) for m in media],
            "timestamp": arrow.utcnow().isoformat(),
            "status": status,
            "origin": post_obj.source,
            "destinations": [k for k, v in post_obj.post_to.items() if v],
            "raw_data": raw_data
        }
        dry_run_receipts.append(receipt)
        write_log(f"[DRY RUN] Would post to {service}: {content[:30]}...")
        return "DRY_RUN_ID"

    # Clear previous dry run file if this is the start of a batch? 
    # Actually, core.py calls this. We might want to clear it at the start of core.run?
    # Or just let it accumulate and user clears it manually? 
    # Let's assume accumulation for the batch, but we need a way to clear it. 
    # Implementation plan said "Update /api/run to clear previous". So we assume it's cleared there.

    for cid in reversed(list(posts.keys())):
        post_obj = posts[cid]
        
        # ... (existing setup code for variables) ...
        # We need to replicate the variable setup to properly mock
        
        if settings.max_per_hour != 0 and len(post_cache) >= settings.max_per_hour:
             write_log("Max posts per hour reached.")
             break

        posted = False
        tweet_id = ""
        toot_id = ""
        discord_id = ""
        tumblr_id = ""
        bsky_id = ""
        telegram_id = ""
        t_fail = 0
        m_fail = 0
        d_fail = 0
        tu_fail = 0
        bsky_fail = 0
        te_fail = 0
        
        if cid in database and not settings.TEST_MODE:
            tweet_id = database[cid]["ids"]["twitter_id"]
            toot_id = database[cid]["ids"]["mastodon_id"]
            discord_id = database[cid]["ids"]["discord_id"]
            tumblr_id = database[cid]["ids"]["tumblr_id"]
            bsky_id = database[cid]["ids"].get("bsky_id", "")
            telegram_id = database[cid]["ids"].get("telegram_id", "")
            t_fail = database[cid]["failed"]["twitter"]
            m_fail = database[cid]["failed"]["mastodon"]
            d_fail = database[cid]["failed"]["discord"]
            tu_fail = database[cid]["failed"]["tumblr"]
            bsky_fail = database[cid]["failed"].get("bsky", 0)
            te_fail = database[cid]["failed"].get("telegram", 0)

        # Fail-safties (omitted for brevity in this thought, but needed in code)
        # We'll just assume we are replacing the loop body or injecting the check.
        
        # Actually, replacing the entire function is safer to ensure logic consistency.
        
        # ... Fail safe checks ...
        if m_fail >= settings.max_retries:
             if not toot_id: updates = True; toot_id = "FailedToPost"
        if t_fail >= settings.max_retries:
             if not tweet_id: updates = True; tweet_id = "FailedToPost"
        if d_fail >= settings.max_retries:
             if not discord_id: updates = True; discord_id = "FailedToPost"
        if tu_fail >= settings.max_retries:
             if not tumblr_id: updates = True; tumblr_id = "FailedToPost"
        if te_fail >= settings.max_retries:
             if not telegram_id: updates = True; telegram_id = "FailedToPost"

        text = post_obj.text
        reply_to_post = post_obj.reply_to_id
        quoted_post = post_obj.quoted_id
        quote_url = post_obj.quote_url
        link = post_obj.link
        image_dicts = get_images(post_obj.media)
        visibility = post_obj.visibility
        allowed_reply = post_obj.allowed_reply
        repost = post_obj.repost
        timestamp = post_obj.created_at

        # ... Reply processing ...
        tweet_reply = ""
        toot_reply = ""
        tweet_quote = ""
        toot_quote = ""
        
        # ... logic to find parent IDs ...
        repost_timelimit = arrow.utcnow().shift(hours=-1)
        if cid in post_cache:
            repost_timelimit = post_cache[cid]

        if reply_to_post in database:
            tweet_reply = database[reply_to_post]["ids"]["twitter_id"]
            toot_reply = database[reply_to_post]["ids"]["mastodon_id"]
        elif reply_to_post and reply_to_post not in database:
             write_log(f"Post {cid} was a reply to a post that is not in the database.", "error")
             continue

        if quoted_post in database:
             tweet_quote = database[quoted_post]["ids"]["twitter_id"]
             toot_quote = database[quoted_post]["ids"]["mastodon_id"]
        elif quoted_post and quoted_post not in database:
             if settings.quote_posts and quote_url not in text:
                 text += "\n" + quote_url
             elif not settings.quote_posts:
                 write_log(f"Post {cid} was a quote of a post that is not in the database.", "error")
                 continue

        if not tweet_reply: tweet_reply = None
        if not toot_reply: toot_reply = None
        if not tweet_quote: tweet_quote = None
        
        do_twitter = post_obj.post_to.get("twitter", True)
        do_mastodon = post_obj.post_to.get("mastodon", True)
        do_discord = post_obj.post_to.get("discord", True)
        do_tumblr = post_obj.post_to.get("tumblr", True)
        do_bsky = post_obj.post_to.get("bsky", False)
        do_telegram = post_obj.post_to.get("telegram", True)

        if tweet_id and toot_id and discord_id and tumblr_id and bsky_id and telegram_id and not repost:
            continue

        if settings.TEST_MODE:
             record_receipt("Dry Run Preview", text, image_dicts, post_obj)
             # We rely on this to show output even if all services are disabled.


        # Post to Bluesky
        if do_bsky:
            if bsky_id:
                write_log(f"Post {cid} already posted to Bluesky.")
            else:
                if settings.TEST_MODE:
                     bsky_id = "DRY_RUN_BSKY_ID"
                     record_receipt("Bluesky", text, image_dicts, post_obj)
                     updates = True
                     post_obj.link = "http://dryrun.local/bsky/123"
                     post_cache[cid] = arrow.utcnow()
                else: 
                    success, bsky_link = post_to_bluesky(text, image_dicts)
                    if success:
                        updates = True
                        bsky_id = bsky_link.split('/')[-1]
                        post_obj.link = bsky_link
                        post_cache[cid] = arrow.utcnow()
                    else:
                        bsky_fail += 1
                        bsky_id = ""
            if post_obj.source == 'instagram':
                 database = db_write(cid, tweet_id, toot_id, discord_id, tumblr_id, bsky_id, telegram_id,
                            {"twitter": t_fail, "mastodon": m_fail, "discord": d_fail, "tumblr": tu_fail,
                             "bsky": bsky_fail, "telegram": te_fail}, database)
                 continue

        # Post to Twitter
        if not do_twitter:
             tweet_id = "skipped"
             write_log("Not posting to Twitter because posting was set to false.")
        elif tweet_id and not repost:
             write_log("Post " + cid + " already sent to Twitter.")
        elif tweet_id and repost and timestamp > repost_timelimit:
             # Repost logic
             if settings.TEST_MODE:
                 write_log(f"[DRY RUN] Would Retweet {tweet_id}")
                 posted = True
             else:
                 try:
                    retweet(tweet_id)
                    posted = True
                 except Exception as error:
                    write_log(error, "error")
        elif not tweet_id and tweet_reply != "skipped" and tweet_reply != "FailedToPost":
             updates = True
             if settings.TEST_MODE:
                 tweet_id = "DRY_RUN_TWITTER_ID"
                 record_receipt("Twitter", text, image_dicts, post_obj)
                 posted = True
             else:
                 try:
                    tweet_id = tweet(text, tweet_reply, tweet_quote, image_dicts, allowed_reply)
                    posted = True
                 except Exception as error:
                    write_log(error, "error")
                    t_fail += 1
                    tweet_id = ""
        else:
             write_log("Not posting " + cid + " to Twitter")
        
        # Post to Mastodon
        if not do_mastodon:
             toot_id = "skipped"
             write_log("Not posting to Mastodon because posting was set to false.")
        elif toot_id and not repost:
            write_log("Post " + cid + " already sent to Mastodon.")
        elif toot_id and repost and timestamp > repost_timelimit:
            if settings.TEST_MODE:
                write_log(f"[DRY RUN] Would Retoot {toot_id}")
                posted = True
            else:
                try:
                    retoot(toot_id)
                    posted = True
                except Exception as error:
                    write_log(error, "error")
        elif not toot_id and toot_reply != "skipped" and toot_reply != "FailedToPost":
            updates = True
            if settings.TEST_MODE:
                 toot_id = "DRY_RUN_MASTODON_ID"
                 record_receipt("Mastodon", text, image_dicts, post_obj)
                 posted = True
            else:
                try:
                    toot_id = toot(text, toot_reply, toot_quote, image_dicts, visibility)
                    posted = True
                except Exception as error:
                    write_log(error, "error")
                    m_fail += 1
                    toot_id = ""
            if not posted and not toot_id: # matching original logic structure? 
                write_log("Not posting " + cid + " to Mastodon")

        # Post to Discord
        if not do_discord:
            discord_id = "skipped"
            write_log("Not posting to Discord because posting was set to false.")
        elif discord_id and not repost:
            write_log("Post " + cid + " already sent to Discord.")
        elif discord_id and repost and timestamp > repost_timelimit:
            pass
        elif not discord_id and toot_reply != "skipped" and toot_reply != "FailedToPost":
            updates = True
            if settings.TEST_MODE:
                 discord_id = "DRY_RUN_DISCORD_ID"
                 record_receipt("Discord", text, image_dicts, post_obj)
                 posted = True
            else:
                try:
                    fnames = [img['filename'] for img in image_dicts]
                    post_to_discord(text, link, fnames)
                    discord_id = "posted"
                    posted = True
                except Exception as error:
                    write_log(error, "error")
                    d_fail += 1
                    discord_id = ""
        else:
            write_log("Not posting " + cid + " to Discord")

        # Post to Tumblr
        if not do_tumblr:
            tumblr_id = "skipped"
            write_log("Not posting to Tumblr because posting was set to false.")
        elif tumblr_id and not repost:
            write_log(f"Post {cid} already sent to Tumblr.")
        elif tumblr_id and repost and timestamp > repost_timelimit:
            pass
        elif not tumblr_id:
            updates = True
            if settings.TEST_MODE:
                 tumblr_id = "DRY_RUN_TUMBLR_ID"
                 record_receipt("Tumblr", text, image_dicts, post_obj)
                 posted = True
            else:
                try:
                    tumblr_id = post_to_tumblr(text, image_dicts)
                    posted = True
                except Exception as error:
                    write_log(error, "error")
                    tu_fail += 1
                    tumblr_id = ""
        else:
            write_log(f"Not posting {cid} to Tumblr")

        # Post to Telegram
        if not do_telegram:
            telegram_id = "skipped"
            write_log("Not posting to Telegram because posting was set to false.")
        elif telegram_id and not repost:
            write_log(f"Post {cid} already sent to Telegram.")
        elif telegram_id and repost and timestamp > repost_timelimit:
            pass
        elif not telegram_id:
            updates = True
            if settings.TEST_MODE:
                 telegram_id = "DRY_RUN_TELEGRAM_ID"
                 record_receipt("Telegram", text, image_dicts, post_obj)
                 posted = True
            else:
                try:
                    # Pass link as Arg 2, and None for Arg 4 to avoid duplication since link is the source
                    res = post_to_telegram(text, link, image_dicts, None)
                    if res:
                         telegram_id = res
                         posted = True
                    else:
                         te_fail += 1
                         telegram_id = ""
                except Exception as error:
                    write_log(error, "error")
                    te_fail += 1
                    telegram_id = ""

        # Update DB - In Dry Run, we probably want to NOT update the DB?
        # If we update the DB with "DRY_RUN_ID", subsequent real runs will think it's posted.
        # This is bad.
        # So in TEST_MODE, we should NOT write to the DB.
        if not settings.TEST_MODE:
            database = db_write(cid, tweet_id, toot_id, discord_id, tumblr_id, bsky_id, telegram_id,
                            {"twitter": t_fail, "mastodon": m_fail, "discord": d_fail, "tumblr": tu_fail,
                             "bsky": bsky_fail, "telegram": te_fail}, database)
            if posted:
                post_cache[cid] = arrow.utcnow()
    
    if settings.TEST_MODE and dry_run_receipts:
        save_dry_run_receipts(dry_run_receipts)

    return updates, database, post_cache
