import os
import requests
import json
import tweepy
from datetime import datetime, timedelta
import time
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables (GitHub Actions sets these directly)
RADAR_TOKEN = os.getenv("RADAR_TOKEN")
TWITTER_API_KEY = os.getenv("API_KEY")
TWITTER_API_SECRET = os.getenv("API_KEY_SECRET")
TWITTER_ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
TWITTER_ACCESS_TOKEN_SECRET = os.getenv("ACCESS_TOKEN_SECRET")
TWITTER_BEARER_TOKEN = os.getenv("BEARER_TOKEN")

# Check required environment variables
if not RADAR_TOKEN:
    logger.error("Missing RADAR_TOKEN in environment")
    exit(1)

if not all([TWITTER_API_KEY, TWITTER_API_SECRET, TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_TOKEN_SECRET]):
    logger.error("Missing Twitter API credentials in environment")
    logger.info("Required: API_KEY, API_KEY_SECRET, ACCESS_TOKEN, ACCESS_TOKEN_SECRET, BEARER_TOKEN")
    exit(1)

# Rate limit configuration based on Twitter API v2 limits
class RateLimitConfig:
    # Assuming Free tier - adjust these based on your actual tier
    POST_TWEETS_PER_24H = 17  # Free tier limit
    POST_TWEETS_PER_APP_24H = 17  # Free tier app limit
    
    # Safety margins
    SAFETY_MARGIN = 0.8  # Use only 80% of rate limit
    MAX_POSTS_PER_RUN = min(3, int(POST_TWEETS_PER_24H * SAFETY_MARGIN / 96))  # 96 runs per day (every 15min)
    MIN_INTERVAL_BETWEEN_POSTS = 60  # seconds

# Initialize Twitter API with better error handling
try:
    client = tweepy.Client(
        bearer_token=TWITTER_BEARER_TOKEN,
        consumer_key=TWITTER_API_KEY,
        consumer_secret=TWITTER_API_SECRET,
        access_token=TWITTER_ACCESS_TOKEN,
        access_token_secret=TWITTER_ACCESS_TOKEN_SECRET,
        wait_on_rate_limit=True
    )
    logger.info("Twitter API initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize Twitter API: {e}")
    exit(1)

# File to track posted outages and rate limit info
POSTED_OUTAGES_FILE = "posted_outages.json"
RATE_LIMIT_FILE = "rate_limit_tracker.json"

def load_posted_outages():
    """Load previously posted outage IDs from file"""
    if os.path.exists(POSTED_OUTAGES_FILE):
        try:
            with open(POSTED_OUTAGES_FILE, 'r') as f:
                return set(json.load(f))
        except Exception as e:
            logger.warning(f"Could not load posted outages: {e}")
            return set()
    return set()

def save_posted_outages(posted_ids):
    """Save posted outage IDs to file"""
    try:
        with open(POSTED_OUTAGES_FILE, 'w') as f:
            json.dump(list(posted_ids), f, indent=2)
        logger.info(f"Saved {len(posted_ids)} posted outage IDs")
    except Exception as e:
        logger.error(f"Could not save posted outages: {e}")

def load_rate_limit_tracker():
    """Load rate limit tracking data"""
    if os.path.exists(RATE_LIMIT_FILE):
        try:
            with open(RATE_LIMIT_FILE, 'r') as f:
                data = json.load(f)
                # Clean old entries (older than 24 hours)
                cutoff = datetime.now() - timedelta(hours=24)
                data['posts'] = [
                    post for post in data.get('posts', [])
                    if datetime.fromisoformat(post) > cutoff
                ]
                return data
        except Exception as e:
            logger.warning(f"Could not load rate limit tracker: {e}")
    
    return {'posts': [], 'last_reset': datetime.now().isoformat()}

def save_rate_limit_tracker(tracker_data):
    """Save rate limit tracking data"""
    try:
        with open(RATE_LIMIT_FILE, 'w') as f:
            json.dump(tracker_data, f, indent=2)
    except Exception as e:
        logger.error(f"Could not save rate limit tracker: {e}")

