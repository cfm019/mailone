import base64
import email
from email import policy
from email.utils import parseaddr, parsedate_to_datetime
from datetime import datetime
import json
import re
from typing import Dict, Any, List, Tuple, Optional
from bs4 import BeautifulSoup
from backend.app.imap.otp import extract_otp_code

class EmailParsedResult:
    def __init__(
        self,
        message_id: str,
        subject: str,
        from_name: str,
        from_address: str,
        to_addresses: List[str],
        date: Optional[datetime],
        snippet: str,
        html_body: str,
        text_body: str,
        has_attachments: bool,
        attachments: List[Dict[str, Any]],
        otp_code: Optional[str]
    ):
        self.message_id = message_id
        self.subject = subject
        self.from_name = from_name
        self.from_address = from_address
        self.to_addresses = to_addresses
        self.date = date
        self.snippet = snippet
        self.html_body = html_body
        self.text_body = text_body
        self.has_attachments = has_attachments
        self.attachments = attachments
        self.otp_code = otp_code

def sanitize_html(raw_html: str, cid_map: Dict[str, str]) -> str:
    """
    安全净化 HTML，移除危险脚本、替换 cid: 内联图片为 Base64
    """
    if not raw_html:
        return ""

    soup = BeautifulSoup(raw_html, "html.parser")

    # 移除危险标签
    for tag in soup(["script", "iframe", "object", "embed", "applet", "form", "base"]):
        tag.decompose()

    # 移除所有内联事件处理属性（如 onclick, onload 等）
    for el in soup.find_all(True):
        attrs = dict(el.attrs)
        for attr in attrs:
            if attr.lower().startswith("on"):
                del el.attrs[attr]

    # 替换 cid: 图片为 Base64 data URL
    for img in soup.find_all("img"):
        src = img.get("src", "")
        if src.startswith("cid:"):
            cid = src[4:].strip("<>")
            if cid in cid_map:
                img["src"] = cid_map[cid]

        # 过滤宽度或高度为 1 的隐形追踪像素
        style = img.get("style", "")
        width = img.get("width", "")
        height = img.get("height", "")
        if width in ("0", "1") or height in ("0", "1") or "width:1px" in style or "height:1px" in style:
            img.decompose()

    return str(soup)

def parse_raw_email(raw_bytes: bytes) -> EmailParsedResult:
    """
    解析原始 RFC822 / MIME 邮件数据
    """
    msg = email.message_from_bytes(raw_bytes, policy=policy.default)

    message_id = msg.get("Message-ID", "")
    subject = msg.get("Subject", "(无主题)")
    
    from_header = msg.get("From", "")
    from_name, from_address = parseaddr(from_header)
    if not from_address:
        from_address = from_header

    to_headers = msg.get_all("To", [])
    to_addresses = []
    for h in to_headers:
        name, addr = parseaddr(str(h))
        if addr:
            to_addresses.append(addr)

    date_header = msg.get("Date")
    parsed_date = None
    if date_header:
        try:
            parsed_date = parsedate_to_datetime(date_header)
        except Exception:
            parsed_date = datetime.now()
    else:
        parsed_date = datetime.now()

    html_parts = []
    text_parts = []
    attachments = []
    cid_map = {}

    for part in msg.walk():
        content_maintype = part.get_content_maintype()
        content_disposition = part.get_content_disposition()
        filename = part.get_filename()

        # 检查是否为附件或内联媒体
        content_id = part.get("Content-ID")
        if content_id:
            content_id = content_id.strip("<>")

        if filename or content_disposition == "attachment":
            payload_data = part.get_payload(decode=True) or b""
            size = len(payload_data)
            ctype = part.get_content_type()
            
            # 记录附件元数据
            att_info = {
                "filename": filename or f"attachment_{len(attachments) + 1}",
                "content_type": ctype,
                "size": size,
                "content_id": content_id
            }
            attachments.append(att_info)

            # 如果带有 Content-ID 且是图片，准备内联替换
            if content_id and ctype.startswith("image/"):
                b64 = base64.b64encode(payload_data).decode("ascii")
                cid_map[content_id] = f"data:{ctype};base64,{b64}"
            continue

        # 如果带有 Content-ID 的非命名内嵌图片
        if content_id and part.get_content_type().startswith("image/"):
            payload_data = part.get_payload(decode=True) or b""
            ctype = part.get_content_type()
            b64 = base64.b64encode(payload_data).decode("ascii")
            cid_map[content_id] = f"data:{ctype};base64,{b64}"
            continue

        # 提取正文文本
        if content_maintype == "text":
            charset = part.get_content_charset() or "utf-8"
            payload_bytes = part.get_payload(decode=True) or b""
            try:
                decoded_str = payload_bytes.decode(charset, errors="replace")
            except Exception:
                decoded_str = payload_bytes.decode("utf-8", errors="replace")

            if part.get_content_subtype() == "html":
                html_parts.append(decoded_str)
            else:
                text_parts.append(decoded_str)

    raw_html = "\n".join(html_parts)
    raw_text = "\n".join(text_parts)

    # 如果只有 HTML，提取纯文本供提取摘要和全文搜索使用
    if not raw_text and raw_html:
        soup_temp = BeautifulSoup(raw_html, "html.parser")
        raw_text = soup_temp.get_text(separator=" ", strip=True)

    # 净化 HTML 并内嵌 cid 图片
    clean_html = sanitize_html(raw_html, cid_map) if raw_html else ""

    # 生成 160 字纯文本摘要
    cleaned_snippet = re.sub(r'\s+', ' ', raw_text).strip()
    snippet = cleaned_snippet[:160] + ("..." if len(cleaned_snippet) > 160 else "")

    # 提取验证码/OTP
    otp_code = extract_otp_code(subject, raw_text)

    return EmailParsedResult(
        message_id=str(message_id),
        subject=str(subject),
        from_name=str(from_name),
        from_address=str(from_address),
        to_addresses=to_addresses,
        date=parsed_date,
        snippet=snippet,
        html_body=clean_html or f"<pre style='font-family: inherit;'>{raw_text}</pre>",
        text_body=raw_text,
        has_attachments=len(attachments) > 0,
        attachments=attachments,
        otp_code=otp_code
    )
