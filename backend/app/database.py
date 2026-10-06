import aiosqlite
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from backend.app.config import settings

logger = logging.getLogger("mailone.database")

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- 管理员账户表
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    totp_secret TEXT,
    is_totp_enabled INTEGER NOT NULL DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 外部 IMAP 邮箱账户表
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,                  -- 备注别名，如 "个人 Gmail", "工作 Outlook"
    color TEXT NOT NULL DEFAULT '#3b82f6', -- UI 显示徽标药丸颜色
    email TEXT NOT NULL,                 -- 邮箱地址
    imap_server TEXT NOT NULL,           -- IMAP 地址
    imap_port INTEGER NOT NULL DEFAULT 993,
    use_ssl INTEGER NOT NULL DEFAULT 1,
    username TEXT NOT NULL,              -- 登录用户名
    password_encrypted TEXT NOT NULL,    -- AES-GCM 加密后的应用密码
    folder TEXT NOT NULL DEFAULT 'INBOX',
    is_active INTEGER NOT NULL DEFAULT 1,-- 是否开启同步
    sync_status TEXT DEFAULT 'idle',     -- idle, syncing, error
    last_sync_at DATETIME,
    last_uid INTEGER DEFAULT 0,          -- 当前已同步的最大 UID（增量同步）
    last_error TEXT,
    sync_delete_remote INTEGER NOT NULL DEFAULT 0, -- 删除邮件时是否联动原邮箱
    sync_read_remote INTEGER NOT NULL DEFAULT 0,   -- 标已读时是否联动原邮箱
    history_exhausted INTEGER NOT NULL DEFAULT 0,  -- 远端历史邮件是否已全部同步到本地
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 邮件元数据表
CREATE TABLE IF NOT EXISTS emails (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    message_id TEXT,                     -- 原生 Message-ID
    uid INTEGER NOT NULL,                -- 远程 IMAP UID
    subject TEXT NOT NULL DEFAULT '',
    from_name TEXT DEFAULT '',
    from_address TEXT NOT NULL,
    to_addresses TEXT DEFAULT '[]',      -- JSON 格式收件人数组
    date DATETIME,
    snippet TEXT DEFAULT '',             -- 纯文本精简摘要（前 200 字）
    has_attachments INTEGER NOT NULL DEFAULT 0,
    attachments_json TEXT DEFAULT '[]',  -- 附件列表元数据
    otp_code TEXT,                       -- 识别出的验证码/OTP 代码
    is_read INTEGER NOT NULL DEFAULT 0,
    is_starred INTEGER NOT NULL DEFAULT 0,
    is_deleted INTEGER NOT NULL DEFAULT 0, -- 移入废纸篓
    has_body INTEGER NOT NULL DEFAULT 1, -- 是否已拉取完整正文(0=仅标题, 1=完整本体)
    eml_path TEXT NOT NULL DEFAULT '',   -- .eml 相对路径
    raw_size INTEGER NOT NULL DEFAULT 0, -- 文件字节大小
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(account_id, uid)
);

CREATE INDEX IF NOT EXISTS idx_emails_account_id ON emails(account_id);
CREATE INDEX IF NOT EXISTS idx_emails_date ON emails(date DESC);
CREATE INDEX IF NOT EXISTS idx_emails_is_deleted ON emails(is_deleted);
CREATE INDEX IF NOT EXISTS idx_emails_from_address ON emails(from_address);
CREATE INDEX IF NOT EXISTS idx_emails_otp_code ON emails(otp_code);

-- FTS5 全文搜索虚拟表
CREATE VIRTUAL TABLE IF NOT EXISTS emails_fts USING fts5(
    subject,
    from_name,
    from_address,
    snippet,
    content='emails',
    content_rowid='id',
    tokenize='unicode61'
);

-- 自动同步 FTS 触发器
CREATE TRIGGER IF NOT EXISTS emails_ai AFTER INSERT ON emails BEGIN
    INSERT INTO emails_fts(rowid, subject, from_name, from_address, snippet)
    VALUES (new.id, new.subject, new.from_name, new.from_address, new.snippet);
END;

CREATE TRIGGER IF NOT EXISTS emails_ad AFTER DELETE ON emails BEGIN
    INSERT INTO emails_fts(emails_fts, rowid, subject, from_name, from_address, snippet)
    VALUES ('delete', old.id, old.subject, old.from_name, old.from_address, old.snippet);
END;

CREATE TRIGGER IF NOT EXISTS emails_au AFTER UPDATE ON emails BEGIN
    INSERT INTO emails_fts(emails_fts, rowid, subject, from_name, from_address, snippet)
    VALUES ('delete', old.id, old.subject, old.from_name, old.from_address, old.snippet);
    INSERT INTO emails_fts(rowid, subject, from_name, from_address, snippet)
    VALUES (new.id, new.subject, new.from_name, new.from_address, new.snippet);
END;

-- 标签表
CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    color TEXT NOT NULL DEFAULT '#6366f1'
);

CREATE TABLE IF NOT EXISTS email_tags (
    email_id INTEGER NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY(email_id, tag_id)
);
"""

async def init_db():
    """初始化数据库及表结构"""
    async with aiosqlite.connect(settings.DB_PATH) as db:
        await db.executescript(SCHEMA_SQL)
        try:
            await db.execute("ALTER TABLE emails ADD COLUMN has_body INTEGER NOT NULL DEFAULT 1")
        except Exception:
            pass  # 已存在该字段
        try:
            await db.execute("ALTER TABLE accounts ADD COLUMN history_exhausted INTEGER NOT NULL DEFAULT 0")
        except Exception:
            pass  # 已存在该字段
        try:
            await db.execute("""
                UPDATE accounts SET history_exhausted = 1 
                WHERE id IN (SELECT account_id FROM emails GROUP BY account_id HAVING MIN(uid) <= 1)
            """)
        except Exception:
            pass
        await db.commit()
    logger.info("Database initialized successfully at %s", settings.DB_PATH)

@asynccontextmanager
async def get_db() -> AsyncGenerator[aiosqlite.Connection, None]:
    """获取数据库异步连接上下文"""
    async with aiosqlite.connect(settings.DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA foreign_keys = ON;")
        yield db
