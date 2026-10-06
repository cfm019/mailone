// MailOne - Core Frontend Application Logic

let currentView = 'inbox';
let currentAccountId = null;
let currentSearchQuery = '';
let currentPage = 1;
let currentMailDetail = null;
let accountsData = [];

// --- 主题管理 (Claude Warm Parchment vs Obsidian Graphite Dark) ---
function initTheme() {
  const savedTheme = localStorage.getItem('mailone_theme') || 'light';
  applyTheme(savedTheme);
}

function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  localStorage.setItem('mailone_theme', theme);
  const toggleButtons = [
    document.getElementById('btn-toggle-theme'),
    document.getElementById('btn-toggle-theme-mobile')
  ];
  toggleButtons.forEach(btn => {
    if (btn) {
      btn.textContent = theme === 'light' ? '☀️' : '🌙';
      btn.title = theme === 'light' ? '当前：Claude 暖米调（点击切为高级石墨黑）' : '当前：高级石墨黑（点击切为 Claude 暖米调）';
    }
  });
}

function toggleTheme() {
  const current = document.documentElement.getAttribute('data-theme') || 'light';
  const next = current === 'light' ? 'dark' : 'light';
  applyTheme(next);
  showToast(next === 'light' ? '已切换至 Claude 暖米色调 ☀️' : '已切换至高级石墨深色 🌙', 'info');
}

// 移动端辅助：关闭侧边抽屉与详情面板
function closeMobileSidebarAndDetail() {
  const sidebar = document.getElementById('sidebar');
  const backdrop = document.getElementById('sidebar-backdrop');
  if (sidebar) sidebar.classList.remove('open');
  if (backdrop) backdrop.classList.remove('active');
  if (window.innerWidth <= 900) {
    const detailPanel = document.getElementById('mail-detail-panel');
    if (detailPanel) detailPanel.classList.remove('active');
  }
}

// --- Toast 提示工具 ---
function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container');
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(10px)';
    toast.style.transition = 'all 0.3s ease';
    setTimeout(() => toast.remove(), 300);
  }, 3200);
}

// --- 认证与初始化 ---
async function checkAuthAndInit() {
  try {
    const res = await fetch('/api/auth/me');
    if (!res.ok) {
      window.location.href = '/login';
      return;
    }
    const data = await res.json();
    document.getElementById('current-username').textContent = data.username;

    // 加载数据
    await loadAccounts();
    await loadEmails();
  } catch (err) {
    window.location.href = '/login';
  }
}

// --- 加载账户列表 ---
async function loadAccounts() {
  try {
    const res = await fetch('/api/accounts');
    if (!res.ok) return;
    accountsData = await res.json();
    renderAccountsNav();
  } catch (e) {
    console.error('Error loading accounts:', e);
  }
}

function renderAccountsNav() {
  const container = document.getElementById('accounts-nav-list');
  container.innerHTML = '';

  accountsData.forEach(acc => {
    const item = document.createElement('div');
    item.className = `nav-item ${currentAccountId === acc.id ? 'active' : ''}`;
    item.innerHTML = `
      <div class="nav-item-left" style="flex: 1; min-width: 0;">
        <span class="account-color-dot" style="background-color: ${acc.color};"></span>
        <span style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 125px;">${escapeHtml(acc.name)}</span>
      </div>
      <div style="display: flex; align-items: center; gap: 4px;">
        ${acc.sync_status === 'syncing' ? '<span title="同步中" style="font-size: 11px;">⏳</span>' : ''}
        ${acc.sync_status === 'error' ? '<span title="同步异常" style="color: var(--danger); font-size: 11px;">⚠️</span>' : ''}
        <button class="btn-icon btn-edit-acc" title="编辑或删除此账户" style="font-size: 12px; padding: 2px 4px; border-radius: 4px;">⚙️</button>
      </div>
    `;

    const editBtn = item.querySelector('.btn-edit-acc');
    if (editBtn) {
      editBtn.onclick = (e) => {
        e.stopPropagation();
        openEditAccountModal(acc);
      };
    }

    item.onclick = () => {
      currentAccountId = acc.id;
      document.querySelectorAll('.sidebar .nav-item').forEach(el => el.classList.remove('active'));
      item.classList.add('active');
      const title = acc.name;
      const statusText = document.getElementById('list-status-text');
      const mobileTitle = document.getElementById('mobile-header-title');
      if (statusText) statusText.textContent = title;
      if (mobileTitle) mobileTitle.textContent = title;
      closeMobileSidebarAndDetail();
      loadEmails(1);
    };
    container.appendChild(item);
  });
}

