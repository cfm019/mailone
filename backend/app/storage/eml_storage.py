import os
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple
from backend.app.config import settings

class EMLStorage:
    @staticmethod
    def save_eml(account_id: int, uid: int, raw_bytes: bytes, date_hint: Optional[datetime] = None) -> Tuple[str, int]:
        """
        持久化原始 EML 文件到磁盘。
        结构: storage/emails/{account_id}/{YYYY-MM}/{uid}.eml
        返回: (相对存储路径, 文件字节大小)
        """
        now = date_hint or datetime.now()
        year_month = now.strftime("%Y-%m")
        dir_path = settings.STORAGE_DIR / "emails" / str(account_id) / year_month
        dir_path.mkdir(parents=True, exist_ok=True)

        filename = f"{uid}.eml"
        file_path = dir_path / filename

        # 写入文件
        file_path.write_bytes(raw_bytes)
        rel_path = str(file_path.relative_to(settings.STORAGE_DIR))
        return rel_path, len(raw_bytes)

    @staticmethod
    def get_eml_bytes(rel_path: str) -> Optional[bytes]:
        """读取指定相对路径的 EML 原始数据"""
        full_path = settings.STORAGE_DIR / rel_path
        if not full_path.exists():
            return None
        return full_path.read_bytes()

    @staticmethod
    def delete_eml(rel_path: str) -> bool:
        """物理删除单个 EML 文件"""
        try:
            full_path = settings.STORAGE_DIR / rel_path
            if full_path.exists():
                full_path.unlink()
                return True
        except Exception:
            pass
        return False

    @staticmethod
    def delete_account_storage(account_id: int):
        """物理递归删除指定账户的所有本地 EML 文件及归档目录"""
        import shutil
        account_dir = settings.STORAGE_DIR / "emails" / str(account_id)
        if account_dir.exists():
            shutil.rmtree(account_dir, ignore_errors=True)

eml_storage = EMLStorage()
