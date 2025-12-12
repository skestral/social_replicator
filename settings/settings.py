import os

# Helper: normalize boolean-ish env values
def _env_bool(name, default=False):
	val = os.environ.get(name)
	if val is None:
		return default
	return str(val).strip().lower() in {"1", "true", "yes", "on"}

# Helper: parse integers safely from env
def _env_int(name, default: int) -> int:
	val = os.environ.get(name)
	if val is None or str(val).strip() == "":
		return default
	try:
		return int(str(val).strip())
	except Exception:
		return default

# Enables/disables crossposting to services
# Accepted values: True, False
Twitter = False
Mastodon = True
Discord = True
Tumblr = False
Instagram = True
Telegram = False

# log_level determines what messages will be written to the log.
# "error" means only error messages will be written to the log.
# "verbose" means all messages will be written to the log.
# "none" means no messages will be written to the log (not recommended).
# Accepted values: error, verbose, none
log_level = "verbose"
# visibility sets what visibility should be used when posting to Mastodon. Options are "public" for always public, "unlisted" for always unlisted,
# "private" for always private and "hybrid" for all posts public except responses in threads (meaning first post in a thread is public and the rest unlisted).
# Accepted values: public, private, hybrid
visibility = "hybrid"
# mentions set what is to be done with posts containing a mention of another user. Options are "ignore",
# for crossposting with no change, "skip" for skipping posts with mentions, "strip" for removing
# the starting @ of a username and "url" to replace the username with a link to their bluesky profile.
# Accepted values: ignore, skip, strip, url
mentions = "strip"
# post_default sets default posting mode. True means all posts will be crossposted unless otherwise specified,
# False means no posts will be crossposted unless explicitly specified. If no toggle (below) is specified
# post_default will be treated as True no matter what is set.
# Accepted values: True, False
post_default = True
# The function to select what posts are crossposted (mis)uses the language function in Bluesky.
# Enter a language here and all posts will be filtered based on if that language is included 
# in the post. 
# E.g. if you set post_default to True and add German ("de") as post toggle, all posts including
# German as a language will be skipped. If post_default is set to False, only posts including
# german will be crossposted. You can use different languages as selectors for Mastodon
# and Twitter. You can have both the actual language of the tweet, and the selector language
# added to the tweet and it will still work.
# Accepted values: Any language tag in quotes (https://en.wikipedia.org/wiki/IETF_language_tag)
mastodon_lang = ""
twitter_lang = ""
# quote_posts determines if quote reposts of other users' posts should be crossposted with the quoted post included as a link. If False these posts will be ignored.
quote_posts = True
# max_retries sets maximum amount of times poster will retry a failed crosspost.
# Accepted values: Integers greater than 0
max_retries = 5
# post_time_limit sets max time limit (in hours) for fetching posts. If no database exists, all posts within this time 
# period will be posted.
# Accepted values: Integers greater than 0
post_time_limit = 12
# max_per_hour limits the amount of posts that can be crossposted withing an hour. 0 means no limit.
# Accepted values: Any integer
max_per_hour = 0
# overflow_posts determines what happens to posts that are not crossposted due to the hourly limit.
# If set to "retry" the poster will attempt to send them again when posts per hour are below the limit.
# If set to "skip" the posts will be skipped and the poster will instead continue on with new posts.
# Accepted values: retry, skip
overflow_posts = "retry"



# Override settings with environment variables if they exist
Twitter = _env_bool('TWITTER_CROSSPOSTING', Twitter)
Mastodon = _env_bool('MASTODON_CROSSPOSTING', Mastodon)
Discord = _env_bool('DISCORD_CROSSPOSTING', Discord)
Tumblr = _env_bool('TUMBLR_CROSSPOSTING', Tumblr)
Instagram = _env_bool('INSTAGRAM_CROSSPOSTING', Instagram)
Telegram = _env_bool('TELEGRAM_CROSSPOSTING', Telegram)

log_level_env = os.environ.get('LOG_LEVEL')
if log_level_env:
	log_level_env = log_level_env.strip().lower()
	if log_level_env in {"error", "verbose", "none"}:
		log_level = log_level_env

visibility = os.environ.get('MASTODON_VISIBILITY', visibility) or visibility
mentions = os.environ.get('MENTIONS', mentions) or mentions

post_default = _env_bool('POST_DEFAULT', post_default)
mastodon_lang = os.environ.get('MASTODON_LANG', mastodon_lang) or mastodon_lang
twitter_lang = os.environ.get('TWITTER_LANG', twitter_lang) or twitter_lang
quote_posts = _env_bool('QUOTE_POSTS', quote_posts)

max_retries = _env_int('MAX_RETRIES', max_retries)
post_time_limit = _env_int('POST_TIME_LIMIT', post_time_limit)
max_per_hour = _env_int('MAX_PER_HOUR', max_per_hour)
# Support both new and legacy env var names
overflow_posts = (os.environ.get('OVERFLOW_POSTS') or os.environ.get('OVERFLOW_POST') or overflow_posts)

# Dry Run / Test Mode
TEST_MODE = False
TEST_MODE = _env_bool("TEST_MODE", False)

# Log Timezone
TIMEZONE = os.getenv("TIMEZONE", "US/Pacific")