def can_post_tweet(tracker_data):
    """Check if we can post a tweet based on rate limits"""
    now = datetime.now()
    cutoff_24h = now - timedelta(hours=24)
    
    # Count posts in last 24 hours
    recent_posts = [
        datetime.fromisoformat(post) for post in tracker_data.get('posts', [])
        if datetime.fromisoformat(post) > cutoff_24h
    ]
    
    posts_in_24h = len(recent_posts)
    
    # Check 24-hour limit
    if posts_in_24h >= RateLimitConfig.POST_TWEETS_PER_24H:
        logger.warning(f"Reached 24-hour tweet limit: {posts_in_24h}/{RateLimitConfig.POST_TWEETS_PER_24H}")
        return False
    
    # Check if enough time has passed since last post
    if recent_posts:
        last_post = max(recent_posts)
        time_since_last = (now - last_post).total_seconds()
        if time_since_last < RateLimitConfig.MIN_INTERVAL_BETWEEN_POSTS:
            logger.info(f"Too soon since last post. Wait {RateLimitConfig.MIN_INTERVAL_BETWEEN_POSTS - time_since_last:.0f} more seconds")
            return False
    
    return True

def record_tweet_post(tracker_data):
    """Record a successful tweet post"""
    tracker_data.setdefault('posts', []).append(datetime.now().isoformat())
    return tracker_data

def create_outage_id(outage):
    """Create a unique ID for an outage based on its properties"""
    start = outage.get("startDate", "")
    regions = ",".join(sorted(outage.get("locations", [])))
    cause = outage.get("outage", {}).get("outageCause", "")
    desc = outage.get("description", "")[:50]  # First 50 chars for uniqueness
    return f"{start}_{regions}_{cause}_{hash(desc) % 10000}"

def format_tweet(outage):
    """Format outage data into a tweet with improved formatting"""
    desc = outage.get("description", "Internet outage detected")
    locations = outage.get("locations", [])
    cause = outage.get("outage", {}).get("outageCause", "Unknown")
    outage_type = outage.get("outage", {}).get("outageType", "Unknown")
    start = outage.get("startDate")
    end = outage.get("endDate")
    link = outage.get("linkedUrl", "")
    
    # Enhanced country emoji mapping
    country_emojis = {
        'IQ': '🇮🇶', 'CW': '🇨🇼', 'HT': '🇭🇹', 'US': '🇺🇸', 'CA': '🇨🇦',
        'GB': '🇬🇧', 'FR': '🇫🇷', 'DE': '🇩🇪', 'JP': '🇯🇵', 'CN': '🇨🇳',
        'IN': '🇮🇳', 'BR': '🇧🇷', 'RU': '🇷🇺', 'AU': '🇦🇺', 'ZA': '🇿🇦',
        'IT': '🇮🇹', 'ES': '🇪🇸', 'NL': '🇳🇱', 'SE': '🇸🇪', 'NO': '🇳🇴',
        'KR': '🇰🇷', 'SG': '🇸🇬', 'MX': '🇲🇽', 'AR': '🇦🇷', 'CL': '🇨🇱'
    }
    
    # Format regions
    if len(locations) == 1:
        country_code = locations[0]
        emoji = country_emojis.get(country_code, '🌍')
        region_text = f"{emoji} {country_code}"
    elif len(locations) <= 3:
        region_parts = [f"{country_emojis.get(loc, '🌍')} {loc}" for loc in locations]
        region_text = ", ".join(region_parts)
    else:
        region_text = f"🌍 {len(locations)} regions"
    
    # Format timestamp with better handling
    def fmt_time(ts):
        if not ts:
            return "Unknown time"
        try:
            # Handle different timestamp formats
            if ts.endswith('Z'):
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            else:
                dt = datetime.fromisoformat(ts)
            return dt.strftime("%m/%d %H:%M UTC")
        except Exception as e:
            logger.warning(f"Could not parse timestamp {ts}: {e}")
            return "Unknown time"
    
    # Enhanced cause emoji mapping
    cause_emojis = {
        'GOVERNMENT_DIRECTED': '🏛️',
        'POWER_OUTAGE': '⚡',
        'CABLE_CUT': '📡',
        'MAINTENANCE': '🔧',
        'CYBER_ATTACK': '🛡️',
        'NATURAL_DISASTER': '🌪️',
        'TECHNICAL_FAILURE': '⚙️',
        'CAPACITY_ISSUES': '📊'
    }
    
    cause_emoji = cause_emojis.get(cause, '❓')
    
    # Determine status
    status = "🚨 ONGOING" if not end else "✅ RESOLVED"
    
    # Create base tweet with improved structure
    tweet = f"{status} Internet outage: {region_text}\n"
    tweet += f"{cause_emoji} {cause.replace('_', ' ').title()}\n"
    
    # Add timing info
    if end:
        tweet += f"⏰ {fmt_time(start)} - {fmt_time(end)}\n"
    else:
        tweet += f"⏰ Started: {fmt_time(start)}\n"
    
    # Add outage type if meaningful
    if outage_type and outage_type.lower() not in ['unknown', 'general']:
        tweet += f"📊 Type: {outage_type.replace('_', ' ').title()}\n"
    
    # Add description if informative
    if desc and len(desc) > 10 and desc.lower() not in ["internet outage detected", "no description"]:
        # Calculate remaining space (Twitter limit is 280 chars)
        base_length = len(tweet)
        link_length = len(link) + 1 if link else 0
        hashtag_length = 25  # Reserve space for hashtags
        remaining_chars = 280 - base_length - link_length - hashtag_length
        
        if remaining_chars > 20:  # Only add if we have reasonable space
            if len(desc) > remaining_chars:
                desc = desc[:remaining_chars-3] + "..."
            tweet += f"💬 {desc}\n"
    
    # Add relevant hashtags
    hashtags = ["#InternetOutage"]
    if cause in ['GOVERNMENT_DIRECTED']:
        hashtags.append("#InternetShutdown")
    elif cause in ['CABLE_CUT', 'TECHNICAL_FAILURE']:
        hashtags.append("#TechIssue")
    
    tweet += " ".join(hashtags)
    
    # Add link if available and space permits
    if link and len(tweet + " " + link) <= 280:
        tweet += f"\n🔗 {link}"
    
    return tweet

