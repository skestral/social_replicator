import json
import os
import shutil
import arrow
from settings.paths import database_path, backup_path
from local.functions import write_log

class DatabaseManager:
    def __init__(self, db_path=database_path, backup_path_val=backup_path):
        self.db_path = db_path
        self.backup_path = backup_path_val

    def read(self):
        """Reads the database file and returns a dictionary."""
        database = {}
        if not os.path.exists(self.db_path):
            return database

        with open(self.db_path, 'r') as file:
            for line in file:
                try:
                    json_line = json.loads(line)
                except json.JSONDecodeError:
                    continue
                
                if "skeet" not in json_line:
                    continue

                skeet = json_line["skeet"]
                ids = self._convert_ids(json_line.get("ids", {}))
                
                # Default failure counts
                failed = {"twitter": 0, "mastodon": 0, "discord": 0, "tumblr": 0, "bsky": 0}
                if "failed" in json_line:
                    failed.update(json_line["failed"])

                database[skeet] = {
                    "ids": ids,
                    "failed": failed
                }
        return database

    def write(self, skeet, tweet, toot, discord, tumblr, bsky, failed, database):
        """Adds a new entry to the database and appends it to the file."""
        ids = {
            "twitter_id": tweet,
            "mastodon_id": toot,
            "discord_id": discord,
            "tumblr_id": tumblr,
            "bsky_id": bsky
        }
        data = {
            "ids": ids,
            "failed": failed
        }
        
        # Update in-memory dict
        database[skeet] = data
        
        # Prepare row for append
        row = {
            "skeet": skeet,
            "ids": ids,
            "failed": failed
        }
        json_string = json.dumps(row)
        
        # Check if already exists to avoid duplicates (naive check)
        if not self._is_in_db(json_string):
            write_log("Adding to database: " + json_string)
            mode = 'a' if os.path.exists(self.db_path) else 'w'
            with open(self.db_path, mode) as file:
                file.write(json_string + "\n")
        
        return database

    def save(self, database):
        """Completely overwrites the database file with the current in-memory state."""
        write_log("Saving new database")
        with open(self.db_path, 'w') as file:
            for skeet, data in database.items():
                row = {
                    "skeet": skeet,
                    "ids": data["ids"],
                    "failed": data["failed"]
                }
                file.write(json.dumps(row) + "\n")

    def backup(self):
        """Creates a backup of the database."""
        backup_dir = os.path.dirname(self.backup_path)
        if not os.path.exists(backup_dir):
            os.makedirs(backup_dir)

        # Check if backup is needed (older than 24h)
        if os.path.isfile(self.backup_path):
            last_modified = arrow.Arrow.fromtimestamp(os.stat(self.backup_path).st_mtime)
            if last_modified > arrow.utcnow().shift(hours=-24):
                return

        if not os.path.isfile(self.db_path):
            return

        # Smart backup: if live DB shrank, save old backup before overwriting
        if os.path.isfile(self.backup_path):
            if self._count_lines(self.backup_path) < self._count_lines(self.db_path):
                os.remove(self.backup_path)
            else:
                # Live DB is smaller? Suspicious. Archive the current backup.
                date = arrow.utcnow().format("YYMMDD")
                os.rename(self.backup_path, f"{self.backup_path}_{date}")
                write_log("Current backup file contains more entries than live database, archived old backup.", "error")
        
        shutil.copyfile(self.db_path, self.backup_path)
        write_log("Backup of database taken")

    def _convert_ids(self, ids_in):
        """Converts legacy camelCase keys to snake_case."""
        ids_out = {}
        ids_out["twitter_id"] = ids_in.get("twitter_id") or ids_in.get("twitterId", "")
        ids_out["mastodon_id"] = ids_in.get("mastodon_id") or ids_in.get("mastodonId", "")
        ids_out["discord_id"] = ids_in.get("discord_id") or ids_in.get("discordId", "")
        ids_out["tumblr_id"] = ids_in.get("tumblr_id") or ids_in.get("tumblrId", "")
        ids_out["bsky_id"] = ids_in.get("bsky_id", "")
        ids_out["telegram_id"] = ids_in.get("telegram_id") or ids_in.get("telegramId", "")
        return ids_out

    def _is_in_db(self, line):
        if not os.path.exists(self.db_path):
            return False
        with open(self.db_path, 'r') as file:
            # Note: This reads the whole file into memory. 
            # For very large files, this might need optimization, 
            # but fits the current scale.
            return line in file.read()

    def _count_lines(self, filepath):
        count = 0
        try:
            with open(filepath, 'r') as f:
                for _ in f:
                    count += 1
        except FileNotFoundError:
            return 0
        return count
