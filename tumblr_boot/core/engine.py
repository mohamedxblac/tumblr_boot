# -*- coding: utf-8 -*-
"""
core/engine.py — Bot Orchestration Engine
=========================================
Coordinates the entire bot lifecycle in a dedicated background worker thread:
- Fingerprint rotation and browser isolation per account
- Automatic scraping when target queue drops below threshold
- Direct message delivery with human-like timing, typing, and follows
- Live reporting of status, progress, countdowns, and logs via a thread-safe Queue
- Graceful pause, resume, and stop controls
"""

import os
import time
import random
import threading
import queue
from typing import List, Dict, Optional, Any

from config.settings import SettingsManager
from core.browser import BrowserFactory
from core.auth import login, logout, dismiss_consent_screen_if_present
from core.scraper import scrape_post_master_queue, parse_post_info
from core.messenger import send_message_to_user, compose_message_parts
from core.persistence import persistence
from utils.logger import logger
from utils.helpers import random_sleep


class BotEngine:
    """Multi-account automated messaging engine with threading and GUI integration."""

    def __init__(self, settings_mgr: SettingsManager, gui_queue: Optional[queue.Queue] = None):
        self.settings_mgr = settings_mgr
        self.gui_queue = gui_queue or queue.Queue()

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._is_running = False

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def is_paused(self) -> bool:
        return self._pause_event.is_set()

    def post_gui_update(self, event_type: str, data: Dict[str, Any]):
        """Pushes a structured event to the GUI message queue."""
        if self.gui_queue:
            self.gui_queue.put({"type": event_type, **data})

    def start(self):
        """Starts the bot engine in a background thread."""
        if self._is_running:
            logger.warning("[ENGINE] Bot is already running.")
            return

        self._stop_event.clear()
        self._pause_event.clear()
        self._is_running = True

        self._thread = threading.Thread(target=self._run_loop, name="BotEngineWorker", daemon=True)
        self._thread.start()
        self.post_gui_update("state_changed", {"running": True, "paused": False})
        logger.info("[ENGINE] Bot engine started.")

    def pause(self):
        """Pauses the bot between tasks."""
        if not self._is_running:
            return
        self._pause_event.set()
        self.post_gui_update("state_changed", {"running": True, "paused": True})
        logger.info("[ENGINE] Pause requested.")

    def resume(self):
        """Resumes the bot from pause."""
        if not self._is_running:
            return
        self._pause_event.clear()
        self.post_gui_update("state_changed", {"running": True, "paused": False})
        logger.info("[ENGINE] Resumed from pause.")

    def stop(self):
        """Signals the engine to stop gracefully."""
        if not self._is_running:
            return
        self._stop_event.set()
        self._pause_event.clear()
        logger.info("[ENGINE] Stop requested. Waiting for current action to wrap up...")

    def _sleep_with_checks(self, seconds: float, label: str = "Waiting") -> bool:
        """
        Sleeps for the given number of seconds while checking stop and pause flags every 0.5s.
        Posts live countdown updates to the GUI. Returns False if stopped.
        """
        remaining = float(seconds)
        step = 0.5
        while remaining > 0:
            if self._stop_event.is_set():
                return False

            while self._pause_event.is_set():
                if self._stop_event.is_set():
                    return False
                self.post_gui_update("status_info", {"status": "Paused", "detail": "Paused by user"})
                time.sleep(0.5)

            self.post_gui_update("countdown", {
                "label": label,
                "remaining": int(remaining),
                "total": int(seconds)
            })

            time.sleep(min(step, remaining))
            remaining -= step

        self.post_gui_update("countdown", {"label": "", "remaining": 0, "total": 0})
        return True

    def _run_loop(self):
        """Main execution thread."""
        try:
            settings = self.settings_mgr.get_settings()
            accounts = self.settings_mgr.get_accounts()
            messages = self.settings_mgr.get_messages()
            greetings = self.settings_mgr.get_greetings()

            post_url = settings.get("post_url", "").strip()
            tab_type = settings.get("tab_type", "likes").strip().lower()
            max_per_account = int(settings.get("max_success_per_account", 30))
            session_cap = int(settings.get("session_success_cap", 15))
            no_msg_limit = int(settings.get("no_message_limit", 10))
            line_delay = float(settings.get("line_delay", 7.55))
            after_send_delay = float(settings.get("after_send_delay", 2.2))
            after_success_delay = float(settings.get("after_success_delay", 2.2))
            min_between = float(settings.get("min_between_users", 60))
            max_between = float(settings.get("max_between_users", 130))
            notes_max = int(settings.get("notes_max_users", 3000))
            follow_every = int(settings.get("follow_every_n", 4))
            scrape_threshold = int(settings.get("scrape_threshold", 15))
            scrape_timeout = int(settings.get("scrape_timeout_sec", 150))
            enable_fp_rotation = bool(settings.get("enable_fingerprint_rotation", True))
            start_acc_idx = int(settings.get("start_account_index", 0))

            if not post_url:
                logger.error("[ENGINE] No Target Post URL specified! Please set one in Settings.")
                self.post_gui_update("error", {"message": "Please specify a Target Post URL in Settings."})
                return

            if not accounts:
                logger.error("[ENGINE] No accounts configured! Please add accounts in the Accounts tab.")
                self.post_gui_update("error", {"message": "No accounts available to run."})
                return

            if not messages:
                logger.error("[ENGINE] No message templates configured!")
                self.post_gui_update("error", {"message": "No message templates configured."})
                return

            sent_users = persistence.load_sent_users()
            progress = persistence.load_progress()
            target_queue = persistence.load_target_queue()

            # Global round loop
            while not self._stop_event.is_set():
                # Filter pending accounts
                pending_accounts = [
                    accounts[i]
                    for i in range(start_acc_idx, len(accounts))
                    if int(progress.get(accounts[i]["email"], 0)) < max_per_account
                ]

                if not pending_accounts:
                    if start_acc_idx > 0:
                        start_acc_idx = 0
                        continue
                    logger.info("[ENGINE] All accounts have reached their target message limit!")
                    self.post_gui_update("status_info", {"status": "Complete", "detail": "All accounts finished"})
                    break

                logger.info(f"[ENGINE] Starting round with {len(pending_accounts)} pending accounts...")

                for acc_idx, acc in enumerate(pending_accounts):
                    if self._stop_event.is_set():
                        break

                    email = acc.get("email", "").strip()
                    password = acc.get("password", "").strip()

                    self.post_gui_update("account_active", {
                        "email": email,
                        "account_index": acc_idx + 1,
                        "total_accounts": len(pending_accounts),
                    })

                    self._process_single_account(
                        acc=acc,
                        post_url=post_url,
                        tab_type=tab_type,
                        target_queue=target_queue,
                        sent_users=sent_users,
                        progress=progress,
                        messages=messages,
                        greetings=greetings,
                        max_per_account=max_per_account,
                        session_cap=session_cap,
                        no_msg_limit=no_msg_limit,
                        line_delay=line_delay,
                        after_send_delay=after_send_delay,
                        after_success_delay=after_success_delay,
                        min_between=min_between,
                        max_between=max_between,
                        notes_max=notes_max,
                        follow_every=follow_every,
                        scrape_threshold=scrape_threshold,
                        scrape_timeout=scrape_timeout,
                        enable_fp_rotation=enable_fp_rotation,
                    )

                start_acc_idx = 0

                # Check if all accounts are done across the board
                still_pending = [
                    a for a in accounts
                    if int(progress.get(a["email"], 0)) < max_per_account
                ]
                if not still_pending or self._stop_event.is_set():
                    break

                # Sleep between rounds
                sleep_hrs = float(settings.get("sleep_between_rounds_hrs", 12))
                sleep_seconds = sleep_hrs * 3600
                logger.info(f"[ENGINE] Round finished. Sleeping {sleep_hrs} hours before next cycle...")
                if not self._sleep_with_checks(sleep_seconds, label=f"Next Round in ({sleep_hrs}h)"):
                    break

        except Exception as e:
            logger.error(f"[ENGINE] Unhandled exception in run loop: {e}")
        finally:
            self._is_running = False
            self.post_gui_update("state_changed", {"running": False, "paused": False})
            self.post_gui_update("status_info", {"status": "Idle", "detail": "Bot stopped"})
            logger.info("[ENGINE] Bot engine stopped cleanly.")

    def _process_single_account(
        self,
        acc: dict,
        post_url: str,
        tab_type: str,
        target_queue: List[str],
        sent_users: set,
        progress: dict,
        messages: List[str],
        greetings: List[str],
        max_per_account: int,
        session_cap: int,
        no_msg_limit: int,
        line_delay: float,
        after_send_delay: float,
        after_success_delay: float,
        min_between: float,
        max_between: float,
        notes_max: int,
        follow_every: int,
        scrape_threshold: int,
        scrape_timeout: int,
        enable_fp_rotation: bool,
    ):
        email = acc["email"]
        password = acc["password"]

        total_ok = int(progress.get(email, 0))
        session_ok = 0
        fail_count = 0
        no_msg_streak = 0
        account_note = "completed"

        driver = None
        profile_dir = None

        try:
            self.post_gui_update("status_info", {
                "status": "Starting Browser",
                "detail": f"Initializing browser for {email}"
            })

            # ── 1. Create Browser with Stealth & Fingerprint ─────────────────
            fp = None if enable_fp_rotation else {"user_agent": "", "screen_width": 1920, "screen_height": 1080}
            driver, profile_dir, used_fp = BrowserFactory.create_browser(fingerprint=fp)

            if not login(driver, email, password):
                account_note = "login_failed"
                logger.log_event(email, total_ok, fail_count, note=account_note)
                logger.log_summary(email, total_ok, fail_count, note=account_note)
                return

            self.post_gui_update("status_info", {
                "status": "Logged In",
                "detail": f"Active: {email} | Target limit: {total_ok}/{max_per_account}"
            })

            # ── 2. Check Queue & Scrape if Below Threshold ───────────────────
            uncontacted = [u for u in target_queue if u not in sent_users]

            if len(uncontacted) < scrape_threshold and not self._stop_event.is_set():
                self.post_gui_update("status_info", {
                    "status": "Scraping Notes",
                    "detail": f"Queue low ({len(uncontacted)}). Scraping fresh users..."
                })

                owner_blog, _ = parse_post_info(post_url)
                fresh_users = scrape_post_master_queue(
                    driver=driver,
                    post_url=post_url,
                    tab_type=tab_type,
                    owner_blog=owner_blog or "",
                    already_sent=sent_users,
                    max_users=notes_max,
                    timeout_sec=scrape_timeout,
                    progress_callback=lambda count, total: self.post_gui_update("scrape_progress", {"count": count, "max": total}),
                    stop_check=lambda: self._stop_event.is_set()
                )

                for u in fresh_users:
                    if u not in target_queue:
                        target_queue.append(u)
                persistence.save_target_queue(target_queue)
                uncontacted = [u for u in target_queue if u not in sent_users]

            if not uncontacted:
                account_note = "no_uncontacted_users_left"
                logger.log_event(email, total_ok, fail_count, note=account_note)
                logger.log_summary(email, total_ok, fail_count, note=account_note)
                logout(driver)
                return

            logger.info(f"[{email}] Ready! Processing up to {session_cap} users in this session...")

            # ── 3. Send DMs Sequentially in Same Browser Tab ─────────────────
            msg_i = 0
            greet_i = 0
            users_seen = 0

            for username in uncontacted:
                if self._stop_event.is_set():
                    account_note = "stopped_by_user"
                    break

                while self._pause_event.is_set():
                    if self._stop_event.is_set():
                        break
                    time.sleep(0.5)

                if session_ok >= session_cap:
                    account_note = f"session_cap_{session_cap}_reached"
                    logger.log_event(email, total_ok, fail_count, note=account_note)
                    break

                if total_ok >= max_per_account:
                    account_note = f"reached_max_{max_per_account}"
                    logger.log_event(email, total_ok, fail_count, note=account_note)
                    break

                username = username.strip().lower()
                if not username or username in sent_users:
                    continue

                users_seen += 1
                do_follow = (follow_every > 0 and users_seen % follow_every == 0)

                base_msg = messages[msg_i % len(messages)]
                greeting = greetings[greet_i % len(greetings)]
                parts = compose_message_parts(username, base_msg, greeting, msg_i)
                msg_i += 1
                greet_i += 1

                self.post_gui_update("status_info", {
                    "status": "Messaging",
                    "detail": f"Sending DM to: @{username} (session: {session_ok + 1}/{session_cap})"
                })

                result, ok_follow = send_message_to_user(
                    driver=driver,
                    username=username,
                    messages=parts,
                    do_follow=do_follow,
                    line_delay=line_delay,
                    after_send_delay=after_send_delay,
                )

                if do_follow:
                    logger.log_event(email, total_ok, fail_count, note=f"follow | user={username} | ok={ok_follow}")

                if result == "could_not_send":
                    account_note = "could_not_send"
                    logger.log_event(email, total_ok, fail_count, note=account_note)
                    break

                if result == "no_message_button":
                    fail_count += 1
                    no_msg_streak += 1
                    logger.log_event(
                        email, total_ok, fail_count,
                        note=f"no_msg_button streak={no_msg_streak}/{no_msg_limit} user={username}"
                    )
                    if no_msg_streak >= no_msg_limit:
                        account_note = f"{no_msg_limit}x_no_msg_button_logout"
                        logger.log_event(email, total_ok, fail_count, note=account_note)
                        break

                    delay = random.uniform(min_between, max_between)
                    if not self._sleep_with_checks(delay, label=f"Next user (@{username})"):
                        break
                    continue

                no_msg_streak = 0

                if result is True:
                    persistence.save_sent_user(username)
                    sent_users.add(username)
                    total_ok += 1
                    session_ok += 1
                    progress[email] = total_ok
                    persistence.save_progress(progress)

                    self.post_gui_update("progress_update", {
                        "email": email,
                        "total_ok": total_ok,
                        "session_ok": session_ok,
                        "total_sent": len(sent_users),
                    })

                    logger.log_event(
                        email, total_ok, fail_count,
                        note=f"sent_ok | user={username} | session={session_ok}/{session_cap} | total={total_ok}/{max_per_account}"
                    )

                    time.sleep(after_success_delay)
                    delay = random.uniform(min_between, max_between)
                    if not self._sleep_with_checks(delay, label=f"Next user (@{username})"):
                        break
                else:
                    fail_count += 1
                    logger.log_event(email, total_ok, fail_count, note=f"send_failed | user={username}")
                    delay = random.uniform(min_between, max_between)
                    if not self._sleep_with_checks(delay, label=f"Retry/Next (@{username})"):
                        break

            # ── 4. Clean Logout ──────────────────────────────────────────────
            logger.log_summary(email, total_ok, fail_count, note=account_note)
            logout(driver)

        except Exception as e:
            logger.error(f"[ENGINE] Session exception for {email}: {e}")
            logger.log_summary(email, total_ok, fail_count, note=f"session_exception: {e}")
            if driver:
                BrowserFactory.capture_screenshot(driver, prefix=f"crash_{email.split('@')[0]}")
        finally:
            BrowserFactory.close_browser(driver, profile_dir)
            time.sleep(2.0)
