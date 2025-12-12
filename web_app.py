from flask import Flask, render_template, jsonify, request, send_from_directory
import json
import os
import arrow
import threading
import time
from database import DatabaseManager
from core import Crossposter
from settings import settings
from settings.paths import log_path, image_path
from settings_manager import SettingsManager

app = Flask(__name__)
db_manager = DatabaseManager()
# We need to pass the settings manager to the crossposter now
settings_manager = SettingsManager()
crossposter = Crossposter(db_manager, settings_manager)

# Scheduler Globals
scheduler_thread = None
stop_event = threading.Event()

def run_scheduler():
    """Background loop to handle auto-running jobs."""
    print("Scheduler thread started.")
    last_run = 0
    
    while not stop_event.is_set():
        try:
            # Reload settings each loop to catch changes
            auto_run = settings_manager.get_bool("AUTO_RUN", False)
            interval_minutes = int(settings_manager.get("RUN_INTERVAL", 5))
            
            if auto_run:
                now = time.time()
                # Check if enough time has passed
                if now - last_run >= (interval_minutes * 60):
                    print(f"Auto-run triggered. Interval: {interval_minutes}m")
                    crossposter.run()
                    last_run = time.time()
            
            # Sleep in short bursts to allow for responsive shutdown/updates
            time.sleep(10)
            
        except Exception as e:
            print(f"Scheduler Error: {e}")
            time.sleep(60) # Backoff on error

@app.route('/')
def home():
    auto_run = settings_manager.get_bool("AUTO_RUN", False)
    interval = settings_manager.get("RUN_INTERVAL", 5)
    test_mode = settings_manager.get_bool("TEST_MODE", False)
    return render_template('index.html', auto_run=auto_run, interval=interval, test_mode=test_mode)

@app.route('/images/<path:filename>')
def serve_image(filename):
    return send_from_directory(image_path, filename)

@app.route('/settings', methods=['GET', 'POST'])
def settings_page():
    if request.method == 'POST':
        # Extract all potential keys we care about
        # Bool toggles
        toggles = [
            'TWITTER_CROSSPOSTING', 'MASTODON_CROSSPOSTING', 'DISCORD_CROSSPOSTING',
            'TUMBLR_CROSSPOSTING', 'INSTAGRAM_CROSSPOSTING', 'BLUESKY_CROSSPOSTING',
            'TELEGRAM_CROSSPOSTING',
            'AUTO_RUN', 'TEST_MODE' 
        ]
        updates = {}
        for key in toggles:
            updates[key] = key in request.form
            
        # Text fields
        text_fields = [
            'BSKY_HANDLE', 'BSKY_PASSWORD', 
            'MASTODON_INSTANCE', 'MASTODON_HANDLE', 'MASTODON_TOKEN',
            'TWITTER_APP_KEY', 'TWITTER_APP_SECRET', 'TWITTER_ACCESS_TOKEN', 'TWITTER_ACCESS_TOKEN_SECRET',
            'DISCORD_WEBHOOK_URL',
            'TUMBLR_CONSUMER_KEY', 'TUMBLR_CONSUMER_SECRET', 'TUMBLR_OAUTH_TOKEN', 'TUMBLR_OAUTH_SECRET', 'TUMBLR_BLOG_NAME',
            'INSTAGRAM_API_KEY',
            'TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHANNEL_ID',
            'RUN_INTERVAL', 'TIMEZONE'
        ]
        
        for key in text_fields:
            if key in request.form:
                updates[key] = request.form[key]
        
        settings_manager.bulk_update(updates)
        return render_template('settings.html', settings=settings_manager.get_all(), success=True)

    return render_template('settings.html', settings=settings_manager.get_all())

@app.route('/api/schedule', methods=['POST'])
def update_schedule():
    data = request.json
    if 'auto_run' in data:
        settings_manager.set("AUTO_RUN", data['auto_run'])
    if 'interval' in data:
        settings_manager.set("RUN_INTERVAL", data['interval'])
    
    return jsonify({'status': 'success'})

@app.route('/api/setting', methods=['POST'])
def update_setting():
    try:
        # Handle both JSON and form data
        if request.is_json:
            data = request.json
            key = data.get('key')
            value = data.get('value')
        else:
            key = request.form.get('key')
            value = request.form.get('value')

        if not key:
            return jsonify({'error': 'Missing key'}), 400

        # Basic validation/type conversion if needed
        # For boolean toggles coming from JS, we might get 'true'/'false' strings or booleans
        if isinstance(value, str) and value.lower() in ('true', 'on', 'yes'):
             value = True
        elif isinstance(value, str) and value.lower() in ('false', 'off', 'no'):
             value = False
             
        settings_manager.set(key, value)
        return jsonify({'status': 'success', 'key': key, 'value': value})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/dry_run_results')
def get_dry_run_results():
    if os.path.exists("dry_run_last.json"):
        with open("dry_run_last.json", 'r') as f:
            return jsonify(json.load(f))
    return jsonify([])

@app.route('/logs')
def logs_page():
    return render_template('logs.html')

@app.route('/api/run', methods=['POST'])
def run_job():
    # Clear dry run results if exists
    if os.path.exists("dry_run_last.json"):
        os.remove("dry_run_last.json")
    
    # We should ensure TEST_MODE is respected. 
    # core.run() uses SettingsManager which reads .env.
    # The user might have just toggled it in Settings, so it should be fine.
    
    # Run the crossposter in a separate thread so we don't block
    def validation_run():
        crossposter = Crossposter(db_manager, settings_manager)
        crossposter.run()

    thread = threading.Thread(target=validation_run)
    thread.start()
    return jsonify({"status": "Run triggered"})

@app.route('/api/logs')
def get_logs():
    date = arrow.utcnow().format("YYMMDD")
    current_log = log_path + date + ".log"
    
    if os.path.exists(current_log):
        # Parse query params
        limit = request.args.get('limit', 100, type=int)
        hours = request.args.get('hours', 0, type=int)

        # Get configured timezone
        tz = settings_manager.get("TIMEZONE", "US/Pacific")
        
        with open(current_log, 'r') as f:
            content = f.read()
            lines = content.splitlines()
            
            if hours > 0:
                # Calculate cutoff in the configured timezone
                cutoff = arrow.now(tz).shift(hours=-hours)
                filtered = []
                for line in lines:
                    try:
                        # Extract timestamp: "12/12/2025 01:38:21 (MESSAGE)..."
                        parts = line.split('(', 1)
                        if len(parts) > 1:
                            ts_str = parts[0].strip()
                            # Parse with explicit timezone
                            ts = arrow.get(ts_str, "MM/DD/YYYY HH:mm:ss", tzinfo=tz)
                            
                            if ts >= cutoff:
                                filtered.append(line)
                        else:
                            if filtered: filtered.append(line)
                    except:
                        if filtered: filtered.append(line)
                lines = filtered

            if limit > 0:
                lines = lines[-limit:]
                
            return jsonify({'logs': '\n'.join(lines)})
    
    return jsonify({'logs': 'No logs for today.'})

def start_scheduler():
    global scheduler_thread
    if not scheduler_thread or not scheduler_thread.is_alive():
        scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
        scheduler_thread.start()

if __name__ == '__main__':
    start_scheduler()
    app.run(host='0.0.0.0', port=5001, debug=True)