// --- 加载邮件列表 ---
async function loadEmails(page = 1) {
  currentPage = page;
  const listContainer = document.getElementById('mail-list-container');
  listContainer.innerHTML = '<div style="padding: 24px; text-align: center; color: var(--text-muted);">加载中...</div>';

  const params = new URLSearchParams({
    view: currentView,
    page: currentPage,
    page_size: 40
  });

  if (currentAccountId) params.append('account_id', currentAccountId);
  if (currentSearchQuery) params.append('q', currentSearchQuery);

  try {
    const res = await fetch(`/api/mails?${params.toString()}`);
    if (!res.ok) throw new Error('Failed to load emails');
    const data = await res.json();

    const unreadEl = document.getElementById('badge-total-unread');
    if (unreadEl) unreadEl.textContent = data.unread_total || 0;

    renderMailList(data.items);
  } catch (err) {
    listContainer.innerHTML = '<div style="padding: 24px; text-align: center; color: var(--danger);">加载邮件失败</div>';
  }
}

function renderMailList(items) {
  const container = document.getElementById('mail-list-container');
  container.innerHTML = '';

  if (!items || items.length === 0) {
    container.innerHTML = '<div style="padding: 32px; text-align: center; color: var(--text-muted);">暂无匹配邮件</div>';
    return;
  }

  items.forEach(mail => {
    const card = document.createElement('div');
    card.className = `mail-card ${!mail.is_read ? 'unread' : ''} ${currentMailDetail && currentMailDetail.id === mail.id ? 'selected' : ''}`;
    card.dataset.id = mail.id;

    const formattedDate = formatMailDate(mail.date);
    const senderDisplay = mail.from_name || mail.from_address.split('@')[0];

    card.innerHTML = `
      <div class="mail-card-header">
        <div class="mail-card-sender">
          ${!mail.is_read ? '<span class="unread-indicator-dot"></span>' : ''}
          <span>${escapeHtml(senderDisplay)}</span>
        </div>
        <span class="mail-card-time">${formattedDate}</span>
      </div>
      <div class="mail-card-subject">${escapeHtml(mail.subject || '(无主题)')}</div>
      <div class="mail-card-snippet">${escapeHtml(mail.snippet)}</div>
      <div class="mail-card-footer">
        <span class="account-pill-badge" style="background-color: ${mail.account_color};">${escapeHtml(mail.account_name)}</span>
        ${!mail.has_body ? '<span title="正文未下载，点击时即时载入" style="font-size:11px; color:var(--text-muted);">☁️ 待载入</span>' : ''}
        ${mail.has_attachments ? '<span title="含附件" style="font-size: 11px;">📎</span>' : ''}
        ${mail.is_starred ? '<span style="font-size: 11px; color: #fbbf24;">⭐</span>' : ''}
      </div>
    `;

    card.addEventListener('click', () => {
      document.querySelectorAll('.mail-card').forEach(c => c.classList.remove('selected'));
      card.classList.add('selected');
      card.classList.remove('unread');
      const dot = card.querySelector('.unread-indicator-dot');
      if (dot) dot.remove();
      loadMailDetail(mail.id);
    });

    container.appendChild(card);
  });
}

