# MailOne 📬

> **多邮箱聚合查看、本地归档并推送 Telegram 的轻量邮箱管理系统。**

---

## 🌟 系统功能

- **多 IMAP 邮箱聚合收信**：同时监听 Gmail、Outlook、QQ、163 等多个邮箱，支持 **IMAP IDLE 长连接秒级推送** 与定时轮询兜底。
- **混合持久化存储 (Hybrid Storage)**：
  - **邮件本体**：本地保存为标准 `.eml` 文件（按账户与年月分级），无损归档，随时可导出或使用任何本地客户端直接打开，避免频繁登录网页邮箱。
  - **元数据与全文索引**：使用轻量 SQLite WAL 模式，配合 **SQLite FTS5** 实现全文检索。
- **Telegram Bot 推送**：
  - **短期签名 Magic Link**：针对每封邮件生成 30 分钟有效的只读免密链接，点击直接在手机端渲染安全清洗后的 HTML 邮件，**免去反复登录的繁琐**，同时严格防越权。
  - **白名单保护**：严格校验 `chat_id`，防止未授权访问。
- **极简 Web 面板**：
  - **统一收件箱（Unified Inbox）**：多邮箱时间线混排，以彩色药丸微标显示来源。
  - **账户管理与级联清理**：支持对各邮箱账户编辑参数，删除账户时同步级联物理清理本地数据库与 .eml 归档。
  - **删除联动**：支持本地移入废纸篓，并可自选是否同步删除远程原邮箱邮件。
- **公网安全防护**：
  - 支持 **TOTP 2FA（双因素认证）**，兼容 Google Authenticator、1Password 等。
  - 邮箱应用密码采用 **AES-GCM / Fernet 加密** 存储。

---

## 🚀 快速启动

### 方式一：一键自动安装（推荐 VPS 原生部署，带 Systemd 开机自启）

在 Linux VPS（Ubuntu / Debian / CentOS / Rocky 等）上直接运行以下命令，即可全自动拉取最新代码、安装 Python 依赖并配置开机自启动：

```bash
# 一键在线安装
bash <(curl -fsSL https://raw.githubusercontent.com/cfm019/mailone/main/install.sh)
```

或者克隆仓库后在本地执行：
```bash
git clone https://github.com/cfm019/mailone.git
cd mailone
sudo bash install.sh
```

> **后续更新代码**：只需再次在安装目录下执行 `sudo bash install.sh`，脚本会自动拉取 GitHub 最新版本、更新依赖并平滑重启服务，同时安全保留现有的 `.env` 配置与 `data/` 邮件数据。

---

### 方式二：Docker Compose 容器部署

1. 克隆本仓库：
   ```bash
   git clone https://github.com/cfm019/mailone.git
   cd mailone
   ```

2. 准备配置文件：
   ```bash
   cp .env.example .env
   ```
   编辑 `.env`：
   ```ini
   # 外部公网访问域名（用于在 TG 消息里生成可点击的免密链接）
   BASE_URL=https://mail.yourdomain.com:8000

   # Telegram Bot 配置
   TELEGRAM_BOT_TOKEN=123456789:ABCdefGHI...
   TELEGRAM_ALLOWED_CHAT_IDS=987654321
   ```

3. 一键启动容器：
   ```bash
   docker compose up -d
   ```

4. 打开浏览器访问 `http://<your-vps-ip>:8000`，首次启动会引导设置管理员账号密码。

---

### 方式三：本地开发运行（使用 uv / Python）

1. 创建并激活虚拟环境：
   ```bash
   uv venv .venv
   source .venv/bin/activate
   ```

2. 安装依赖：
   ```bash
   uv pip install -r requirements.txt
   ```

3. 启动服务：
   ```bash
   python -m backend.app.main
   ```
   服务将运行在 `http://127.0.0.1:8000`。

---

## ⚙️ 邮箱配置指南（应用专用密码）

为了账号安全，MailOne 强制要求配置**“应用专用密码”（App Password）**而非邮箱主密码：

- **Gmail**：登录 Google 账号 -> 安全性 -> 开启两步验证 -> 搜索并进入“应用专用密码” -> 生成 16 位专属密码。
- **Outlook / Hotmail**：微软账户 -> 安全性 -> 高级安全选项 -> 应用密码。
- **QQ 邮箱 / 163 邮箱**：进入邮箱网页版 -> 设置 -> 账户 -> 开启 POP3/IMAP 服务 -> 生成授权码。

---

## 🤖 Telegram Bot 配置步骤

1. 在 Telegram 中找到 [@BotFather](https://t.me/BotFather)，发送 `/newbot`，按提示创建一个 Bot 并保存得到的 **API Token**。
2. 找到 [@userinfobot](https://t.me/userinfobot) 或 [@getidsbot](https://t.me/getidsbot)，获取你的个人数字 **Chat ID**。
3. 将两者填入 `.env` 中的 `TELEGRAM_BOT_TOKEN` 和 `TELEGRAM_ALLOWED_CHAT_IDS`。
4. 部署后，可在 Web 面板的【设置 -> Telegram Bot 推送诊断】中点击“发送测试消息”验证是否连通。

---

## 📁 数据存储结构

数据默认持久化在 `./data` 目录下：
```text
data/
├── db.sqlite           # SQLite 数据库（用户信息、元数据、FTS5 全文搜索）
├── .secret_key         # 自动生成的系统签名私钥
└── storage/
    └── emails/
        └── {account_id}/
            └── 2026-10/
                └── 123.eml  # 原始国际标准 MIME 邮件文件
```

---

## 🧪 自动化测试

项目内置完整的单元测试与端到端测试套件：
```bash
# 测试核心功能（OTP 提取、Magic Link 加密校验、数据库）
PYTHONPATH=. .venv/bin/python tests/test_core.py

# 端到端 API 测试
PYTHONPATH=. .venv/bin/python tests/test_api.py
```

---

## 📄 开源许可证

MIT License.
