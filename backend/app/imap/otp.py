import re
from typing import Optional

# 验证码提取关键词模式
OTP_PATTERNS = [
    # 模式 1: 关键词后跟冒号/空格/等号/为/是，捕获带连字符或不带连字符的验证码 (如 "839201", "G-928172", "123-456")
    r'(?:验证码|校验码|动态码|安全码|确认码|激活码|安全确认码|verification[\s_-]?code|security[\s_-]?code|confirmation[\s_-]?code|otp|passcode|one-time[\s_-]?password|pin)[\s:：is为是\-=]{1,10}(?:<b>|<strong>)?([0-9a-zA-Z]{1,4}-[0-9a-zA-Z]{3,7}|[0-9a-zA-Z]{4,8})(?:</b>|</strong>)?(?:\b|[^\d\w])',
    
    # 模式 2: 数字在前面，紧跟 "是您的/为您的验证码" (例如: "839201 是您的验证码")
    r'(?:\b)([0-9]{4,8})(?:\b)\s*(?:是您的|为您的|是本次|为本次)[\u4e00-\u9fa5]{0,6}(?:验证码|动态码|安全码)',
    
    # 模式 3: "Use 123456 to verify" 或 "Enter 123456 in"
    r'(?:use|enter|code is)[\s:：]{1,5}([0-9a-zA-Z]{4,8})[\s]{1,5}(?:to|as|for|in)',

    # 模式 4: 兜底通用连字符格式
    r'(?:code|pin|码)[\s:：is为]{1,8}(G-[0-9]{6}|[0-9]{3}-[0-9]{3})',

    # 模式 5: 英文常见的 "code to verify your account. 769591"
    r'(?:code|pin)[\s\w]{0,35}[.:：\s]+([0-9]{4,8})(?:\b|[^\d\w])',
]

EXCLUDE_WORDS = {
    "2024", "2025", "2026", "2027", "2028", "1234", "0000", "html", "http", "true", "null",
    "from", "with", "into", "your", "that", "this", "have", "alert", "notice", "email",
    "group", "user", "please", "after", "login", "code", "mail", "team", "cloud", "here",
    "click", "reset", "help", "view", "link", "info", "admin", "send", "sent"
}

def extract_otp_code(subject: str, text_body: str) -> Optional[str]:
    """
    从邮件主题和正文中提取验证码/OTP 代码。
    返回提取到的代码字符串，若未识别则返回 None。
    """
    combined_text = f"{subject}\n{text_body}"

    # 1. 优先在主题中搜索高置信度验证码
    for pattern in OTP_PATTERNS:
        match = re.search(pattern, subject, re.IGNORECASE)
        if match:
            code = match.group(1).strip()
            if _is_valid_code(code):
                return code

    # 2. 在正文前 2000 个字符中搜索
    search_scope = text_body[:2000] if text_body else combined_text[:2000]
    for pattern in OTP_PATTERNS:
        matches = re.finditer(pattern, search_scope, re.IGNORECASE)
        for m in matches:
            code = m.group(1).strip()
            if _is_valid_code(code):
                return code

    return None

def _is_valid_code(code: str) -> bool:
    if not code:
        return False
    lower_c = code.lower()
    if lower_c in EXCLUDE_WORDS:
        return False
    # 长度 4 到 10 位（兼容带连字符的验证码如 G-123456）
    if not (4 <= len(code) <= 10):
        return False
    # 如果全为纯小写英文字母且不含数字，极大概率是英文普通单词，直接排除
    if code.isalpha() and code.islower():
        return False
    # 如果是全数字，排除明显的年份 19xx, 20xx
    if code.isdigit():
        if len(code) == 4 and (code.startswith("19") or code.startswith("20")):
            return False
    return True
