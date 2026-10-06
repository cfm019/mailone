import asyncio
from fastapi import APIRouter, Depends, HTTPException, status
from typing import List

from backend.app.database import get_db
from backend.app.schemas import AccountCreate, AccountUpdate, AccountResponse, AccountTestRequest
from backend.app.auth import encrypt_secret, get_current_user
from backend.app.imap.client import IMAPClient
from backend.app.imap.worker import sync_manager

router = APIRouter(prefix="/api/accounts", tags=["accounts"])

@router.get("", response_model=List[AccountResponse])
async def list_accounts(user: dict = Depends(get_current_user)):
    """获取所有已绑定的邮箱账户"""
    async with get_db() as db:
        cursor = await db.execute(
            """
            SELECT a.id, a.name, a.color, a.email, a.imap_server, a.imap_port, a.use_ssl,
                   a.username, a.folder, a.is_active, a.sync_status, a.last_sync_at,
                   a.last_uid, a.last_error, a.sync_delete_remote, a.sync_read_remote,
                   a.history_exhausted, a.created_at,
                   (SELECT COUNT(*) FROM emails e WHERE e.account_id = a.id AND e.is_read = 0 AND e.is_deleted = 0) as unread_count
            FROM accounts a ORDER BY a.id ASC
            """
        )
        rows = await cursor.fetchall()
    
    return [
        AccountResponse(
            id=r["id"],
            name=r["name"],
            color=r["color"],
            email=r["email"],
            imap_server=r["imap_server"],
            imap_port=r["imap_port"],
            use_ssl=bool(r["use_ssl"]),
            username=r["username"],
            folder=r["folder"],
            is_active=bool(r["is_active"]),
            sync_status=r["sync_status"] or "idle",
            last_sync_at=r["last_sync_at"],
            last_uid=r["last_uid"] or 0,
            last_error=r["last_error"],
            sync_delete_remote=bool(r["sync_delete_remote"]),
            sync_read_remote=bool(r["sync_read_remote"]),
            history_exhausted=bool(r["history_exhausted"]) if "history_exhausted" in r.keys() else False,
            unread_count=r["unread_count"] or 0,
            created_at=str(r["created_at"])
        )
        for r in rows
    ]

@router.post("/test")
async def test_account_connection(req: AccountTestRequest, user: dict = Depends(get_current_user)):
    """测试指定 IMAP 配置是否能成功连接与登录"""
    enc_pw = None
    if req.password and req.password.strip():
        enc_pw = encrypt_secret(req.password.strip())
    elif req.account_id:
        async with get_db() as db:
            cursor = await db.execute("SELECT password_encrypted FROM accounts WHERE id = ?", (req.account_id,))
            row = await cursor.fetchone()
            if row and row["password_encrypted"]:
                enc_pw = row["password_encrypted"]

    if not enc_pw:
        raise HTTPException(status_code=400, detail="请填写邮箱专用密码或授权码进行测试")

    client_wrapper = IMAPClient(
        host=req.imap_server,
        port=req.imap_port,
        use_ssl=req.use_ssl,
        username=req.username,
        password_encrypted=enc_pw,
        folder=req.folder
    )
    ok, msg = await client_wrapper.test_connection()
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg}

