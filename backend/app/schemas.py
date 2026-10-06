from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime

# --- 认证相关 ---
class LoginRequest(BaseModel):
    username: str
    password: str
    totp_code: Optional[str] = None

class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    is_totp_required: bool = False
    username: str

class SetupTOTPResponse(BaseModel):
    secret: str
    qr_code_data_url: str

class VerifyTOTPRequest(BaseModel):
    secret: str
    code: str

# --- 账户相关 ---
class AccountCreate(BaseModel):
    name: str = Field(..., description="别名，如'个人Gmail'")
    color: str = Field(default="#3b82f6", description="微徽标颜色Hex")
    email: str
    imap_server: str
    imap_port: int = 993
    use_ssl: bool = True
    username: str
    password: str = Field(..., description="应用专用密码")
    folder: str = "INBOX"
    sync_delete_remote: bool = False
    sync_read_remote: bool = False

class AccountTestRequest(BaseModel):
    account_id: Optional[int] = None
    imap_server: str
    imap_port: int = 993
    use_ssl: bool = True
    username: str
    password: Optional[str] = None
    folder: str = "INBOX"

class AccountUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None
    email: Optional[str] = None
    imap_server: Optional[str] = None
    imap_port: Optional[int] = None
    use_ssl: Optional[bool] = None
    username: Optional[str] = None
    password: Optional[str] = None
    folder: Optional[str] = None
    is_active: Optional[bool] = None
    sync_delete_remote: Optional[bool] = None
    sync_read_remote: Optional[bool] = None

class AccountResponse(BaseModel):
    id: int
    name: str
    color: str
    email: str
    imap_server: str
    imap_port: int
    use_ssl: bool
    username: str
    folder: str
    is_active: bool
    sync_status: str
    last_sync_at: Optional[str]
    last_uid: int
    last_error: Optional[str]
    sync_delete_remote: bool
    sync_read_remote: bool
    history_exhausted: bool = False
    unread_count: int = 0
    created_at: str

# --- 邮件相关 ---
class EmailSummary(BaseModel):
    id: int
    account_id: int
    account_name: str
    account_color: str
    message_id: Optional[str]
    uid: int
    subject: str
    from_name: str
    from_address: str
    date: Optional[str]
    snippet: str
    has_attachments: bool
    otp_code: Optional[str]
    is_read: bool
    is_starred: bool
    is_deleted: bool
    has_body: bool = True
    raw_size: int

class AttachmentInfo(BaseModel):
    filename: str
    content_type: str
    size: int
    content_id: Optional[str] = None

class EmailDetail(EmailSummary):
    to_addresses: List[str]
    attachments: List[AttachmentInfo]
    html_body: str
    text_body: str

class EmailBatchActionRequest(BaseModel):
    email_ids: List[int]
    action: str  # read, unread, star, unstar, trash, restore, delete_permanent
    sync_remote: Optional[bool] = None
