import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Optional, List

from backend.app.config import settings
from backend.app.database import get_db
from backend.app.imap.client import IMAPClient
from backend.app.imap.parser import parse_raw_email
from backend.app.storage.eml_storage import eml_storage
from backend.app.telegram.bot import telegram_notifier

logger = logging.getLogger("mailone.imap.worker")

class SyncManager:
    def __init__(self):
        self._tasks: Dict[int, asyncio.Task] = {}
        self._running = False
        self._batch_fetch_tasks: Dict[int, asyncio.Task] = {}

    async def start(self):
        """启动后台多账号定时轮询同步管理器"""
        self._running = True
        logger.info("IMAP SyncManager starting (Periodic Polling mode)...")
        await self.refresh_all_accounts()

    async def stop(self):
        """停止所有同步任务"""
        self._running = False
        for account_id, task in list(self._tasks.items()):
            task.cancel()
        self._tasks.clear()
        for account_id, task in list(self._batch_fetch_tasks.items()):
            task.cancel()
        self._batch_fetch_tasks.clear()
        logger.info("IMAP SyncManager stopped.")

    async def refresh_all_accounts(self):
        """刷新账户任务列表"""
        async with get_db() as db:
            cursor = await db.execute("SELECT id, is_active FROM accounts")
            accounts = await cursor.fetchall()

        active_ids = {row["id"] for row in accounts if row["is_active"]}

        for account_id in list(self._tasks.keys()):
            if account_id not in active_ids:
                self._tasks[account_id].cancel()
                del self._tasks[account_id]

        for account_id in active_ids:
            if account_id not in self._tasks or self._tasks[account_id].done():
                task = asyncio.create_task(self._account_loop(account_id))
                self._tasks[account_id] = task

    async def trigger_sync(self, account_id: int):
        """手动触发单个账户即时同步"""
        await self._sync_account_once(account_id)

    async def _account_loop(self, account_id: int):
        """简洁可靠的定时轮询循环（不维持脆弱的常驻长连接，安全稳定零开销）"""
        while self._running:
            try:
                await self._sync_account_once(account_id)
                # 轮询休眠（默认 60 秒）
                await asyncio.sleep(settings.POLL_INTERVAL_SECONDS)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in polling loop for account %s: %s", account_id, e)
                await asyncio.sleep(30)

    async def _sync_account_once(self, account_id: int):
        """单次同步：初次仅拉 Header，增量拉完整 Body + 推 TG"""
        account = None
        async with get_db() as db:
            cursor = await db.execute("SELECT * FROM accounts WHERE id = ?", (account_id,))
            account = await cursor.fetchone()

        if not account or not account["is_active"]:
            return

        async with get_db() as db:
            await db.execute("UPDATE accounts SET sync_status = 'syncing' WHERE id = ?", (account_id,))
            await db.commit()

        client_wrapper = IMAPClient(
            host=account["imap_server"],
            port=account["imap_port"],
            use_ssl=bool(account["use_ssl"]),
            username=account["username"],
            password_encrypted=account["password_encrypted"],
            folder=account["folder"]
        )

        try:
            client = await client_wrapper.connect()
            last_uid = account["last_uid"] or 0
            is_initial = (last_uid == 0)

            # 查询新邮件 UID 列表
            if is_initial:
                # 初次同步：获取全部历史邮件 UID
                resp = await client.uid_search("ALL")
            else:
                resp = await client.uid_search(f"UID {last_uid + 1}:*")

            raw_uids = []
            if resp.result == "OK" and resp.lines:
                for line in resp.lines:
                    if isinstance(line, bytes):
                        line = line.decode("ascii", errors="ignore")
                    for p in line.strip().split():
                        if p.isdigit():
                            u_int = int(p)
                            if is_initial or u_int > last_uid:
                                raw_uids.append(u_int)

            sorted_uids = sorted(list(set(raw_uids)))
            max_uid = max([last_uid] + sorted_uids) if sorted_uids else last_uid

            if is_initial:
                # 方案 A 阶段 1：初次接入历史邮件，从最新到最旧优先索引 Header，极速呈现最新邮件
                logger.info("Initial sync for account %s: indexing %s history headers (newest first, Body on-demand)...", account_id, len(sorted_uids))
                for uid in sorted(sorted_uids, reverse=True):
                    if not self._running:
                        break
                    
                    header_bytes = await client_wrapper.fetch_header_fast(client, uid)
                    if not header_bytes:
                        continue

                    parsed = parse_raw_email(header_bytes)
                    async with get_db() as db:
                        await db.execute(
                            """
                            INSERT OR IGNORE INTO emails (
                                account_id, message_id, uid, subject, from_name, from_address,
                                to_addresses, date, snippet, has_attachments, attachments_json,
                                otp_code, has_body, eml_path, raw_size
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, '', 0)
                            """,
                            (
                                account_id,
                                parsed.message_id,
                                uid,
                                parsed.subject,
                                parsed.from_name,
                                parsed.from_address,
                                json.dumps(parsed.to_addresses),
                                parsed.date.isoformat() if parsed.date else datetime.now().isoformat(),
                                "",
                                0,
                                "[]",
                                None
                            )
                        )
                        await db.commit()

                    if uid > max_uid:
                        max_uid = uid

            else:
                # 日常增量新邮件：全量拉取完整 Body、落盘 .eml、并发送 Telegram 推送
                for uid in sorted_uids:
                    if not self._running:
                        break

                    raw_bytes = await client_wrapper.fetch_raw_email(client, uid)
                    if not raw_bytes:
                        continue

                    parsed = parse_raw_email(raw_bytes)
                    rel_path, raw_size = eml_storage.save_eml(
                        account_id=account_id,
                        uid=uid,
                        raw_bytes=raw_bytes,
                        date_hint=parsed.date
                    )

                    inserted_id = None
                    async with get_db() as db:
                        cursor = await db.execute(
                            """
                            INSERT INTO emails (
                                account_id, message_id, uid, subject, from_name, from_address,
                                to_addresses, date, snippet, has_attachments, attachments_json,
                                otp_code, has_body, eml_path, raw_size
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                            """,
                            (
                                account_id,
                                parsed.message_id,
                                uid,
                                parsed.subject,
                                parsed.from_name,
                                parsed.from_address,
                                json.dumps(parsed.to_addresses),
                                parsed.date.isoformat() if parsed.date else datetime.now().isoformat(),
                                parsed.snippet,
                                1 if parsed.has_attachments else 0,
                                json.dumps(parsed.attachments),
                                parsed.otp_code,
                                rel_path,
                                raw_size
                            )
                        )
                        inserted_id = cursor.lastrowid
                        await db.commit()

                    if uid > max_uid:
                        max_uid = uid

                    # 仅对增量新邮件推送到 Telegram
                    if inserted_id:
                        asyncio.create_task(
                            telegram_notifier.send_new_email_notification(
                                mail_id=inserted_id,
                                account_name=account["name"],
                                subject=parsed.subject,
                                from_name=parsed.from_name,
                                from_address=parsed.from_address,
                                snippet=parsed.snippet,
                                otp_code=parsed.otp_code
                            )
                        )

            await client_wrapper.close()

            now_iso = datetime.now(timezone.utc).isoformat()
            async with get_db() as db:
                await db.execute(
                    """
                    UPDATE accounts 
                    SET sync_status = 'idle', last_sync_at = ?, last_uid = ?, last_error = NULL
                    WHERE id = ?
                    """,
                    (now_iso, max_uid, account_id)
                )
                await db.commit()

        except Exception as e:
            logger.error("Sync failed for account %s: %s", account_id, e)
            await client_wrapper.close()
            async with get_db() as db:
                await db.execute(
                    "UPDATE accounts SET sync_status = 'error', last_error = ? WHERE id = ?",
                    (str(e), account_id)
                )
                await db.commit()

    async def fetch_single_email_body_on_demand(self, email_id: int) -> bool:
        """用户在 Web 端点开一封只有标题的历史邮件时，即时连 IMAP 拉取正文落盘"""
        mail_row = None
        async with get_db() as db:
            cursor = await db.execute(
                """
                SELECT e.*, a.imap_server, a.imap_port, a.use_ssl, a.username, a.password_encrypted, a.folder
                FROM emails e
                JOIN accounts a ON e.account_id = a.id
                WHERE e.id = ?
                """,
                (email_id,)
            )
            mail_row = await cursor.fetchone()

        if not mail_row or mail_row["has_body"]:
            return True

        client_wrapper = IMAPClient(
            host=mail_row["imap_server"],
            port=mail_row["imap_port"],
            use_ssl=bool(mail_row["use_ssl"]),
            username=mail_row["username"],
            password_encrypted=mail_row["password_encrypted"],
            folder=mail_row["folder"]
        )

        try:
            client = await client_wrapper.connect()
            raw_bytes = await client_wrapper.fetch_raw_email(client, mail_row["uid"])
            await client_wrapper.close()

            if not raw_bytes:
                return False

            parsed = parse_raw_email(raw_bytes)
            rel_path, raw_size = eml_storage.save_eml(
                account_id=mail_row["account_id"],
                uid=mail_row["uid"],
                raw_bytes=raw_bytes,
                date_hint=parsed.date
            )

            async with get_db() as db:
                await db.execute(
                    """
                    UPDATE emails
                    SET has_body = 1, eml_path = ?, raw_size = ?, snippet = ?,
                        has_attachments = ?, attachments_json = ?, otp_code = ?
                    WHERE id = ?
                    """,
                    (
                        rel_path,
                        raw_size,
                        parsed.snippet,
                        1 if parsed.has_attachments else 0,
                        json.dumps(parsed.attachments),
                        parsed.otp_code,
                        email_id
                    )
                )
                await db.commit()
            return True
        except Exception as e:
            logger.error("Failed to fetch on-demand body for email %s: %s", email_id, e)
            await client_wrapper.close()
            return False

    async def start_batch_body_fetch(self, account_id: int):
        """后台异步任务：手动触发将该账号所有历史邮件正文下载到本地归档"""
        if account_id in self._batch_fetch_tasks and not self._batch_fetch_tasks[account_id].done():
            return
        self._batch_fetch_tasks[account_id] = asyncio.create_task(self._batch_fetch_worker(account_id))

    async def _batch_fetch_worker(self, account_id: int):
        logger.info("Batch fetching all history bodies for account %s...", account_id)
        while self._running:
            async with get_db() as db:
                cursor = await db.execute(
                    "SELECT id FROM emails WHERE account_id = ? AND has_body = 0 LIMIT 10",
                    (account_id,)
                )
                rows = await cursor.fetchall()
            if not rows:
                break
            for r in rows:
                if not self._running:
                    break
                await self.fetch_single_email_body_on_demand(r["id"])
                await asyncio.sleep(0.3)
        logger.info("Batch body fetch completed for account %s.", account_id)

sync_manager = SyncManager()
