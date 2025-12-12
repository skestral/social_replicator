import requests
import arrow
import random
import string
import urllib.request
import os
from settings.auth import INSTAGRAM_API_KEY as DEFAULT_KEY
from settings.paths import image_path
from local.functions import write_log
from models.post import Post, Media
from typing import Dict

def get_images(images):
    local_images = []
    for image in images:
        url: str = image["url"]
        alt: str = image["alt"]
        type = ".mp4" if ".mp4" in url else ".jpg"
        filename = ''.join(random.choice(string.ascii_lowercase) for i in range(10)) + type
        filepath = image_path + filename
        try:
            urllib.request.urlretrieve(url, filepath)
            image_info = Media(filename=filepath, url=url, alt=alt, kind="video" if type == ".mp4" else "image")
            local_images.append(image_info)
        except Exception as e:
             write_log(f"Failed to download image {url}: {e}", "error")

    return local_images

def get_instagram_posts(timelimit=arrow.utcnow().shift(hours=-1)) -> Dict[str, Post]:
    write_log("Gathering Instagram posts")
    posts = {}
    
    # Get key dynamically (preferred) or fallback to import
    api_key = os.environ.get("INSTAGRAM_API_KEY", DEFAULT_KEY)
    
    url = f"https://graph.instagram.com/me/media?fields=id,caption,media_url,timestamp,media_type,children&access_token={api_key}"
    try:
        response = requests.get(url)
    except Exception as e:
        write_log(f"Failed to connect to Instagram API: {e}", "error")
        return posts

    if response.status_code != 200:
        write_log(f"Failed to fetch Instagram posts: {response.status_code} - {response.text}", "error")
        return posts

    try:
        media_list = response.json().get('data', [])
    except ValueError:
        write_log(f"Failed to parse Instagram response as JSON. Status: {response.status_code}, Body: {response.text[:100]}", "error")
        return posts
    for media in media_list:
        created_at = arrow.get(media['timestamp'])
        if created_at > timelimit:
            images = []
            if media['media_type'] == 'CAROUSEL_ALBUM':
                children_url = f"https://graph.instagram.com/{media['id']}/children?fields=media_url&access_token={api_key}"
                children_response = requests.get(children_url)
                if children_response.status_code == 200:
                    children_data = children_response.json().get('data', [])
                    for child in children_data:
                        images.append({"url": child.get('media_url', ''), "alt": ''})
            else:
                images.append({"url": media.get('media_url', ''), "alt": ''})

            media_objects = get_images(images)
            
            p = Post(
                id=media['id'],
                source="instagram",
                text=media.get('caption', ''),
                created_at=created_at,
                link=media.get('permalink', ''), # added permalink if available, else empty
                media=media_objects,
                visibility="public",
                allowed_reply="All",
                repost=False
            )
            # For IG, we want to first post to bsky
            p.post_to["bsky"] = True
            
            posts[media['id']] = p

    return posts
