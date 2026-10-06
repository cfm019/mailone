import asyncio
import json
import logging
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import Response, StreamingResponse
import io

from backend.app.database import get_db
from backend.app.schemas import EmailSummary, EmailDetail, EmailBatchActionRequest, AttachmentInfo
from backend.app.auth import get_current_user
from backend.app.storage.eml_storage import eml_storage
from backend.app.imap.parser import parse_raw_email
from backend.app.imap.client import IMAPClient
from backend.app.imap.worker import sync_manager

logger = logging.getLogger("mailone.api.mail")
router = APIRouter(prefix="/api/mails", tags=["mails"])

@router.get("")
async def list_emails(
    account_id: Optional[int] = Query(None, description="指定账户ID"),
    view: str = Query("inbox", description="视图: inbox, otp, starred, trash, unread"),
    from_address: Optional[str] = Query(None, description="按发件人地址聚合筛选"),
    q: Optional[str] = Query(None, description="全文搜索关键词"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=300),
    user: dict = Depends(get_current_user)
):
    """多维复合邮件列表检索（支持全文检索、发件人聚合、OTP专区）"""
    offset = (page - 1) * page_size
    conditions = []
    params = []

    # 视图分支处理
    if view == "trash":
        conditions.append("e.is_deleted = 1")
    else:
        conditions.append("e.is_deleted = 0")
        if view == "otp":
            conditions.append("e.otp_code IS NOT NULL AND e.otp_code != ''")
        elif view == "starred":
            conditions.append("e.is_starred = 1")
        elif view == "unread":
            conditions.append("e.is_read = 0")

    if account_id:
        conditions.append("e.account_id = ?")
        params.append(account_id)

    if from_address:
        conditions.append("e.from_address = ?")
        params.append(from_address)

    # 全文搜索 (FTS5)
    join_fts = ""
    if q and q.strip():
        # FTS5 MATCH
        search_terms = " ".join([f'"{term}"*' for term in q.strip().split()])
        join_fts = "JOIN emails_fts fts ON e.id = fts.rowid"
        conditions.append("emails_fts MATCH ?")
        params.append(search_terms)

    where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

    async with get_db() as db:
        # 统计总数
        count_sql = f"SELECT count(*) as total FROM emails e {join_fts} {where_clause}"
        cursor = await db.execute(count_sql, tuple(params))
        total_row = await cursor.fetchone()
        total = total_row["total"] if total_row else 0

        # 查询列表
        select_sql = f"""
            SELECT e.id, e.account_id, a.name as account_name, a.color as account_color,
                   e.message_id, e.uid, e.subject, e.from_name, e.from_address,
                   e.date, e.snippet, e.has_attachments, e.otp_code,
                   e.is_read, e.is_starred, e.is_deleted, e.has_body, e.raw_size
            FROM emails e
            JOIN accounts a ON e.account_id = a.id
            {join_fts}
            {where_clause}
            ORDER BY e.date DESC, e.id DESC
            LIMIT ? OFFSET ?
        """
        query_params = list(params) + [page_size, offset]
        cursor = await db.execute(select_sql, tuple(query_params))
        rows = await cursor.fetchall()

        # 统计未读总数与 OTP 邮件总数
        stat_cursor = await db.execute(
            """
            SELECT 
                SUM(CASE WHEN is_read = 0 AND is_deleted = 0 THEN 1 ELSE 0 END) as unread_count,
                SUM(CASE WHEN otp_code IS NOT NULL AND otp_code != '' AND is_deleted = 0 THEN 1 ELSE 0 END) as otp_count
            FROM emails
            """
        )
        stat_row = await stat_cursor.fetchone()
        unread_total = stat_row["unread_count"] or 0
        otp_total = stat_row["otp_count"] or 0

    items = [
        EmailSummary(
            id=r["id"],
            account_id=r["account_id"],
            account_name=r["account_name"],
            account_color=r["account_color"],
            message_id=r["message_id"],
            uid=r["uid"],
            subject=r["subject"] or "(无主题)",
            from_name=r["from_name"] or "",
            from_address=r["from_address"],
            date=r["date"],
            snippet=r["snippet"] or "",
            has_attachments=bool(r["has_attachments"]),
            otp_code=r["otp_code"],
            is_read=bool(r["is_read"]),
            is_starred=bool(r["is_starred"]),
            is_deleted=bool(r["is_deleted"]),
            has_body=bool(r["has_body"]),
            raw_size=r["raw_size"]
        )
        for r in rows
    ]

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "unread_total": unread_total,
        "otp_total": otp_total
    }

