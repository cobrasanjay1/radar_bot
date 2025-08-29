import os
import requests
import json
import tweepy
from datetime import datetime

# Load environment variables (GitHub Actions sets these directly)
RADAR_TOKEN = os.getenv("RADAR_TOKEN")
TWITTER_API_KEY = os.getenv("API_KEY")
TWITTER_API_SECRET = os.getenv("API_KEY_SECRET")
TWITTER_ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
TWITTER_ACCESS_TOKEN_SECRET = os.getenv("ACCESS_TOKEN_SECRET")
TWITTER_BEARER_TOKEN = os.getenv("BEARER_TOKEN")

# Check required environment variables
if not RADAR_TOKEN:
    print("[ERROR] Missing RADAR_TOKEN in environment")
    exit(1)

if not all([TWITTER_API_KEY, TWITTER_API_SECRET, TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_TOKEN_SECRET]):
    print("[ERROR] Missing Twitter API credentials in environment")
    print("[INFO] Required: API_KEY, API_KEY_SECRET, ACCESS_TOKEN, ACCESS_TOKEN_SECRET, BEARER_TOKEN")
    exit(1)

# Initialize Twitter API
try:
    client = tweepy.Client(
        bearer_token=TWITTER_BEARER_TOKEN,
        consumer_key=TWITTER_API_KEY,
        consumer_secret=TWITTER_API_SECRET,
        access_token=TWITTER_ACCESS_TOKEN,
        access_token_secret=TWITTER_ACCESS_TOKEN_SECRET,
        wait_on_rate_limit=True
    )
    print("[INFO] Twitter API initialized successfully")
except Exception as e:
    print(f"[ERROR] Failed to initialize Twitter API: {e}")
    exit(1)

# File to track posted outages
POSTED_OUTAGES_FILE = "posted_outages.json"

def load_posted_outages():
    """Load previously posted outage IDs from file"""
    if os.path.exists(POSTED_OUTAGES_FILE):
        try:
            with open(POSTED_OUTAGES_FILE, 'r') as f:
                return set(json.load(f))
        except Exception as e:
            print(f"[WARNING] Could not load posted outages: {e}")
            return set()
    return set()

def save_posted_outages(posted_ids):
    """Save posted outage IDs to file"""
    try:
        with open(POSTED_OUTAGES_FILE, 'w') as f:
            json.dump(list(posted_ids), f, indent=2)
        print(f"[INFO] Saved {len(posted_ids)} posted outage IDs")
    except Exception as e:
        print(f"[ERROR] Could not save posted outages: {e}")

def create_outage_id(outage):
    """Create a unique ID for an outage based on its properties"""
    start = outage.get("startDate", "")
    regions = ",".join(sorted(outage.get("locations", [])))
    cause = outage.get("outage", {}).get("outageCause", "")
    desc = outage.get("description", "")[:50]  # First 50 chars for uniqueness
    return f"{start}_{regions}_{cause}_{hash(desc) % 10000}"

