#!/usr/bin/env bash
# ==============================================================================
# MailOne 生产环境自动部署与更新脚本
# 支持：Ubuntu / Debian / CentOS / RHEL / AlmaLinux / Rocky Linux
# 功能：
#   1. 检查并安装系统级依赖（Python 3.10+、pip、venv、git、curl）
#   2. 自动拉取/更新 GitHub 最新代码 (https://github.com/cfm019/mailone.git)
#   3. 创建/更新 Python 虚拟环境并自动安装所有依赖
#   4. 保护用户既有数据与配置（保留 .env 与 data/ 目录）
#   5. 配置 Systemd 系统服务并设置开机自启
# ==============================================================================

set -euo pipefail

# 默认配置
REPO_URL="https://github.com/cfm019/mailone.git"
DEFAULT_INSTALL_DIR="/opt/mailone"
SERVICE_NAME="mailone"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

info() { echo -e "${CYAN}[INFO]${NC} $*"; }
success() { echo -e "${GREEN}[SUCCESS]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# 1. 权限检查
if [[ $EUID -ne 0 ]]; then
  error "请使用 root 权限或 sudo 运行此安装脚本："
  echo "  sudo bash $0"
  exit 1
fi

echo -e "${PURPLE}"
cat << 'EOF'
 __  __       _ _  ___            
|  \/  |     (_) |/ _ \ _ __   ___ 
| |\/| | __ _ _| | | | | '_ \ / _ \
| |  | |/ _` | | | |_| | | | |  __/
|_|  |_|\__,_|_|_|\___/|_| |_|\___|
   MailOne 极简多邮箱聚合管理系统
EOF
echo -e "${NC}"

# 2. 判断当前工作路径
# 如果脚本位于已有 mailone 源码目录中执行，则直接以当前目录作为安装目录；否则默认安装至 /opt/mailone
if [[ -f "./backend/app/main.py" && -f "./requirements.txt" ]]; then
  INSTALL_DIR="$(pwd)"
  info "检测到在已有 MailOne 源码目录下执行，安装路径：${INSTALL_DIR}"
else
  INSTALL_DIR="${DEFAULT_INSTALL_DIR}"
  info "目标安装目录：${INSTALL_DIR}"
fi

# 3. 安装系统依赖工具
info "检查系统包管理器与运行环境..."

install_packages() {
  if command -v apt-get &>/dev/null; then
    info "检测到 Debian/Ubuntu 系列系统，更新软件源并安装依赖..."
    apt-get update -y
    apt-get install -y git curl python3 python3-pip python3-venv ca-certificates
  elif command -v dnf &>/dev/null; then
    info "检测到 RHEL/CentOS/Fedora/Rocky 系列系统 (dnf)，安装依赖..."
    dnf install -y git curl python3 python3-pip ca-certificates
  elif command -v yum &>/dev/null; then
    info "检测到 CentOS/RHEL 系列系统 (yum)，安装依赖..."
    yum install -y git curl python3 python3-pip ca-certificates
  elif command -v pacman &>/dev/null; then
    info "检测到 Arch Linux 系统，安装依赖..."
    pacman -Sy --noconfirm git curl python python-pip
  else
    warn "未识别的包管理器，请确保已手动安装 git, curl, python3 (>=3.10), python3-pip, python3-venv"
  fi
}

install_packages

# 4. 检查 Python 版本 (>= 3.10)
if ! command -v python3 &>/dev/null; then
  error "未找到 python3，请先安装 Python 3.10 及以上版本！"
  exit 1
fi

PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)

if (( PY_MAJOR < 3 || (PY_MAJOR == 3 && PY_MINOR < 10) )); then
  error "当前 Python 版本为 ${PY_VER}，MailOne 需要 Python 3.10 或更高版本！"
  exit 1
fi
success "Python 版本检测通过: ${PY_VER}"

# 5. 克隆或拉取最新代码
mkdir -p "$(dirname "${INSTALL_DIR}")"

if [[ -d "${INSTALL_DIR}/.git" ]]; then
  info "目标目录已存在 Git 仓库，拉取最新代码..."
  cd "${INSTALL_DIR}"
  # 暂存未提交修改，避免意外拉取冲突
  git fetch --all --tags
  git reset --hard origin/main || git pull origin main || true
  success "代码已更新至最新版本！"
elif [[ -d "${INSTALL_DIR}" && -f "${INSTALL_DIR}/backend/app/main.py" ]]; then
  info "当前为已有目录，跳过 clone 操作..."
  cd "${INSTALL_DIR}"
else
  info "从 GitHub 克隆最新仓库..."
  git clone "${REPO_URL}" "${INSTALL_DIR}"
  cd "${INSTALL_DIR}"
  success "代码仓库克隆成功！"
fi

# 确保关键本地数据目录存在
mkdir -p "${INSTALL_DIR}/data/storage/emails"

# 6. 配置 Python 虚拟环境与依赖
info "配置 Python 独立虚拟环境 (.venv)..."
if [[ ! -d "${INSTALL_DIR}/.venv" ]]; then
  python3 -m venv "${INSTALL_DIR}/.venv"
fi

VENV_PYTHON="${INSTALL_DIR}/.venv/bin/python"
VENV_PIP="${INSTALL_DIR}/.venv/bin/pip"

info "更新 pip 并安装 Python 依赖项..."
"${VENV_PIP}" install --upgrade pip
"${VENV_PIP}" install -r "${INSTALL_DIR}/requirements.txt"
success "Python 依赖安装完成！"