@router.get("/{email_id}", response_model=EmailDetail)
async def get_email_detail(email_id: int, user: dict = Depends(get_current_user)):
    """获取单封邮件完整详情；若尚未拉取正文，即时从原邮箱惰性下载并落盘；自动同步原邮箱为已读"""
    async with get_db() as db:
        cursor = await db.execute(
            """
            SELECT e.*, a.name as account_name, a.color as account_color,
                   a.imap_server, a.imap_port, a.use_ssl, a.username, a.password_encrypted, a.folder
            FROM emails e
            JOIN accounts a ON e.account_id = a.id
            WHERE e.id = ?
            """,
            (email_id,)
        )
        row = await cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="邮件不存在")

    # 惰性拉取：若尚未下载正文或本地 eml 丢失，即时连接原邮箱拉取
    if not row["has_body"] or not eml_storage.get_eml_bytes(row["eml_path"]):
        success = await sync_manager.fetch_single_email_body_on_demand(email_id)
        if success:
            async with get_db() as db:
                cursor = await db.execute(
                    """
                    SELECT e.*, a.name as account_name, a.color as account_color,
                           a.imap_server, a.imap_port, a.use_ssl, a.username, a.password_encrypted, a.folder
                    FROM emails e
                    JOIN accounts a ON e.account_id = a.id
                    WHERE e.id = ?
                    """,
                    (email_id,)
                )
                row = await cursor.fetchone()

    raw_bytes = eml_storage.get_eml_bytes(row["eml_path"])
    html_body = ""
    text_body = ""
    to_addresses = []
    attachments = []

    if raw_bytes:
        parsed = parse_raw_email(raw_bytes)
        html_body = parsed.html_body
        text_body = parsed.text_body
        to_addresses = parsed.to_addresses
        attachments = [
            AttachmentInfo(
                filename=att["filename"],
                content_type=att["content_type"],
                size=att["size"],
                content_id=att.get("content_id")
            )
            for att in parsed.attachments
        ]
    else:
        html_body = f"<p style='color:#64748b;'>未能从远程邮箱获取到该邮件正文内容。</p>"

    # 1. 本地自动标记已读
    if not row["is_read"]:
        async with get_db() as db:
            await db.execute("UPDATE emails SET is_read = 1 WHERE id = ?", (email_id,))
            await db.commit()

    # 2. 自动状态回写：阅读后立即异步向远程原邮箱回写已读标（消除原邮箱未读红点）
    asyncio.create_task(_async_remote_mark_seen(row))

    return EmailDetail(
        id=row["id"],
        account_id=row["account_id"],
        account_name=row["account_name"],
        account_color=row["account_color"],
        message_id=row["message_id"],
        uid=row["uid"],
        subject=row["subject"] or "(无主题)",
        from_name=row["from_name"] or "",
        from_address=row["from_address"],
        date=row["date"],
        snippet=row["snippet"] or "",
        has_attachments=bool(row["has_attachments"]),
        otp_code=row["otp_code"],
        is_read=True,
        is_starred=bool(row["is_starred"]),
        is_deleted=bool(row["is_deleted"]),
        raw_size=row["raw_size"],
        to_addresses=to_addresses,
        attachments=attachments,
        html_body=html_body,
        text_body=text_body
    )

@router.post("/batch")
async def batch_action(req: EmailBatchActionRequest, user: dict = Depends(get_current_user)):
    """
    批量操作邮件（已读、未读、标星、移入废纸篓、彻底删除）
    支持智能联动远程原邮箱同步删除
    """
    if not req.email_ids:
        return {"affected": 0}

    async with get_db() as db:
        # 查询这批邮件的账号信息与 UID，用于后续可能的远程同步
        placeholders = ",".join("?" * len(req.email_ids))
        cursor = await db.execute(
            f"""
            SELECT e.id, e.account_id, e.uid, e.eml_path,
                   a.sync_delete_remote, a.imap_server, a.imap_port,
                   a.use_ssl, a.username, a.password_encrypted, a.folder
            FROM emails e
            JOIN accounts a ON e.account_id = a.id
            WHERE e.id IN ({placeholders})
            """,
            tuple(req.email_ids)
        )
        mail_rows = await cursor.fetchall()

        if req.action == "read":
            await db.execute(f"UPDATE emails SET is_read = 1 WHERE id IN ({placeholders})", tuple(req.email_ids))
        elif req.action == "unread":
            await db.execute(f"UPDATE emails SET is_read = 0 WHERE id IN ({placeholders})", tuple(req.email_ids))
        elif req.action == "star":
            await db.execute(f"UPDATE emails SET is_starred = 1 WHERE id IN ({placeholders})", tuple(req.email_ids))
        elif req.action == "unstar":
            await db.execute(f"UPDATE emails SET is_starred = 0 WHERE id IN ({placeholders})", tuple(req.email_ids))
        elif req.action == "trash":
            # 移入本地废纸篓
            await db.execute(f"UPDATE emails SET is_deleted = 1 WHERE id IN ({placeholders})", tuple(req.email_ids))
            
            # 检查是否需要联动远程删除
            for m in mail_rows:
                should_sync = req.sync_remote if req.sync_remote is not None else bool(m["sync_delete_remote"])
                if should_sync:
                    asyncio.create_task(_async_remote_delete(m))

        elif req.action == "restore":
            # 从废纸篓恢复
            await db.execute(f"UPDATE emails SET is_deleted = 0 WHERE id IN ({placeholders})", tuple(req.email_ids))
        elif req.action == "delete_permanent":
            # 永久彻底删除本地数据库与 EML 文件
            for m in mail_rows:
                eml_storage.delete_eml(m["eml_path"])
                should_sync = req.sync_remote if req.sync_remote is not None else bool(m["sync_delete_remote"])
                if should_sync:
                    asyncio.create_task(_async_remote_delete(m))
            await db.execute(f"DELETE FROM emails WHERE id IN ({placeholders})", tuple(req.email_ids))

        await db.commit()

    return {"message": "操作完成", "count": len(req.email_ids)}

