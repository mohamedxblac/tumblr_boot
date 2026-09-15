"""Resolve one Firefox profile and preserve Tumblr container cookies across restart."""

import configparser
import json
import os
import re
import shutil
import sqlite3
import time
from pathlib import Path


_USER_CONTEXT_PATTERN = re.compile(r"(?:^|[&^])userContextId=(\d+)(?:&|$)")


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


def _container_user_context_ids(profile_dir: str, slot_count: int) -> list[int]:
    """Map Firefox container shortcut slots to their persistent context IDs."""
    containers_file = Path(profile_dir) / "containers.json"
    if not containers_file.is_file():
        raise RuntimeError(
            "Firefox containers.json was not found. Install/enable Multi-Account "
            "Containers and configure the requested container shortcuts."
        )
    try:
        payload = json.loads(containers_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise RuntimeError(f"Could not read Firefox containers.json: {error}") from error

    context_ids = []
    for identity in payload.get("identities", []):
        try:
            context_id = int(identity.get("userContextId", 0))
        except (TypeError, ValueError):
            continue
        if context_id > 0 and identity.get("public", True) and context_id not in context_ids:
            context_ids.append(context_id)
        if len(context_ids) >= slot_count:
            break
    if len(context_ids) < slot_count:
        raise RuntimeError(
            f"Firefox has only {len(context_ids)} usable container(s), but "
            f"{slot_count} login slot(s) were requested."
        )
    return context_ids


def _origin_context_id(origin_attributes: str) -> int | None:
    match = _USER_CONTEXT_PATTERN.search(str(origin_attributes or ""))
    return int(match.group(1)) if match else None


def clear_container_sessions_offline(
    profile_dir: str,
    slot_count: int,
) -> tuple[list[int], dict[int, int], int]:
    """Clear cookies and Tumblr web storage while Firefox is closed.

    Working against the persistent profile removes the old dependency on an
    active foreground desktop. That makes this phase reliable in RDP sessions,
    where keyboard shortcuts after the first container can be dropped.
    """
    profile = Path(profile_dir).resolve()
    context_ids = _container_user_context_ids(str(profile), slot_count)
    requested_ids = set(context_ids)
    database = profile / "cookies.sqlite"
    if not database.is_file():
        raise RuntimeError("Firefox cookies.sqlite was not found before container cleanup.")

    backup = database.with_name("cookies.sqlite.tumblr-bot-pre-cleanup")
    shutil.copy2(database, backup)
    deleted_by_context = {context_id: 0 for context_id in context_ids}
    connection = sqlite3.connect(database, timeout=15)
    try:
        connection.execute("PRAGMA busy_timeout = 15000")
        rows = connection.execute(
            "SELECT id, originAttributes FROM moz_cookies"
        ).fetchall()
        delete_ids = []
        for cookie_id, origin_attributes in rows:
            context_id = _origin_context_id(origin_attributes)
            if context_id in requested_ids:
                delete_ids.append((cookie_id,))
                deleted_by_context[context_id] += 1
        if delete_ids:
            connection.executemany("DELETE FROM moz_cookies WHERE id = ?", delete_ids)
        connection.commit()
        remaining = connection.execute(
            "SELECT originAttributes FROM moz_cookies"
        ).fetchall()
        uncleared = {
            context_id
            for (origin_attributes,) in remaining
            if (context_id := _origin_context_id(origin_attributes)) in requested_ids
        }
        if uncleared:
            raise RuntimeError(
                "Firefox container cookie verification failed for context ID(s): "
                + ", ".join(str(value) for value in sorted(uncleared))
            )
    except sqlite3.Error as error:
        connection.rollback()
        raise RuntimeError(f"Could not clear Firefox container cookies: {error}") from error
    finally:
        connection.close()

    deleted_storage_dirs = 0
    storage_root = (profile / "storage").resolve()
    if storage_root.is_dir():
        for storage_kind in ("default", "temporary", "permanent"):
            storage_dir = (storage_root / storage_kind).resolve()
            if not storage_dir.is_dir():
                continue
            for child in storage_dir.iterdir():
                context_id = _origin_context_id(child.name)
                if context_id not in requested_ids or "tumblr" not in child.name.lower():
                    continue
                resolved_child = child.resolve()
                try:
                    resolved_child.relative_to(storage_root)
                except ValueError as error:
                    raise RuntimeError(
                        f"Refusing to remove storage outside the Firefox profile: {resolved_child}"
                    ) from error
                if resolved_child.is_dir():
                    shutil.rmtree(resolved_child)
                else:
                    resolved_child.unlink()
                deleted_storage_dirs += 1

    return context_ids, deleted_by_context, deleted_storage_dirs


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
