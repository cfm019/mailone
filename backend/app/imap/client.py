import asyncio
import logging
import re
from typing import Optional, List, Tuple, Dict
from aioimaplib import aioimaplib
from backend.app.auth import decrypt_secret

logger = logging.getLogger("mailone.imap.client")

class IMAPClient:
    def __init__(
        self,
        host: str,
        port: int,
        use_ssl: bool,
        username: str,
        password_encrypted: str,
        folder: str = "INBOX"
    ):
        self.host = host
        self.port = port
        self.use_ssl = use_ssl
        self.username = username
        self.password = decrypt_secret(password_encrypted)
        self.folder = folder
        self._client: Optional[aioimaplib.IMAP4_SSL] = None

    async def connect(self) -> aioimaplib.IMAP4_SSL:
        """建立连接并登录"""
        if not self.host or not self.host.strip():
            raise ConnectionError("IMAP 服务器地址不能为空，请填写正确的服务器主机名（如 imap.163.com, imap.qq.com 等）")

        if self.use_ssl:
            client = aioimaplib.IMAP4_SSL(host=self.host.strip(), port=self.port, timeout=30)
        else:
            client = aioimaplib.IMAP4(host=self.host.strip(), port=self.port, timeout=30)

        await client.wait_hello_from_server()
        resp = await client.login(self.username, self.password)
        if resp.result != "OK":
            raise ConnectionError(f"IMAP login failed: {resp.lines}")

        # 发送 RFC 2971 ID 身份认证（解决网易 163 / 126 等邮箱要求客户端标识的 Unsafe Login 拦截）
        try:
            from aioimaplib.aioimaplib import Command
            id_arg = f'("name" "MailOne" "version" "1.0.0" "vendor" "MailOne" "contact" "{self.username}")'
            cmd = Command('ID', client.protocol.new_tag(), id_arg, loop=client.protocol.loop)
            await client.protocol.execute(cmd)
        except Exception as e:
            logger.debug("IMAP ID command error: %s", e)

        # 选择文件夹
        select_resp = await client.select(self.folder)
        if select_resp.result != "OK":
            raise ConnectionError(f"IMAP select folder '{self.folder}' failed: {select_resp.lines}")

        self._client = client
        return client

    async def close(self):
        """安全关闭连接"""
        if self._client:
            try:
                await self._client.logout()
            except Exception:
                pass
            self._client = None

    async def test_connection(self) -> Tuple[bool, str]:
        """测试连接与认证是否成功"""
        try:
            client = await self.connect()
            await self.close()
            return True, "连接并登录成功"
        except Exception as e:
            return False, f"连接失败: {str(e)}"

    async def fetch_new_uids(self, client: aioimaplib.IMAP4_SSL, last_uid: int, limit_initial: int = 50) -> List[int]:
        """查询大于 last_uid 的所有新邮件 UID"""
        if last_uid > 0:
            resp = await client.uid_search(f"UID {last_uid + 1}:*")
        else:
            resp = await client.uid_search("ALL")

        if resp.result != "OK" or not resp.lines:
            return []

        uids = []
        # 解析返回的 UID 行
        for line in resp.lines:
            if isinstance(line, bytes):
                line = line.decode("ascii", errors="ignore")
            parts = line.strip().split()
            for p in parts:
                if p.isdigit():
                    uid_int = int(p)
                    if last_uid == 0 or uid_int > last_uid:
                        uids.append(uid_int)

        sorted_uids = sorted(list(set(uids)))
        # 初次接入：默认拉取最新的 50 封邮件，避免拉取数万封历史旧信
        if last_uid == 0 and len(sorted_uids) > limit_initial:
            sorted_uids = sorted_uids[-limit_initial:]

        return sorted_uids

    async def fetch_raw_email(self, client: aioimaplib.IMAP4_SSL, uid: int, timeout_seconds: float = 30.0) -> Optional[bytes]:
        """
        使用 BODY.PEEK[] 抓取邮件原始字节数据（只读拉取，绝不惊扰原邮箱未读状态）
        """
        try:
            resp = await asyncio.wait_for(
                client.uid("FETCH", str(uid), "(BODY.PEEK[])"),
                timeout=timeout_seconds
            )
        except asyncio.TimeoutError:
            logger.warning("Fetch raw email timed out for UID %s", uid)
            return None
        except Exception as e:
            logger.error("Fetch raw email error for UID %s: %s", uid, e)
            return None

        if resp.result != "OK":
            logger.error("Failed to fetch email UID %s: %s", uid, resp.lines)
            return None

        for item in resp.lines:
            if isinstance(item, (bytearray, bytes)):
                if b'FETCH (' in item or item == b')' or b'completed' in item.lower():
                    continue
                return bytes(item)
            elif isinstance(item, tuple) and len(item) == 2:
                return bytes(item[1])

        return None

    async def fetch_header_fast(self, client: aioimaplib.IMAP4_SSL, uid: int, timeout_seconds: float = 12.0) -> Optional[bytes]:
        """仅拉取单封邮件 Header 元数据（Subject, From, Date 等）"""
        try:
            resp = await asyncio.wait_for(
                client.uid("FETCH", str(uid), "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM TO DATE MESSAGE-ID)])"),
                timeout=timeout_seconds
            )
        except Exception as e:
            logger.warning("Fetch header timed out or failed for UID %s: %s", uid, e)
            return None

        if resp.result != "OK":
            return None
        for item in resp.lines:
            if isinstance(item, (bytearray, bytes)):
                if b'FETCH (' in item or item == b')' or b'completed' in item.lower():
                    continue
                return bytes(item)
            elif isinstance(item, tuple) and len(item) == 2:
                return bytes(item[1])
        return None

    async def fetch_headers_batch(
        self, client: aioimaplib.IMAP4_SSL, uids: List[int], timeout_seconds: float = 25.0
    ) -> Dict[int, bytes]:
        """
        单次指令批量抓取多个 UID 的 Header 元数据（Subject, From, Date 等）。
        将 N 次独立网络往返压缩为 1 次，防止触发 Gmail / 163 等服务端的频率风控与连接挂起。
        """
        if not uids:
            return {}

        uids_str = ",".join(str(u) for u in uids)
        command = "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM TO DATE MESSAGE-ID)])"

        try:
            resp = await asyncio.wait_for(
                client.uid("FETCH", uids_str, command),
                timeout=timeout_seconds
            )
        except asyncio.TimeoutError:
            logger.warning("Batch fetch headers timed out for %s UIDs (%s...)", len(uids), uids_str[:40])
            return {}
        except Exception as e:
            logger.error("Batch fetch headers network error: %s", e)
            return {}

        if resp.result != "OK":
            logger.error("Batch fetch headers failed: %s", resp.lines)
            return {}

        headers_map: Dict[int, bytes] = {}
        current_uid: Optional[int] = None

        for item in resp.lines:
            # 兼容标准元组格式 [(b'... UID ...', b'...'), ...]
            if isinstance(item, tuple) and len(item) == 2:
                status_line = item[0] if isinstance(item[0], (bytes, bytearray)) else b""
                m = re.search(rb'UID\s+(\d+)', status_line, re.IGNORECASE)
                if m:
                    headers_map[int(m.group(1))] = bytes(item[1])
                continue

            # 兼容 aioimaplib 的扁平字节/字面量结构：首行为带有 UID 的 FETCH 行，随行为字面量 bytearray
            if isinstance(item, (bytes, bytearray)):
                raw_item = bytes(item)
                m = re.search(rb'UID\s+(\d+)', raw_item, re.IGNORECASE)
                if m and (b'FETCH' in raw_item or b'{' in raw_item):
                    current_uid = int(m.group(1))
                    continue

                if current_uid is not None:
                    # 忽略协议闭合括号行或结束标记
                    if raw_item == b')' or b'completed' in raw_item.lower() or b'success' in raw_item.lower():
                        current_uid = None
                        continue
                    headers_map[current_uid] = raw_item
                    current_uid = None

        return headers_map

    async def mark_seen(self, uid: int, client: Optional[aioimaplib.IMAP4_SSL] = None) -> bool:
        """向远程服务器将邮件标记为已读"""
        should_close = False
        try:
            if not client:
                client = await self.connect()
                should_close = True
            resp = await client.uid("STORE", str(uid), "+FLAGS", r"(\Seen)")
            if should_close:
                await self.close()
            return resp.result == "OK"
        except Exception as e:
            logger.error("Failed to mark remote seen for UID %s: %s", uid, e)
            if should_close:
                await self.close()
            return False

    async def delete_remote_email(self, uid: int) -> bool:
        """向远程服务器标记删除并清理邮件"""
        try:
            client = await self.connect()
            # 1. 尝试添加 \Deleted 标记
            store_resp = await client.uid("store", str(uid), "+FLAGS", r"(\Deleted)")
            # 2. 调用 expunge 提交删除
            if store_resp.result == "OK":
                await client.expunge()
            await self.close()
            return store_resp.result == "OK"
        except Exception as e:
            logger.error("Failed to delete remote email UID %s: %s", uid, e)
            return False
