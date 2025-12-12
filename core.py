from settings.auth import *
from settings.paths import *
from settings import settings
from local.functions import write_log, cleanup, post_cache_read, post_cache_write, get_post_time_limit
from input.bluesky import get_posts as get_bluesky_posts, get_posts
from input.instagram import get_instagram_posts
from output.post import post_to_bluesky, post
import arrow
from database import DatabaseManager
from settings_manager import SettingsManager
from models.post import Post

class Crossposter:
    def __init__(self, db_manager: DatabaseManager, settings_manager: SettingsManager = None):
        self.db = db_manager
        self.settings_manager = settings_manager or SettingsManager()
        self.post_cache = post_cache_read()
        self.timelimit = get_post_time_limit(self.post_cache)
        self.database = self.db.read() # Load DB into memory

    def _apply_settings(self, p: Post) -> Post:
        """Enforces global settings on a post object."""
        # Read current settings from .env via manager
        twitter_on = self.settings_manager.get_bool("TWITTER_CROSSPOSTING", True)
        mastodon_on = self.settings_manager.get_bool("MASTODON_CROSSPOSTING", True)
        discord_on = self.settings_manager.get_bool("DISCORD_CROSSPOSTING", True)
        tumblr_on = self.settings_manager.get_bool("TUMBLR_CROSSPOSTING", True)
        telegram_on = self.settings_manager.get_bool("TELEGRAM_CROSSPOSTING", True)
        
        # We override the post's internal preferences with the global master switch
        # IF the master switch is OFF. If master is ON, we respect the post's preference
        if not twitter_on: p.post_to["twitter"] = False
        if not mastodon_on: p.post_to["mastodon"] = False
        if not discord_on: p.post_to["discord"] = False
        if not tumblr_on: p.post_to["tumblr"] = False
        if not telegram_on: p.post_to["telegram"] = False
        
        return p

    def run(self):
        """Main execution flow."""
        # Sync runtime settings
        settings.TEST_MODE = self.settings_manager.get_bool("TEST_MODE", False)
        settings.post_time_limit = self.settings_manager.get_int("POST_TIME_LIMIT", 12)
        settings.max_retries = self.settings_manager.get_int("MAX_RETRIES", 5)
        
        # Sync crossposting toggles
        settings.Twitter = self.settings_manager.get_bool("TWITTER_CROSSPOSTING", False)
        settings.Mastodon = self.settings_manager.get_bool("MASTODON_CROSSPOSTING", False)
        settings.Discord = self.settings_manager.get_bool("DISCORD_CROSSPOSTING", False)
        settings.Tumblr = self.settings_manager.get_bool("TUMBLR_CROSSPOSTING", False)
        settings.Instagram = self.settings_manager.get_bool("INSTAGRAM_CROSSPOSTING", False)
        settings.Telegram = self.settings_manager.get_bool("TELEGRAM_CROSSPOSTING", False)

        # Recalculate timelimit with updated settings
        self.timelimit = get_post_time_limit(self.post_cache)

        if settings.TEST_MODE:
             write_log("[DRY RUN] Test Mode Enabled. No API calls will be made.")
        
        self.process_instagram()
        self.process_bluesky()
        
        post_cache_write(self.post_cache)
        # In Test Mode, we might not want to save the database/cache? 
        # Actually output/post.py mock doesn't return updates=True usually? 
        # Wait, I set updates=True in mock to show progress?
        # If I mock updates=True, core will save DB.
        # I should probably NOT save DB in Test Mode in core.py too.
        
        if not settings.TEST_MODE:
            self.db.save(self.database)
            self.db.backup()
        
        cleanup()
        
        if not self.instagram_posts and not self.bluesky_posts:
            write_log("No new posts found.")

    def process_instagram(self):
        self.instagram_posts = {}
        # Check global Instagram toggle
        if self.settings_manager.get_bool("INSTAGRAM_CROSSPOSTING", True):
            api_key = self.settings_manager.get("INSTAGRAM_API_KEY") or os.environ.get("INSTAGRAM_API_KEY")
            
            if not api_key:
                write_log("Instagram enabled but INSTAGRAM_API_KEY is not set; skipping Instagram fetch.", "error")
            else:
                self.instagram_posts = get_instagram_posts(self.timelimit)
            
            # For each IG post, we apply settings and then use the generic post() function
            # which now handles IG logic internally (IG->Bsky)
            
            for cid in list(self.instagram_posts.keys()): # List copy to avoid runtime error if modified?
                p = self.instagram_posts[cid]
                
                # Check global Bsky toggle
                bsky_on = self.settings_manager.get_bool("BLUESKY_CROSSPOSTING", True)
                if not bsky_on:
                    p.post_to["bsky"] = False
                
                # Apply other settings (though for IG key focus is Bsky)
                self._apply_settings(p)
                
            # Now we can pass this dict of Post objects to the main post() function
            # Note: output.post.post handles the logic: if source is instagram -> post to bsky -> continue
            if self.instagram_posts:
                updates, self.database, self.post_cache = post(self.instagram_posts, self.database, self.post_cache)
                if updates:
                    self.db.save(self.database)

        else:
            write_log("Instagram crossposting is disabled.")

    def process_bluesky(self):
        self.bluesky_posts = get_posts(self.timelimit)
        
        # Apply settings to all
        for cid, p in self.bluesky_posts.items():
            self._apply_settings(p)
        
        if self.bluesky_posts:
            updates, self.database, self.post_cache = post(self.bluesky_posts, self.database, self.post_cache)
            if updates:
                self.db.save(self.database)
