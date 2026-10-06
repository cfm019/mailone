// MailOne - Core Frontend Application Logic
// Design Aesthetic: Classic Gmail Material System (Zero Emojis, Monochrome SVG Icons, Classic Pagination)

let currentView = 'inbox';
let currentAccountId = null;
let currentSearchQuery = '';
let currentPage = 1;
const PAGE_SIZE = 50;
let currentTotalMails = 0;
let currentMails = [];
let isLoadingMails = false;
let currentMailDetail = null;
let accountsData = [];
let accountHistoryStatus = {};

// --- 主题管理 (Gmail Classic Light vs Obsidian Dark) ---
function initTheme() {
  const savedTheme = localStorage.getItem('mailone_theme') || 'light';
  applyTheme(savedTheme);
}

function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  localStorage.setItem('mailone_theme', theme);
}

function toggleTheme() {
  const current = document.documentElement.getAttribute('data-theme') || 'light';
  const next = current === 'light' ? 'dark' : 'light';
  applyTheme(next);
  showToast(next === 'light' ? '已切换至经典浅色主题' : '已切换至深色护眼主题', 'info');
}

// --- 侧边栏折叠管理 (像 Gmail 一样收拢/展开) ---
function initSidebar() {
  const isCollapsed = localStorage.getItem('mailone_sidebar_collapsed') === 'true';
  const sidebar = document.getElementById('sidebar');
  if (sidebar && isCollapsed && window.innerWidth > 900) {
    sidebar.classList.add('collapsed');
  }
}

function toggleSidebar() {
  const sidebar = document.getElementById('sidebar');
  const backdrop = document.getElementById('sidebar-backdrop');
  if (!sidebar) return;

  if (window.innerWidth <= 900) {
    // 移动端：切换抽屉开闭
    sidebar.classList.toggle('open');
    if (backdrop) backdrop.classList.toggle('active');
  } else {
    // 桌面端：收拢或展开
    const collapsed = sidebar.classList.toggle('collapsed');
    localStorage.setItem('mailone_sidebar_collapsed', collapsed ? 'true' : 'false');
  }
}

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

// --- 账户信息与当前用户初始化 ---
async function checkAuthAndLoadInitialData() {
  try {
    const res = await fetch('/api/auth/me');
    if (!res.ok) {
      window.location.href = '/login';
      return;
    }
    const user = await res.json();
    const usernameEl = document.getElementById('current-username');
    const userInitialEl = document.getElementById('current-username-initial');
    if (usernameEl) usernameEl.textContent = user.username;
    if (userInitialEl) userInitialEl.textContent = (user.username || 'A')[0].toUpperCase();

    await loadAccounts();
    await loadEmails(1);
  } catch (err) {
    window.location.href = '/login';
  }
}

// --- 加载邮箱账号列表 ---
async function loadAccounts() {
  try {
    const res = await fetch('/api/accounts');
    if (!res.ok) return;
    accountsData = await res.json();
    renderAccountsNav(accountsData);
    updateRemoteHistoryBtn();
  } catch (err) {
    console.error('Failed to load accounts', err);
  }
}

// 乐观扣减账号未读数（即时响应用户点击已读操作）
function decrementAccountUnread(accountId) {
  if (!accountsData) return;
  const acc = accountsData.find(a => a.id === accountId);
  if (acc && acc.unread_count > 0) {
    acc.unread_count = Math.max(0, acc.unread_count - 1);
    updateAccountBadgeDom(accountId, acc.unread_count);
  }
  // 全局收件箱总未读数
  const totalUnreadEl = document.getElementById('badge-total-unread');
  if (totalUnreadEl) {
    const cur = parseInt(totalUnreadEl.textContent, 10) || 0;
    totalUnreadEl.textContent = Math.max(0, cur - 1);
  }
}

// 更新指定账号卡片的未读徽标 DOM
function updateAccountBadgeDom(accountId, count) {
  const accItem = document.querySelector(`.account-item[data-id="${accountId}"]`);
  if (!accItem) return;
  let badge = accItem.querySelector('.badge-count');
  if (count > 0) {
    if (badge) {
      badge.textContent = count;
    } else {
      const rightEl = accItem.querySelector('.account-item-right');
      if (rightEl) {
        badge = document.createElement('span');
        badge.className = 'badge-count';
        badge.textContent = count;
        rightEl.insertBefore(badge, rightEl.firstChild);
      }
    }
  } else if (badge) {
    badge.remove();
  }
}

