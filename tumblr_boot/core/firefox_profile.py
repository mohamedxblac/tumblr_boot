"""Resolve one Firefox profile and preserve Tumblr container cookies across restart."""

import configparser
import os
import shutil
import sqlite3
import time
from pathlib import Path


def _resolve_profile(root: Path, value: str) -> Path:
    candidate = Path(os.path.expandvars(value))
    return candidate if candidate.is_absolute() else root / candidate


def find_default_profile() -> str:
    root = Path(os.environ.get("APPDATA", "")) / "Mozilla" / "Firefox"
    candidates = []
    for filename in ("installs.ini", "profiles.ini"):
        path = root / filename
        if not path.is_file():
            continue
        parser = configparser.RawConfigParser()
        parser.read(path, encoding="utf-8")
        for section in parser.sections():
            if parser.has_option(section, "Default"):
                value = parser.get(section, "Default").strip()
                if value and value not in {"0", "1"}:
                    candidates.append(_resolve_profile(root, value))
        for section in parser.sections():
            if not section.lower().startswith("profile"):
                continue
            value = parser.get(section, "Path", fallback="").strip()
            if not value:
                continue
            profile = _resolve_profile(root, value)
            if parser.get(section, "Default", fallback="0") == "1":
                candidates.insert(0, profile)
            else:
                candidates.append(profile)
    seen = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if resolved.is_dir() and (resolved / "prefs.js").is_file():
            return str(resolved)
    raise RuntimeError(
        "Firefox's default profile could not be found from profiles.ini/installs.ini."
    )


def snapshot_tumblr_cookies(profile_dir: str) -> tuple[list[str], list[tuple]]:
    database = Path(profile_dir) / "cookies.sqlite"
    if not database.is_file():
        raise RuntimeError("Firefox cookies.sqlite was not found after native login.")
    last_error = None
    for _ in range(12):
        try:
            connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True, timeout=3)
            try:
                columns = [row[1] for row in connection.execute("PRAGMA table_info(moz_cookies)")]
                placeholders = ", ".join(f'"{column}"' for column in columns)
                rows = connection.execute(
                    f"SELECT {placeholders} FROM moz_cookies "
                    "WHERE host = 'tumblr.com' OR host LIKE '%.tumblr.com'"
                ).fetchall()
                if rows:
                    return columns, rows
            finally:
                connection.close()
        except sqlite3.Error as error:
            last_error = error
        time.sleep(0.5)
    if last_error:
        raise RuntimeError(f"Could not read Tumblr cookies from Firefox: {last_error}")
    raise RuntimeError("No Tumblr cookies were saved after native login.")


def restore_tumblr_cookies(profile_dir: str, snapshot: tuple[list[str], list[tuple]]) -> int:
    columns, rows = snapshot
    database = Path(profile_dir) / "cookies.sqlite"
    if not database.is_file():
        raise RuntimeError("Firefox cookies.sqlite disappeared before session restore.")
    backup = database.with_name("cookies.sqlite.tumblr-bot-backup")
    shutil.copy2(database, backup)
    names = ", ".join(f'"{column}"' for column in columns)
    parameters = ", ".join("?" for _ in columns)
    connection = sqlite3.connect(database, timeout=15)
    try:
        connection.executemany(
            f"INSERT OR REPLACE INTO moz_cookies ({names}) VALUES ({parameters})",
            rows,
        )
        connection.commit()
    finally:
        connection.close()
    return len(rows)
