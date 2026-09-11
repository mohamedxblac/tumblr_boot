# -*- coding: utf-8 -*-
import re
import time
import random
from datetime import datetime
from typing import Optional
from urllib.parse import unquote, urlsplit

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


# استخراج التوقيت الحالي بصيغة YYYY-MM-DD HH:MM:SS
def now_ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# استخراج اسم المستخدم من رابط أو نص وتنظيفه
def extract_username(url_or_str: str) -> str:
    if not url_or_str:
        return ""
    
    value = url_or_str.strip().lower().lstrip("@")
    if "://" not in value and not value.startswith("//"):
        if value.split("/", 1)[0].split("?", 1)[0].endswith("tumblr.com"):
            value = "https://" + value
    try:
        parsed = urlsplit(value)
    except ValueError:
        return ""
    host = parsed.hostname or ""
    if host.endswith(".tumblr.com") and host != "www.tumblr.com":
        return host.removesuffix(".tumblr.com")
    if host and host not in ("tumblr.com", "www.tumblr.com"):
        return ""
    parts = [unquote(part).lower() for part in parsed.path.split("/") if part]
    if host and parts[:2] == ["blog", "view"]:
        parts = parts[2:]
    return parts[0].lstrip("@") if parts else ""


# التحقق من صحة اسم الحساب والتأكد أنه ليس رابطاً نظامياً أو كلمة محجوزة
def is_valid_blog(name: str) -> bool:
    if not name or not isinstance(name, str):
        return False
    
    name = name.strip().lower()
    if not name or name in RESERVED_USERNAMES:
        return False
        
    if any(name.startswith(p) for p in BAD_PREFIXES):
        return False
        
    return bool(re.match(r"^[a-z0-9][a-z0-9\-]{0,30}[a-z0-9]$|^[a-z0-9]$", name))


# استخراج اسم الحساب من وسم الرابط (href)
def extract_blog_from_href(href: str) -> Optional[str]:
    if not href:
        return None
    candidate = extract_username(href.strip().lower())
    return candidate if is_valid_blog(candidate) else None


# انتظار عشوائي بين حدين أدنى وأقصى لمحاكاة السلوك البشري
def random_sleep(min_s: float, max_s: float) -> float:
    if max_s < min_s:
        max_s = min_s
    actual = random.uniform(min_s, max_s)
    time.sleep(actual)
    return actual


# تحويل الثواني إلى صيغة مقروءة (ساعات ودقائق وثواني)
def format_seconds(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    rem_seconds = seconds % 60
    if minutes < 60:
        return f"{minutes}m {rem_seconds:02d}s"
    return f"{minutes // 60}h {minutes % 60:02d}m {rem_seconds:02d}s"
