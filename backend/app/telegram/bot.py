import asyncio
import logging
import html
import httpx
from typing import Optional, List
from backend.app.config import settings
from backend.app.auth import create_magic_link_token
from backend.app.database import get_db

logger = logging.getLogger("mailone.telegram")

class TelegramNotifier:
    def __init__(self):
        self.bot_token = settings.TELEGRAM_BOT_TOKEN
        self.api_base = settings.TELEGRAM_API_BASE.rstrip("/")
        self._polling_task: Optional[asyncio.Task] = None
        self._running = False

    @property
    def is_configured(self) -> bool:
        return bool(self.bot_token and settings.telegram_chat_ids_list)

    async def reload_config(self, bot_token: str, allowed_chat_ids: str, api_base: str):
        """动态更新配置并重启长轮询服务"""
        settings.TELEGRAM_BOT_TOKEN = bot_token
        settings.TELEGRAM_ALLOWED_CHAT_IDS = allowed_chat_ids
        settings.TELEGRAM_API_BASE = api_base
        self.bot_token = bot_token
        self.api_base = api_base.rstrip("/")
        await self.stop_polling()
        if self.is_configured:
            await self.start_polling()

    async def start_polling(self):
        """启动 Telegram 指令长轮询监听协程"""
        if not self.is_configured:
            logger.info("Telegram Bot not configured, skipping command listener.")
            return
        self._running = True
        self._polling_task = asyncio.create_task(self._poll_loop())
        logger.info("Telegram Bot command listener started.")

    async def stop_polling(self):
        """停止 Telegram 指令监听"""
        self._running = False
        if self._polling_task:
            self._polling_task.cancel()
            self._polling_task = None
        logger.info("Telegram Bot command listener stopped.")

    async def _poll_loop(self):
        """Long Polling 接收用户发送的指令"""
        offset = 0
        async with httpx.AsyncClient(timeout=35.0) as client:
            while self._running:
                try:
                    url = f"{self.api_base}/bot{self.bot_token}/getUpdates"
                    params = {"offset": offset, "timeout": 25}
                    resp = await client.get(url, params=params)
                    if resp.status_code != 200:
                        await asyncio.sleep(5)
                        continue

                    data = resp.json()
                    updates = data.get("result", [])
                    for up in updates:
                        offset = up["update_id"] + 1
                        msg = up.get("message")
                        if not msg:
                            continue

                        chat_id = msg.get("chat", {}).get("id")
                        text = msg.get("text", "").strip()

                        # 严格权限校验：只响应白名单内的 Chat ID，其他人一律静默忽略
                        if chat_id not in settings.telegram_chat_ids_list:
                            logger.warning("Ignored unauthorized Telegram message from chat_id %s", chat_id)
                            continue

                        if text:
                            await self._handle_command(chat_id, text, client)

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.debug("Error in Telegram poll loop: %s", e)
                    await asyncio.sleep(5)

    async def _handle_command(self, chat_id: int, text: str, client: httpx.AsyncClient):
        """解析并处理用户向 Bot 发送的指令"""
        cmd = text.split()[0].lower()

        if cmd in ("/start", "/help"):
            reply = (
                "👋 <b>MailOne 邮件助手</b>\n\n"
                "可用指令：\n"
                "• <code>/recent</code> - 查看最近 5 封邮件及阅读链接\n"
                "• <code>/status</code> - 查看绑定的邮箱与邮件状态统计\n"
                "• <code>/sync</code> - 立即触发一次邮箱新信检查\n"
            )
            await self._send_raw_message(chat_id, reply, client)

        elif cmd in ("/recent", "/latest"):
            await self._handle_recent_command(chat_id, client)

        elif cmd == "/status":
            await self._handle_status_command(chat_id, client)

        elif cmd == "/sync":
            from backend.app.imap.worker import sync_manager
            await self._send_raw_message(chat_id, "🔄 正在通知后台检查所有邮箱...", client)
            await sync_manager.refresh_all_accounts()
            await self._send_raw_message(chat_id, "✅ 邮箱检查任务已触发！", client)

    async def _handle_recent_command(self, chat_id: int, client: httpx.AsyncClient):
        """处理 /recent 指令，返回最近邮件卡片"""
        async with get_db() as db:
            cursor = await db.execute(
                """
                SELECT e.id, e.subject, e.from_name, e.from_address, e.date, e.snippet,
                       a.name as account_name
                FROM emails e
                JOIN accounts a ON e.account_id = a.id
                WHERE e.is_deleted = 0
                ORDER BY e.date DESC, e.id DESC
                LIMIT 5
                """
            )
            rows = await cursor.fetchall()

        if not rows:
            await self._send_raw_message(chat_id, "📭 当前暂无邮件记录", client)
            return

        lines = ["📬 <b>最近邮件列表：</b>\n"]
        inline_keyboard = []

        for idx, r in enumerate(rows, start=1):
            s_name = r["from_name"] or r["from_address"]
            s_subj = r["subject"] or "(无主题)"
            date_str = str(r["date"])[:16]
            lines.append(f"{idx}. <b>[{html.escape(r['account_name'])}]</b> {html.escape(s_subj)}")
            lines.append(f"   👤 {html.escape(s_name)} | ⏱️ {date_str}\n")

            magic_token = create_magic_link_token(r["id"])
            magic_url = f"{settings.BASE_URL.rstrip('/')}/view.html?id={r['id']}&token={magic_token}"
            inline_keyboard.append([{"text": f"📖 阅览 #{idx} ({html.escape(s_name[:12])})", "url": magic_url}])

        reply_markup = {"inline_keyboard": inline_keyboard}
        await self._send_raw_message(chat_id, "\n".join(lines), client, reply_markup=reply_markup)

    async def _handle_status_command(self, chat_id: int, client: httpx.AsyncClient):
        """处理 /status 指令，返回系统统计"""
        async with get_db() as db:
            cursor = await db.execute("SELECT name, email, sync_status, last_sync_at FROM accounts")
            accs = await cursor.fetchall()

            cursor = await db.execute(
                """
                SELECT count(*) as total,
                       SUM(CASE WHEN is_read = 0 AND is_deleted = 0 THEN 1 ELSE 0 END) as unread,
                       SUM(CASE WHEN has_body = 1 THEN 1 ELSE 0 END) as with_body
                FROM emails
                """
            )
            stats = await cursor.fetchone()

        lines = ["📊 <b>MailOne 系统运行状态</b>\n"]
        lines.append(f"• 邮件总索引量: <b>{stats['total'] or 0}</b> 封")
        lines.append(f"• 未读邮件: <b>{stats['unread'] or 0}</b> 封")
        lines.append(f"• 本地已缓存正文: <b>{stats['with_body'] or 0}</b> 封\n")
        lines.append("<b>已绑定邮箱列表：</b>")
        for a in accs:
            status_emoji = "🟢" if a["sync_status"] == "idle" else ("⏳" if a["sync_status"] == "syncing" else "🔴")
            lines.append(f"{status_emoji} <b>{html.escape(a['name'])}</b> ({html.escape(a['email'])})")

        await self._send_raw_message(chat_id, "\n".join(lines), client)

    async def _send_raw_message(self, chat_id: int, text: str, client: httpx.AsyncClient, reply_markup: Optional[dict] = None):
        url = f"{self.api_base}/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        try:
            await client.post(url, json=payload)
        except Exception as e:
            logger.error("Failed to send telegram raw message: %s", e)

    async def send_new_email_notification(
        self,
        mail_id: int,
        account_name: str,
        subject: str,
        from_name: str,
        from_address: str,
        snippet: str,
        otp_code: Optional[str] = None
    ) -> bool:
        """向配置的 Telegram Chat 发送新到达邮件通知"""
        if not self.is_configured:
            return False

        sender_display = f"{from_name} &lt;{from_address}&gt;" if from_name else from_address
        escaped_sender = html.escape(sender_display)
        escaped_subject = html.escape(subject or "(无主题)")
        escaped_account = html.escape(account_name)
        escaped_snippet = html.escape(snippet)

        magic_token = create_magic_link_token(mail_id)
        magic_url = f"{settings.BASE_URL.rstrip('/')}/view.html?id={mail_id}&token={magic_token}"

        lines = []
        lines.append(f"📬 <b>[{escaped_account}] 新邮件到达</b>")
        lines.append(f"👤 <b>发件人:</b> {escaped_sender}")
        lines.append(f"📋 <b>主题:</b> {escaped_subject}")

        if otp_code:
            lines.append("")
            lines.append(f"🔑 <b>验证码 / Code:</b>")
            lines.append(f"<code>{html.escape(otp_code)}</code>  <i>(点击复制)</i>")

        if escaped_snippet:
            lines.append("")
            lines.append(f"📝 <b>摘要:</b>")
            lines.append(f"<i>{escaped_snippet}</i>")

        reply_markup = {
            "inline_keyboard": [
                [
                    {"text": "📖 免密查看完整邮件", "url": magic_url}
                ]
            ]
        }

        success = True
        async with httpx.AsyncClient(timeout=10.0) as client:
            for chat_id in settings.telegram_chat_ids_list:
                url = f"{self.api_base}/bot{self.bot_token}/sendMessage"
                payload = {
                    "chat_id": chat_id,
                    "text": "\n".join(lines),
                    "parse_mode": "HTML",
                    "reply_markup": reply_markup,
                    "disable_web_page_preview": True
                }
                try:
                    resp = await client.post(url, json=payload)
                    if resp.status_code != 200:
                        success = False
                except Exception as e:
                    success = False
        return success

    async def send_test_message(
        self,
        test_chat_id: Optional[int] = None,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
        api_base: Optional[str] = None
    ) -> tuple[bool, str]:
        """测试 Telegram Bot 连接配置"""
        token = bot_token.strip() if bot_token else self.bot_token
        if not token:
            return False, "Bot Token 未配置"

        base = (api_base.strip() if api_base else self.api_base).rstrip("/")

        target_ids = []
        if chat_id:
            for x in chat_id.split(","):
                x = x.strip()
                if x:
                    try:
                        target_ids.append(int(x))
                    except ValueError:
                        pass
        elif test_chat_id:
            target_ids = [test_chat_id]
        else:
            target_ids = settings.telegram_chat_ids_list

        if not target_ids:
            return False, "未设置允许的 Chat ID (必须为纯数字)"

        async with httpx.AsyncClient(timeout=10.0) as client:
            url = f"{base}/bot{token}/sendMessage"
            payload = {
                "chat_id": target_ids[0],
                "text": "🎉 <b>MailOne 测试消息</b>\n\nTelegram Bot 推送与交互通道配置正常！可尝试向机器人发送 <code>/recent</code> 或 <code>/status</code>。",
                "parse_mode": "HTML"
            }
            try:
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    return True, "发送成功"
                return False, f"API 响应错误 ({resp.status_code}): {resp.text}"
            except Exception as e:
                return False, f"网络错误: {str(e)}"

telegram_notifier = TelegramNotifier()
