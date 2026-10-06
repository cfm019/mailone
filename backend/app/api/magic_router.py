import json
from fastapi import APIRouter, HTTPException, Query
from backend.app.database import get_db
from backend.app.auth import verify_magic_link_token
from backend.app.storage.eml_storage import eml_storage
from backend.app.imap.parser import parse_raw_email

router = APIRouter(prefix="/api/magic", tags=["magic"])

@router.get("/view")
async def get_magic_email_view(
    id: int = Query(..., description="邮件ID"),
    token: str = Query(..., description="安全免密签名令牌")
):
    """
    通过短期签名的 Magic Link 免密安全查看单封邮件
    无需用户登录会话，仅对该邮件只读授权
    """
    if not verify_magic_link_token(id, token):
        raise HTTPException(
            status_code=403,
            detail="查看链接无效或已过期，请在 Telegram 中重新获取或登录系统查看"
        )

    async with get_db() as db:
        cursor = await db.execute(
            """
            SELECT e.*, a.name as account_name, a.color as account_color
            FROM emails e
            JOIN accounts a ON e.account_id = a.id
            WHERE e.id = ?
            """,
            (id,)
        )
        row = await cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="邮件不存在或已被删除")

    raw_bytes = eml_storage.get_eml_bytes(row["eml_path"])
    html_body = ""
    attachments = []

    if raw_bytes:
        parsed = parse_raw_email(raw_bytes)
        html_body = parsed.html_body
        attachments = parsed.attachments
    else:
        html_body = f"<p>{row['snippet']}</p>"

    return {
        "id": row["id"],
        "account_name": row["account_name"],
        "account_color": row["account_color"],
        "subject": row["subject"] or "(无主题)",
        "from_name": row["from_name"] or "",
        "from_address": row["from_address"],
        "date": row["date"],
        "otp_code": row["otp_code"],
        "has_attachments": bool(row["has_attachments"]),
        "attachments": attachments,
        "html_body": html_body
    }