@router.post("", response_model=AccountResponse)
async def create_account(req: AccountCreate, user: dict = Depends(get_current_user)):
    """添加新的 IMAP 邮箱账户"""
    enc_pw = encrypt_secret(req.password)
    # 先验证连接
    client_wrapper = IMAPClient(
        host=req.imap_server,
        port=req.imap_port,
        use_ssl=req.use_ssl,
        username=req.username,
        password_encrypted=enc_pw,
        folder=req.folder
    )
    ok, msg = await client_wrapper.test_connection()
    if not ok:
        raise HTTPException(status_code=400, detail=f"邮箱连接验证失败: {msg}")

    inserted_id = None
    async with get_db() as db:
        cursor = await db.execute(
            """
            INSERT INTO accounts (
                name, color, email, imap_server, imap_port, use_ssl,
                username, password_encrypted, folder, sync_delete_remote, sync_read_remote
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                req.name, req.color, req.email, req.imap_server, req.imap_port,
                1 if req.use_ssl else 0, req.username, enc_pw, req.folder,
                1 if req.sync_delete_remote else 0, 1 if req.sync_read_remote else 0
            )
        )
        inserted_id = cursor.lastrowid
        await db.commit()

        cursor = await db.execute("SELECT * FROM accounts WHERE id = ?", (inserted_id,))
        row = await cursor.fetchone()

    # 触发后台监听任务刷新
    await sync_manager.refresh_all_accounts()

    return AccountResponse(
        id=row["id"],
        name=row["name"],
        color=row["color"],
        email=row["email"],
        imap_server=row["imap_server"],
        imap_port=row["imap_port"],
        use_ssl=bool(row["use_ssl"]),
        username=row["username"],
        folder=row["folder"],
        is_active=bool(row["is_active"]),
        sync_status=row["sync_status"] or "idle",
        last_sync_at=row["last_sync_at"],
        last_uid=row["last_uid"] or 0,
        last_error=row["last_error"],
        sync_delete_remote=bool(row["sync_delete_remote"]),
        sync_read_remote=bool(row["sync_read_remote"]),
        history_exhausted=bool(row["history_exhausted"]) if "history_exhausted" in row.keys() else False,
        unread_count=0,
        created_at=str(row["created_at"])
    )

@router.put("/{account_id}")
async def update_account(account_id: int, req: AccountUpdate, user: dict = Depends(get_current_user)):
    """更新邮箱账户设置"""
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM accounts WHERE id = ?", (account_id,))
        existing = await cursor.fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="账户不存在")

        updates = []
        params = []

        if req.name is not None:
            updates.append("name = ?")
            params.append(req.name)
        if req.color is not None:
            updates.append("color = ?")
            params.append(req.color)
        if req.email is not None:
            updates.append("email = ?")
            params.append(req.email)
        if req.imap_server is not None:
            updates.append("imap_server = ?")
            params.append(req.imap_server)
        if req.imap_port is not None:
            updates.append("imap_port = ?")
            params.append(req.imap_port)
        if req.use_ssl is not None:
            updates.append("use_ssl = ?")
            params.append(1 if req.use_ssl else 0)
        if req.username is not None:
            updates.append("username = ?")
            params.append(req.username)
        if req.password is not None and req.password.strip():
            updates.append("password_encrypted = ?")
            params.append(encrypt_secret(req.password))
        if req.folder is not None:
            updates.append("folder = ?")
            params.append(req.folder)
        if req.is_active is not None:
            updates.append("is_active = ?")
            params.append(1 if req.is_active else 0)
        if req.sync_delete_remote is not None:
            updates.append("sync_delete_remote = ?")
            params.append(1 if req.sync_delete_remote else 0)
        if req.sync_read_remote is not None:
            updates.append("sync_read_remote = ?")
            params.append(1 if req.sync_read_remote else 0)

        if updates:
            params.append(account_id)
            sql = f"UPDATE accounts SET {', '.join(updates)} WHERE id = ?"
            await db.execute(sql, tuple(params))
            await db.commit()

    await sync_manager.refresh_all_accounts()
    return {"message": "账户已更新"}

@router.delete("/{account_id}")
async def delete_account(account_id: int, user: dict = Depends(get_current_user)):
    """删除绑定的邮箱账户，并同步物理清理本地所有关联邮件数据与 EML 归档文件"""
    deleted_mails_count = 0
    acc_name = ""
    async with get_db() as db:
        cursor = await db.execute("SELECT id, name FROM accounts WHERE id = ?", (account_id,))
        acc = await cursor.fetchone()
        if not acc:
            raise HTTPException(status_code=404, detail="账户不存在")
        acc_name = acc["name"]

        # 统计要删除的关联邮件数
        cursor = await db.execute("SELECT COUNT(*) FROM emails WHERE account_id = ?", (account_id,))
        count_row = await cursor.fetchone()
        deleted_mails_count = count_row[0] if count_row else 0

        # 删除 emails 表中该账号关联的所有记录（触发器自动同步清理 FTS5 全文索引）
        await db.execute("DELETE FROM emails WHERE account_id = ?", (account_id,))
        # 删除 accounts 表中该账号记录
        await db.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
        await db.commit()

    # 物理递归删除本地磁盘上的该账号 EML 存储目录
    from backend.app.storage.eml_storage import eml_storage
    eml_storage.delete_account_storage(account_id)

    # 刷新后台同步监听任务
    await sync_manager.refresh_all_accounts()

    return {
        "message": f"账户 '{acc_name}' 已成功删除",
        "deleted_emails_count": deleted_mails_count
    }

@router.post("/sync-all")
async def trigger_sync_all_accounts(user: dict = Depends(get_current_user)):
    """立即手动触发所有活跃邮箱的即时同步检查"""
    async with get_db() as db:
        cursor = await db.execute("SELECT id FROM accounts WHERE is_active = 1")
        rows = await cursor.fetchall()
    for r in rows:
        asyncio.create_task(sync_manager.trigger_sync(r["id"]))
    return {"message": "已触发全部邮箱同步任务"}

@router.post("/fetch-more-history-all")
async def fetch_more_history_all_accounts(user: dict = Depends(get_current_user)):
    """为所有活跃邮箱各拉取一批（30封）更早的历史邮件"""
    res = await sync_manager.fetch_more_history_all(count=30)
    return res

@router.post("/{account_id}/sync")
async def trigger_account_sync(account_id: int, user: dict = Depends(get_current_user)):
    """立即手动触发一次增量同步检查"""
    asyncio.create_task(sync_manager.trigger_sync(account_id))
    return {"message": "已触发同步任务"}

@router.post("/{account_id}/fetch-all-bodies")
async def trigger_fetch_all_bodies(account_id: int, user: dict = Depends(get_current_user)):
    """手工发起将该账号所有历史邮件正文下载到本地的归档任务"""
    await sync_manager.start_batch_body_fetch(account_id)
    return {"message": "已在后台启动全部历史邮件正文下载任务"}

@router.post("/{account_id}/fetch-more-history")
async def fetch_more_account_history(account_id: int, user: dict = Depends(get_current_user)):
    """按需拉取更早的 50 封历史邮件 Header（单次批量 FETCH，防风控，秒级响应）"""
    res = await sync_manager.fetch_more_history(account_id, count=50)
    if not res.get("success", False):
        raise HTTPException(status_code=500, detail=res.get("error", "拉取历史邮件失败"))
    return res

