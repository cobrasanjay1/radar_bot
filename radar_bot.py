import os
import requests
import json
import tweepy
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
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
        except:
            return set()
    return set()

def save_posted_outages(posted_ids):
    """Save posted outage IDs to file"""
    with open(POSTED_OUTAGES_FILE, 'w') as f:
        json.dump(list(posted_ids), f)

def create_outage_id(outage):
    """Create a unique ID for an outage based on its properties"""
    start = outage.get("startDate", "")
    regions = ",".join(outage.get("locations", []))
    cause = outage.get("outage", {}).get("outageCause", "")
    return f"{start}_{regions}_{cause}"

def format_tweet(outage):
    """Format outage data into a tweet"""
    desc = outage.get("description", "Internet outage detected")
    locations = outage.get("locations", [])
    cause = outage.get("outage", {}).get("outageCause", "Unknown")
    outage_type = outage.get("outage", {}).get("outageType", "Unknown")
    start = outage.get("startDate")
    link = outage.get("linkedUrl", "")
    
    # Format regions
    if len(locations) == 1:
        region_text = f"in {locations[0]}"
    elif len(locations) <= 3:
        region_text = f"in {', '.join(locations)}"
    else:
        region_text = f"in {len(locations)} regions"
    
    # Format timestamp
    def fmt_time(ts):
        if ts:
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                return dt.strftime("%Y-%m-%d %H:%M UTC")
            except:
                return "Unknown time"
        return "Unknown time"
    
    # Create base tweet
    tweet = f"🚨 Internet outage {region_text}\n"
    tweet += f"📍 Cause: {cause.replace('_', ' ').title()}\n"
    tweet += f"🔍 Type: {outage_type.replace('_', ' ').title()}\n"
    tweet += f"⏰ Started: {fmt_time(start)}\n"
    
    # Add description if it's not too generic
    if desc and desc not in ["Internet outage detected", "No description"]:
        # Truncate description if needed to fit Twitter limit
        remaining_chars = 280 - len(tweet) - (len(link) + 1 if link else 0) - 20  # 20 chars buffer
        if len(desc) > remaining_chars:
            desc = desc[:remaining_chars-3] + "..."
        tweet += f"\n{desc}"
    
    # Add link if available
    if link:
        tweet += f"\n{link}"
    
    return tweet

def fetch_outages():
    """Fetch outages from Cloudflare Radar API"""
    url = "https://api.cloudflare.com/client/v4/radar/annotations/outages"
    params = {
        "limit": 10,  # Check more outages to catch new ones
        "offset": 0,
        "dateRange": "1d",  # Check last 24 hours for new outages
        "format": "json"
    }
    headers = {"Authorization": f"Bearer {RADAR_TOKEN}"}
    
    response = requests.get(url, headers=headers, params=params)
    
    if response.status_code != 200:
        print(f"[HTTP ERROR] {response.status_code}: {response.text}")
        return []
    
    data = response.json()
    result = data.get("result", {})
    return result.get("annotations", [])

def main():
    print("[INFO] Checking for new outages...")
    
    # Load previously posted outages
    posted_outages = load_posted_outages()
    
    # Fetch current outages
    outages = fetch_outages()
    
    if not outages:
        print("[INFO] No outages found in the last 24 hours.")
        return
    
    new_posts = 0
    
    for outage in outages:
        outage_id = create_outage_id(outage)
        
        if outage_id not in posted_outages:
            try:
                tweet_text = format_tweet(outage)
                print(f"[INFO] Posting new outage: {outage_id}")
                print(f"Tweet: {tweet_text}")
                print("-" * 50)
                
                # Post to Twitter
                response = client.create_tweet(text=tweet_text)
                print(f"[SUCCESS] Tweet posted: https://twitter.com/i/web/status/{response.data['id']}")
                
                # Add to posted outages
                posted_outages.add(outage_id)
                new_posts += 1
                
            except Exception as e:
                print(f"[ERROR] Failed to post tweet for outage {outage_id}: {e}")
                continue
    
    # Save updated posted outages list
    save_posted_outages(posted_outages)
    
    if new_posts > 0:
        print(f"[INFO] Posted {new_posts} new outage(s) to Twitter")
    else:
        print("[INFO] No new outages to post")

if __name__ == "__main__":
    main()