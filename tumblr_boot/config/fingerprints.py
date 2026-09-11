# -*- coding: utf-8 -*-
import random

USER_AGENTS_WINDOWS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 11.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 11.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
]

USER_AGENTS_MAC = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_2_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
]

USER_AGENTS_LINUX = [
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
]

SCREEN_RESOLUTIONS = [
    {"width": 1920, "height": 1080, "avail_height": 1040},
    {"width": 1536, "height": 864,  "avail_height": 824},
    {"width": 1440, "height": 900,  "avail_height": 875},
    {"width": 1366, "height": 768,  "avail_height": 728},
    {"width": 1680, "height": 1050, "avail_height": 1010},
    {"width": 1600, "height": 900,  "avail_height": 860},
    {"width": 1280, "height": 800,  "avail_height": 760},
    {"width": 1920, "height": 1200, "avail_height": 1160},
]

WEBGL_PROFILES_WINDOWS = [
    {"vendor": "Google Inc. (NVIDIA)", "renderer": "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)"},
    {"vendor": "Google Inc. (NVIDIA)", "renderer": "ANGLE (NVIDIA, NVIDIA GeForce GTX 1660 SUPER Direct3D11 vs_5_0 ps_5_0, D3D11)"},
    {"vendor": "Google Inc. (NVIDIA)", "renderer": "ANGLE (NVIDIA, NVIDIA GeForce RTX 4070 Direct3D11 vs_5_0 ps_5_0, D3D11)"},
    {"vendor": "Google Inc. (NVIDIA)", "renderer": "ANGLE (NVIDIA, NVIDIA GeForce GTX 1070 Direct3D11 vs_5_0 ps_5_0, D3D11)"},
    {"vendor": "Google Inc. (Intel)",  "renderer": "ANGLE (Intel, Intel(R) Iris(R) Xe Graphics Direct3D11 vs_5_0 ps_5_0, D3D11)"},
    {"vendor": "Google Inc. (AMD)",    "renderer": "ANGLE (AMD, AMD Radeon RX 6700 XT Direct3D11 vs_5_0 ps_5_0, D3D11)"},
]

WEBGL_PROFILES_MAC = [
    {"vendor": "Apple Inc.", "renderer": "Apple M1 Pro"},
    {"vendor": "Apple Inc.", "renderer": "Apple M2"},
    {"vendor": "Apple Inc.", "renderer": "Apple M3 Max"},
    {"vendor": "Google Inc. (Apple)", "renderer": "ANGLE (Apple, Apple M1, OpenGL 4.1)"},
    {"vendor": "Google Inc. (Apple)", "renderer": "ANGLE (Apple, Apple M2 Pro, OpenGL 4.1)"},
]

WEBGL_PROFILES_LINUX = [
    {"vendor": "Mesa/X.org", "renderer": "Mesa Intel(R) UHD Graphics (CML GT2)"},
    {"vendor": "X.Org", "renderer": "AMD Radeon RX 580 Series (radeonsi, polaris10, LLVM 15.0.7)"},
]

TIMEZONE_PROFILES = [
    {"tz": "America/New_York",    "locale": "en-US", "languages": ["en-US", "en"]},
    {"tz": "America/Chicago",     "locale": "en-US", "languages": ["en-US", "en"]},
    {"tz": "America/Los_Angeles", "locale": "en-US", "languages": ["en-US", "en"]},
    {"tz": "America/Toronto",     "locale": "en-CA", "languages": ["en-CA", "en-US", "en"]},
    {"tz": "Europe/London",       "locale": "en-GB", "languages": ["en-GB", "en"]},
    {"tz": "Europe/Berlin",       "locale": "de-DE", "languages": ["de-DE", "de", "en"]},
    {"tz": "Europe/Paris",        "locale": "fr-FR", "languages": ["fr-FR", "fr", "en"]},
    {"tz": "Australia/Sydney",    "locale": "en-AU", "languages": ["en-AU", "en"]},
]


# توليد بصمة متصفح وهمية متناسقة وواقعية لتفادي كشف البوت وحظر الحسابات
def generate_stealth_fingerprint() -> dict:
    platform_choice = random.choices(["windows", "mac", "linux"], weights=[80, 15, 5])[0]

    if platform_choice == "windows":
        ua = random.choice(USER_AGENTS_WINDOWS)
        platform = "Win32"
        webgl = random.choice(WEBGL_PROFILES_WINDOWS)
    elif platform_choice == "mac":
        ua = random.choice(USER_AGENTS_MAC)
        platform = "MacIntel"
        webgl = random.choice(WEBGL_PROFILES_MAC)
    else:
        ua = random.choice(USER_AGENTS_LINUX)
        platform = "Linux x86_64"
        webgl = random.choice(WEBGL_PROFILES_LINUX)

    res = random.choice(SCREEN_RESOLUTIONS)
    tz = random.choice(TIMEZONE_PROFILES)
    cores = random.choice([4, 6, 8, 12, 16])
    memory = random.choice([4, 8, 16])

    return {
        "platform_type": platform_choice,
        "user_agent": ua,
        "platform": platform,
        "screen_width": res["width"],
        "screen_height": res["height"],
        "avail_height": res["avail_height"],
        "webgl_vendor": webgl["vendor"],
        "webgl_renderer": webgl["renderer"],
        "timezone": tz["tz"],
        "locale": tz["locale"],
        "languages": tz["languages"],
        "hardware_concurrency": cores,
        "device_memory": memory,
    }