function renderAccountsNav(accounts) {
  const container = document.getElementById('accounts-nav-list');
  if (!container) return;
  container.innerHTML = '';

  if (!accounts || accounts.length === 0) {
    container.innerHTML = '<div style="padding: 6px 12px; font-size: 12px; color: var(--text-muted);">暂未绑定邮箱</div>';
    return;
  }

  accounts.forEach(acc => {
    const item = document.createElement('div');
    item.className = `account-item ${currentAccountId === acc.id ? 'active' : ''}`;
    item.dataset.id = acc.id;
    item.title = `${acc.name} (${acc.email})`;

    item.innerHTML = `
      <div class="account-item-left">
        <span class="account-color-dot" style="background-color: ${acc.color};"></span>
        <span class="account-name-text">${escapeHtml(acc.name)}</span>
      </div>
      <div class="account-item-right">
        ${acc.unread_count > 0 ? `<span class="badge-count">${acc.unread_count}</span>` : ''}
        <button class="btn-icon btn-edit-acc" title="设置此邮箱">
          <svg class="icon" style="width: 13px; height: 13px;" viewBox="0 0 24 24"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>
        </button>
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
      document.querySelectorAll('.sidebar .account-item').forEach(el => el.classList.remove('active'));
      item.classList.add('active');

      closeMobileSidebarAndDetail();
      loadEmails(1);
      updateRemoteHistoryBtn();
    };
    container.appendChild(item);
  });
}

// --- 邮件卡片 DOM 创建 (无 Emoji, 纯净 Material 风格) ---
function createMailCard(mail) {
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
      ${!mail.has_body ? '<span class="mail-pending-body-tag" style="font-size:11px; color:var(--text-muted); display:inline-flex; align-items:center; gap:3px;"><svg class="icon" style="width:12px;height:12px;" viewBox="0 0 24 24"><path d="M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z"/></svg> 待载入</span>' : ''}
      ${mail.has_attachments ? '<span style="display:inline-flex; align-items:center; color:var(--text-muted);" title="含附件"><svg class="icon" style="width:13px;height:13px;" viewBox="0 0 24 24"><path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg></span>' : ''}
      <button class="card-star-btn ${mail.is_starred ? 'active' : ''}" title="${mail.is_starred ? '取消标星' : '标星'}">
        <svg class="icon" viewBox="0 0 24 24" ${mail.is_starred ? 'fill="currentColor"' : 'fill="none"'}><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>
      </button>
    </div>
  `;

  // 标星点击
  const starBtn = card.querySelector('.card-star-btn');
  if (starBtn) {
    starBtn.onclick = async (e) => {
      e.stopPropagation();
      const nextStar = !mail.is_starred;
      mail.is_starred = nextStar;
      starBtn.classList.toggle('active', nextStar);
      const starIcon = starBtn.querySelector('.icon');
      if (nextStar) {
        starIcon.setAttribute('fill', 'currentColor');
      } else {
        starIcon.setAttribute('fill', 'none');
      }
      await fetch('/api/mails/batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email_ids: [mail.id], action: nextStar ? 'star' : 'unstar' })
      });
    };
  }

  // 卡片点击查看详情
  card.addEventListener('click', () => {
    document.querySelectorAll('.mail-card').forEach(c => c.classList.remove('selected'));
    card.classList.add('selected');

    // 乐观消除未读红点并扣减账号未读数字
    if (!mail.is_read) {
      mail.is_read = true;
      card.classList.remove('unread');
      const dot = card.querySelector('.unread-indicator-dot');
      if (dot) dot.remove();
      decrementAccountUnread(mail.account_id);
    }

    loadMailDetail(mail.id, mail);
  });

  return card;
}

// --- 加载邮件列表 (经典 Gmail 分页模式) ---
async function loadEmails(page = 1) {
  if (isLoadingMails) return;
  isLoadingMails = true;
  currentPage = page;

  const listContainer = document.getElementById('mail-list-container');
  listContainer.innerHTML = '<div style="padding: 28px; text-align: center; color: var(--text-muted); font-size: 13px;">加载中...</div>';

  const params = new URLSearchParams({
    view: currentView,
    page: currentPage,
    page_size: PAGE_SIZE
  });

  if (currentAccountId) params.append('account_id', currentAccountId);
  if (currentSearchQuery) params.append('q', currentSearchQuery);

  try {
    const res = await fetch(`/api/mails?${params.toString()}`);
    if (!res.ok) throw new Error('Failed to load emails');
    const data = await res.json();

    currentTotalMails = data.total || 0;
    currentMails = data.items || [];

    const unreadEl = document.getElementById('badge-total-unread');
    if (unreadEl) unreadEl.textContent = data.unread_total || 0;

    renderMailList(currentMails);
    updatePaginationControls();
    updateListTitleAndCounter();
    updateRemoteHistoryBtn();
    listContainer.scrollTop = 0;
  } catch (err) {
    listContainer.innerHTML = '<div style="padding: 28px; text-align: center; color: var(--danger); font-size: 13px;">加载邮件失败，请点击刷新重试</div>';
  } finally {
    isLoadingMails = false;
  }
}

function renderMailList(items) {
  const container = document.getElementById('mail-list-container');
  container.innerHTML = '';

  if (!items || items.length === 0) {
    container.innerHTML = '<div style="padding: 40px; text-align: center; color: var(--text-muted); font-size: 13.5px;">暂无匹配邮件</div>';
    return;
  }

  items.forEach(mail => {
    container.appendChild(createMailCard(mail));
  });
}

// --- 更新经典 Gmail 翻页控件 (1–50 / 758) ---
function updatePaginationControls() {
  const total = currentTotalMails;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  
  const start = total === 0 ? 0 : (currentPage - 1) * PAGE_SIZE + 1;
  const end = Math.min(currentPage * PAGE_SIZE, total);
  const pageText = `${start}–${end} / ${total}`;

  // 顶栏与底栏翻页文本更新
  const topText = document.getElementById('pagination-top-text');
  const bottomText = document.getElementById('pagination-bottom-text');
  if (topText) topText.textContent = pageText;
  if (bottomText) bottomText.textContent = pageText;

  // 上下翻页按钮禁用状态更新
  const hasPrev = currentPage > 1;
  const hasNext = currentPage < totalPages;

  const btnPrevTop = document.getElementById('btn-page-prev-top');
  const btnNextTop = document.getElementById('btn-page-next-top');
  const btnPrevBottom = document.getElementById('btn-page-prev-bottom');
  const btnNextBottom = document.getElementById('btn-page-next-bottom');

  if (btnPrevTop) btnPrevTop.disabled = !hasPrev;
  if (btnNextTop) btnNextTop.disabled = !hasNext;
  if (btnPrevBottom) btnPrevBottom.disabled = !hasPrev;
  if (btnNextBottom) btnNextBottom.disabled = !hasNext;
}

function updateListTitleAndCounter() {
  let baseTitle = '收件箱';
  if (currentAccountId) {
    const acc = accountsData.find(a => a.id == currentAccountId);
    baseTitle = acc ? acc.name : '邮箱账户';
  } else {
    const activeNav = document.querySelector('.sidebar .nav-item.active[data-view]');
    if (activeNav) {
      const textSpan = activeNav.querySelector('.nav-item-text');
      if (textSpan) baseTitle = textSpan.textContent.trim();
    }
  }

  const listTitle = document.getElementById('list-header-title') || document.getElementById('mobile-header-title');
  if (listTitle) listTitle.textContent = baseTitle;
}

// --- 更新底部远端历史拉取按钮状态 ---
function updateRemoteHistoryBtn() {
  const remoteCheckBtn = document.getElementById('btn-check-remote-history');
  const textSpan = document.getElementById('remote-history-text');
  if (!remoteCheckBtn || !textSpan) return;

  if (currentAccountId) {
    const acc = accountsData.find(a => a.id == currentAccountId);
    const runtimeStatus = accountHistoryStatus[currentAccountId];

    if (acc && (acc.history_exhausted || (runtimeStatus && runtimeStatus.hasMore === false))) {
      textSpan.textContent = '历史已完整';
      remoteCheckBtn.disabled = true;
      remoteCheckBtn.classList.add('disabled');
      return;
    }

    if (runtimeStatus && runtimeStatus.remaining !== undefined) {
      textSpan.textContent = `更早历史 (余 ${runtimeStatus.remaining})`;
      remoteCheckBtn.disabled = false;
      remoteCheckBtn.classList.remove('disabled');
      return;
    }
  } else {
    // "所有邮箱" 模式：如果所有绑定的活跃邮箱都已拉完整
    const allExhausted = accountsData.length > 0 && accountsData.every(a => {
      const st = accountHistoryStatus[a.id];
      return a.history_exhausted || (st && st.hasMore === false);
    });

    if (allExhausted) {
      textSpan.textContent = '历史已完整';
      remoteCheckBtn.disabled = true;
      remoteCheckBtn.classList.add('disabled');
      return;
    }
  }

  textSpan.textContent = '更早历史';
  remoteCheckBtn.disabled = false;
  remoteCheckBtn.classList.remove('disabled');
}

// --- 邮件详情查看 ---
let activeLoadingMailId = null;

// 即时/统一渲染邮件头部信息 (标题、发件人、日期、标星等)
function renderMailDetailHeader(meta) {
  if (!meta) return;

  // 1. 标题立即更新 (无须等待正文网络请求)
  document.getElementById('detail-subject').textContent = meta.subject || '(无主题)';

  // 2. 发件人姓名与地址
  const senderName = meta.from_name || meta.from_address || '未知发件人';
  document.getElementById('detail-from-name').textContent = senderName;
  document.getElementById('detail-from-address').textContent = meta.from_address ? `<${meta.from_address}>` : '';

  // 3. 邮件日期
  if (meta.date) {
    document.getElementById('detail-date').textContent = new Date(meta.date).toLocaleString('zh-CN');
  } else {
    document.getElementById('detail-date').textContent = '';
  }

  // 4. 发件人头像首字母
  const avatarLetter = (senderName || 'M')[0].toUpperCase();
  document.getElementById('detail-avatar').textContent = avatarLetter;

  // 5. 标星状态
  const starBtn = document.getElementById('btn-detail-star');
  if (starBtn) {
    starBtn.classList.toggle('active', !!meta.is_starred);
    const starIcon = starBtn.querySelector('.icon-star');
    if (starIcon) {
      starIcon.setAttribute('fill', meta.is_starred ? 'currentColor' : 'none');
    }
  }

  // 6. 附件指示角标
  const attTag = document.getElementById('detail-has-att');
  if (attTag) {
    const hasAtt = meta.attachments ? meta.attachments.length > 0 : !!meta.has_attachments;
    attTag.style.display = hasAtt ? 'inline-flex' : 'none';
  }
}

async function loadMailDetail(mailId, initialMeta = null) {
  activeLoadingMailId = mailId;

  const detailPanel = document.getElementById('mail-detail-panel');
  detailPanel.classList.add('active');
  detailPanel.scrollTop = 0;

  document.getElementById('detail-empty-state').style.display = 'none';
  const contentWrapper = document.getElementById('detail-content-wrapper');
  contentWrapper.style.display = 'flex';

  // 1. 优先使用列表已有元数据即时渲染头部，告别等待
  const meta = initialMeta || currentMails.find(m => m.id === mailId);
  if (meta) {
    currentMailDetail = { ...meta };
    renderMailDetailHeader(meta);
  }

  // 清空/隐藏旧邮件的附件列表（待详情接口返回完整附件结构）
  const attBox = document.getElementById('detail-attachments-box');
  if (attBox) {
    attBox.style.display = 'none';
    attBox.innerHTML = '';
  }

  // 2. 正文区域展示优雅加载状态
  const bodyContainer = document.getElementById('detail-body-container');
  bodyContainer.scrollTop = 0;
  bodyContainer.innerHTML = `
    <div class="mail-body-loading">
      <div class="mail-loading-spinner"></div>
      <span>正在载入邮件正文并同步状态...</span>
    </div>
  `;

  try {
    const res = await fetch(`/api/mails/${mailId}`);
    if (!res.ok) throw new Error('Load detail failed');
    const data = await res.json();

    // 检查是否仍是当前所选邮件，避免快速连点时的网络竞态冲突
    if (activeLoadingMailId !== mailId) return;

    currentMailDetail = data;

    // 1. 同步内存中列表对应邮件对象的状态
    const targetMail = currentMails.find(m => m.id === mailId);
    if (targetMail) {
      targetMail.has_body = true;
      targetMail.is_read = true;
      if (data.snippet) targetMail.snippet = data.snippet;
    }

    // 2. 及时消除当前卡片的“待载入”微标，并更新正文摘要
    const cardEl = document.querySelector(`.mail-card[data-id="${mailId}"]`);
    if (cardEl) {
      const pendingTag = cardEl.querySelector('.mail-pending-body-tag');
      if (pendingTag) {
        pendingTag.style.transition = 'opacity 0.25s ease, transform 0.25s ease';
        pendingTag.style.opacity = '0';
        pendingTag.style.transform = 'scale(0.8)';
        setTimeout(() => pendingTag.remove(), 250);
      }
      if (data.snippet) {
        const snippetEl = cardEl.querySelector('.mail-card-snippet');
        if (snippetEl && !snippetEl.textContent.trim()) {
          snippetEl.textContent = data.snippet;
        }
      }
    }

    // 3. 静默在后台对齐账户真实未读数
    loadAccounts();

    // 完整数据到达后，再次刷新头部（同步可能更新的标星、发件人全称等）
    renderMailDetailHeader(currentMailDetail);

    // 附件展示 (沉底渲染，正文优先)
    const attTag = document.getElementById('detail-has-att');
    if (currentMailDetail.attachments && currentMailDetail.attachments.length > 0) {
      if (attTag) attTag.style.display = 'inline-flex';
      attBox.style.display = 'flex';
      attBox.innerHTML = `
        <div class="attachments-header">
          <svg class="icon" style="width:14px;height:14px;" viewBox="0 0 24 24"><path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>
          <span>附件列表 (${currentMailDetail.attachments.length} 个)</span>
        </div>
        <div class="attachments-list"></div>
      `;
      const listEl = attBox.querySelector('.attachments-list');
      currentMailDetail.attachments.forEach((att, idx) => {
        const link = document.createElement('a');
        link.className = 'attachment-pill';
        link.href = `/api/mails/${mailId}/attachment/${idx}`;
        link.target = '_blank';
        link.innerHTML = `
          <svg class="icon" style="width:13px;height:13px;" viewBox="0 0 24 24"><path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>
          <span>${escapeHtml(att.filename)}</span>
          <small style="color:var(--text-muted)">(${formatBytes(att.size)})</small>
        `;
        listEl.appendChild(link);
      });
    } else {
      if (attTag) attTag.style.display = 'none';
      attBox.style.display = 'none';
    }

    // HTML 正文渲染（使用 Shadow DOM 彻底隔离邮件自带的全局 CSS，杜绝 h1 / body 等外部样式污染主界面）
    bodyContainer.classList.remove('paper-light');
    bodyContainer.innerHTML = '<div id="mail-shadow-host"></div>';
    const shadowHost = document.getElementById('mail-shadow-host');
    const shadow = shadowHost.attachShadow({ mode: 'open' });

    const baseShadowStyle = `
      <style>
        :host {
          display: block;
          font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
          color: inherit;
          line-height: 1.6;
          word-break: break-word;
        }
        img { max-width: 100% !important; height: auto !important; }
        a { color: #1a73e8; }
      </style>
    `;

    shadow.innerHTML = baseShadowStyle + (currentMailDetail.html_body || `<pre style="font-family:inherit; white-space:pre-wrap;">${escapeHtml(currentMailDetail.text_body)}</pre>`);

    // 确保邮件内所有链接均在新标签页安全打开
    shadow.querySelectorAll('a').forEach(a => {
      if (!a.getAttribute('target')) a.setAttribute('target', '_blank');
      a.setAttribute('rel', 'noopener noreferrer');
    });

  } catch (e) {
    if (activeLoadingMailId === mailId) {
      showToast('加载邮件详情失败', 'error');
    }
  }
}

// --- 账户弹窗控制（新建与编辑） ---
function openAddAccountModal() {
  document.getElementById('account-modal-title').textContent = '绑定 IMAP 邮箱账户';
  document.getElementById('form-account').reset();
  document.getElementById('acc-id').value = '';
  document.getElementById('acc-password').required = true;
  document.getElementById('btn-delete-account').style.display = 'none';
  document.getElementById('modal-account').classList.add('active');
}

function openEditAccountModal(acc) {
  document.getElementById('account-modal-title').textContent = `编辑邮箱账户 - ${acc.name}`;
  document.getElementById('acc-id').value = acc.id;
  document.getElementById('acc-name').value = acc.name;
  document.getElementById('acc-email').value = acc.email;
  document.getElementById('acc-color').value = acc.color;
  document.getElementById('acc-server').value = acc.imap_server;
  document.getElementById('acc-port').value = acc.imap_port;
  document.getElementById('acc-username').value = acc.username;
  document.getElementById('acc-password').value = '';
  document.getElementById('acc-password').required = false;
  document.getElementById('acc-folder').value = acc.folder;
  document.getElementById('acc-ssl').checked = acc.use_ssl;
  document.getElementById('acc-sync-read').checked = acc.sync_read_remote;
  document.getElementById('acc-sync-del').checked = acc.sync_delete_remote;
  document.getElementById('btn-delete-account').style.display = 'block';
  document.getElementById('modal-account').classList.add('active');
}

function closeModal(modalId) {
  const modal = document.getElementById(modalId);
  if (modal) modal.classList.remove('active');
}

// --- 事件监听与初始化绑定 ---
document.addEventListener('DOMContentLoaded', () => {
  initTheme();
  initSidebar();
  checkAuthAndLoadInitialData();

  // 汉堡菜单按钮：收拢/展开侧边栏
  const toggleSidebarBtn = document.getElementById('btn-toggle-sidebar');
  if (toggleSidebarBtn) {
    toggleSidebarBtn.addEventListener('click', toggleSidebar);
  }

  // Logo 点击：重置到第一页收件箱
  const brandLogo = document.getElementById('brand-logo');
  if (brandLogo) {
    brandLogo.addEventListener('click', () => {
      currentView = 'inbox';
      currentAccountId = null;
      currentSearchQuery = '';
      const searchInput = document.getElementById('search-input');
      if (searchInput) searchInput.value = '';
      document.querySelectorAll('.sidebar .nav-item').forEach(el => el.classList.remove('active'));
      document.querySelectorAll('.sidebar .account-item').forEach(el => el.classList.remove('active'));
      const inboxNav = document.querySelector('.sidebar .nav-item[data-view="inbox"]');
      if (inboxNav) inboxNav.classList.add('active');
      loadEmails(1);
    });
  }

  // 移动端菜单按钮
  const mobileMenuBtn = document.getElementById('btn-mobile-menu');
  if (mobileMenuBtn) {
    mobileMenuBtn.addEventListener('click', toggleSidebar);
  }

  const backdrop = document.getElementById('sidebar-backdrop');
  if (backdrop) {
    backdrop.addEventListener('click', closeMobileSidebarAndDetail);
  }

  // 主题切换
  const themeBtn = document.getElementById('btn-toggle-theme');
  if (themeBtn) {
    themeBtn.addEventListener('click', toggleTheme);
  }

  // 搜索框输入与防抖
  const searchInput = document.getElementById('search-input');
  const clearSearchBtn = document.getElementById('btn-clear-search');
  let searchTimer = null;

  if (searchInput) {
    searchInput.addEventListener('input', (e) => {
      clearTimeout(searchTimer);
      const val = e.target.value.trim();
      if (clearSearchBtn) {
        clearSearchBtn.style.display = val ? 'flex' : 'none';
      }
      searchTimer = setTimeout(() => {
        currentSearchQuery = val;
        loadEmails(1);
      }, 350);
    });
  }

  if (clearSearchBtn) {
    clearSearchBtn.addEventListener('click', () => {
      searchInput.value = '';
      clearSearchBtn.style.display = 'none';
      currentSearchQuery = '';
      loadEmails(1);
    });
  }

  // 导航视图切换
  document.querySelectorAll('.sidebar .nav-item[data-view]').forEach(item => {
    item.addEventListener('click', () => {
      document.querySelectorAll('.sidebar .nav-item').forEach(el => el.classList.remove('active'));
      document.querySelectorAll('.sidebar .account-item').forEach(el => el.classList.remove('active'));
      item.classList.add('active');
      currentView = item.dataset.view;
      currentAccountId = null;
      closeMobileSidebarAndDetail();
      loadEmails(1);
      updateRemoteHistoryBtn();
    });
  });

  // 全量即时同步所有邮箱（已移动至设置弹窗，并增加二次确认与防误触保护）
  const syncAllBtn = document.getElementById('btn-sync-all');
  if (syncAllBtn) {
    syncAllBtn.addEventListener('click', async () => {
      if (!confirm('全量同步将同时连接所有已绑定的邮箱服务器检查新邮件，确定执行吗？')) return;
      syncAllBtn.disabled = true;
      const textEl = document.getElementById('btn-sync-all-text');
      const originalText = textEl ? textEl.textContent : '';
      if (textEl) textEl.textContent = '同步触发中...';
      showToast('正在向各邮箱服务器触发增量同步...', 'info');
      try {
        await fetch('/api/accounts/sync-all', { method: 'POST' });
        setTimeout(loadAccounts, 1500);
        setTimeout(() => loadEmails(1), 2500);
      } catch (err) {
        showToast('同步请求失败', 'error');
      } finally {
        setTimeout(() => {
          syncAllBtn.disabled = false;
          if (textEl) textEl.textContent = originalText;
        }, 3000);
      }
    });
  }

  // 刷新按钮 (顶栏、移动端)
  const handleRefresh = async () => {
    const btn = document.getElementById('btn-refresh-list');
    if (btn) {
      btn.style.transform = 'rotate(360deg)';
      btn.style.transition = 'transform 0.5s ease';
    }
    try {
      if (currentAccountId) {
        fetch(`/api/accounts/${currentAccountId}/sync`, { method: 'POST' }).catch(() => {});
      } else {
        fetch('/api/accounts/sync-all', { method: 'POST' }).catch(() => {});
      }
      await loadEmails(currentPage);
    } finally {
      setTimeout(() => {
        if (btn) {
          btn.style.transition = 'none';
          btn.style.transform = 'none';
        }
      }, 500);
    }
  };
  document.getElementById('btn-refresh-list').addEventListener('click', handleRefresh);
  const mobileRefresh = document.getElementById('btn-refresh-list-mobile');
  if (mobileRefresh) mobileRefresh.addEventListener('click', handleRefresh);

  // 标记当前页为已读
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
    showToast(`已将当前页 ${ids.length} 封邮件标记为已读`, 'success');
    await loadEmails(currentPage);
    await loadAccounts();
  });

  // Gmail 经典翻页按钮事件绑定 (顶部与底部)
  const bindPageNav = (prevBtnId, nextBtnId) => {
    const prevBtn = document.getElementById(prevBtnId);
    const nextBtn = document.getElementById(nextBtnId);
    if (prevBtn) {
      prevBtn.addEventListener('click', () => {
        if (currentPage > 1) loadEmails(currentPage - 1);
      });
    }
    if (nextBtn) {
      nextBtn.addEventListener('click', () => {
        const totalPages = Math.max(1, Math.ceil(currentTotalMails / PAGE_SIZE));
        if (currentPage < totalPages) loadEmails(currentPage + 1);
      });
    }
  };
  bindPageNav('btn-page-prev-top', 'btn-page-next-top');
  bindPageNav('btn-page-prev-bottom', 'btn-page-next-bottom');

  // 检查远端更早历史 (IMAP 单次批量拉取)
  const remoteCheckBtn = document.getElementById('btn-check-remote-history');
  if (remoteCheckBtn) {
    remoteCheckBtn.addEventListener('click', async () => {
      remoteCheckBtn.disabled = true;
      const textSpan = document.getElementById('remote-history-text');
      if (textSpan) textSpan.textContent = '正在拉取...';

      try {
        const url = currentAccountId
          ? `/api/accounts/${currentAccountId}/fetch-more-history`
          : `/api/accounts/fetch-more-history-all`;

        const res = await fetch(url, { method: 'POST' });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || '检测失败');

        if (currentAccountId) {
          accountHistoryStatus[currentAccountId] = {
            hasMore: data.has_more,
            remaining: data.remaining
          };
          if (!data.has_more) {
            const acc = accountsData.find(a => a.id == currentAccountId);
            if (acc) acc.history_exhausted = true;
          }
        }

        if (data.fetched > 0) {
          showToast(`已从服务器拉取 ${data.fetched} 封更早历史邮件`, 'success');
          await loadEmails(1);
        } else {
          showToast(data.message || '远程邮件服务器上已无更早的历史邮件', 'info');
        }
      } catch (e) {
        showToast(`检测失败: ${e.message}`, 'error');
      } finally {
        updateRemoteHistoryBtn();
      }
    });
  }

  // 邮件详情操作按钮
  const starDetailBtn = document.getElementById('btn-detail-star');
  if (starDetailBtn) {
    starDetailBtn.addEventListener('click', async () => {
      if (!currentMailDetail) return;
      const nextStar = !currentMailDetail.is_starred;
      currentMailDetail.is_starred = nextStar;
      starDetailBtn.classList.toggle('active', nextStar);
      const starIcon = starDetailBtn.querySelector('.icon-star');
      if (starIcon) starIcon.setAttribute('fill', nextStar ? 'currentColor' : 'none');
      await fetch('/api/mails/batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email_ids: [currentMailDetail.id], action: nextStar ? 'star' : 'unstar' })
      });
      showToast(nextStar ? '已标星' : '已取消标星', 'info');
      loadEmails(currentPage);
    });
  }

  const unreadDetailBtn = document.getElementById('btn-detail-unread');
  if (unreadDetailBtn) {
    unreadDetailBtn.addEventListener('click', async () => {
      if (!currentMailDetail) return;
      await fetch('/api/mails/batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email_ids: [currentMailDetail.id], action: 'unread' })
      });
      showToast('已标记为未读', 'info');
      closeMobileSidebarAndDetail();
      loadEmails(currentPage);
      loadAccounts();
    });
  }

  const trashDetailBtn = document.getElementById('btn-detail-trash');
  if (trashDetailBtn) {
    trashDetailBtn.addEventListener('click', async () => {
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
      loadAccounts();
    });
  }

  const paperModeBtn = document.getElementById('btn-detail-paper-mode');
  if (paperModeBtn) {
    paperModeBtn.addEventListener('click', () => {
      const container = document.getElementById('detail-body-container');
      const isLight = container.classList.toggle('paper-light');
      showToast(isLight ? '已切换至纯白信纸原貌' : '已切换至深色信纸', 'info');
    });
  }

  document.getElementById('btn-detail-download-eml').addEventListener('click', () => {
    if (currentMailDetail) {
      window.open(`/api/mails/${currentMailDetail.id}/eml`, '_blank');
    }
  });

  const backToListBtn = document.getElementById('btn-back-to-list');
  if (backToListBtn) {
    backToListBtn.addEventListener('click', () => {
      document.getElementById('mail-detail-panel').classList.remove('active');
    });
  }

  const detailOpenSidebarBtn = document.getElementById('btn-detail-open-sidebar');
  if (detailOpenSidebarBtn) {
    detailOpenSidebarBtn.addEventListener('click', toggleSidebar);
  }

  // 添加账户按钮
  document.getElementById('btn-add-account').addEventListener('click', openAddAccountModal);

  // 删除账户
  document.getElementById('btn-delete-account').addEventListener('click', async () => {
    const accId = document.getElementById('acc-id').value;
    const accName = document.getElementById('acc-name').value;
    if (!accId) return;

    const confirmed = confirm(`确定要解绑邮箱账户「${accName}」吗？\n注意：此操作将清空本地归档的所有该邮箱邮件！`);
    if (!confirmed) return;

    try {
      const res = await fetch(`/api/accounts/${accId}`, { method: 'DELETE' });
      if (!res.ok) throw new Error('Delete account failed');
      showToast(`已成功解绑并清理「${accName}」`, 'success');
      closeModal('modal-account');
      currentAccountId = null;
      await loadAccounts();
      await loadEmails(1);
    } catch (e) {
      showToast(`删除失败: ${e.message}`, 'error');
    }
  });

  // 测试账户连接
  document.getElementById('btn-test-account').addEventListener('click', async () => {
    const btn = document.getElementById('btn-test-account');
    const originalText = btn.textContent;
    btn.disabled = true;
    btn.textContent = '测试中...';

    const payload = {
      account_id: document.getElementById('acc-id').value ? parseInt(document.getElementById('acc-id').value) : null,
      imap_server: document.getElementById('acc-server').value,
      imap_port: parseInt(document.getElementById('acc-port').value),
      use_ssl: document.getElementById('acc-ssl').checked,
      username: document.getElementById('acc-username').value,
      password: document.getElementById('acc-password').value || null
    };

    try {
      const res = await fetch('/api/accounts/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (res.ok && data.success) {
        showToast(data.message || '连接与认证成功！', 'success');
      } else {
        showToast(`连接失败: ${data.detail || data.error}`, 'error');
      }
    } catch (e) {
      showToast(`连接异常: ${e.message}`, 'error');
    } finally {
      btn.disabled = false;
      btn.textContent = originalText;
    }
  });

  // 保存账户表单提交
  document.getElementById('form-account').addEventListener('submit', async (e) => {
    e.preventDefault();
    const accId = document.getElementById('acc-id').value;
    const saveBtn = document.getElementById('btn-save-account');
    saveBtn.disabled = true;

    const payload = {
      name: document.getElementById('acc-name').value.trim(),
      email: document.getElementById('acc-email').value.trim(),
      color: document.getElementById('acc-color').value,
      imap_server: document.getElementById('acc-server').value.trim(),
      imap_port: parseInt(document.getElementById('acc-port').value),
      use_ssl: document.getElementById('acc-ssl').checked,
      username: document.getElementById('acc-username').value.trim(),
      folder: document.getElementById('acc-folder').value.trim() || 'INBOX',
      sync_read_remote: document.getElementById('acc-sync-read').checked,
      sync_delete_remote: document.getElementById('acc-sync-del').checked
    };

    const passwordVal = document.getElementById('acc-password').value;
    if (passwordVal) {
      payload.password = passwordVal;
    }

    try {
      let res;
      if (accId) {
        res = await fetch(`/api/accounts/${accId}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
      } else {
        res = await fetch('/api/accounts', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
      }

      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || '保存失败');
      }

      showToast('邮箱配置已成功保存！', 'success');
      closeModal('modal-account');
      await loadAccounts();
      await loadEmails(1);
    } catch (err) {
      showToast(err.message, 'error');
    } finally {
      saveBtn.disabled = false;
    }
  });

  // 设置模态窗选项卡切换
  const settingsTabBtns = document.querySelectorAll('#settings-tabs .modal-tab-btn');
  settingsTabBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      const target = btn.dataset.tab;
      settingsTabBtns.forEach(b => b.classList.toggle('active', b === btn));
      document.querySelectorAll('#modal-settings .modal-tab-panel').forEach(panel => {
        panel.classList.toggle('active', panel.id === `tab-panel-${target}`);
      });
      if (target === 'telegram') {
        loadTelegramConfig();
      }
    });
  });

  // 设置模态窗打开
  document.getElementById('btn-settings').addEventListener('click', async () => {
    document.getElementById('modal-settings').classList.add('active');
    await Promise.all([loadTotpStatus(), loadTelegramConfig()]);
  });

  // Telegram 表单保存
  const tgForm = document.getElementById('form-telegram-settings');
  if (tgForm) {
    tgForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const saveBtn = document.getElementById('btn-save-telegram');
      const originalText = saveBtn.textContent;
      saveBtn.disabled = true;
      saveBtn.textContent = '保存中...';

      const payload = {
        bot_token: document.getElementById('tg-bot-token').value.trim(),
        allowed_chat_ids: document.getElementById('tg-chat-id').value.trim(),
        api_base: document.getElementById('tg-api-base').value.trim() || 'https://api.telegram.org'
      };

      try {
        const res = await fetch('/api/telegram/config', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (res.ok && data.success) {
          showToast(data.message || 'Telegram 配置已保存并即时生效', 'success');
          await loadTelegramConfig();
        } else {
          showToast(data.detail || '保存失败', 'error');
        }
      } catch (err) {
        showToast('网络请求失败', 'error');
      } finally {
        saveBtn.disabled = false;
        saveBtn.textContent = originalText;
      }
    });
  }

  // Telegram 测试推送
  const testTgBtn = document.getElementById('btn-test-telegram');
  if (testTgBtn) {
    testTgBtn.addEventListener('click', async () => {
      const textSpan = document.getElementById('btn-test-telegram-text');
      const originalText = textSpan ? textSpan.textContent : '发送测试消息';
      testTgBtn.disabled = true;
      if (textSpan) textSpan.textContent = '正在发送...';

      const botToken = document.getElementById('tg-bot-token').value.trim();
      const chatId = document.getElementById('tg-chat-id').value.trim();
      const apiBase = document.getElementById('tg-api-base').value.trim();

      try {
        const res = await fetch('/api/telegram/test', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            bot_token: botToken || null,
            chat_id: chatId || null,
            api_base: apiBase || null
          })
        });
        const data = await res.json();
        if (res.ok && data.success) {
          showToast(data.message || '测试消息已成功下发至 Telegram！', 'success');
        } else {
          showToast(`下发失败: ${data.message || data.detail || '未知错误'}`, 'error');
        }
      } catch (e) {
        showToast(`发送出错: ${e.message}`, 'error');
      } finally {
        testTgBtn.disabled = false;
        if (textSpan) textSpan.textContent = originalText;
      }
    });
  }

  // 登出
  document.getElementById('btn-logout').addEventListener('click', async () => {
    if (confirm('确定要退出当前管理会话吗？')) {
      await fetch('/api/auth/logout', { method: 'POST' });
      window.location.href = '/login';
    }
  });

  // 通用模态窗关闭
  document.querySelectorAll('.modal-close-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.modal-backdrop').forEach(m => m.classList.remove('active'));
    });
  });
});

// --- TOTP 2FA 相关辅助 ---
async function loadTotpStatus() {
  try {
    const res = await fetch('/api/auth/me');
    if (!res.ok) return;
    const user = await res.json();
    const statusText = document.getElementById('totp-status-text');
    const manageBtn = document.getElementById('btn-manage-totp');
    const setupArea = document.getElementById('totp-setup-area');

    const isEnabled = !!(user.is_totp_enabled ?? user.totp_enabled);
    if (isEnabled) {
      statusText.textContent = '两步验证已启用 (受保护状态)';
      statusText.style.color = 'var(--success)';
      manageBtn.textContent = '关闭 2FA';
      manageBtn.onclick = disableTotp;
      setupArea.style.display = 'none';
    } else {
      statusText.textContent = '两步验证未开启';
      statusText.style.color = 'var(--text-muted)';
      manageBtn.textContent = '配置 2FA';
      manageBtn.onclick = startSetupTotp;
    }
  } catch (e) {}
}

async function startSetupTotp() {
  try {
    const res = await fetch('/api/auth/setup-totp', { method: 'POST' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || '获取 2FA 配置失败');

    const qrSrc = data.qr_code_data_url || data.qr_uri;
    const qrImg = document.getElementById('totp-qr-img');
    if (qrImg && qrSrc) {
      qrImg.src = qrSrc;
    }

    const secretText = document.getElementById('totp-secret-text');
    if (secretText) {
      secretText.textContent = data.secret || '';
    }

    const copyBtn = document.getElementById('btn-copy-totp-secret');
    if (copyBtn) {
      copyBtn.onclick = () => {
        if (!data.secret) return;
        navigator.clipboard.writeText(data.secret).then(() => {
          showToast('密钥已复制到剪贴板', 'success');
        }).catch(() => {
          showToast('请手动复制密钥', 'info');
        });
      };
    }

    const verifyInput = document.getElementById('totp-verify-input');
    if (verifyInput) {
      verifyInput.value = '';
    }

    document.getElementById('totp-setup-area').style.display = 'block';

    document.getElementById('btn-confirm-totp').onclick = async () => {
      const rawCode = document.getElementById('totp-verify-input').value.trim();
      const code = rawCode.replace(/\s+/g, '');
      if (!code || code.length !== 6) {
        showToast('请输入 6 位有效动态口令', 'error');
        return;
      }
      const verifyRes = await fetch('/api/auth/verify-totp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ secret: data.secret, code })
      });
      const verifyData = await verifyRes.json();
      if (verifyRes.ok) {
        showToast('两步验证配置成功！', 'success');
        await loadTotpStatus();
      } else {
        showToast(verifyData.detail || '验证码不正确，请重新输入', 'error');
      }
    };
  } catch (e) {
    showToast(e.message || '获取 2FA 配置失败', 'error');
  }
}

async function disableTotp() {
  const code = prompt('请输入当前的 6 位动态口令以确认关闭 2FA：');
  if (!code) return;
  const cleanCode = code.trim().replace(/\s+/g, '');
  try {
    const res = await fetch('/api/auth/disable-totp', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code: cleanCode })
    });
    const data = await res.json();
    if (res.ok) {
      showToast('两步验证已关闭', 'info');
      await loadTotpStatus();
    } else {
      showToast(data.detail || '口令错误，关闭失败', 'error');
    }
  } catch (e) {
    showToast('网络错误，关闭 2FA 失败', 'error');
  }
}

// --- Telegram 配置读取与状态 ---
async function loadTelegramConfig() {
  try {
    const res = await fetch('/api/telegram/config');
    if (!res.ok) return;
    const data = await res.json();
    const tokenInput = document.getElementById('tg-bot-token');
    const chatIdInput = document.getElementById('tg-chat-id');
    const apiBaseInput = document.getElementById('tg-api-base');
    const badge = document.getElementById('tg-status-badge');

    if (tokenInput && !tokenInput.value) tokenInput.value = data.bot_token || '';
    if (chatIdInput && !chatIdInput.value) chatIdInput.value = data.allowed_chat_ids || '';
    if (apiBaseInput && !apiBaseInput.value) apiBaseInput.value = data.api_base || 'https://api.telegram.org';

    if (badge) {
      if (data.is_configured) {
        badge.textContent = '● 已配置运行中';
        badge.style.background = 'rgba(20, 108, 46, 0.12)';
        badge.style.color = 'var(--success)';
      } else {
        badge.textContent = '○ 未配置';
        badge.style.background = 'var(--bg-hover)';
        badge.style.color = 'var(--text-muted)';
      }
    }
  } catch (e) {}
}

// --- 通用辅助工具函数 ---
function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.textContent = message;

  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transition = 'opacity 0.25s ease';
    setTimeout(() => toast.remove(), 250);
  }, 2600);
}

function escapeHtml(str) {
  if (!str) return '';
  return str.replace(/[&<>"']/g, m => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#039;'
  })[m]);
}

function formatMailDate(isoStr) {
  if (!isoStr) return '';
  const d = new Date(isoStr);
  const now = new Date();
  if (d.toDateString() === now.toDateString()) {
    return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
  }
  return `${d.getMonth() + 1}月${d.getDate()}日`;
}

function formatBytes(bytes) {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

// --- 窗口切回前台或轻量定时对齐账号未读状态 ---
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') {
    loadAccounts();
  }
});

// 每 60 秒轻量静默对齐一次各账户未读数
setInterval(() => {
  if (document.visibilityState === 'visible') {
    loadAccounts();
  }
}, 60000);