// --- 邮件详情查看 ---
async function loadMailDetail(mailId) {
  const detailPanel = document.getElementById('mail-detail-panel');
  detailPanel.classList.add('active');
  detailPanel.scrollTop = 0;

  document.getElementById('detail-empty-state').style.display = 'none';
  const contentWrapper = document.getElementById('detail-content-wrapper');
  contentWrapper.style.display = 'flex';

  const bodyContainer = document.getElementById('detail-body-container');
  bodyContainer.scrollTop = 0;
  bodyContainer.innerHTML = '<div style="padding:40px; text-align:center; color:#64748b;">⏳ 正在从服务器载入正文并同步状态...</div>';

  try {
    const res = await fetch(`/api/mails/${mailId}`);
    if (!res.ok) throw new Error('Load detail failed');
    currentMailDetail = await res.json();

    // 渲染基础信息
    document.getElementById('detail-subject').textContent = currentMailDetail.subject || '(无主题)';
    document.getElementById('detail-from-name').textContent = currentMailDetail.from_name || currentMailDetail.from_address;
    document.getElementById('detail-from-address').textContent = `<${currentMailDetail.from_address}>`;
    document.getElementById('detail-date').textContent = new Date(currentMailDetail.date).toLocaleString('zh-CN');
    
    // 发件人头像首字母
    const avatarLetter = (currentMailDetail.from_name || currentMailDetail.from_address)[0].toUpperCase();
    document.getElementById('detail-avatar').textContent = avatarLetter;

    // 标星状态更新
    const starBtn = document.getElementById('btn-detail-star');
    if (starBtn) {
      starBtn.textContent = currentMailDetail.is_starred ? '⭐' : '☆';
      starBtn.title = currentMailDetail.is_starred ? '取消标星' : '标星';
    }

    // 来源邮箱徽标（若存在）
    const badge = document.getElementById('detail-account-badge');
    if (badge) {
      badge.textContent = currentMailDetail.account_name;
      badge.style.backgroundColor = currentMailDetail.account_color;
    }

    // 附件展示
    const attBox = document.getElementById('detail-attachments-box');
    if (currentMailDetail.attachments && currentMailDetail.attachments.length > 0) {
      attBox.style.display = 'flex';
      attBox.innerHTML = '';
      currentMailDetail.attachments.forEach((att, idx) => {
        const link = document.createElement('a');
        link.className = 'attachment-chip';
        link.href = `/api/mails/${mailId}/attachment/${idx}`;
        link.target = '_blank';
        link.innerHTML = `📎 <span>${escapeHtml(att.filename)}</span> <small style="color:var(--text-muted)">(${formatBytes(att.size)})</small>`;
        attBox.appendChild(link);
      });
    } else {
      attBox.style.display = 'none';
    }

    // HTML 正文沙箱隔离渲染并重置信纸模式
    const bodyContainer = document.getElementById('detail-body-container');
    bodyContainer.classList.remove('paper-light');
    const paperModeBtn = document.getElementById('btn-detail-paper-mode');
    if (paperModeBtn) {
      paperModeBtn.textContent = '📄';
      paperModeBtn.title = '切换信纸明暗（深色/浅白信纸）';
    }
    bodyContainer.innerHTML = currentMailDetail.html_body || `<pre>${escapeHtml(currentMailDetail.text_body)}</pre>`;

  } catch (e) {
    showToast('加载邮件详情失败', 'error');
  }
}

// --- 账户弹窗控制（新建与编辑） ---
function openAddAccountModal() {
  document.getElementById('account-modal-title').textContent = '绑定 IMAP 邮箱账户';
  document.getElementById('form-account').reset();
  document.getElementById('acc-id').value = '';
  document.getElementById('acc-color').value = '#3b82f6';
  document.getElementById('acc-imap-port').value = '993';
  document.getElementById('acc-password-label').textContent = '应用专用密码 (App Password)';
  document.getElementById('acc-password').placeholder = '建议生成专用授权码或密码';
  document.getElementById('acc-password').required = true;
  document.getElementById('btn-save-account').textContent = '保存并同步';
  document.getElementById('btn-delete-account').style.display = 'none';
  document.getElementById('modal-account').classList.add('active');
}

function openEditAccountModal(acc) {
  document.getElementById('account-modal-title').textContent = `编辑邮箱账户：${acc.name}`;
  document.getElementById('acc-id').value = acc.id;
  document.getElementById('acc-name').value = acc.name || '';
  document.getElementById('acc-email').value = acc.email || '';
  document.getElementById('acc-color').value = acc.color || '#3b82f6';
  document.getElementById('acc-imap-server').value = acc.imap_server || '';
  document.getElementById('acc-imap-port').value = acc.imap_port || 993;
  document.getElementById('acc-username').value = acc.username || '';
  document.getElementById('acc-password').value = '';
  document.getElementById('acc-password').placeholder = '留空表示保持现有密码不变';
  document.getElementById('acc-password').required = false;
  document.getElementById('acc-password-label').innerHTML = '应用专用密码 <small style="color:var(--text-muted); font-weight:normal;">(不修改请留空)</small>';
  document.getElementById('acc-sync-delete').checked = !!acc.sync_delete_remote;
  document.getElementById('btn-save-account').textContent = '保存修改';
  document.getElementById('btn-delete-account').style.display = 'inline-flex';
  document.getElementById('modal-account').classList.add('active');
}