@router.post("/mark-all-read")
async def mark_all_emails_read(
    account_id: Optional[int] = None,
    view: str = "inbox",
    user: dict = Depends(get_current_user)
):
    """
    一键将当前邮箱或当前分类下的所有未读邮件全部标记为已读
    """
    async with get_db() as db:
        query = "UPDATE emails SET is_read = 1 WHERE is_read = 0 AND is_deleted = 0"
        params = []
        if account_id:
            query += " AND account_id = ?"
            params.append(account_id)
        if view == "starred":
            query += " AND is_starred = 1"
        cursor = await db.execute(query, tuple(params))
        affected = cursor.rowcount
        await db.commit()
    return {"affected": affected, "message": f"已将全部 {affected} 封未读邮件标记为已读"}

@router.get("/{email_id}/eml")
async def download_eml(email_id: int, user: dict = Depends(get_current_user)):
    """导出并下载原汁原味的 .eml 邮件文件"""
    async with get_db() as db:
        cursor = await db.execute("SELECT eml_path, subject FROM emails WHERE id = ?", (email_id,))
        row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="邮件不存在")

    raw_bytes = eml_storage.get_eml_bytes(row["eml_path"])
    if not raw_bytes:
        raise HTTPException(status_code=404, detail="本地 EML 文件丢失")

    filename = f"email_{email_id}.eml"
    return Response(
        content=raw_bytes,
        media_type="message/rfc822",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )

@router.get("/{email_id}/attachment/{att_idx}")
async def download_attachment(email_id: int, att_idx: int, user: dict = Depends(get_current_user)):
    """从原始 EML 中惰性流式提取并下载指定序号的附件"""
    async with get_db() as db:
        cursor = await db.execute("SELECT eml_path FROM emails WHERE id = ?", (email_id,))
        row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="邮件不存在")

    raw_bytes = eml_storage.get_eml_bytes(row["eml_path"])
    if not raw_bytes:
        raise HTTPException(status_code=404, detail="邮件文件不存在")

    import email
    from email import policy
    msg = email.message_from_bytes(raw_bytes, policy=policy.default)
    
    current_idx = 0
    for part in msg.walk():
        filename = part.get_filename()
        disposition = part.get_content_disposition()
        if filename or disposition == "attachment":
            if current_idx == att_idx:
                payload = part.get_payload(decode=True) or b""
                ctype = part.get_content_type() or "application/octet-stream"
                fname = filename or f"attachment_{att_idx}"
                return Response(
                    content=payload,
                    media_type=ctype,
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'}
                )
            current_idx += 1

    raise HTTPException(status_code=404, detail="未找到该附件")

# --- 异步远程操作辅助函数 ---

async def _async_remote_mark_seen(account_data: dict):
    try:
        client = IMAPClient(
            host=account_data["imap_server"],
            port=account_data["imap_port"],
            use_ssl=bool(account_data["use_ssl"]),
            username=account_data["username"],
            password_encrypted=account_data["password_encrypted"],
            folder=account_data["folder"]
        )
        await client.mark_seen(account_data["uid"])
    except Exception as e:
        logger.error("Async remote mark seen error: %s", e)

async def _async_remote_delete(account_data: dict):
    try:
        client = IMAPClient(
            host=account_data["imap_server"],
            port=account_data["imap_port"],
            use_ssl=bool(account_data["use_ssl"]),
            username=account_data["username"],
            password_encrypted=account_data["password_encrypted"],
            folder=account_data["folder"]
        )
        await client.delete_remote_email(account_data["uid"])
    except Exception as e:
        logger.error("Async remote delete error: %s", e)