def fetch_outages():
    """Fetch outages from Cloudflare Radar API with better error handling"""
    url = "https://api.cloudflare.com/client/v4/radar/annotations/outages"
    params = {
        "limit": 20,  # Increased to catch more potential outages
        "offset": 0,
        "dateRange": "1d",  # Reduced to focus on more recent outages
        "format": "json"
    }
    headers = {
        "Authorization": f"Bearer {RADAR_TOKEN}",
        "Content-Type": "application/json"
    }
    
    logger.info(f"Fetching outages from Cloudflare Radar API")
    logger.debug(f"API URL: {url}")
    logger.debug(f"API Params: {params}")
    
    try:
        response = requests.get(url, headers=headers, params=params, timeout=30)
        logger.debug(f"Response status: {response.status_code}")
        
        if response.status_code == 429:
            logger.warning("Rate limited by Cloudflare API")
            return []
        elif response.status_code != 200:
            logger.error(f"API Error {response.status_code}: {response.text}")
            return []
            
    except requests.exceptions.RequestException as e:
        logger.error(f"API request failed: {e}")
        return []
    
    try:
        data = response.json()
        if not data.get("success", False):
            logger.error(f"API returned error: {data.get('errors', 'Unknown error')}")
            return []
            
        result = data.get("result", {})
        annotations = result.get("annotations", [])
        logger.info(f"API returned {len(annotations)} annotations")
        return annotations
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse API response: {e}")
        logger.debug(f"Raw response: {response.text[:500]}")
        return []

