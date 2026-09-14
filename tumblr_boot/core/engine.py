# -*- coding: utf-8 -*-
import os
import time
import random
import threading
import queue
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Optional, Any

from config.settings import SettingsManager
from config.fingerprints import generate_stealth_fingerprint
from core.browser import BrowserFactory
from core.auth import login, logout, dismiss_consent_screen_if_present
from core.scraper import scrape_post_master_queue, parse_post_info
from core.messenger import (
    NonRepeatingTemplateRotator,
    compose_message_parts,
    send_message_to_user,
)
from core.persistence import persistence
from core.contact_history import ContactHistoryError, normalize_recipient
from utils.logger import logger
from utils.helpers import random_sleep


# محرك البوت الرئيسي الذي يدير عمليات التشغيل والإرسال والتنقل بين الحسابات في خيط معالجة مستقل
class BotEngine:
    def __init__(self, settings_mgr: SettingsManager, gui_queue: Optional[queue.Queue] = None):
        self.settings_mgr = settings_mgr
        self.gui_queue = gui_queue or queue.Queue()

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._is_running = False
        self._state_lock = threading.RLock()
        self._scrape_lock = threading.Lock()
        self._active_lock = threading.Lock()
        self._active_accounts = set()
        self._login_stats_lock = threading.Lock()
        self._login_success_count = 0
        self._login_failure_count = 0
        self._login_total_accounts = 0
        self._session_login_failed_accounts = set()
        self._session_login_results = {}

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def is_paused(self) -> bool:
        return self._pause_event.is_set()

    def post_gui_update(self, event_type: str, data: Dict[str, Any]):
        if self.gui_queue:
            self.gui_queue.put({"type": event_type, **data})

    def _reset_login_stats(self, total_accounts: int):
        with self._login_stats_lock:
            self._login_success_count = 0
            self._login_failure_count = 0
            self._login_total_accounts = total_accounts
            self._session_login_failed_accounts.clear()
            self._session_login_results.clear()
            snapshot = {
                "success": 0,
                "failed": 0,
                "processed": 0,
                "total": total_accounts,
            }
        self.post_gui_update("login_stats", snapshot)

    def _record_login_result(self, email: str, success: bool):
        with self._login_stats_lock:
            account_key = email.strip().lower()
            previous = self._session_login_results.get(account_key)
            if previous is not None and previous != success:
                if previous:
                    self._login_success_count -= 1
                else:
                    self._login_failure_count -= 1
            if previous is None or previous != success:
                if success:
                    self._login_success_count += 1
                else:
                    self._login_failure_count += 1
            self._session_login_results[account_key] = success
            if success:
                self._session_login_failed_accounts.discard(account_key)
            else:
                self._session_login_failed_accounts.add(account_key)
            snapshot = {
                "success": self._login_success_count,
                "failed": self._login_failure_count,
                "processed": self._login_success_count + self._login_failure_count,
                "total": self._login_total_accounts,
            }
        self.post_gui_update("login_stats", snapshot)

    def start(self):
        if self._is_running:
            logger.warning("[ENGINE] Bot is already running.")
            return

        self._stop_event.clear()
        self._pause_event.clear()
        self._is_running = True
        self._reset_login_stats(len(self.settings_mgr.get_accounts()))

        self._thread = threading.Thread(target=self._run_loop, name="BotEngineWorker", daemon=True)
        self._thread.start()
        self.post_gui_update("state_changed", {"running": True, "paused": False})
        logger.info("[ENGINE] Bot engine started.")

    def pause(self):
        if not self._is_running:
            return
        self._pause_event.set()
        self.post_gui_update("state_changed", {"running": True, "paused": True})
        logger.info("[ENGINE] Pause requested.")

    def resume(self):
        if not self._is_running:
            return
        self._pause_event.clear()
        self.post_gui_update("state_changed", {"running": True, "paused": False})
        logger.info("[ENGINE] Resumed from pause.")

    def stop(self):
        if not self._is_running:
            return
        self._stop_event.set()
        self._pause_event.clear()
        logger.info("[ENGINE] Stop requested. Waiting for current action to wrap up...")

    def _sleep_with_checks(self, seconds: float, label: str = "Waiting") -> bool:
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

    def _set_account_active(self, email: str, active: bool, total_accounts: int):
        with self._active_lock:
            if active:
                self._active_accounts.add(email)
            else:
                self._active_accounts.discard(email)
            active_accounts = sorted(self._active_accounts)
        self.post_gui_update("workers_active", {
            "accounts": active_accounts,
            "active_count": len(active_accounts),
            "total_accounts": total_accounts,
        })

    def _run_account_worker(self, *, total_accounts: int, **kwargs):
        email = kwargs["acc"].get("email", "").strip()
        self._set_account_active(email, True, total_accounts)
        try:
            return self._process_single_account(**kwargs)
        finally:
            self._set_account_active(email, False, total_accounts)

    def _run_loop(self):
        try:
            settings = self.settings_mgr.get_settings()
            accounts = self.settings_mgr.get_accounts()
            messages = self.settings_mgr.get_messages()
            greetings = self.settings_mgr.get_greetings()

            post_url = settings.get("post_url", "").strip()
            tab_type = settings.get("tab_type", "likes").strip().lower()
            max_per_account = int(settings.get("max_success_per_account", 30))
            session_cap = int(settings.get("session_success_cap", 15))
            parallel_accounts = max(1, min(10, int(settings.get("parallel_accounts", 1))))
            no_msg_limit = int(settings.get("no_message_limit", 10))
            action_delay = float(settings.get("action_delay", 0.5))
            typing_min_delay = max(0.01, float(settings.get("typing_min_delay", 0.05)))
            typing_max_delay = max(
                typing_min_delay,
                float(settings.get("typing_max_delay", 0.14)),
            )
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

            distinct_messages = list(dict.fromkeys(
                str(message).strip() for message in messages if str(message).strip()
            ))
            if len(distinct_messages) < 2:
                logger.error("[ENGINE] At least two different message templates are required!")
                self.post_gui_update("error", {
                    "message": (
                        "Please save at least two different message templates. "
                        "This is required to prevent consecutive recipients from receiving the same text."
                    )
                })
                return

            distinct_greetings = list(dict.fromkeys(
                str(greeting).strip() for greeting in greetings if str(greeting).strip()
            ))
            if not distinct_greetings:
                distinct_greetings = ["I hope this message finds you in peace"]

            message_rotator = NonRepeatingTemplateRotator(distinct_messages)
            greeting_rotator = NonRepeatingTemplateRotator(distinct_greetings)

            sent_users = persistence.load_sent_users()
            progress = persistence.load_progress()
            target_queue = persistence.load_target_queue()

            while not self._stop_event.is_set():
                pending_accounts = [
                    (i, accounts[i])
                    for i in range(start_acc_idx, len(accounts))
                    if int(progress.get(accounts[i]["email"], 0)) < max_per_account
                    and accounts[i]["email"].strip().lower() not in self._session_login_failed_accounts
                ]

                if not pending_accounts:
                    if start_acc_idx > 0:
                        start_acc_idx = 0
                        continue
                    logger.info("[ENGINE] All accounts have reached their target message limit!")
                    self.post_gui_update("status_info", {"status": "Complete", "detail": "All accounts finished"})
                    break

                worker_count = min(parallel_accounts, len(pending_accounts))
                logger.info(
                    f"[ENGINE] Starting round with {len(pending_accounts)} pending accounts "
                    f"across {worker_count} parallel browser(s)..."
                )

                with ThreadPoolExecutor(
                    max_workers=worker_count,
                    thread_name_prefix="TumblrAccount",
                ) as executor:
                    futures = []
                    for _, acc in pending_accounts:
                        futures.append(executor.submit(
                            self._run_account_worker,
                            total_accounts=len(pending_accounts),
                            acc=acc,
                            post_url=post_url,
                            tab_type=tab_type,
                            target_queue=target_queue,
                            sent_users=sent_users,
                            progress=progress,
                            messages=distinct_messages,
                            greetings=distinct_greetings,
                            max_per_account=max_per_account,
                            session_cap=session_cap,
                            no_msg_limit=no_msg_limit,
                            action_delay=action_delay,
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
                            typing_min_delay=typing_min_delay,
                            typing_max_delay=typing_max_delay,
                            message_rotator=message_rotator,
                            greeting_rotator=greeting_rotator,
                        ))

                    for future in as_completed(futures):
                        try:
                            future.result()
                        except ContactHistoryError:
                            self._stop_event.set()
                            for pending in futures:
                                pending.cancel()
                            raise

                start_acc_idx = 0

                still_pending = [
                    a for a in accounts
                    if int(progress.get(a["email"], 0)) < max_per_account
                    and a["email"].strip().lower() not in self._session_login_failed_accounts
                ]
                if not still_pending or self._stop_event.is_set():
                    break

                sleep_hrs = float(settings.get("sleep_between_rounds_hrs", 12))
                sleep_seconds = sleep_hrs * 3600
                logger.info(f"[ENGINE] Round finished. Sleeping {sleep_hrs} hours before next cycle...")
                if not self._sleep_with_checks(sleep_seconds, label=f"Next Round in ({sleep_hrs}h)"):
                    break

        except ContactHistoryError as e:
            logger.error(f"[ENGINE] {e}")
            self.post_gui_update("error", {"message": str(e)})
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
        action_delay: float,
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
        typing_min_delay: float = 0.05,
        typing_max_delay: float = 0.14,
        message_rotator: Optional[NonRepeatingTemplateRotator] = None,
        greeting_rotator: Optional[NonRepeatingTemplateRotator] = None,
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
        login_result_recorded = False

        try:
            self.post_gui_update("status_info", {
                "status": "Starting Browser",
                "detail": f"Initializing browser for {email}"
            })

            fp = generate_stealth_fingerprint() if enable_fp_rotation else None
            # AutoHotkey relies on the active desktop. Keep the entire login and
            # dashboard verification inside one global slot so a second RDP
            # window cannot steal focus before the first login has completed.
            with BrowserFactory.desktop_login_slot():
                driver, profile_dir, used_fp = BrowserFactory.create_browser(
                    fingerprint=fp,
                    email=email,
                    password=password,
                )

                if not login(driver, email, password):
                    self._record_login_result(email, success=False)
                    login_result_recorded = True
                    account_note = "login_failed"
                    logger.log_event(email, total_ok, fail_count, note=account_note)
                    logger.log_summary(email, total_ok, fail_count, note=account_note)
                    return

                self._record_login_result(email, success=True)
                login_result_recorded = True

                # Only the native login needs the foreground. Move this exact
                # instance away before the next account acquires the RDP slot.
                BrowserFactory.move_browser_to_background(driver, email)

            self.post_gui_update("status_info", {
                "status": "Logged In",
                "detail": f"Active: {email} | Target limit: {total_ok}/{max_per_account}"
            })

            with self._state_lock:
                contacted_users = persistence.load_contacted_users() | set(sent_users)
                uncontacted = [
                    u for u in target_queue
                    if normalize_recipient(u) not in contacted_users
                ]

            if len(uncontacted) < scrape_threshold and not self._stop_event.is_set():
                # Only one account scrapes at a time.  Waiting workers re-check
                # the shared queue after the current scrape completes.
                with self._scrape_lock:
                    with self._state_lock:
                        contacted_users = persistence.load_contacted_users() | set(sent_users)
                        uncontacted = [
                            u for u in target_queue
                            if normalize_recipient(u) not in contacted_users
                        ]

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
                            already_sent=contacted_users,
                            max_users=notes_max,
                            timeout_sec=scrape_timeout,
                            progress_callback=lambda count, total: self.post_gui_update("scrape_progress", {"count": count, "max": total}),
                            stop_check=lambda: self._stop_event.is_set()
                        )

                        with self._state_lock:
                            contacted_users = persistence.load_contacted_users() | set(sent_users)
                            for u in fresh_users:
                                u = normalize_recipient(u)
                                if u and u not in target_queue and u not in contacted_users:
                                    target_queue.append(u)
                            persistence.save_target_queue(target_queue)
                            uncontacted = [
                                u for u in target_queue
                                if normalize_recipient(u) not in contacted_users
                            ]

            if not uncontacted:
                account_note = "no_uncontacted_users_left"
                logger.log_event(email, total_ok, fail_count, note=account_note)
                logger.log_summary(email, total_ok, fail_count, note=account_note)
                logout(driver)
                return

            logger.info(f"[{email}] Ready! Processing up to {session_cap} users in this session...")

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

                if self._stop_event.is_set():
                    account_note = "stopped_by_user"
                    break

                if session_ok >= session_cap:
                    account_note = f"session_cap_{session_cap}_reached"
                    logger.log_event(email, total_ok, fail_count, note=account_note)
                    break

                if total_ok >= max_per_account:
                    account_note = f"reached_max_{max_per_account}"
                    logger.log_event(email, total_ok, fail_count, note=account_note)
                    break

                username = normalize_recipient(username)
                if not username or username in contacted_users:
                    continue

                users_seen += 1
                do_follow = (follow_every > 0 and users_seen % follow_every == 0)

                # Commit an exclusive claim before any possible message delivery.
                # Never retry an uncertain attempt, including across accounts/runs.
                with self._state_lock:
                    if not persistence.claim_recipient(username):
                        contacted_users.add(username)
                        logger.info(f"[ENGINE] Skipping previously attempted recipient: {username}")
                        continue
                    contacted_users.add(username)
                    target_queue[:] = [
                        u for u in target_queue
                        if normalize_recipient(u) != username
                    ]
                    persistence.save_target_queue(target_queue)

                if message_rotator is None:
                    base_msg = messages[msg_i % len(messages)]
                    message_index = msg_i
                    msg_i += 1
                else:
                    base_msg, message_index = message_rotator.next_template()

                if greeting_rotator is None:
                    greeting = greetings[greet_i % len(greetings)]
                    greet_i += 1
                else:
                    greeting, _ = greeting_rotator.next_template()
                parts = compose_message_parts(username, base_msg, greeting, message_index)

                self.post_gui_update("status_info", {
                    "status": "Messaging",
                    "detail": f"Sending DM to: @{username} (session: {session_ok + 1}/{session_cap})"
                })

                result, ok_follow = send_message_to_user(
                    driver=driver,
                    username=username,
                    messages=parts,
                    do_follow=do_follow,
                    action_delay=action_delay,
                    line_delay=line_delay,
                    after_send_delay=after_send_delay,
                    typing_min_delay=typing_min_delay,
                    typing_max_delay=typing_max_delay,
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
                    with self._state_lock:
                        persistence.save_sent_user(username)
                        sent_users.add(username)
                        total_ok += 1
                        session_ok += 1
                        progress[email] = total_ok
                        persistence.save_progress(progress)
                        total_sent = len(sent_users)

                    self.post_gui_update("progress_update", {
                        "email": email,
                        "total_ok": total_ok,
                        "session_ok": session_ok,
                        "total_sent": total_sent,
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

            logger.log_summary(email, total_ok, fail_count, note=account_note)
            logout(driver)

        except ContactHistoryError:
            raise
        except Exception as e:
            if not login_result_recorded:
                self._record_login_result(email, success=False)
                login_result_recorded = True
            logger.error(f"[ENGINE] Session exception for {email}: {e}")
            logger.log_summary(email, total_ok, fail_count, note=f"session_exception: {e}")
            if driver:
                BrowserFactory.capture_screenshot(driver, prefix=f"crash_{email.split('@')[0]}")
        finally:
            BrowserFactory.close_browser(driver, profile_dir)
            time.sleep(2.0)
