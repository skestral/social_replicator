import os
import requests
import json
from settings.auth import TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID
from local.functions import write_log

def post_to_telegram(content, link, images=None, bluesky_link=None):
    """
    Posts a message to a Telegram channel via the Bot API.
    """
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN)
    channel_id = os.environ.get("TELEGRAM_CHANNEL_ID", TELEGRAM_CHANNEL_ID)

    if not bot_token or not channel_id:
        write_log("Telegram Bot Token or Channel ID missing.", "error")
        return None

    # Format content - Native style (Raw content only)
    text = content

    base_url = f"https://api.telegram.org/bot{bot_token}"

    try:
        if images:
            # Handle media
            # If single image, use sendPhoto. If multiple, use sendMediaGroup.
            # Convert file paths to open file handles
            
            # Simple list of paths logic:
            if len(images) == 1:
                img_path = images[0]
                if isinstance(img_path, dict): img_path = img_path.get('filename') # Handle dict from get_images
                
                with open(img_path, 'rb') as f:
                    response = requests.post(
                        f"{base_url}/sendPhoto",
                        data={"chat_id": channel_id, "caption": text},
                        files={"photo": f}
                    )
            else:
                # Media Group for multiple images
                media_group = []
                files = {}
                for i, img in enumerate(images):
                    path = img if isinstance(img, str) else img.get('filename')
                    # We need to map file inputs. Key can be "photo0", "photo1"...
                    # Media item: {"type": "photo", "media": "attach://photo0"}
                    media_group.append({
                        "type": "photo",
                        "media": f"attach://photo{i}",
                        "caption": text if i == 0 else "" # Caption only on first item
                    })
                    files[f"photo{i}"] = open(path, 'rb')
                
                response = requests.post(
                    f"{base_url}/sendMediaGroup",
                    data={"chat_id": channel_id, "media": json.dumps(media_group)},
                    files=files
                )
                
                # Close files
                for f in files.values():
                    f.close()
                    
        else:
            # Text only
            response = requests.post(
                f"{base_url}/sendMessage",
                data={"chat_id": channel_id, "text": text}
            )

        if response.status_code < 300:
            result = response.json()
            if result.get("ok"):
                write_log("Posted to Telegram successfully")
                # Telegram returns a message object. We can use message_id as ID.
                # If group, it returns list of messages.
                res_content = result.get("result")
                if isinstance(res_content, list):
                    return str(res_content[0].get("message_id"))
                return str(res_content.get("message_id"))
            else:
                write_log(f"Telegram API Error: {result.get('description')}", "error")
                return None
        else:
            write_log(f"Failed to post to Telegram: {response.status_code} - {response.text}", "error")
            return None

    except Exception as e:
        write_log(f"Telegram Exception: {e}", "error")
        return None