def prioritize_outages(outages):
    """Prioritize outages by severity and recency"""
    def get_priority(outage):
        priority = 0
        
        # Prioritize by cause (government directed = highest priority)
        cause = outage.get("outage", {}).get("outageCause", "")
        if cause == "GOVERNMENT_DIRECTED":
            priority += 100
        elif cause in ["CYBER_ATTACK", "NATURAL_DISASTER"]:
            priority += 80
        elif cause in ["POWER_OUTAGE", "CABLE_CUT"]:
            priority += 60
        else:
            priority += 40
        
        # Prioritize by number of affected regions
        locations = outage.get("locations", [])
        priority += len(locations) * 10
        
        # Prioritize ongoing outages
        if not outage.get("endDate"):
            priority += 50
        
        # Prioritize by recency
        start = outage.get("startDate")
        if start:
            try:
                start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                hours_ago = (datetime.now(start_dt.tzinfo) - start_dt).total_seconds() / 3600
                # More recent = higher priority
                priority += max(0, 24 - hours_ago)
            except:
                pass
        
        return priority
    
    return sorted(outages, key=get_priority, reverse=True)

def main():
    logger.info("🤖 Cloudflare Radar Twitter Bot starting...")
    logger.info(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    
    # Load tracking data
    posted_outages = load_posted_outages()
    rate_tracker = load_rate_limit_tracker()
    
    logger.info(f"📝 Loaded {len(posted_outages)} previously posted outages")
    
    # Fetch current outages
    outages = fetch_outages()
    
    if not outages:
        logger.info("✅ No outages found in the last 24 hours.")
        return
    
    # Prioritize outages
    outages = prioritize_outages(outages)
    logger.info(f"🔍 Found {len(outages)} total outages (prioritized)")
    
    new_posts = 0
    
    for outage in outages:
        # Check rate limits before attempting to post
        if not can_post_tweet(rate_tracker):
            logger.warning("🛑 Rate limit reached. Stopping for this run.")
            break
            
        if new_posts >= RateLimitConfig.MAX_POSTS_PER_RUN:
            logger.info(f"🛑 Reached maximum posts per run ({RateLimitConfig.MAX_POSTS_PER_RUN}). Remaining outages will be posted in next runs.")
            break
            
        outage_id = create_outage_id(outage)
        
        if outage_id not in posted_outages:
            try:
                tweet_text = format_tweet(outage)
                
                # Validate tweet length
                if len(tweet_text) > 280:
                    logger.warning(f"Tweet too long ({len(tweet_text)} chars). Skipping outage {outage_id}")
                    continue
                
                logger.info(f"📤 Posting new outage: {outage_id}")
                logger.info(f"Tweet preview ({len(tweet_text)} chars):")
                logger.info(f"{tweet_text}")
                logger.info("-" * 50)
                
                # Post to Twitter
                response = client.create_tweet(text=tweet_text)
                tweet_id = response.data['id']
                tweet_url = f"https://twitter.com/i/web/status/{tweet_id}"
                logger.info(f"✅ Tweet posted: {tweet_url}")
                
                # Record the post
                posted_outages.add(outage_id)
                rate_tracker = record_tweet_post(rate_tracker)
                new_posts += 1
                
                # Add delay between posts to respect rate limits and avoid spam appearance
                if new_posts < RateLimitConfig.MAX_POSTS_PER_RUN:
                    delay = RateLimitConfig.MIN_INTERVAL_BETWEEN_POSTS
                    logger.info(f"⏳ Waiting {delay} seconds before next post...")
                    time.sleep(delay)
                
            except tweepy.TooManyRequests:
                logger.error("❌ Twitter rate limit exceeded. Stopping for this run.")
                break
            except tweepy.Forbidden as e:
                logger.error(f"❌ Twitter API forbidden error: {e}")
                continue
            except Exception as e:
                logger.error(f"❌ Failed to post tweet for outage {outage_id}: {e}")
                continue
    
    # Save updated data
    save_posted_outages(posted_outages)
    save_rate_limit_tracker(rate_tracker)
    
    if new_posts > 0:
        logger.info(f"🎉 Posted {new_posts} new outage(s) to Twitter")
    else:
        logger.info("ℹ️ No new outages to post")
    
    # Log current rate limit status
    posts_24h = len([
        p for p in rate_tracker.get('posts', [])
        if datetime.fromisoformat(p) > datetime.now() - timedelta(hours=24)
    ])
    logger.info(f"📊 Rate limit status: {posts_24h}/{RateLimitConfig.POST_TWEETS_PER_24H} posts in last 24h")

if __name__ == "__main__":
    main()