def format_tweet(outage):
    """Format outage data into a tweet"""
    desc = outage.get("description", "Internet outage detected")
    locations = outage.get("locations", [])
    cause = outage.get("outage", {}).get("outageCause", "Unknown")
    outage_type = outage.get("outage", {}).get("outageType", "Unknown")
    start = outage.get("startDate")
    link = outage.get("linkedUrl", "")
    
    # Format regions with country emoji mapping
    country_emojis = {
        'IQ': '🇮🇶', 'CW': '🇨🇼', 'HT': '🇭🇹', 'US': '🇺🇸', 'CA': '🇨🇦',
        'GB': '🇬🇧', 'FR': '🇫🇷', 'DE': '🇩🇪', 'JP': '🇯🇵', 'CN': '🇨🇳',
        'IN': '🇮🇳', 'BR': '🇧🇷', 'RU': '🇷🇺', 'AU': '🇦🇺', 'ZA': '🇿🇦'
    }
    
    if len(locations) == 1:
        country_code = locations[0]
        emoji = country_emojis.get(country_code, '🌍')
        region_text = f"{emoji} {country_code}"
    elif len(locations) <= 3:
        region_parts = [f"{country_emojis.get(loc, '🌍')} {loc}" for loc in locations]
        region_text = ", ".join(region_parts)
    else:
        region_text = f"🌍 {len(locations)} regions"
    
    # Format timestamp
    def fmt_time(ts):
        if ts:
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                return dt.strftime("%Y-%m-%d %H:%M UTC")
            except:
                return "Unknown time"
        return "Unknown time"
    
    # Cause emoji mapping
    cause_emojis = {
        'GOVERNMENT_DIRECTED': '🏛️',
        'POWER_OUTAGE': '⚡',
        'CABLE_CUT': '📡',
        'MAINTENANCE': '🔧',
        'CYBER_ATTACK': '🛡️',
        'NATURAL_DISASTER': '🌪️'
    }
    
    cause_emoji = cause_emojis.get(cause, '❓')
    
    # Create base tweet
    tweet = f"🚨 Internet outage: {region_text}\n"
    tweet += f"{cause_emoji} {cause.replace('_', ' ').title()}\n"
    tweet += f"📊 {outage_type.replace('_', ' ').title()}\n"
    tweet += f"⏰ {fmt_time(start)}\n"
    
    # Add description if it's informative
    if desc and len(desc) > 10 and desc not in ["Internet outage detected", "No description"]:
        # Calculate remaining space
        remaining_chars = 260 - len(tweet) - (len(link) + 1 if link else 0)
        if len(desc) > remaining_chars:
            desc = desc[:remaining_chars-3] + "..."
        tweet += f"\n💭 {desc}"
    
    # Add link if available
    if link:
        tweet += f"\n🔗 {link}"
    
    return tweet

def fetch_outages():
    """Fetch outages from Cloudflare Radar API"""
    url = "https://api.cloudflare.com/client/v4/radar/annotations/outages"
    params = {
        "limit": 20,  # Check more outages
        "offset": 0,
        "dateRange": "6h",  # Check last 6 hours (more frequent than the 15min cron)
        "format": "json"
    }
    headers = {"Authorization": f"Bearer {RADAR_TOKEN}"}
    
    try:
        response = requests.get(url, headers=headers, params=params, timeout=30)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] API request failed: {e}")
        return []
    
    try:
        data = response.json()
        result = data.get("result", {})
        return result.get("annotations", [])
    except json.JSONDecodeError as e:
        print(f"[ERROR] Failed to parse API response: {e}")
        return []

def main():
    print("[INFO] 🤖 Cloudflare Radar Twitter Bot starting...")
    print(f"[INFO] 📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    
    # Load previously posted outages
    posted_outages = load_posted_outages()
    print(f"[INFO] 📝 Loaded {len(posted_outages)} previously posted outages")
    
    # Fetch current outages
    outages = fetch_outages()
    
    if not outages:
        print("[INFO] ✅ No outages found in the last 6 hours.")
        return
    
    print(f"[INFO] 🔍 Found {len(outages)} total outages")
    new_posts = 0
    
    for outage in outages:
        outage_id = create_outage_id(outage)
        
        if outage_id not in posted_outages:
            try:
                tweet_text = format_tweet(outage)
                print(f"[INFO] 📤 Posting new outage: {outage_id}")
                print(f"Tweet preview:\n{tweet_text}")
                print("-" * 50)
                
                # Post to Twitter
                response = client.create_tweet(text=tweet_text)
                tweet_url = f"https://twitter.com/i/web/status/{response.data['id']}"
                print(f"[SUCCESS] ✅ Tweet posted: {tweet_url}")
                
                # Add to posted outages
                posted_outages.add(outage_id)
                new_posts += 1
                
            except Exception as e:
                print(f"[ERROR] ❌ Failed to post tweet for outage {outage_id}: {e}")
                continue
    
    # Save updated posted outages list
    save_posted_outages(posted_outages)
    
    if new_posts > 0:
        print(f"[SUCCESS] 🎉 Posted {new_posts} new outage(s) to Twitter")
    else:
        print("[INFO] ℹ️ No new outages to post")

if __name__ == "__main__":
    main()
