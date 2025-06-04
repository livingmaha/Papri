# backend/ai_agents/utils.py
import logging
import re
from urllib.parse import urlparse, urljoin
from datetime import datetime, timedelta
import hashlib
import unicodedata # For normalizing unicode text

# from some_library import some_specific_utility # Example

logger = logging.getLogger(__name__)

def clean_text(text: str) -> str:
    """Basic text cleaning: lowercase, remove extra whitespace."""
    if not text:
        return ""
    text = text.lower().strip()
    text = re.sub(r'\s+', ' ', text) # Replace multiple spaces with single
    return text

def normalize_text_unicode(text: str, form='NFKC') -> str:
    """
    Normalize Unicode text to a standard form.
    'NFKC' is often good for matching and case-folding.
    """
    if not text:
        return ""
    return unicodedata.normalize(form, text)

def generate_deduplication_hash(title: str, duration_seconds: int = None, platform_video_id: str = None) -> str:
    """
    Generates a simple deduplication hash based on title and optionally duration/platform ID.
    This is a basic example; more robust methods might involve near-duplicate detection algorithms.
    """
    data_string = normalize_text_unicode(title.lower())
    if duration_seconds is not None:
        # Normalize duration slightly to catch minor variations, e.g., group into 5-second buckets
        # This is a simple heuristic and might need adjustment.
        normalized_duration = (duration_seconds // 5) * 5
        data_string += f"|duration:{normalized_duration}"
    if platform_video_id: # If available, this is a strong signal for same video on same platform
        data_string += f"|pid:{platform_video_id.lower()}"

    return hashlib.sha256(data_string.encode('utf-8')).hexdigest()


def calculate_time_ago(dt_object: datetime) -> str:
    """Calculates a human-readable 'time ago' string."""
    if not isinstance(dt_object, datetime):
        return "Unknown time"
    
    now = timezone.now() if timezone.is_aware(dt_object) else datetime.now()
    diff = now - dt_object
    
    seconds = diff.total_seconds()
    if seconds < 0: # Future date
        return "In the future"
    if seconds < 60:
        return f"{int(seconds)} seconds ago"
    
    minutes = seconds / 60
    if minutes < 60:
        return f"{int(minutes)} minutes ago"
        
    hours = minutes / 60
    if hours < 24:
        return f"{int(hours)} hours ago"
        
    days = hours / 24
    if days < 7:
        return f"{int(days)} days ago"
    if days < 30:
        return f"{int(days / 7)} weeks ago"
    if days < 365:
        return f"{int(days / 30)} months ago"
        
    return f"{int(days / 365)} years ago"

def robust_json_loads(json_string, default_value=None):
    """Safely load JSON string, returning default_value on failure."""
    if not json_string:
        return default_value
    try:
        return json.loads(json_string)
    except json.JSONDecodeError:
        logger.warning(f"Failed to decode JSON string: {json_string[:100]}...")
        return default_value

def get_domain_from_url(url: str) -> str:
    """Extracts the domain (e.g., 'youtube.com') from a URL."""
    if not url:
        return ""
    try:
        parsed_url = urlparse(url)
        return parsed_url.netloc.replace('www.', '')
    except Exception:
        return ""

def make_absolute_url(base_url: str, relative_url: str) -> str:
    """Converts a relative URL to an absolute URL given a base URL."""
    if not relative_url:
        return base_url # Or None, depending on desired behavior
    if urlparse(relative_url).scheme: # Already absolute
        return relative_url
    return urljoin(base_url, relative_url)

# Add more utility functions as needed, e.g., for specific API interactions, data transformations, etc.