// --- 事件监听绑定 ---
document.addEventListener('DOMContentLoaded', () => {
  initTheme();
  checkAuthAndInit();

  // 主题切换按钮（PC端侧边栏底端、移动端邮件列表顶栏）
  ['btn-toggle-theme', 'btn-toggle-theme-mobile'].forEach(id => {
    const btn = document.getElementById(id);
    if (btn) {
      btn.addEventListener('click', toggleTheme);
    }
  });

  // 移动端：返回邮件列表
  const backBtn = document.getElementById('btn-back-to-list');
  if (backBtn) {
    backBtn.addEventListener('click', () => {
      document.getElementById('mail-detail-panel').classList.remove('active');
    });
  }

  // 移动端：从邮件详情直接呼出邮箱与分类抽屉
  const detailOpenSidebarBtn = document.getElementById('btn-detail-open-sidebar');
  const sidebar = document.getElementById('sidebar');
  const backdrop = document.getElementById('sidebar-backdrop');
  if (detailOpenSidebarBtn && sidebar && backdrop) {
    detailOpenSidebarBtn.addEventListener('click', () => {
      document.getElementById('mail-detail-panel').classList.remove('active');
      sidebar.classList.add('open');
      backdrop.classList.add('active');
    });
  }

  // 移动端：打开侧边栏抽屉
  const mobileMenuBtn = document.getElementById('btn-mobile-menu');
  if (mobileMenuBtn && sidebar && backdrop) {
    mobileMenuBtn.addEventListener('click', () => {
      sidebar.classList.add('open');
      backdrop.classList.add('active');
    });
  }

  // 移动端：关闭侧边栏抽屉（点击遮罩或右上角叉号）
  if (backdrop && sidebar) {
    backdrop.addEventListener('click', () => {
      sidebar.classList.remove('open');
      backdrop.classList.remove('active');
    });
  }

  const closeSidebarBtn = document.getElementById('btn-close-sidebar');
  if (closeSidebarBtn && sidebar && backdrop) {
    closeSidebarBtn.addEventListener('click', () => {
      sidebar.classList.remove('open');
      backdrop.classList.remove('active');
    });
  }

  // 移动端顶部刷新按钮
  const mobileRefreshBtn = document.getElementById('btn-refresh-list-mobile');
  if (mobileRefreshBtn) {
    mobileRefreshBtn.addEventListener('click', () => loadEmails(currentPage));
  }

  // 标星/取消
  const starBtn = document.getElementById('btn-detail-star');
  if (starBtn) {
    starBtn.addEventListener('click', async () => {
      if (!currentMailDetail) return;
      const nextStar = !currentMailDetail.is_starred;
      currentMailDetail.is_starred = nextStar;
      starBtn.textContent = nextStar ? '⭐' : '☆';
      starBtn.title = nextStar ? '取消标星' : '标星';
      await fetch('/api/mails/batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email_ids: [currentMailDetail.id], action: nextStar ? 'star' : 'unstar' })
      });
      showToast(nextStar ? '已标星 ⭐' : '已取消标星', 'info');
      loadEmails(currentPage);
    });
  }

  // 设为未读
  const unreadBtn = document.getElementById('btn-detail-unread');
  if (unreadBtn) {
    unreadBtn.addEventListener('click', async () => {
      if (!currentMailDetail) return;
      await fetch('/api/mails/batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email_ids: [currentMailDetail.id], action: 'unread' })
      });
      showToast('已标记为未读 ✉️', 'info');
      if (window.innerWidth <= 900) {
        document.getElementById('mail-detail-panel').classList.remove('active');
      }
      loadEmails(currentPage);
    });
  }

  // 移入废纸篓
  document.getElementById('btn-detail-trash').addEventListener('click', async () => {
    if (!currentMailDetail) return;
    const confirmTrash = confirm('确定要将该邮件移入废纸篓吗？');
    if (!confirmTrash) return;

    await fetch('/api/mails/batch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email_ids: [currentMailDetail.id], action: 'trash' })
    });
    showToast('已移入废纸篓', 'info');
    document.getElementById('detail-empty-state').style.display = 'flex';
    document.getElementById('detail-content-wrapper').style.display = 'none';
    currentMailDetail = null;
    loadEmails(currentPage);
  });

  // 下载原始 .eml
  document.getElementById('btn-detail-download-eml').addEventListener('click', () => {
    if (currentMailDetail) {
      window.open(`/api/mails/${currentMailDetail.id}/eml`, '_blank');
    }
  });

  // 切换信纸明暗底色（深色/浅白纸张模式）
  const paperModeBtn = document.getElementById('btn-detail-paper-mode');
  if (paperModeBtn) {
    paperModeBtn.addEventListener('click', () => {
      const container = document.getElementById('detail-body-container');
      const isLightPaper = container.classList.toggle('paper-light');
      paperModeBtn.textContent = isLightPaper ? '💡' : '📄';
      paperModeBtn.title = isLightPaper ? '当前：浅白信纸（点击切回深色信纸）' : '当前：深色信纸（点击切为浅白信纸）';
      showToast(isLightPaper ? '已切换为浅白信纸原貌' : '已切换为护眼深色信纸', 'info');
    });
  }

  // 搜索防抖
  let searchTimer = null;
  document.getElementById('search-input').addEventListener('input', (e) => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      currentSearchQuery = e.target.value.trim();
      loadEmails(1);
    }, 350);
  });

  // 智能视图切换
  document.querySelectorAll('.sidebar .nav-item[data-view]').forEach(item => {
    item.addEventListener('click', () => {
      document.querySelectorAll('.sidebar .nav-item').forEach(el => el.classList.remove('active'));
      item.classList.add('active');
      currentView = item.dataset.view;
      currentAccountId = null;
      const titleSpan = item.querySelector('.nav-item-left span:last-child') || item.querySelector('span:nth-child(2)');
      const title = titleSpan ? titleSpan.textContent.trim() : '邮件列表';
      const statusText = document.getElementById('list-status-text');
      const mobileTitle = document.getElementById('mobile-header-title');
      if (statusText) statusText.textContent = title;
      if (mobileTitle) mobileTitle.textContent = title;
      closeMobileSidebarAndDetail();
      loadEmails(1);
    });
  });

  // 全量即时同步
  document.getElementById('btn-sync-all').addEventListener('click', async () => {
    showToast('正在触发所有邮箱即时同步...', 'info');
    for (const acc of accountsData) {
      await fetch(`/api/accounts/${acc.id}/sync`, { method: 'POST' });
    }
    setTimeout(loadAccounts, 2000);
    setTimeout(loadEmails, 3000);
  });

  // 刷新与全部已读
  document.getElementById('btn-refresh-list').addEventListener('click', () => loadEmails(currentPage));
  document.getElementById('btn-mark-all-read').addEventListener('click', async () => {
    const cards = document.querySelectorAll('.mail-card.unread');
    const ids = Array.from(cards).map(c => parseInt(c.dataset.id));
    if (ids.length === 0) {
      showToast('当前页暂无未读邮件', 'info');
      return;
    }
    await fetch('/api/mails/batch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email_ids: ids, action: 'read' })
    });
    showToast('已全部标记为已读', 'success');
    loadEmails(currentPage);
  });

  // 绑定邮箱模态窗（添加账户）
  document.getElementById('btn-add-account').addEventListener('click', openAddAccountModal);

  // 删除邮箱账户（连带清空本地邮件）
  document.getElementById('btn-delete-account').addEventListener('click', async () => {
    const accId = document.getElementById('acc-id').value;
    const accName = document.getElementById('acc-name').value;
    if (!accId) return;

    const confirmed = confirm(
      `确定要删除邮箱账户「${accName}」吗？\n\n⚠️ 警告：删除此账户将同时永久清理本地数据库中的所有关联邮件记录，以及存储在磁盘中的全部 .eml 原始归档文件，此操作不可恢复！`
    );
    if (!confirmed) return;

    showToast('正在删除账户并物理清理本地关联邮件...', 'info');
    try {
      const res = await fetch(`/api/accounts/${accId}`, { method: 'DELETE' });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || '删除失败');

      document.getElementById('modal-account').classList.remove('active');
      showToast(`🎉 账户已删除，已同步清理本地邮件！`, 'success');

      if (currentAccountId == accId) {
        currentAccountId = null;
        currentView = 'inbox';
        document.getElementById('list-status-text').textContent = '聚合收件箱';
        const mobileTitle = document.getElementById('mobile-header-title');
        if (mobileTitle) mobileTitle.textContent = '全部邮件';
      }

      await loadAccounts();
      await loadEmails(1);
    } catch (e) {
      showToast(`删除失败: ${e.message}`, 'error');
    }
  });

  // 测试连接
  document.getElementById('btn-test-account-conn').addEventListener('click', async () => {
    const accId = document.getElementById('acc-id').value;
    const payload = getAccountFormData();
    if (accId) {
      payload.account_id = parseInt(accId);
    }
    showToast('正在测试 IMAP 连接与认证...', 'info');
    try {
      const res = await fetch('/api/accounts/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (res.ok) {
        showToast('🎉 连接并登录成功！', 'success');
      } else {
        showToast(`连接失败: ${data.detail}`, 'error');
      }
    } catch (e) {
      showToast('网络错误，无法连接服务器', 'error');
    }
  });

  // 保存邮箱账户（新增或修改）
  document.getElementById('form-account').addEventListener('submit', async (e) => {
    e.preventDefault();
    const accId = document.getElementById('acc-id').value;
    const payload = getAccountFormData();

    if (accId) {
      // 修改更新现有账户
      showToast('正在保存账户配置...', 'info');
      try {
        const updatePayload = { ...payload };
        if (!updatePayload.password || !updatePayload.password.trim()) {
          delete updatePayload.password;
        }
        const res = await fetch(`/api/accounts/${accId}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(updatePayload)
        });
        const data = await res.json();
        if (res.ok) {
          showToast('账户配置更新成功！', 'success');
          document.getElementById('modal-account').classList.remove('active');
          await loadAccounts();
          await loadEmails(currentPage);
        } else {
          showToast(`更新失败: ${data.detail || '未知错误'}`, 'error');
        }
      } catch (e) {
        showToast('网络请求失败', 'error');
      }
    } else {
      // 添加新账户
      showToast('正在保存并启动后台同步...', 'info');
      try {
        const res = await fetch('/api/accounts', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (res.ok) {
          showToast('🎉 邮箱绑定成功！已加入聚合收信任务', 'success');
          document.getElementById('modal-account').classList.remove('active');
          await loadAccounts();
          setTimeout(() => loadEmails(1), 1200);
        } else {
          showToast(`保存失败: ${data.detail}`, 'error');
        }
      } catch (e) {
        showToast('保存失败，请检查网络', 'error');
      }
    }
  });

  // 设置与安全弹窗
  document.getElementById('btn-settings').addEventListener('click', async () => {
    document.getElementById('modal-settings').classList.add('active');
    loadSettingsModal();
  });

  // 手工启动历史邮件正文下载
  document.getElementById('btn-batch-fetch-bodies').addEventListener('click', async () => {
    if (accountsData.length === 0) {
      showToast('未绑定邮箱账户', 'info');
      return;
    }
    showToast('正在后台启动全量历史正文下载任务...', 'info');
    for (const acc of accountsData) {
      await fetch(`/api/accounts/${acc.id}/fetch-all-bodies`, { method: 'POST' });
    }
    showToast('任务已在后台运行，正在分批落盘 .eml', 'success');
  });

  // Telegram 测试推送
  document.getElementById('btn-test-telegram-push').addEventListener('click', async () => {
    showToast('正在向 Telegram 发送测试消息...', 'info');
    const res = await fetch('/api/telegram/test', { method: 'POST' });
    const data = await res.json();
    if (data.success) {
      showToast('🎉 Telegram 测试消息发送成功！', 'success');
    } else {
      showToast(`Telegram 推送失败: ${data.message}`, 'error');
    }
  });

  // 登出
  document.getElementById('btn-logout').addEventListener('click', async () => {
    await fetch('/api/auth/logout', { method: 'POST' });
    window.location.href = '/login';
  });

  // 弹窗关闭按钮
  document.querySelectorAll('.modal-close-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.modal-backdrop').forEach(m => m.classList.remove('active'));
    });
  });
});

function getAccountFormData() {
  return {
    name: document.getElementById('acc-name').value,
    email: document.getElementById('acc-email').value,
    color: document.getElementById('acc-color').value,
    imap_server: document.getElementById('acc-imap-server').value,
    imap_port: parseInt(document.getElementById('acc-imap-port').value),
    use_ssl: true,
    username: document.getElementById('acc-username').value,
    password: document.getElementById('acc-password').value,
    sync_delete_remote: document.getElementById('acc-sync-delete').checked
  };
}

async function loadSettingsModal() {
  const box = document.getElementById('totp-status-box');
  const res = await fetch('/api/auth/me');
  if (!res.ok) return;
  const user = await res.json();

  if (user.is_totp_enabled) {
    box.innerHTML = `
      <div style="display:flex; align-items:center; justify-content:space-between; background:rgba(16,185,129,0.1); border:1px solid rgba(16,185,129,0.3); padding:10px 14px; border-radius:var(--radius-md);">
        <span style="color:var(--success); font-weight:600;">✅ 已开启 TOTP 两步验证</span>
        <button class="btn-secondary" id="btn-disable-totp-action" style="color:var(--danger); font-size:12px;">关闭2FA</button>
      </div>
    `;
    document.getElementById('btn-disable-totp-action').onclick = disableTotpPrompt;
  } else {
    box.innerHTML = `
      <div style="display:flex; align-items:center; justify-content:space-between; background:rgba(255,255,255,0.03); border:1px solid var(--border-color); padding:10px 14px; border-radius:var(--radius-md);">
        <span style="color:var(--text-muted);">未开启两步验证</span>
        <button class="btn-primary" id="btn-enable-totp-action" style="font-size:12px;">立即配置2FA</button>
      </div>
      <div id="totp-setup-interactive" style="display:none; margin-top:12px; flex-direction:column; gap:10px;"></div>
    `;
    document.getElementById('btn-enable-totp-action').onclick = startTotpSetup;
  }
}

async function startTotpSetup() {
  const interactive = document.getElementById('totp-setup-interactive');
  interactive.style.display = 'flex';
  interactive.innerHTML = '正在生成密钥与二维码...';

  const res = await fetch('/api/auth/setup-totp', { method: 'POST' });
  const data = await res.json();

  interactive.innerHTML = `
    <div style="text-align:center;">
      <p style="font-size:12px; margin-bottom:8px;">请使用 Google Authenticator / 1Password 等扫码：</p>
      <img src="${data.qr_code_data_url}" style="width:160px; height:160px; border-radius:8px; border:2px solid #fff;">
      <div style="font-family:monospace; font-size:11px; margin-top:6px; color:var(--text-muted);">${data.secret}</div>
    </div>
    <div class="form-group" style="margin-top:8px;">
      <label class="form-label">输入扫码后生成的 6 位验证码以确认：</label>
      <div style="display:flex; gap:8px;">
        <input type="text" id="input-confirm-totp" class="form-input" placeholder="000000" maxlength="6">
        <button class="btn-primary" id="btn-confirm-totp-submit">验证并开启</button>
      </div>
    </div>
  `;

  document.getElementById('btn-confirm-totp-submit').onclick = async () => {
    const code = document.getElementById('input-confirm-totp').value.trim();
    const verifyRes = await fetch('/api/auth/verify-totp', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ secret: data.secret, code })
    });
    if (verifyRes.ok) {
      showToast('🎉 两步验证开启成功！', 'success');
      loadSettingsModal();
    } else {
      showToast('验证码错误，请重新输入', 'error');
    }
  };
}

async function disableTotpPrompt() {
  const code = prompt('请输入当前的 6 位动态验证码以关闭 2FA：');
  if (!code) return;
  const res = await fetch('/api/auth/disable-totp', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ secret: '', code })
  });
  if (res.ok) {
    showToast('已关闭两步验证', 'info');
    loadSettingsModal();
  } else {
    showToast('验证码错误，关闭失败', 'error');
  }
}

// 辅助函数
function escapeHtml(str) {
  if (!str) return '';
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function formatBytes(bytes) {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

function formatMailDate(dateStr) {
  if (!dateStr) return '';
  const d = new Date(dateStr);
  const now = new Date();
  if (d.toDateString() === now.toDateString()) {
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }
  return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
}
