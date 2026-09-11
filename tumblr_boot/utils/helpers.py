# -*- coding: utf-8 -*-
"""
utils/helpers.py — Utility Functions & Helper Methods
=====================================================
URL parsing, username extraction, blog validation, timing, and formatting helpers.
"""

import re
import time
import random
from datetime import datetime
from typing import Optional

# Reserved words / Tumblr system URLs that should never be targeted
RESERVED_USERNAMES = {
    "dashboard", "explore", "settings", "help", "about", "press", "terms",
    "privacy", "policy", "jobs", "developers", "support", "security",
    "search", "inbox", "activity", "following", "likes", "login", "register",
    "tagged", "communities", "blog", "blogs", "edit", "new", "archive",
    "posts", "themes", "mega-editor", "api", "static", "assets", "none"
}

BAD_PREFIXES = (
    "https://", "http://", "assets.", "static.", "help.", "api.",
    "www.tumblr.com", "tumblr.com"
)


def now_ts() -> str:
    """Returns current timestamp formatted as YYYY-MM-DD HH:MM:SS."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def extract_username(url_or_str: str) -> str:
    """
    Extracts a clean, lowercase Tumblr username from a URL or raw string.
    Handles subdomains (user.tumblr.com), paths (tumblr.com/user), and plain names.
    """
    if not url_or_str:
        return ""
    
    url = url_or_str.strip().lower()
    url = url.replace("https://", "").replace("http://", "").replace("www.", "")
    
    if ".tumblr.com" in url:
        part = url.split(".tumblr.com")[0].strip("/")
        return part.split("/")[-1]
    
    if "tumblr.com/" in url:
        part = url.split("tumblr.com/")[1].strip("/")
        return part.split("/")[0]
        
    return url.strip("/").split("/")[0]


def is_valid_blog(name: str) -> bool:
    """
    Validates if a scraped name represents an actual valid Tumblr blog handle.
    Rules:
    - 1 to 32 characters
    - only lowercase letters, digits, and hyphens
    - cannot start or end with a hyphen
    - not a reserved Tumblr system name
    - not a system URL prefix
    """
    if not name or not isinstance(name, str):
        return False
    
    name = name.strip().lower()
    if not name:
        return False
        
    if name in RESERVED_USERNAMES:
        return False
        
    if any(name.startswith(p) for p in BAD_PREFIXES):
        return False
        
    # Tumblr handles: 1-32 chars, a-z, 0-9, hyphens, not leading/trailing hyphen
    if not re.match(r"^[a-z0-9][a-z0-9\-]{0,30}[a-z0-9]$|^[a-z0-9]$", name):
        return False
        
    return True


def extract_blog_from_href(href: str) -> Optional[str]:
    """Extracts a valid blog name from an anchor href, or returns None."""
    if not href:
        return None
    
    raw = href.strip().lower()
    candidate = extract_username(raw)
    
    if is_valid_blog(candidate):
        return candidate
    return None


def random_sleep(min_s: float, max_s: float) -> float:
    """Sleeps for a random duration between min_s and max_s with jitter."""
    if max_s < min_s:
        max_s = min_s
    actual = random.uniform(min_s, max_s)
    time.sleep(actual)
    return actual


def format_seconds(seconds: float) -> str:
    """Formats seconds into human-readable 1h 23m 45s string."""
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    rem_seconds = seconds % 60
    if minutes < 60:
        return f"{minutes}m {rem_seconds:02d}s"
    hours = minutes // 60
    rem_minutes = minutes % 60
    return f"{hours}h {rem_minutes:02d}m {rem_seconds:02d}s"