# 7. 配置文件初始化 (.env)
if [[ ! -f "${INSTALL_DIR}/.env" ]]; then
  info "首次安装，生成默认配置文件 .env ..."
  cp "${INSTALL_DIR}/.env.example" "${INSTALL_DIR}/.env"
  
  # 自动生成随机 SECRET_KEY
  RANDOM_SECRET=$("${VENV_PYTHON}" -c "import secrets; print(secrets.token_urlsafe(32))" 2>/dev/null || echo "mailone_secret_$(date +%s)")
  sed -i "s|SECRET_KEY=.*|SECRET_KEY=${RANDOM_SECRET}|g" "${INSTALL_DIR}/.env" || true
  
  success "已自动生成 .env 配置文件"
  warn "提示：公网域名可在 ${INSTALL_DIR}/.env 中配置；Telegram 推送直接在网页端【系统设置】配置即可"
else
  info "保留已有的 .env 配置文件（不覆盖）"
fi

# 8. 创建 Systemd 自启动服务
info "配置 Systemd 守护进程 (${SERVICE_NAME}.service)..."

SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

cat > "${SERVICE_FILE}" << EOF
[Unit]
Description=MailOne Email Aggregator & Management Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=${INSTALL_DIR}
EnvironmentFile=-${INSTALL_DIR}/.env
Environment="PATH=${INSTALL_DIR}/.venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin"
ExecStart=${INSTALL_DIR}/.venv/bin/python -m backend.app.main
Restart=always
RestartSec=5s
KillMode=process
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
EOF

# 9. 启动与设置开机自启
info "重载 Systemd 并启动服务..."
systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"
systemctl restart "${SERVICE_NAME}"

# 等待 2 秒检查状态
sleep 2

if systemctl is-active --quiet "${SERVICE_NAME}"; then
  # 读取 .env 中实际配置的监听地址与端口
  ENV_HOST=$(grep -E '^HOST=' "${INSTALL_DIR}/.env" 2>/dev/null | cut -d= -f2 | tr -d ' "\r' || echo "127.0.0.1")
  ENV_PORT=$(grep -E '^PORT=' "${INSTALL_DIR}/.env" 2>/dev/null | cut -d= -f2 | tr -d ' "\r' || echo "11001")
  LOCAL_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "你的服务器IP")
  
  echo ""
  echo -e "${GREEN}================================================================${NC}"
  echo -e "${GREEN}  MailOne 服务已成功安装并启动！开机自启已生效！${NC}"
  echo -e "${GREEN}================================================================${NC}"
  echo ""
  echo -e "  服务监听地址:  ${CYAN}http://${ENV_HOST}:${ENV_PORT}${NC}"
  echo -e "  程序安装目录:  ${YELLOW}${INSTALL_DIR}${NC}"
  echo -e "  核心配置文件:  ${YELLOW}${INSTALL_DIR}/.env${NC}"
  echo -e "  本地邮件归档:  ${YELLOW}${INSTALL_DIR}/data/${NC}"
  echo ""
  
  if [[ "${ENV_HOST}" == "127.0.0.1" || "${ENV_HOST}" == "localhost" ]]; then
    echo -e "${PURPLE}反向代理配置指引 (推荐 Caddy，自带自动 HTTPS)：${NC}"
    echo -e "  当前服务已默认安全监听于本地 127.0.0.1:${ENV_PORT}，不向公网暴露明文端口。"
    echo -e "  若使用 Caddy，只需在 ${CYAN}/etc/caddy/Caddyfile${NC} 中添加："
    echo -e "  --------------------------------------------------"
    echo -e "  ${GREEN}mail.yourdomain.com {${NC}"
    echo -e "      ${GREEN}reverse_proxy 127.0.0.1:${ENV_PORT}${NC}"
    echo -e "  ${GREEN}}${NC}"
    echo -e "  --------------------------------------------------"
    echo -e "  然后执行: ${CYAN}systemctl reload caddy${NC} 即可自动完成 SSL 证书申请与代理！"
    echo ""
  else
    echo -e "  公网直连访问:  ${CYAN}http://${LOCAL_IP}:${ENV_PORT}${NC}"
    echo ""
  fi

  echo -e "${PURPLE}如何修改设置：${NC}"
  echo -e "  1. 编辑配置文件:  ${CYAN}nano ${INSTALL_DIR}/.env${NC}"
  echo -e "  2. 重启服务生效:  ${CYAN}systemctl restart ${SERVICE_NAME}${NC}"
  echo ""
  echo -e "${PURPLE}常用运维命令：${NC}"
  echo -e "  • 查看实时日志:    ${CYAN}journalctl -u ${SERVICE_NAME} -f${NC}"
  echo -e "  • 重启服务:        ${CYAN}systemctl restart ${SERVICE_NAME}${NC}"
  echo -e "  • 停止服务:        ${CYAN}systemctl stop ${SERVICE_NAME}${NC}"
  echo -e "  • 查看运行状态:    ${CYAN}systemctl status ${SERVICE_NAME}${NC}"
  echo -e "  • 一键升级更新:    ${CYAN}cd ${INSTALL_DIR} && bash install.sh${NC}"
  echo ""
  echo -e "${YELLOW}首次使用提醒：${NC}"
  echo -e "  打开 Web 界面后，系统会自动引导您创建初始管理员账号与密码。"
  echo ""
else
  error "服务启动遇到异常，请运行以下命令查看详细错误日志："
  echo "  journalctl -u ${SERVICE_NAME} -n 50 --no-pager"
  exit 1
fi
