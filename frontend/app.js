/**
 * StudyMind — Grounded Study Assistant Frontend Logic
 * Implements Phase 6: Auth, Workspace/Library with Upload & Progress,
 * Grounded Chat with Verified Citations, and Synchronized Source Viewer with Bounding Box Overlay.
 */

// Configuration
const urlParams = typeof window !== 'undefined' ? new URLSearchParams(window.location.search) : null;
if (urlParams && urlParams.get('api')) {
  localStorage.setItem('studymind_api_base', urlParams.get('api').replace(/\/$/, ''));
}
const API_BASE = (typeof window !== 'undefined' && (window.__STUDYMIND_API_BASE__ || localStorage.getItem('studymind_api_base'))) || '/api/v1';

// Application State
const state = {
  token: localStorage.getItem('studymind_token') || null,
  user: null,
  workspaces: [],
  currentWorkspaceId: localStorage.getItem('studymind_ws_id') || null,
  conversations: [],
  currentConversationId: null,
  documents: [],
  currentViewerDocId: null,
  currentViewerPage: 1,
  currentViewerMaxPages: 1,
  viewerZoom: 1.0,
  activeCitation: null,
  strictMode: false,
};

// ============================================================================
// API Client
// ============================================================================

async function apiRequest(endpoint, options = {}) {
  const headers = options.headers || {};
  if (state.token) {
    headers['Authorization'] = `Bearer ${state.token}`;
  }
  if (!options.isFormData && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/json';
  }

  const config = {
    ...options,
    headers,
  };

  try {
    const res = await fetch(`${API_BASE}${endpoint}`, config);
    if (res.status === 401) {
      handleUnauthorized();
      throw new Error('Authentication expired or invalid');
    }
    if (res.status === 204) {
      return null;
    }
    const data = await res.json().catch(() => null);
    if (!res.ok) {
      const msg = data?.error?.message || data?.detail || `API error (${res.status})`;
      throw new Error(msg);
    }
    return data;
  } catch (err) {
    console.error(`API Error [${endpoint}]:`, err);
    throw err;
  }
}

// ============================================================================
// UI Utilities & Toasts
// ============================================================================

function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.innerHTML = `<span>${type === 'success' ? '✓' : type === 'error' ? '⚠' : 'ℹ'}</span> <span>${escapeHtml(message)}</span>`;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(10px)';
    setTimeout(() => toast.remove(), 300);
  }, 3500);
}

function escapeHtml(text) {
  if (!text) return '';
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

// ============================================================================
// Auth & Initial Setup
// ============================================================================

async function initApp() {
  bindEventListeners();

  if (state.token) {
    try {
      state.user = await apiRequest('/auth/me');
      state.isGuest = state.user?.email?.startsWith('guest_') || localStorage.getItem('studymind_is_guest') === 'true';
      updateUserNavUI();
      await loadWorkspaces();
      return;
    } catch {
      // Fallback to guest if token expired
    }
  }

  // Seamless Guest Mode: users can use the app without signing in
  await startGuestSession();
}

async function startGuestSession() {
  try {
    const res = await apiRequest('/auth/guest', { method: 'POST' });
    state.token = res.access_token;
    state.user = res.user;
    state.isGuest = true;
    localStorage.setItem('studymind_token', state.token);
    localStorage.setItem('studymind_is_guest', 'true');
    updateUserNavUI();
    showAuthModal(false);
    showToast('Active in Guest Mode. Upload documents & start studying!', 'info');
    await loadWorkspaces();
  } catch (err) {
    console.error('Failed to start guest session:', err);
    showAuthModal(true);
  }
}

function handleUnauthorized() {
  state.token = null;
  state.user = null;
  state.isGuest = false;
  localStorage.removeItem('studymind_token');
  localStorage.removeItem('studymind_is_guest');
  updateUserNavUI();
  startGuestSession();
}

function updateUserNavUI() {
  const badge = document.getElementById('user-profile-badge');
  const loginBtn = document.getElementById('btn-open-login');
  const emailText = document.getElementById('user-email-text');
  const roleBadge = document.getElementById('user-role-badge');
  const saveBtn = document.getElementById('btn-save-guest');

  if (state.user && state.token) {
    badge.classList.remove('hidden');
    loginBtn.classList.add('hidden');

    const isGuest = state.isGuest || state.user.email?.startsWith('guest_');
    if (isGuest) {
      if (roleBadge) {
        roleBadge.classList.remove('hidden');
        roleBadge.textContent = 'Guest';
      }
      if (saveBtn) saveBtn.classList.remove('hidden');
      emailText.textContent = 'Guest Session';
    } else {
      if (roleBadge) roleBadge.classList.add('hidden');
      if (saveBtn) saveBtn.classList.add('hidden');
      emailText.textContent = state.user.email;
    }
  } else {
    badge.classList.add('hidden');
    loginBtn.classList.remove('hidden');
    if (roleBadge) roleBadge.classList.add('hidden');
    if (saveBtn) saveBtn.classList.add('hidden');
  }
}

function showAuthModal(show) {
  const modal = document.getElementById('auth-modal');
  const errorEl = document.getElementById('auth-error-msg');
  if (errorEl) errorEl.classList.add('hidden');
  if (show) {
    modal.classList.remove('hidden');
  } else {
    modal.classList.add('hidden');
  }
}

// ============================================================================
// Workspace Management
// ============================================================================

async function loadWorkspaces() {
  try {
    const wsList = await apiRequest('/workspaces');
    state.workspaces = wsList || [];

    const select = document.getElementById('workspace-select');
    select.innerHTML = '';

    if (state.workspaces.length === 0) {
      // Auto-create default workspace
      const created = await apiRequest('/workspaces', {
        method: 'POST',
        body: JSON.stringify({ name: 'Default Study Workspace' }),
      });
      state.workspaces = [created];
    }

    state.workspaces.forEach((ws) => {
      const opt = document.createElement('option');
      opt.value = ws.id;
      opt.textContent = ws.name;
      select.appendChild(opt);
    });

    // Select active workspace
    const existing = state.workspaces.find((w) => w.id === state.currentWorkspaceId);
    if (existing) {
      select.value = existing.id;
    } else {
      select.value = state.workspaces[0].id;
      state.currentWorkspaceId = state.workspaces[0].id;
    }
    localStorage.setItem('studymind_ws_id', state.currentWorkspaceId);

    // Load workspace data
    await Promise.all([loadDocuments(), loadConversations()]);
  } catch (err) {
    showToast(`Failed to load workspaces: ${err.message}`, 'error');
  }
}

// ============================================================================
// Document Management & Ingestion
// ============================================================================

async function loadDocuments() {
  if (!state.currentWorkspaceId) return;
  try {
    const docs = await apiRequest(`/workspaces/${state.currentWorkspaceId}/documents`);
    state.documents = docs || [];

    const docCountBadge = document.getElementById('library-doc-count');
    if (docCountBadge) docCountBadge.textContent = state.documents.length;

    renderDocumentsTable();
  } catch (err) {
    console.error('Failed to load documents:', err);
  }
}

function renderDocumentsTable() {
  const tbody = document.getElementById('documents-table-body');
  if (!tbody) return;

  if (state.documents.length === 0) {
    tbody.innerHTML = `<tr><td colspan="5" class="table-empty">No documents uploaded yet. Upload course materials above to begin.</td></tr>`;
    return;
  }

  tbody.innerHTML = state.documents
    .map((doc) => {
      const ocrClass = doc.ocr_quality === 'good' ? 'good' : doc.ocr_quality === 'medium' ? 'medium' : 'low';
      const ocrLabel = doc.ocr_quality || 'N/A';
      const statusClass = doc.status === 'ready' ? 'ready' : doc.status === 'failed' ? 'failed' : 'queued';

      return `
      <tr data-doc-id="${doc.id}">
        <td>
          <div style="display:flex; align-items:center; gap:8px;">
            <span>📄</span>
            <span style="font-weight:600; max-width:200px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
              ${escapeHtml(doc.filename)}
            </span>
          </div>
        </td>
        <td>${doc.pages || 1} pages</td>
        <td><span class="badge-ocr ${ocrClass}">${ocrLabel}</span></td>
        <td><span class="badge-status ${statusClass}">${doc.status}</span></td>
        <td>
          <div style="display:flex; gap:6px;">
            <button class="btn-icon-sm btn-inspect-doc" data-doc-id="${doc.id}" data-pages="${doc.pages || 1}" title="View in Source Viewer">👁</button>
            <button class="btn-icon-sm btn-delete-doc" data-doc-id="${doc.id}" title="Delete document" style="color:var(--rose);">🗑</button>
          </div>
        </td>
      </tr>
    `;
    })
    .join('');

  // Attach row actions
  tbody.querySelectorAll('.btn-inspect-doc').forEach((btn) => {
    btn.addEventListener('click', () => {
      const docId = btn.getAttribute('data-doc-id');
      const pages = parseInt(btn.getAttribute('data-pages') || '1', 10);
      openSourceViewer(docId, 1, pages);
    });
  });

  tbody.querySelectorAll('.btn-delete-doc').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const docId = btn.getAttribute('data-doc-id');
      if (!confirm('Are you sure you want to delete this document?')) return;
      try {
        await apiRequest(`/documents/${docId}`, { method: 'DELETE' });
        showToast('Document deleted', 'info');
        await loadDocuments();
      } catch (err) {
        showToast(`Delete failed: ${err.message}`, 'error');
      }
    });
  });
}

async function handleMultipleFiles(files) {
  if (!files || files.length === 0) return;
  if (!state.currentWorkspaceId) {
    showToast('Please select a workspace first', 'error');
    return;
  }

  const fileList = Array.from(files);
  const total = fileList.length;

  const progressCard = document.getElementById('ingestion-progress-card');
  const progressDocName = document.getElementById('progress-doc-name');
  const progressFill = document.getElementById('progress-fill');
  const progressStage = document.getElementById('progress-stage-badge');
  const progressPercent = document.getElementById('progress-percent-text');

  if (progressCard) progressCard.classList.remove('hidden');

  let successCount = 0;
  let lastDocId = null;
  let lastPages = 1;

  for (let i = 0; i < total; i++) {
    const file = fileList[i];
    const itemNum = i + 1;
    const basePct = Math.round((i / total) * 100);

    if (progressDocName) progressDocName.textContent = `[${itemNum}/${total}] ${file.name}`;
    if (progressStage) progressStage.textContent = `uploading ${itemNum}/${total}`;
    if (progressFill) progressFill.style.width = `${basePct + 15}%`;
    if (progressPercent) progressPercent.textContent = `${basePct + 15}%`;

    try {
      const formData = new FormData();
      formData.append('file', file);

      // 1. Upload file
      const uploadRes = await apiRequest(`/workspaces/${state.currentWorkspaceId}/documents`, {
        method: 'POST',
        body: formData,
        isFormData: true,
      });

      const docId = uploadRes.document_id;
      lastDocId = docId;
      lastPages = uploadRes.pages || 1;

      if (progressStage) progressStage.textContent = `processing ${itemNum}/${total}`;
      if (progressFill) progressFill.style.width = `${Math.round(((i + 0.7) / total) * 100)}%`;

      // 2. Trigger ingestion pipeline
      try {
        await apiRequest(`/documents/${docId}/reprocess`, {
          method: 'POST',
          body: JSON.stringify({ force_vision_ocr: false }),
        });
      } catch {
        // In case worker takes over asynchronously
      }

      successCount++;
    } catch (err) {
      console.error(`Failed to upload ${file.name}:`, err);
      showToast(`Upload failed for ${file.name}: ${err.message}`, 'error');
    }
  }

  if (progressFill) progressFill.style.width = '100%';
  if (progressStage) progressStage.textContent = 'ready';
  if (progressPercent) progressPercent.textContent = '100%';

  if (successCount > 0) {
    showToast(
      total === 1
        ? `"${fileList[0].name}" ingested & indexed!`
        : `Successfully ingested & indexed ${successCount} documents!`,
      'success'
    );
  }

  setTimeout(() => {
    if (progressCard) progressCard.classList.add('hidden');
  }, 2500);

  await loadDocuments();

  if (lastDocId) {
    openSourceViewer(lastDocId, 1, lastPages);
  }

  const fileInput = document.getElementById('file-upload-input');
  if (fileInput) fileInput.value = '';
  const galleryInput = document.getElementById('gallery-upload-input');
  if (galleryInput) galleryInput.value = '';
  const cameraInput = document.getElementById('camera-upload-input');
  if (cameraInput) cameraInput.value = '';
}

async function handleFileUpload(file) {
  return handleMultipleFiles([file]);
}

// ============================================================================
// Conversations & Chat
// ============================================================================

async function loadConversations() {
  if (!state.currentWorkspaceId) return;
  try {
    const convs = await apiRequest(`/workspaces/${state.currentWorkspaceId}/conversations`);
    state.conversations = convs || [];

    const select = document.getElementById('conv-select');
    if (select) select.innerHTML = '';

    if (state.conversations.length === 0) {
      // Create first study conversation
      const newConv = await apiRequest(`/workspaces/${state.currentWorkspaceId}/conversations`, {
        method: 'POST',
        body: JSON.stringify({ title: 'Study Chat' }),
      });
      state.conversations = [newConv];
    }

    state.conversations.forEach((c) => {
      if (select) {
        const opt = document.createElement('option');
        opt.value = c.id;
        opt.textContent = c.title;
        select.appendChild(opt);
      }
    });

    state.currentConversationId = state.conversations[0].id;
    if (select) select.value = state.currentConversationId;
    renderSidebarConversations();
    await loadMessages(state.currentConversationId);
  } catch (err) {
    console.error('Failed to load conversations:', err);
  }
}

function renderSidebarConversations() {
  const list = document.getElementById('sidebar-conv-list');
  if (!list) return;
  list.innerHTML = '';

  state.conversations.forEach((c) => {
    const item = document.createElement('div');
    const isActive = c.id === state.currentConversationId;
    item.className = `sidebar-conv-item ${isActive ? 'active' : ''}`;
    item.setAttribute('data-conv-id', c.id);
    item.innerHTML = `
      <div style="display:flex; align-items:center; gap:8px; overflow:hidden; flex:1;">
        <span style="font-size:0.85rem; opacity:0.7;">💬</span>
        <span class="sidebar-conv-title">${escapeHtml(c.title)}</span>
      </div>
    `;
    item.addEventListener('click', async () => {
      if (state.currentConversationId === c.id) return;
      state.currentConversationId = c.id;
      const select = document.getElementById('conv-select');
      if (select) select.value = c.id;
      renderSidebarConversations();
      await loadMessages(c.id);
    });
    list.appendChild(item);
  });
}

async function loadMessages(convId) {
  if (!convId) return;
  try {
    const msgs = await apiRequest(`/conversations/${convId}/messages`);
    renderMessages(msgs || []);
  } catch (err) {
    console.error('Failed to load messages:', err);
  }
}

function renderMessages(messages) {
  const container = document.getElementById('messages-container');
  const emptyState = document.getElementById('chat-empty-state');

  if (messages.length === 0) {
    container.innerHTML = '';
    if (emptyState) container.appendChild(emptyState);
    return;
  }

  container.innerHTML = '';
  messages.forEach((msg) => {
    if (msg.role === 'user') {
      appendUserMessage(msg.content);
    } else {
      appendAssistantMessage({
        message_id: msg.id,
        abstained: msg.abstained,
        confidence: msg.verification?.confidence || 'high',
        answer: [{ text: msg.content, citations: [] }],
        citations: msg.citations || [],
        dropped_claims: msg.verification?.dropped_claims || 0,
        missing_info: msg.verification?.missing_info,
        suggestions: [],
      });
    }
  });

  // Scroll to bottom
  container.scrollTop = container.scrollHeight;
}

function appendUserMessage(text) {
  const container = document.getElementById('messages-container');
  const emptyState = document.getElementById('chat-empty-state');
  if (emptyState && emptyState.parentElement === container) {
    emptyState.remove();
  }

  const bubble = document.createElement('div');
  bubble.className = 'message-user';
  bubble.textContent = text;
  container.appendChild(bubble);
  container.scrollTop = container.scrollHeight;
}

function formatAssistantMarkdown(rawText) {
  if (!rawText) return '';

  // 1. Extract code blocks first (triple backtick) so inner formatting is preserved
  const codeBlocks = [];
  let text = rawText.replace(/```([a-zA-Z0-9_-]*)\n?([\s\S]*?)```/g, (match, lang, code) => {
    const idx = codeBlocks.length;
    codeBlocks.push({ lang: lang || 'code', code: code.trim() });
    return `___CODE_BLOCK_${idx}___`;
  });

  // 2. Replace citations in text with clickable pills [1], [2], etc.
  text = text.replace(/\[(\d+)\]/g, (match, num) => {
    return `<button type="button" class="citation-pill" data-cit-num="${num}" id="pill-cit-${num}">[${num}]</button>`;
  });

  // 3. Inline code `code`
  text = text.replace(/`([^`]+)`/g, (match, code) => {
    return `<code>${escapeHtml(code)}</code>`;
  });

  // 4. Bold: **bold**
  text = text.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');

  // 5. Italic: *italic*
  text = text.replace(/(?<!\*)\*([^*]+)\*(?!\*)/g, '<em>$1</em>');

  // Marks Badge Formatting (1 Mark & 3 Mark)
  text = text.replace(/(?:\(|\[)1\s*Mark(?:\)|\])/gi, '<span class="marks-badge mark-1">1 Mark</span>');
  text = text.replace(/(?:\(|\[)3\s*Marks?(?:\)|\])/gi, '<span class="marks-badge mark-3">3 Marks</span>');

  // Headers: ### Header
  text = text.replace(/###\s*(.+)/g, '<h4 style="margin: 12px 0 6px; color: var(--primary-light); font-weight: 700; font-size: 0.98rem;">$1</h4>');

  // 6. Split into paragraphs and handle lists
  const paragraphs = text.split(/\n{2,}/);
  text = paragraphs
    .map((p) => {
      p = p.trim();
      if (!p) return '';
      if (p.includes('\n- ') || p.startsWith('- ')) {
        const lines = p.split('\n');
        let listItems = '';
        let nonList = '';
        lines.forEach((line) => {
          line = line.trim();
          if (line.startsWith('- ')) {
            listItems += `<li>${line.substring(2)}</li>`;
          } else if (line) {
            if (listItems) {
              nonList += `<ul>${listItems}</ul>`;
              listItems = '';
            }
            nonList += `<p>${line}</p>`;
          }
        });
        if (listItems) nonList += `<ul>${listItems}</ul>`;
        return nonList;
      }
      return `<p>${p.replace(/\n/g, '<br>')}</p>`;
    })
    .join('');

  // 7. Re-inject code blocks
  text = text.replace(/___CODE_BLOCK_(\d+)___/g, (match, idx) => {
    const block = codeBlocks[parseInt(idx, 10)];
    if (!block) return '';
    return `
      <div class="code-block-wrapper">
        <div class="code-block-header">
          <span class="code-lang">${escapeHtml(block.lang)}</span>
          <button type="button" class="btn-copy-code" onclick="copyCodeBlock(this)">Copy code</button>
        </div>
        <pre><code>${escapeHtml(block.code)}</code></pre>
      </div>
    `;
  });

  return text;
}

window.copyToClipboard = async function (text, btnElement) {
  try {
    await navigator.clipboard.writeText(text);
    if (btnElement) {
      const orig = btnElement.innerHTML;
      btnElement.innerHTML = '✓ Copied';
      setTimeout(() => {
        btnElement.innerHTML = orig;
      }, 2000);
    }
    showToast('Copied to clipboard', 'info');
  } catch (err) {
    showToast('Failed to copy to clipboard', 'error');
  }
};

window.copyCodeBlock = function (btn) {
  const codeEl = btn.closest('.code-block-wrapper')?.querySelector('code');
  if (codeEl) {
    window.copyToClipboard(codeEl.innerText, btn);
  }
};

function appendAssistantMessage(payload) {
  const container = document.getElementById('messages-container');
  const emptyState = document.getElementById('chat-empty-state');
  if (emptyState && emptyState.parentElement === container) {
    emptyState.remove();
  }

  const msgId = payload.message_id || `msg-${Date.now()}`;
  const card = document.createElement('div');
  card.className = `message-assistant ${payload.abstained ? 'abstain-card' : ''}`;
  card.setAttribute('id', `msg-card-${msgId}`);

  if (payload.abstained) {
    // Render Abstention Card
    let suggestionsHtml = '';
    if (payload.suggestions && payload.suggestions.length > 0) {
      suggestionsHtml = `
        <div class="suggestions-group">
          <div class="suggestions-title">Suggested Alternative Questions:</div>
          ${payload.suggestions
            .map(
              (s, i) =>
                `<button type="button" class="suggestion-chip" id="suggestion-chip-${i}" data-query="${escapeHtml(s)}">${escapeHtml(s)}</button>`
            )
            .join('')}
        </div>
      `;
    }

    card.innerHTML = `
      <div class="abstain-header">
        <span>⚠</span>
        <span>Insufficient Verified Evidence (Abstention)</span>
      </div>
      <p class="abstain-reason">
        StudyMind only generates answers that are strictly verified against your uploaded materials.
        ${payload.missing_info ? `<br><strong>Missing:</strong> ${escapeHtml(payload.missing_info)}` : ''}
      </p>
      ${suggestionsHtml}
    `;

    // Bind suggestion chips
    card.querySelectorAll('.suggestion-chip').forEach((chip) => {
      chip.addEventListener('click', () => {
        const query = chip.getAttribute('data-query');
        const input = document.getElementById('chat-input');
        input.value = query;
        document.getElementById('chat-form').dispatchEvent(new Event('submit'));
      });
    });
  } else {
    // Normal Grounded Answer
    const confidence = payload.confidence || 'high';
    const answerText = payload.answer
      ? payload.answer
          .map((a) => a.text)
          .join(payload.answer.some((a) => a.text && a.text.trim().startsWith('-')) ? '\n' : ' ')
      : '';
    const formattedHtml = formatAssistantMarkdown(answerText);

    // Render citations card list
    let sourcesListHtml = '';
    if (payload.citations && payload.citations.length > 0) {
      sourcesListHtml = `
        <div class="msg-sources-container">
          <span class="sources-label">Grounded Sources & Citations</span>
          ${payload.citations
            .map((cit) => {
              const docName = getDocumentNameById(cit.document_id);
              return `
              <div class="citation-card" data-cit-num="${cit.n}" id="citation-card-${cit.n}">
                <div class="citation-meta">
                  <span class="citation-index">[${cit.n}]</span>
                  <span class="citation-file">${escapeHtml(docName)}</span>
                  <span class="citation-page">Page ${cit.page}</span>
                </div>
                <div class="citation-quote-preview" title="${escapeHtml(cit.quote)}">"${escapeHtml(cit.quote)}"</div>
                <button type="button" class="btn-inspect-citation" data-cit-num="${cit.n}">Inspect ↗</button>
              </div>
            `;
            })
            .join('')}
        </div>
      `;
    }

    card.innerHTML = `
      <div class="msg-header">
        <div class="msg-author">
          <div class="bot-avatar">⚡</div>
          <span>StudyMind Assistant</span>
        </div>
        <span class="confidence-badge ${confidence}">${confidence} confidence</span>
      </div>
      <div class="msg-body">${formattedHtml}</div>
      ${sourcesListHtml}
      <div class="msg-actions-footer">
        <div class="feedback-group">
          <span class="feedback-prompt">Helpful answer?</span>
          <button type="button" class="btn-feedback" id="btn-thumb-up-${msgId}" title="Accurate & helpful">👍</button>
          <button type="button" class="btn-feedback" id="btn-thumb-down-${msgId}" title="Report issue">👎</button>
          <button type="button" class="btn-feedback" id="btn-copy-msg-${msgId}" title="Copy response to clipboard">📋</button>
        </div>
      </div>
    `;

    // Bind citation pill clicks
    card.querySelectorAll('.citation-pill, .citation-card, .btn-inspect-citation').forEach((el) => {
      el.addEventListener('click', (e) => {
        e.stopPropagation();
        const citNum = parseInt(el.getAttribute('data-cit-num'), 10);
        const cit = payload.citations.find((c) => c.n === citNum);
        if (cit) {
          triggerCitationHighlight(cit);
        }
      });
    });

    // Bind feedback buttons
    const btnUp = card.querySelector(`#btn-thumb-up-${msgId}`);
    const btnDown = card.querySelector(`#btn-thumb-down-${msgId}`);
    const btnCopy = card.querySelector(`#btn-copy-msg-${msgId}`);

    if (btnCopy) {
      btnCopy.addEventListener('click', () => {
        window.copyToClipboard(answerText, btnCopy);
      });
    }

    if (btnUp) {
      btnUp.addEventListener('click', async () => {
        try {
          await apiRequest(`/messages/${payload.message_id}/feedback`, {
            method: 'POST',
            body: JSON.stringify({ rating: 'up' }),
          });
          btnUp.classList.add('active-up');
          btnDown?.classList.remove('active-down');
          showToast('Feedback submitted: Thank you!', 'success');
        } catch (err) {
          showToast(`Feedback failed: ${err.message}`, 'error');
        }
      });
    }

    if (btnDown) {
      btnDown.addEventListener('click', () => {
        openFeedbackModal(payload.message_id);
      });
    }
  }

  container.appendChild(card);
  container.scrollTop = container.scrollHeight;
}

function getDocumentNameById(docId) {
  const doc = state.documents.find((d) => d.id === docId);
  return doc ? doc.filename : 'Course Document';
}

async function handleSendMessage(question) {
  if (!question || !question.trim()) return;
  if (!state.currentConversationId) {
    if (!state.currentWorkspaceId) {
      showToast('Please select a workspace first', 'error');
      return;
    }
    try {
      const newConv = await apiRequest(`/workspaces/${state.currentWorkspaceId}/conversations`, {
        method: 'POST',
        body: JSON.stringify({ title: `Study Chat (${new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })})` }),
      });
      state.currentConversationId = newConv.id;
      await loadConversations();
      const convSelect = document.getElementById('conv-select');
      if (convSelect) convSelect.value = newConv.id;
    } catch (err) {
      showToast('Please select or create a conversation first', 'error');
      return;
    }
  }

  appendUserMessage(question);

  const statusBar = document.getElementById('pipeline-status-bar');
  const statusText = document.getElementById('pipeline-status-text');
  statusBar.classList.remove('hidden');
  statusText.textContent = 'Searching index & verifying citations...';

  try {
    const reqBody = {
      question: question.trim(),
      strict_mode: state.strictMode,
    };
    const qLower = question.toLowerCase();
    if (state.currentViewerDocId && (qLower.includes('this page') || qLower.includes('current page') || qLower.includes('the page') || qLower.includes('this pdf') || qLower.includes('this doc'))) {
      reqBody.document_ids = [state.currentViewerDocId];
      if (qLower.includes('this page') || qLower.includes('current page') || qLower.includes('the page')) {
        reqBody.page = state.currentViewerPage;
      }
    }

    const payload = await apiRequest(`/conversations/${state.currentConversationId}/messages`, {
      method: 'POST',
      body: JSON.stringify(reqBody),
    });

    statusBar.classList.add('hidden');
    appendAssistantMessage(payload);

    // If citations are available, automatically highlight the first one in the viewer
    if (payload.citations && payload.citations.length > 0) {
      triggerCitationHighlight(payload.citations[0]);
    }
  } catch (err) {
    statusBar.classList.add('hidden');
    showToast(`Question failed: ${err.message}`, 'error');
  }
}

// ============================================================================
// Interactive Source Viewer & Bounding Box Overlay (DoD Requirement)
// ============================================================================

function setViewerOpen(open) {
  const viewerPanel = document.getElementById('source-viewer-panel');
  const toggleViewerBtn = document.getElementById('btn-toggle-source-viewer');
  if (!viewerPanel) return;
  if (open) {
    viewerPanel.classList.remove('hidden');
    toggleViewerBtn?.classList.add('active');
  } else {
    viewerPanel.classList.add('hidden');
    toggleViewerBtn?.classList.remove('active');
  }
}

async function openSourceViewer(docId, pageNo = 1, maxPages = 1, citationContext = null) {
  setViewerOpen(true);
  state.currentViewerDocId = docId;
  state.currentViewerPage = pageNo;
  state.activeCitation = citationContext;

  const doc = state.documents.find((d) => d.id === docId);
  const totalPages = doc?.page_count || maxPages || 1;
  state.currentViewerMaxPages = totalPages;

  const titleEl = document.getElementById('viewer-doc-title');
  const placeholderEl = document.getElementById('viewer-empty-state');
  const stageEl = document.getElementById('viewer-stage');
  const pageIndicator = document.getElementById('viewer-page-indicator');
  const prevBtn = document.getElementById('btn-prev-page');
  const nextBtn = document.getElementById('btn-next-page');
  const downloadBtn = document.getElementById('btn-download-file');
  const citationTag = document.getElementById('viewer-citation-tag');

  titleEl.textContent = doc ? doc.filename : `Document (${docId.slice(0, 8)})`;
  placeholderEl.classList.add('hidden');
  stageEl.classList.remove('hidden');

  pageIndicator.textContent = `Page ${pageNo} / ${state.currentViewerMaxPages}`;
  prevBtn.disabled = pageNo <= 1;
  nextBtn.disabled = pageNo >= state.currentViewerMaxPages;
  downloadBtn.disabled = false;

  if (citationContext) {
    citationTag.textContent =
      citationContext.tag ||
      (citationContext.n ? `Referenced by Citation [${citationContext.n}]` : 'Source Reference');
    citationTag.classList.remove('hidden');
  } else {
    citationTag.classList.add('hidden');
    document.getElementById('source-highlight-box')?.classList.add('hidden');
  }

  await loadPageImage(docId, pageNo);
}

async function loadPageImage(docId, pageNo) {
  const imgEl = document.getElementById('viewer-page-image');
  const highlightOverlay = document.getElementById('source-highlight-box');

  // Hide highlight until positioned
  highlightOverlay.classList.add('hidden');

  try {
    const res = await fetch(`${API_BASE}/documents/${docId}/pages/${pageNo}/image`, {
      headers: { Authorization: `Bearer ${state.token}` },
    });
    if (!res.ok) {
      throw new Error(`Failed to load page image (${res.status})`);
    }
    const blob = await res.blob();
    imgEl.src = URL.createObjectURL(blob);

    imgEl.onload = () => {
      // If we have an active citation for this page, re-apply bounding box overlay
      if (
        state.activeCitation &&
        (!state.activeCitation.document_id || state.activeCitation.document_id === docId) &&
        (!state.activeCitation.page || state.activeCitation.page === pageNo)
      ) {
        renderBoundingBoxOverlay(state.activeCitation);
      } else {
        highlightOverlay.classList.add('hidden');
      }
    };
  } catch (err) {
    console.error('Failed to load page image:', err);
    showToast('Failed to load page preview', 'error');
  }
}

function triggerCitationHighlight(citation) {
  state.activeCitation = citation;

  // 1. Highlight pill in chat UI
  document.querySelectorAll('.citation-pill').forEach((pill) => {
    if (pill.getAttribute('data-cit-num') == citation.n) {
      pill.classList.add('active');
    } else {
      pill.classList.remove('active');
    }
  });

  // 2. Open document with citation context
  openSourceViewer(citation.document_id, citation.page, state.currentViewerMaxPages, citation).then(() => {
    renderBoundingBoxOverlay(citation);
  });
}

function renderBoundingBoxOverlay(citation) {
  const imgEl = document.getElementById('viewer-page-image');
  const highlightOverlay = document.getElementById('source-highlight-box');
  const tooltipQuote = document.getElementById('tooltip-quote-text');
  const tooltipCitNum = document.getElementById('tooltip-citation-num');

  if (!imgEl || !highlightOverlay) return;

  const bbox = citation.bbox; // [x0, y0, x1, y1]
  const imgWidth = imgEl.clientWidth || 800;
  const imgHeight = imgEl.clientHeight || 1050;

  // Use natural image dimensions if available; fallback to standard PDF points (612 x 792)
  const natW = imgEl.naturalWidth > 0 ? imgEl.naturalWidth : 612.0;
  const natH = imgEl.naturalHeight > 0 ? imgEl.naturalHeight : 792.0;

  let x0 = 40,
    y0 = 80,
    w = Math.max(imgWidth - 80, 100),
    h = 70;

  if (Array.isArray(bbox) && bbox.length === 4) {
    const [bx0, by0, bx1, by1] = bbox;
    if (bx0 >= 0 && bx1 <= 1 && by0 >= 0 && by1 <= 1) {
      // Normalized coordinates [0..1]
      x0 = bx0 * imgWidth;
      y0 = by0 * imgHeight;
      w = Math.max((bx1 - bx0) * imgWidth, 40);
      h = Math.max((by1 - by0) * imgHeight, 24);
    } else {
      // Absolute pixels or PDF points scaled by natural dimensions
      const scaleX = imgWidth / natW;
      const scaleY = imgHeight / natH;
      x0 = bx0 * scaleX;
      y0 = by0 * scaleY;
      w = Math.max((bx1 - bx0) * scaleX, 40);
      h = Math.max((by1 - by0) * scaleY, 24);
    }
  } else {
    // If no bounding box is provided, position highlight gently at upper third
    x0 = 30;
    y0 = Math.min(imgHeight * 0.12, 100);
    w = Math.max(imgWidth - 60, 100);
    h = 60;
  }

  // Ensure highlight box stays within viewport bounds
  x0 = Math.max(8, Math.min(x0, imgWidth - w - 8));
  y0 = Math.max(8, Math.min(y0, imgHeight - h - 8));

  highlightOverlay.style.left = `${x0}px`;
  highlightOverlay.style.top = `${y0}px`;
  highlightOverlay.style.width = `${w}px`;
  highlightOverlay.style.height = `${h}px`;

  tooltipCitNum.textContent =
    citation.tag || (citation.n ? `Citation [${citation.n}]` : 'Verified Source');
  tooltipQuote.textContent = citation.quote || 'Verified text region';

  highlightOverlay.classList.remove('hidden');

  // Smooth scroll highlighted bounding box into viewport center
  const viewport = document.getElementById('viewer-viewport');
  if (viewport) {
    viewport.scrollTo({
      top: Math.max(0, y0 - 80),
      left: Math.max(0, x0 - 40),
      behavior: 'smooth',
    });
  }
}

// ============================================================================
// Mobile & Web Camera Scanner Logic
// ============================================================================

let cameraStream = null;
let currentFacingMode = 'environment';

async function startCameraScanner() {
  const modal = document.getElementById('camera-modal');
  const video = document.getElementById('camera-video-preview');

  // If getUserMedia is not supported (e.g. non-HTTPS context or restricted browser), seamlessly launch native camera file picker
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    document.getElementById('camera-upload-input')?.click();
    return;
  }

  try {
    if (cameraStream) {
      cameraStream.getTracks().forEach((track) => track.stop());
      cameraStream = null;
    }

    const constraints = {
      video: {
        facingMode: { ideal: currentFacingMode },
        width: { ideal: 1920 },
        height: { ideal: 1080 },
      },
      audio: false,
    };

    cameraStream = await navigator.mediaDevices.getUserMedia(constraints);
    if (video) {
      video.srcObject = cameraStream;
      await video.play();
    }
    modal?.classList.remove('hidden');
  } catch (err) {
    console.warn('getUserMedia failed, falling back to native camera input:', err);
    stopCameraScanner();
    document.getElementById('camera-upload-input')?.click();
  }
}

function stopCameraScanner() {
  if (cameraStream) {
    cameraStream.getTracks().forEach((t) => t.stop());
    cameraStream = null;
  }
  const video = document.getElementById('camera-video-preview');
  if (video) video.srcObject = null;
  document.getElementById('camera-modal')?.classList.add('hidden');
}

function captureCameraSnapshot() {
  const video = document.getElementById('camera-video-preview');
  const canvas = document.getElementById('camera-canvas-capture');
  if (!video || !canvas || video.videoWidth === 0) {
    showToast('Camera not ready yet', 'error');
    return;
  }

  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;
  const ctx = canvas.getContext('2d');
  ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

  canvas.toBlob((blob) => {
    if (!blob) {
      showToast('Failed to capture snapshot', 'error');
      return;
    }
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
    const capturedFile = new File([blob], `note_camera_${timestamp}.jpg`, { type: 'image/jpeg' });
    stopCameraScanner();
    handleMultipleFiles([capturedFile]);
  }, 'image/jpeg', 0.92);
}

function flipCamera() {
  currentFacingMode = currentFacingMode === 'environment' ? 'user' : 'environment';
  startCameraScanner();
}

// ============================================================================
// Event Listeners & Modals
// ============================================================================

function bindEventListeners() {
  // Navigation Tabs
  const tabChatBtn = document.getElementById('tab-chat-btn');
  const tabLibBtn = document.getElementById('tab-library-btn');
  const tabStudyBtn = document.getElementById('tab-study-btn');
  const chatView = document.getElementById('chat-view');
  const libView = document.getElementById('library-view');
  const studyView = document.getElementById('study-view');

  function switchMainTab(target) {
    if (window.innerWidth <= 768) {
      document.getElementById('app-sidebar')?.classList.remove('mobile-open');
      document.getElementById('sidebar-backdrop')?.classList.add('hidden');
    }
    [tabChatBtn, tabLibBtn, tabStudyBtn].forEach((btn) => btn?.classList.remove('active'));
    [chatView, libView, studyView].forEach((view) => {
      view?.classList.add('hidden');
      view?.classList.remove('active');
    });

    if (target === 'chat') {
      tabChatBtn?.classList.add('active');
      chatView?.classList.remove('hidden');
      chatView?.classList.add('active');
    } else if (target === 'library') {
      tabLibBtn?.classList.add('active');
      libView?.classList.remove('hidden');
      libView?.classList.add('active');
    } else if (target === 'study') {
      tabStudyBtn?.classList.add('active');
      studyView?.classList.remove('hidden');
      studyView?.classList.add('active');
      loadSavedStudyItems();
    }
  }

  tabChatBtn?.addEventListener('click', () => switchMainTab('chat'));
  tabLibBtn?.addEventListener('click', () => switchMainTab('library'));
  tabStudyBtn?.addEventListener('click', () => switchMainTab('study'));
  bindStudyToolsEvents();
  initExamPrepEngine();

  // Strict Mode Toggle
  const strictToggle = document.getElementById('strict-mode-toggle');
  strictToggle.addEventListener('change', (e) => {
    state.strictMode = e.target.checked;
    showToast(`Strict mode ${state.strictMode ? 'enabled (zero hallucination)' : 'disabled'}`, 'info');
  });

  // Workspace Select
  const wsSelect = document.getElementById('workspace-select');
  wsSelect.addEventListener('change', async (e) => {
    state.currentWorkspaceId = e.target.value;
    localStorage.setItem('studymind_ws_id', state.currentWorkspaceId);
    await Promise.all([loadDocuments(), loadConversations()]);
  });

  // New Workspace Button & Modal
  document.getElementById('btn-new-workspace').addEventListener('click', () => {
    document.getElementById('workspace-modal').classList.remove('hidden');
  });
  document.getElementById('btn-close-workspace-modal').addEventListener('click', () => {
    document.getElementById('workspace-modal').classList.add('hidden');
  });
  document.getElementById('workspace-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const nameInput = document.getElementById('new-workspace-name');
    try {
      const created = await apiRequest('/workspaces', {
        method: 'POST',
        body: JSON.stringify({ name: nameInput.value.trim() }),
      });
      document.getElementById('workspace-modal').classList.add('hidden');
      nameInput.value = '';
      showToast('Workspace created!', 'success');
      state.currentWorkspaceId = created.id;
      await loadWorkspaces();
    } catch (err) {
      showToast(`Error: ${err.message}`, 'error');
    }
  });

  // New Chat Button
  document.getElementById('btn-new-chat').addEventListener('click', async () => {
    try {
      const newConv = await apiRequest(`/workspaces/${state.currentWorkspaceId}/conversations`, {
        method: 'POST',
        body: JSON.stringify({ title: `Study Chat (${new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })})` }),
      });
      showToast('New chat started', 'info');
      await loadConversations();
      state.currentConversationId = newConv.id;
      document.getElementById('conv-select').value = newConv.id;
      renderMessages([]);
    } catch (err) {
      showToast(`Failed to start chat: ${err.message}`, 'error');
    }
  });

  // Conversation Select Change
  document.getElementById('conv-select').addEventListener('change', async (e) => {
    state.currentConversationId = e.target.value;
    await loadMessages(state.currentConversationId);
  });

  // Sidebar Collapse & Mobile Drawer Toggle
  const sidebar = document.getElementById('app-sidebar');
  const collapseSidebarBtn = document.getElementById('btn-collapse-sidebar');
  const toggleSidebarBtn = document.getElementById('btn-toggle-sidebar');
  const sidebarBackdrop = document.getElementById('sidebar-backdrop');

  function openMobileSidebar() {
    sidebar?.classList.add('mobile-open');
    sidebarBackdrop?.classList.remove('hidden');
  }

  function closeMobileSidebar() {
    sidebar?.classList.remove('mobile-open');
    sidebarBackdrop?.classList.add('hidden');
  }

  function toggleSidebar() {
    if (window.innerWidth <= 768) {
      if (sidebar?.classList.contains('mobile-open')) {
        closeMobileSidebar();
      } else {
        openMobileSidebar();
      }
    } else {
      if (sidebar) sidebar.classList.toggle('collapsed');
    }
  }

  collapseSidebarBtn?.addEventListener('click', toggleSidebar);
  toggleSidebarBtn?.addEventListener('click', toggleSidebar);
  sidebarBackdrop?.addEventListener('click', closeMobileSidebar);

  window.addEventListener('resize', () => {
    if (window.innerWidth > 768) {
      closeMobileSidebar();
    }
  });

  // Source Viewer Toggle & Close
  const toggleViewerBtn = document.getElementById('btn-toggle-source-viewer');
  const closeViewerBtn = document.getElementById('btn-close-viewer');
  toggleViewerBtn?.addEventListener('click', () => {
    const viewerPanel = document.getElementById('source-viewer-panel');
    if (viewerPanel) {
      const isHidden = viewerPanel.classList.contains('hidden');
      setViewerOpen(isHidden);
    }
  });
  closeViewerBtn?.addEventListener('click', () => {
    setViewerOpen(false);
  });

  // Prompt Bar Paperclip Attach -> Open Attach Options Sheet (Camera, Gallery, Files)
  const inputAttachBtn = document.getElementById('btn-input-attach');
  const attachModal = document.getElementById('attach-menu-modal');
  const closeAttachBtn = document.getElementById('btn-close-attach-menu');

  inputAttachBtn?.addEventListener('click', (e) => {
    e.preventDefault();
    e.stopPropagation();
    attachModal?.classList.remove('hidden');
  });

  closeAttachBtn?.addEventListener('click', () => {
    attachModal?.classList.add('hidden');
  });

  attachModal?.addEventListener('click', (e) => {
    if (e.target === attachModal) {
      attachModal.classList.add('hidden');
    }
  });

  document.getElementById('btn-opt-camera')?.addEventListener('click', () => {
    attachModal?.classList.add('hidden');
    startCameraScanner();
  });

  document.getElementById('btn-opt-gallery')?.addEventListener('click', () => {
    attachModal?.classList.add('hidden');
    document.getElementById('gallery-upload-input')?.click();
  });

  document.getElementById('btn-opt-files')?.addEventListener('click', () => {
    attachModal?.classList.add('hidden');
    document.getElementById('file-upload-input')?.click();
  });

  // Chat Form Submit & Auto-resizing Textarea
  const chatForm = document.getElementById('chat-form');
  const chatInput = document.getElementById('chat-input');
  if (chatInput) {
    chatInput.addEventListener('input', () => {
      chatInput.style.height = 'auto';
      chatInput.style.height = Math.min(chatInput.scrollHeight, 180) + 'px';
    });
    chatInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        chatForm.dispatchEvent(new Event('submit'));
      }
    });
  }

  chatForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const q = chatInput.value.trim();
    if (!q) return;
    chatInput.value = '';
    chatInput.style.height = 'auto';
    await handleSendMessage(q);
  });

  // Sample prompt chips in empty state
  document.querySelectorAll('.sample-chips .chip-btn').forEach((chip) => {
    chip.addEventListener('click', async (e) => {
      e.preventDefault();
      const q = chip.getAttribute('data-query');
      if (chatInput) {
        chatInput.value = q;
        chatInput.style.height = 'auto';
      }
      await handleSendMessage(q);
    });
  });

  // Quick Action Chips Bar (1 & 3 Mark Q&A, Summary, Flashcards, Exam)
  document.getElementById('btn-quick-marks')?.addEventListener('click', async (e) => {
    e.preventDefault();
    e.stopPropagation();
    const query = 'Generate questions and answers based on marks like 1 mark and 3 mark from the provided material';
    if (chatInput) {
      chatInput.value = query;
      chatInput.style.height = 'auto';
    }
    await handleSendMessage(query);
  });

  document.getElementById('btn-quick-summary')?.addEventListener('click', (e) => {
    e.preventDefault();
    e.stopPropagation();
    switchMainTab('study');
    document.getElementById('study-subtab-summary')?.click();
  });

  document.getElementById('btn-quick-flashcards')?.addEventListener('click', (e) => {
    e.preventDefault();
    e.stopPropagation();
    switchMainTab('study');
    document.getElementById('study-subtab-flashcards')?.click();
  });

  document.getElementById('btn-quick-exam')?.addEventListener('click', (e) => {
    e.preventDefault();
    e.stopPropagation();
    switchMainTab('study');
    document.getElementById('study-subtab-exam')?.click();
  });

  // Camera, Gallery & Drag and Drop Upload
  const dropzone = document.getElementById('upload-dropzone');
  const fileInput = document.getElementById('file-upload-input');
  const galleryInput = document.getElementById('gallery-upload-input');
  const cameraInput = document.getElementById('camera-upload-input');

  const browseBtn = document.getElementById('btn-browse-files');
  const cameraUploadBtn = document.getElementById('btn-camera-upload');
  const galleryUploadBtn = document.getElementById('btn-gallery-upload');

  browseBtn?.addEventListener('click', () => fileInput?.click());
  galleryUploadBtn?.addEventListener('click', () => galleryInput?.click());
  cameraUploadBtn?.addEventListener('click', () => startCameraScanner());

  fileInput?.addEventListener('change', (e) => {
    if (e.target.files && e.target.files.length > 0) {
      handleMultipleFiles(e.target.files);
    }
  });

  galleryInput?.addEventListener('change', (e) => {
    if (e.target.files && e.target.files.length > 0) {
      handleMultipleFiles(e.target.files);
    }
  });

  cameraInput?.addEventListener('change', (e) => {
    if (e.target.files && e.target.files.length > 0) {
      handleMultipleFiles(e.target.files);
    }
  });

  // In-App Camera Scanner Viewfinder Modal Handlers
  const cameraModal = document.getElementById('camera-modal');
  const closeCameraBtn = document.getElementById('btn-close-camera-modal');
  const snapBtn = document.getElementById('btn-camera-capture');
  const flipBtn = document.getElementById('btn-camera-flip');
  const nativeCameraBtn = document.getElementById('btn-camera-native');

  closeCameraBtn?.addEventListener('click', stopCameraScanner);
  cameraModal?.addEventListener('click', (e) => {
    if (e.target === cameraModal) {
      stopCameraScanner();
    }
  });

  snapBtn?.addEventListener('click', captureCameraSnapshot);
  flipBtn?.addEventListener('click', flipCamera);
  nativeCameraBtn?.addEventListener('click', () => {
    stopCameraScanner();
    cameraInput?.click();
  });

  dropzone?.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropzone.classList.add('dragover');
  });
  dropzone?.addEventListener('dragleave', () => dropzone.classList.remove('dragover'));
  dropzone?.addEventListener('drop', (e) => {
    e.preventDefault();
    dropzone.classList.remove('dragover');
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleMultipleFiles(e.dataTransfer.files);
    }
  });

  // Refresh Docs
  document.getElementById('btn-refresh-docs').addEventListener('click', loadDocuments);

  // Viewer Controls (Prev/Next Page & Zoom)
  document.getElementById('btn-prev-page').addEventListener('click', () => {
    if (state.currentViewerPage > 1) {
      openSourceViewer(state.currentViewerDocId, state.currentViewerPage - 1, state.currentViewerMaxPages);
    }
  });
  document.getElementById('btn-next-page').addEventListener('click', () => {
    if (state.currentViewerPage < state.currentViewerMaxPages) {
      openSourceViewer(state.currentViewerDocId, state.currentViewerPage + 1, state.currentViewerMaxPages);
    }
  });

  document.getElementById('btn-zoom-in').addEventListener('click', () => {
    state.viewerZoom = Math.min(2.0, state.viewerZoom + 0.15);
    applyViewerZoom();
  });
  document.getElementById('btn-zoom-out').addEventListener('click', () => {
    state.viewerZoom = Math.max(0.5, state.viewerZoom - 0.15);
    applyViewerZoom();
  });
  document.getElementById('btn-zoom-fit').addEventListener('click', () => {
    state.viewerZoom = 1.0;
    applyViewerZoom();
  });

  document.getElementById('btn-download-file').addEventListener('click', () => {
    if (!state.currentViewerDocId) return;
    window.open(`${API_BASE}/documents/${state.currentViewerDocId}/file`, '_blank');
  });

  document.getElementById('btn-summarize-current-page')?.addEventListener('click', () => {
    if (!state.currentViewerDocId) {
      showToast('Open a document in the viewer first', 'info');
      return;
    }
    const pageNo = state.currentViewerPage || 1;
    const prompt = `Summarize the topics on page ${pageNo}`;
    const input = document.getElementById('chat-input');
    if (input) {
      input.value = prompt;
    }
    const tabChat = document.getElementById('nav-tab-chat');
    tabChat?.click();
    handleSendMessage(prompt);
  });

  // Auth Modal & Buttons
  document.getElementById('btn-open-login').addEventListener('click', () => showAuthModal(true));
  document.getElementById('btn-close-auth').addEventListener('click', () => showAuthModal(false));
  document.getElementById('btn-logout').addEventListener('click', handleUnauthorized);
  document.getElementById('btn-continue-guest')?.addEventListener('click', () => startGuestSession());
  document.getElementById('btn-save-guest')?.addEventListener('click', () => showAuthModal(true));

  let isRegisterMode = false;
  const loginTab = document.getElementById('auth-tab-login');
  const registerTab = document.getElementById('auth-tab-register');
  const authSubmitBtn = document.getElementById('btn-auth-submit');

  loginTab.addEventListener('click', () => {
    isRegisterMode = false;
    loginTab.classList.add('active');
    registerTab.classList.remove('active');
    authSubmitBtn.textContent = 'Sign In';
  });
  registerTab.addEventListener('click', () => {
    isRegisterMode = true;
    registerTab.classList.add('active');
    loginTab.classList.remove('active');
    authSubmitBtn.textContent = 'Create Account';
  });

  document.getElementById('auth-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const email = document.getElementById('auth-email').value.trim();
    const password = document.getElementById('auth-password').value;
    const errorEl = document.getElementById('auth-error-msg');

    errorEl.classList.add('hidden');
    try {
      if (isRegisterMode) {
        await apiRequest('/auth/register', {
          method: 'POST',
          body: JSON.stringify({ email, password }),
        });
      }
      const tokenRes = await apiRequest('/auth/login', {
        method: 'POST',
        body: JSON.stringify({ email, password }),
      });
      state.token = tokenRes.access_token;
      state.isGuest = false;
      localStorage.setItem('studymind_token', state.token);
      localStorage.removeItem('studymind_is_guest');
      state.user = await apiRequest('/auth/me');

      updateUserNavUI();
      showAuthModal(false);
      showToast('Logged in successfully', 'success');
      await loadWorkspaces();
    } catch (err) {
      errorEl.textContent = err.message;
      errorEl.classList.remove('hidden');
    }
  });

  // Demo Account Quick Test
  document.getElementById('btn-demo-account').addEventListener('click', async () => {
    const demoEmail = 'student@studymind.io';
    const demoPassword = 'password1234';
    try {
      try {
        await apiRequest('/auth/register', {
          method: 'POST',
          body: JSON.stringify({ email: demoEmail, password: demoPassword }),
        });
      } catch {
        // already registered, proceed to login
      }
      const tokenRes = await apiRequest('/auth/login', {
        method: 'POST',
        body: JSON.stringify({ email: demoEmail, password: demoPassword }),
      });
      state.token = tokenRes.access_token;
      localStorage.setItem('studymind_token', state.token);
      state.user = await apiRequest('/auth/me');

      updateUserNavUI();
      showAuthModal(false);
      showToast('Signed in with Demo Student Account!', 'success');
      await loadWorkspaces();
    } catch (err) {
      showToast(`Demo login error: ${err.message}`, 'error');
    }
  });

  // Feedback Modal
  document.getElementById('btn-close-feedback').addEventListener('click', () => {
    document.getElementById('feedback-modal').classList.add('hidden');
  });
  document.getElementById('feedback-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const msgId = document.getElementById('feedback-message-id').value;
    const reason = document.getElementById('feedback-reason').value;
    const comment = document.getElementById('feedback-comment').value;

    try {
      await apiRequest(`/messages/${msgId}/feedback`, {
        method: 'POST',
        body: JSON.stringify({ rating: 'down', reason, comment }),
      });
      document.getElementById('feedback-modal').classList.add('hidden');
      showToast('Report submitted for evaluation', 'info');
    } catch (err) {
      showToast(`Report failed: ${err.message}`, 'error');
    }
  });
}

// ============================================================================
// Study Tools Logic (Phase 7)
// ============================================================================

let currentFlashcardsList = [];
let currentFlashcardIndex = 0;
let isFlashcardFlipped = false;
let currentQuizList = [];

window.inspectQuizQuestionSource = function (qIdx) {
  const q = currentQuizList?.[qIdx];
  if (!q || !q.document_id) return;
  const citationContext = {
    document_id: q.document_id,
    page: q.page || 1,
    quote: q.quote || q.explanation || q.stem,
    tag: `Quiz Question ${qIdx + 1}`,
    bbox: q.bbox || null,
  };
  openSourceViewer(q.document_id, q.page || 1, state.currentViewerMaxPages, citationContext);
};

window.inspectFlashcardSource = function (fcIdx) {
  const fc = currentFlashcardsList?.[fcIdx];
  if (!fc || !fc.document_id) return;
  const citationContext = {
    document_id: fc.document_id,
    page: fc.page || 1,
    quote: fc.quote || fc.answer,
    tag: `Flashcard ${fcIdx + 1}`,
    bbox: fc.bbox || null,
  };
  openSourceViewer(fc.document_id, fc.page || 1, state.currentViewerMaxPages, citationContext);
};

window.inspectSummaryAreaSource = function (areaIdx) {
  const a = state.lastSummaryAreas?.[areaIdx];
  if (!a || !a.document_id) return;
  const citationContext = {
    document_id: a.document_id,
    page: a.page || 1,
    quote: a.quote || a.summary,
    tag: a.area_title || 'Key Area',
    bbox: a.bbox || null,
  };
  openSourceViewer(a.document_id, a.page || 1, state.currentViewerMaxPages, citationContext);
};

window.inspectSummaryTakeawaySource = function (tIdx) {
  const t = state.lastSummaryTakeaways?.[tIdx];
  if (!t || !t.document_id) return;
  const citationContext = {
    document_id: t.document_id,
    page: t.page || 1,
    quote: t.quote || t.point,
    tag: `Takeaway ${tIdx + 1}`,
    bbox: t.bbox || null,
  };
  openSourceViewer(t.document_id, t.page || 1, state.currentViewerMaxPages, citationContext);
};

async function loadExistingFlashcards() {
  if (!state.currentWorkspaceId) return;
  try {
    const res = await apiRequest(`/workspaces/${state.currentWorkspaceId}/study/items?type=flashcard`);
    if (res && res.items && res.items.length > 0) {
      currentFlashcardsList = res.items.map((it) => it.payload).filter(Boolean);
      currentFlashcardIndex = 0;
      isFlashcardFlipped = false;
      renderFlashcardCard();
    }
  } catch {
    // Non-critical background fetch
  }
}

function bindStudyToolsEvents() {
  // Subtabs switching
  const subtabs = document.querySelectorAll('.study-subtab-btn');
  const panes = {
    summary: document.getElementById('study-summary-pane'),
    flashcards: document.getElementById('study-flashcards-pane'),
    quiz: document.getElementById('study-quiz-pane'),
    exam: document.getElementById('study-exam-pane'),
    saved: document.getElementById('study-saved-pane'),
  };

  subtabs.forEach((btn) => {
    btn.addEventListener('click', () => {
      subtabs.forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
      const tool = btn.getAttribute('data-tool');
      Object.entries(panes).forEach(([k, pane]) => {
        if (k === tool) {
          pane?.classList.remove('hidden');
          pane?.classList.add('active');
        } else {
          pane?.classList.add('hidden');
          pane?.classList.remove('active');
        }
      });
      if (tool === 'saved') loadSavedStudyItems();
      if (tool === 'exam') loadExamAnalytics();
      if (tool === 'flashcards' && currentFlashcardsList.length === 0) loadExistingFlashcards();
    });
  });

  // Summary generation
  const btnGenSummary = document.getElementById('btn-generate-summary');
  btnGenSummary?.addEventListener('click', async () => {
    if (!state.currentWorkspaceId) {
      showToast('Select a workspace first', 'error');
      return;
    }
    const lengthSelect = document.getElementById('summary-length-select');
    const container = document.getElementById('summary-output-container');
    container.innerHTML = '<div class="tool-placeholder">⏳ Generating grounded map-reduce summary & extracting key areas...</div>';

    try {
      const summaryRes = await apiRequest(`/workspaces/${state.currentWorkspaceId}/study/summary`, {
        method: 'POST',
        body: JSON.stringify({ length: lengthSelect.value }),
      });
      renderSummaryResult(summaryRes);
      showToast('Summary generated with verified citations & page links!', 'success');
    } catch (err) {
      container.innerHTML = `<div class="tool-placeholder" style="color:var(--rose)">Failed to generate summary: ${escapeHtml(err.message)}</div>`;
    }
  });

  // Reader Mode Toggle
  document.getElementById('btn-reader-mode-toggle')?.addEventListener('click', () => {
    const pane = document.getElementById('study-summary-pane');
    pane?.classList.toggle('reader-mode-active');
    const isReader = pane?.classList.contains('reader-mode-active');
    showToast(`Reader Mode ${isReader ? 'Enabled' : 'Disabled'}`, 'info');
  });

  // Flashcards generation with deck expansion and deduplication
  const btnGenCards = document.getElementById('btn-generate-flashcards');
  btnGenCards?.addEventListener('click', async () => {
    if (!state.currentWorkspaceId) {
      showToast('Select a workspace first', 'error');
      return;
    }
    const countSelect = document.getElementById('flashcards-count-select');
    const container = document.getElementById('flashcards-output-container');
    container.innerHTML = '<div class="tool-placeholder">⏳ Generating verified non-repeating flashcards...</div>';

    try {
      const res = await apiRequest(`/workspaces/${state.currentWorkspaceId}/study/flashcards`, {
        method: 'POST',
        body: JSON.stringify({ count: parseInt(countSelect.value, 10) }),
      });
      const newCards = res.flashcards || [];
      if (currentFlashcardsList.length === 0) {
        currentFlashcardsList = newCards;
        currentFlashcardIndex = 0;
      } else {
        const existingStems = new Set(currentFlashcardsList.map((c) => (c.question || '').toLowerCase().trim()));
        const uniqueCards = newCards.filter((c) => !existingStems.has((c.question || '').toLowerCase().trim()));
        const toAdd = uniqueCards.length > 0 ? uniqueCards : newCards;
        currentFlashcardIndex = currentFlashcardsList.length;
        currentFlashcardsList = currentFlashcardsList.concat(toAdd);
      }
      isFlashcardFlipped = false;
      renderFlashcardCard();
      showToast(`Added ${newCards.length} verified flashcards! Total in deck: ${currentFlashcardsList.length}`, 'success');
    } catch (err) {
      container.innerHTML = `<div class="tool-placeholder" style="color:var(--rose)">Failed: ${escapeHtml(err.message)}</div>`;
    }
  });

  // Shuffle flashcards deck
  document.getElementById('btn-shuffle-flashcards')?.addEventListener('click', () => {
    if (currentFlashcardsList.length <= 1) {
      showToast('Generate more cards to shuffle deck', 'info');
      return;
    }
    for (let i = currentFlashcardsList.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [currentFlashcardsList[i], currentFlashcardsList[j]] = [currentFlashcardsList[j], currentFlashcardsList[i]];
    }
    currentFlashcardIndex = 0;
    isFlashcardFlipped = false;
    renderFlashcardCard();
    showToast(`Shuffled deck (${currentFlashcardsList.length} cards)`, 'info');
  });

  // Clear / Fresh deck
  document.getElementById('btn-clear-flashcards')?.addEventListener('click', () => {
    currentFlashcardsList = [];
    currentFlashcardIndex = 0;
    isFlashcardFlipped = false;
    renderFlashcardCard();
    showToast('Deck reset. Click "Generate More Cards" for a fresh set.', 'info');
  });

  // Quiz generation
  const btnGenQuiz = document.getElementById('btn-generate-quiz');
  btnGenQuiz?.addEventListener('click', async () => {
    if (!state.currentWorkspaceId) {
      showToast('Select a workspace first', 'error');
      return;
    }
    const countSelect = document.getElementById('quiz-count-select');
    const diffSelect = document.getElementById('quiz-difficulty-select');
    const container = document.getElementById('quiz-output-container');
    container.innerHTML = '<div class="tool-placeholder">⏳ Generating grounded quiz questions...</div>';

    try {
      const res = await apiRequest(`/workspaces/${state.currentWorkspaceId}/study/quiz`, {
        method: 'POST',
        body: JSON.stringify({
          count: parseInt(countSelect.value, 10),
          difficulty: diffSelect.value,
        }),
      });
      renderQuizRunner(res.questions || []);
      showToast(`Generated ${res.questions?.length || 0} grounded questions!`, 'success');
    } catch (err) {
      container.innerHTML = `<div class="tool-placeholder" style="color:var(--rose)">Failed: ${escapeHtml(err.message)}</div>`;
    }
  });

  // Export buttons
  document.getElementById('btn-export-anki')?.addEventListener('click', exportAnki);
  document.getElementById('btn-download-anki-deck')?.addEventListener('click', exportAnki);
  document.getElementById('btn-download-study-guide')?.addEventListener('click', () => {
    if (!state.currentWorkspaceId) return;
    window.open(`${API_BASE}/workspaces/${state.currentWorkspaceId}/study/export/markdown`, '_blank');
  });
  document.getElementById('btn-refresh-study-items')?.addEventListener('click', loadSavedStudyItems);
}

function exportAnki() {
  if (!state.currentWorkspaceId) {
    showToast('Select a workspace first', 'error');
    return;
  }
  window.open(`${API_BASE}/workspaces/${state.currentWorkspaceId}/study/export/anki`, '_blank');
  showToast('Exporting Anki TSV deck...', 'info');
}

function renderSummaryResult(summary) {
  const container = document.getElementById('summary-output-container');
  if (!container) return;

  // 1. Referenced Pages Quick Navigator
  const pagesList = summary.referenced_pages || [];
  let pagesNavHtml = '';
  if (pagesList.length > 0) {
    const pageChips = pagesList
      .map(
        (p) => `
      <button class="page-chip-link" onclick="openSourceViewer('${p.document_id}', ${p.page})" title="Jump directly to page ${p.page} in Source Inspector">
        <span class="page-chip-icon">📄</span>
        <span>Page ${p.page} ${p.title ? `(${escapeHtml(p.title)})` : ''}</span>
      </button>
    `
      )
      .join('');

    pagesNavHtml = `
      <div class="summary-pages-navigator">
        <div class="pages-nav-header">
          <span>📍 Important Pages in Material (${pagesList.length})</span>
          <span style="font-size:0.7rem; color:var(--text-muted);">Click any page chip to inspect full region</span>
        </div>
        <div class="summary-pages-bar">${pageChips}</div>
      </div>
    `;
  }

  // 2. Important Areas & Topics Grid
  const importantAreas = summary.important_areas || [];
  state.lastSummaryAreas = importantAreas;
  state.lastSummaryTakeaways = summary.key_takeaways || [];

  let importantAreasHtml = '';
  if (importantAreas.length > 0) {
    const areaCards = importantAreas
      .map(
        (a, aIdx) => `
      <div class="important-area-card">
        <div class="area-card-header">
          <div class="area-title-text">📌 ${escapeHtml(a.area_title)}</div>
          <span class="area-page-badge">Page ${a.page || 1}</span>
        </div>
        <div class="area-card-body">${escapeHtml(a.summary)}</div>
        ${
          a.quote
            ? `<div class="area-quote-snippet">&ldquo;${escapeHtml(a.quote)}&rdquo;</div>`
            : ''
        }
        ${
          a.document_id
            ? `<button class="area-read-btn" onclick="inspectSummaryAreaSource(${aIdx})" title="Open page ${a.page || 1} with supporting quote">
                 <span>Inspect Source (Page ${a.page || 1})</span>
                 <span>↗</span>
               </button>`
            : ''
        }
      </div>
    `
      )
      .join('');

    importantAreasHtml = `
      <div class="important-areas-section">
        <div class="section-title-row">
          <h4>🌟 Core Topics & Important Areas</h4>
          <span style="font-size:0.75rem; color:var(--text-muted);">${importantAreas.length} verified areas</span>
        </div>
        <div class="important-areas-grid">${areaCards}</div>
      </div>
    `;
  }

  // 3. Takeaways list
  const takeawaysHtml = (summary.key_takeaways || [])
    .map(
      (t, tIdx) => `
    <div class="takeaway-item">
      <div>
        <div class="takeaway-text">📌 ${escapeHtml(t.point)}</div>
        <div class="takeaway-quote">&ldquo;${escapeHtml(t.quote)}&rdquo; (Page ${t.page || 1})</div>
      </div>
      ${
        t.document_id
          ? `<button class="btn-inspect-citation" onclick="inspectSummaryTakeawaySource(${tIdx})">View Page ${t.page || 1} ↗</button>`
          : ''
      }
    </div>
  `
    )
    .join('');

  const summaryText = summary.summary || '';
  const formattedSummaryHtml = escapeHtml(summaryText)
    .replace(/\n\n/g, '</p><p>')
    .replace(/\n/g, '<br>');

  container.innerHTML = `
    <div class="summary-reader-view">
      <!-- Reader Hero Bar -->
      <div class="summary-reader-hero">
        <div class="summary-hero-top">
          <h3 class="summary-hero-title">${escapeHtml(summary.title)}</h3>
          <div class="summary-meta-badges">
            <span class="summary-stat-badge active">✓ Grounded Map-Reduce</span>
            <span class="summary-stat-badge">📄 ${pagesList.length || 1} Pages Covered</span>
            <button class="btn-ghost-sm" onclick="navigator.clipboard.writeText(${JSON.stringify(summaryText)}); showToast('Summary copied to clipboard!', 'info');" title="Copy summary text">📋 Copy</button>
          </div>
        </div>
      </div>

      <!-- Quick Page Redirection Navigator -->
      ${pagesNavHtml}

      <!-- Executive Overview / Prose -->
      <div class="summary-text-prose">
        <h4 style="margin-bottom:10px; font-weight:700; color:var(--text-primary); display:flex; align-items:center; gap:6px;">
          <span>📖 Executive Synthesis</span>
        </h4>
        <p>${formattedSummaryHtml}</p>
      </div>

      <!-- Important Areas & Topics Grid -->
      ${importantAreasHtml}

      <!-- Takeaways Section -->
      <div class="takeaways-section">
        <h4>Key Takeaways (${summary.key_takeaways?.length || 0})</h4>
        ${takeawaysHtml || '<p class="tool-placeholder">No individual takeaways.</p>'}
      </div>
    </div>
  `;
}

function renderFlashcardCard() {
  const container = document.getElementById('flashcards-output-container');
  if (!container) return;

  if (currentFlashcardsList.length === 0) {
    container.innerHTML = '<div class="tool-placeholder">No flashcards generated yet.</div>';
    return;
  }

  const card = currentFlashcardsList[currentFlashcardIndex];
  container.innerHTML = `
    <div class="flashcard-viewer">
      <div id="active-flashcard" class="flashcard-card">
        <span class="flashcard-side-tag">${isFlashcardFlipped ? 'Answer (Click to flip)' : 'Question (Click to flip)'}</span>
        <div class="flashcard-prompt-text">${escapeHtml(isFlashcardFlipped ? card.answer : card.question)}</div>
        ${
          isFlashcardFlipped
            ? `<div class="flashcard-quote-box">Proof (Page ${card.page || 1}): &ldquo;${escapeHtml(card.quote)}&rdquo;</div>`
            : '<span class="flashcard-subtext">Click card or spacebar to reveal answer</span>'
        }
      </div>
      <div class="flashcard-controls">
        <button id="btn-fc-prev" class="btn-icon-sm" ${currentFlashcardIndex === 0 ? 'disabled' : ''}>◀</button>
        <span class="page-indicator">Card ${currentFlashcardIndex + 1} / ${currentFlashcardsList.length}</span>
        <button id="btn-fc-next" class="btn-icon-sm" ${currentFlashcardIndex === currentFlashcardsList.length - 1 ? 'disabled' : ''}>▶</button>
        ${
          card.document_id
            ? `<button class="btn-ghost-sm" onclick="inspectFlashcardSource(currentFlashcardIndex)">Inspect Source ↗</button>`
            : ''
        }
      </div>
    </div>
  `;

  document.getElementById('active-flashcard')?.addEventListener('click', () => {
    isFlashcardFlipped = !isFlashcardFlipped;
    renderFlashcardCard();
  });

  document.getElementById('btn-fc-prev')?.addEventListener('click', () => {
    if (currentFlashcardIndex > 0) {
      currentFlashcardIndex--;
      isFlashcardFlipped = false;
      renderFlashcardCard();
    }
  });

  document.getElementById('btn-fc-next')?.addEventListener('click', () => {
    if (currentFlashcardIndex < currentFlashcardsList.length - 1) {
      currentFlashcardIndex++;
      isFlashcardFlipped = false;
      renderFlashcardCard();
    }
  });
}

function renderQuizRunner(questions) {
  const container = document.getElementById('quiz-output-container');
  if (!container) return;

  currentQuizList = questions || [];

  if (questions.length === 0) {
    container.innerHTML = '<div class="tool-placeholder">No quiz questions generated yet.</div>';
    return;
  }

  container.innerHTML = questions
    .map((q, qIdx) => {
      const letters = ['A', 'B', 'C', 'D'];
      const optionsHtml = q.options
        .map(
          (opt, oIdx) => `
        <label class="quiz-option-label" id="opt-label-${qIdx}-${oIdx}">
          <input type="radio" name="quiz-q-${qIdx}" value="${oIdx}">
          <span><strong>${letters[oIdx]}.</strong> ${escapeHtml(opt)}</span>
        </label>
      `
        )
        .join('');

      return `
      <div class="quiz-card" id="quiz-card-${qIdx}">
        <div class="quiz-stem"><strong>Q${qIdx + 1}:</strong> ${escapeHtml(q.stem)}</div>
        <div class="quiz-options">${optionsHtml}</div>
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <button class="btn-primary-sm btn-submit-quiz-q" data-q-idx="${qIdx}">Check Answer</button>
          ${
            q.document_id
              ? `<button class="btn-icon-subtle" onclick="inspectQuizQuestionSource(${qIdx})" title="Inspect Source">View Source ↗</button>`
              : ''
          }
        </div>
        <div id="quiz-feedback-${qIdx}" class="quiz-feedback-box hidden"></div>
      </div>
    `;
    })
    .join('');

  container.querySelectorAll('.btn-submit-quiz-q').forEach((btn) => {
    btn.addEventListener('click', () => {
      const qIdx = parseInt(btn.getAttribute('data-q-idx'), 10);
      const q = questions[qIdx];
      const selected = document.querySelector(`input[name="quiz-q-${qIdx}"]:checked`);
      const feedbackBox = document.getElementById(`quiz-feedback-${qIdx}`);

      if (!selected) {
        showToast('Please select an option first', 'info');
        return;
      }

      const selVal = parseInt(selected.value, 10);
      const isCorrect = selVal === q.correct_answer_index;
      feedbackBox.classList.remove('hidden');

      // Highlight options
      q.options.forEach((_, oIdx) => {
        const lbl = document.getElementById(`opt-label-${qIdx}-${oIdx}`);
        lbl?.classList.remove('correct', 'incorrect');
        if (oIdx === q.correct_answer_index) lbl?.classList.add('correct');
        else if (oIdx === selVal && !isCorrect) lbl?.classList.add('incorrect');
      });

      feedbackBox.innerHTML = `
        <div class="quiz-feedback-header ${isCorrect ? 'correct' : 'incorrect'}">
          ${isCorrect ? '✓ Correct!' : '✗ Incorrect'}
        </div>
        <div>${escapeHtml(q.explanation)}</div>
        <div style="font-size:0.76rem; color:var(--text-muted); margin-top:4px; font-style:italic;">
          Proof: &ldquo;${escapeHtml(q.quote)}&rdquo; (Page ${q.page || 1})
        </div>
      `;
    });
  });
}

async function loadSavedStudyItems() {
  const container = document.getElementById('saved-items-container');
  if (!container || !state.currentWorkspaceId) return;

  try {
    const res = await apiRequest(`/workspaces/${state.currentWorkspaceId}/study/items`);
    const items = res.items || [];
    if (items.length === 0) {
      container.innerHTML = '<div class="tool-placeholder">No saved items yet. Generate summaries, flashcards, or quizzes above.</div>';
      return;
    }

    container.innerHTML = items
      .map((it) => {
        const title = it.payload?.title || it.payload?.question || it.payload?.stem || `${it.type} item`;
        return `
        <div class="saved-item-row" id="saved-item-${it.id}">
          <div class="saved-item-meta">
            <span class="saved-type-badge ${it.type}">${it.type}</span>
            <span style="font-weight:600; max-width:280px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
              ${escapeHtml(title)}
            </span>
          </div>
          <button class="btn-icon-subtle" onclick="deleteStudyItem('${it.id}')" title="Delete" style="color:var(--rose);">🗑</button>
        </div>
      `;
      })
      .join('');
  } catch (err) {
    container.innerHTML = `<div class="tool-placeholder" style="color:var(--rose)">Failed to load items: ${escapeHtml(err.message)}</div>`;
  }
}

async function deleteStudyItem(itemId) {
  if (!confirm('Delete this study item?')) return;
  try {
    await apiRequest(`/study/items/${itemId}`, { method: 'DELETE' });
    showToast('Item deleted', 'info');
    await loadSavedStudyItems();
  } catch (err) {
    showToast(`Delete failed: ${err.message}`, 'error');
  }
}

function applyViewerZoom() {
  const wrapper = document.getElementById('viewer-content-wrapper');
  const zoomText = document.getElementById('zoom-level-text');
  if (wrapper) wrapper.style.transform = `scale(${state.viewerZoom})`;
  if (zoomText) zoomText.textContent = `${Math.round(state.viewerZoom * 100)}%`;
}

function openFeedbackModal(messageId) {
  document.getElementById('feedback-message-id').value = messageId;
  document.getElementById('feedback-comment').value = '';
  document.getElementById('feedback-modal').classList.remove('hidden');
}

// ============================================================================
// Phase 7B: Test Me / Exam Prep Engine Logic
// ============================================================================

let currentExamSession = null;
let currentExamQuestions = [];
let currentExamIndex = 0;
let examTimerInterval = null;
let examSecondsRemaining = 0;
let examUserAnswers = {};

function initExamPrepEngine() {
  const btnStart = document.getElementById('btn-start-exam');
  btnStart?.addEventListener('click', startExamSession);

  document.getElementById('btn-runner-next')?.addEventListener('click', () => {
    if (currentExamIndex < currentExamQuestions.length - 1) {
      currentExamIndex++;
      renderExamQuestion(currentExamIndex);
    }
  });

  document.getElementById('btn-runner-prev')?.addEventListener('click', () => {
    if (currentExamIndex > 0) {
      currentExamIndex--;
      renderExamQuestion(currentExamIndex);
    }
  });

  document.getElementById('btn-runner-submit')?.addEventListener('click', submitCompleteExam);

  // Report Question Modal events
  document.getElementById('btn-report-question')?.addEventListener('click', () => {
    if (currentExamQuestions.length > 0 && currentExamQuestions[currentExamIndex]) {
      openReportQuestionModal(currentExamQuestions[currentExamIndex].id);
    }
  });

  document.getElementById('btn-close-report-modal')?.addEventListener('click', () => {
    document.getElementById('report-question-modal')?.classList.add('hidden');
  });

  document.getElementById('report-question-form')?.addEventListener('submit', handleReportQuestionSubmit);
}

async function loadExamAnalytics() {
  if (!state.currentWorkspaceId) return;
  try {
    const res = await apiRequest(`/workspaces/${state.currentWorkspaceId}/analytics`);
    const scoreDisplay = document.getElementById('readiness-score-display');
    if (scoreDisplay && res) {
      scoreDisplay.textContent = `${Math.round(res.overall_readiness_pct || 0)}%`;
    }
  } catch {
    // Non-critical background telemetry
  }
}

async function startExamSession() {
  if (!state.currentWorkspaceId) {
    showToast('Please select a workspace first', 'error');
    return;
  }

  const mode = document.getElementById('exam-mode-select').value;
  const count = parseInt(document.getElementById('exam-count-select').value, 10);
  const diff = parseInt(document.getElementById('exam-difficulty-select').value, 10);
  const timerVal = parseInt(document.getElementById('exam-timer-select').value, 10);

  const runnerCard = document.getElementById('exam-active-runner');
  const resultsCard = document.getElementById('exam-results-card');
  resultsCard.classList.add('hidden');
  runnerCard.classList.remove('hidden');

  const questionBody = document.getElementById('runner-question-card');
  questionBody.innerHTML = '<div class="tool-placeholder">⏳ Preparing syllabus assessment & sampling verified questions...</div>';

  try {
    const payload = {
      mode: mode,
      count: count,
      difficulty: diff,
      time_limit_s: timerVal > 0 ? timerVal : null,
    };

    const res = await apiRequest(`/workspaces/${state.currentWorkspaceId}/quizzes`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });

    currentExamSession = res.session_id;
    currentExamQuestions = res.questions || [];
    currentExamIndex = 0;
    examUserAnswers = {};

    // Badge
    const badge = document.getElementById('runner-mode-badge');
    if (badge) badge.textContent = `${mode.toUpperCase()} MODE`;

    // Timer setup
    const timerDisplay = document.getElementById('runner-timer-display');
    if (timerVal > 0) {
      timerDisplay.classList.remove('hidden');
      examSecondsRemaining = timerVal;
      updateTimerDisplay();
      if (examTimerInterval) clearInterval(examTimerInterval);
      examTimerInterval = setInterval(() => {
        examSecondsRemaining--;
        updateTimerDisplay();
        if (examSecondsRemaining <= 0) {
          clearInterval(examTimerInterval);
          showToast('Time limit reached! Submitting exam...', 'info');
          submitCompleteExam();
        }
      }, 1000);
    } else {
      timerDisplay.classList.add('hidden');
    }

    renderExamQuestion(0);
    showToast(`Exam session started with ${currentExamQuestions.length} questions!`, 'success');
  } catch (err) {
    questionBody.innerHTML = `<div class="tool-placeholder" style="color:var(--rose)">Failed to start assessment: ${escapeHtml(err.message)}</div>`;
  }
}

function updateTimerDisplay() {
  const el = document.getElementById('runner-timer-display');
  if (!el) return;
  const m = Math.floor(examSecondsRemaining / 60);
  const s = examSecondsRemaining % 60;
  el.textContent = `⏱️ ${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

function renderExamQuestion(index) {
  if (!currentExamQuestions || currentExamQuestions.length === 0) return;
  const q = currentExamQuestions[index];
  const container = document.getElementById('runner-question-card');
  const counter = document.getElementById('runner-progress-indicator');
  const btnPrev = document.getElementById('btn-runner-prev');
  const btnNext = document.getElementById('btn-runner-next');
  const btnSubmit = document.getElementById('btn-runner-submit');

  counter.textContent = `Question ${index + 1} of ${currentExamQuestions.length}`;
  btnPrev.disabled = index === 0;

  if (index === currentExamQuestions.length - 1) {
    btnNext.classList.add('hidden');
    btnSubmit.classList.remove('hidden');
  } else {
    btnNext.classList.remove('hidden');
    btnSubmit.classList.add('hidden');
  }

  const existingAns = examUserAnswers[q.id];
  let inputHtml = '';

  if (q.options && q.options.length > 0) {
    inputHtml = `
      <div class="runner-options-list">
        ${q.options
          .map((opt, oIdx) => {
            const isChecked = existingAns === oIdx;
            return `
            <div class="runner-opt-card ${isChecked ? 'selected' : ''}" id="runner-opt-${q.id}-${oIdx}" onclick="selectExamOption('${q.id}', ${oIdx})">
              <span class="runner-opt-key">${String.fromCharCode(65 + oIdx)}</span>
              <span class="runner-opt-text">${escapeHtml(opt)}</span>
            </div>
          `;
          })
          .join('')}
      </div>
    `;
  } else {
    // Written or numeric input
    inputHtml = `
      <div style="margin-top:10px;">
        <textarea id="runner-written-input" class="form-input" rows="3" placeholder="Type your answer here based on the course material...">${existingAns || ''}</textarea>
        <button class="btn-ghost-sm" style="margin-top:6px;" onclick="saveWrittenExamAnswer('${q.id}')">Save Draft Answer</button>
      </div>
    `;
  }

  const mode = document.getElementById('exam-mode-select')?.value;
  const checkBtnHtml =
    mode !== 'mock'
      ? `<button class="btn-primary-sm" onclick="checkInstantExamAnswer('${q.id}')" style="margin-top:14px;">Check Answer</button>`
      : '';

  container.innerHTML = `
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <span class="stage-badge" style="background:rgba(217,119,87,0.15); color:var(--primary-light); text-transform:uppercase;">${q.type}</span>
      <span style="font-size:0.8rem; color:var(--text-muted); font-weight:700;">${q.marks} Marks</span>
    </div>
    <div class="runner-q-stem">${escapeHtml(q.stem)}</div>
    ${inputHtml}
    ${checkBtnHtml}
    <div id="runner-instant-feedback" class="quiz-feedback-box hidden" style="margin-top:14px;"></div>
  `;
}

window.selectExamOption = function (qId, optionIndex) {
  examUserAnswers[qId] = optionIndex;
  document.querySelectorAll('.runner-opt-card').forEach((el) => el.classList.remove('selected'));
  const target = document.getElementById(`runner-opt-${qId}-${optionIndex}`);
  target?.classList.add('selected');
};

window.saveWrittenExamAnswer = function (qId) {
  const input = document.getElementById('runner-written-input');
  if (input) {
    examUserAnswers[qId] = input.value.trim();
    showToast('Draft answer saved', 'info');
  }
};

window.checkInstantExamAnswer = async function (qId) {
  const ans = examUserAnswers[qId];
  if (ans === undefined) {
    showToast('Please select an answer first', 'info');
    return;
  }
  const feedbackBox = document.getElementById('runner-instant-feedback');
  feedbackBox.classList.remove('hidden');
  feedbackBox.innerHTML = '<span>⏳ Grading answer against cited context...</span>';

  try {
    const res = await apiRequest(`/quizzes/${currentExamSession}/answers`, {
      method: 'POST',
      body: JSON.stringify({ question_id: qId, user_answer: ans, time_s: 10 }),
    });

    const isCorr = res.is_correct;
    feedbackBox.innerHTML = `
      <div class="quiz-feedback-header ${isCorr ? 'correct' : 'incorrect'}">
        ${isCorr ? '✓ Correct!' : '✗ Needs Review'} (Score: ${res.score}/${res.max_score})
      </div>
      <div>${escapeHtml(res.explanation || '')}</div>
      ${
        res.source_quotes && res.source_quotes[0]
          ? `<div style="font-size:0.78rem; color:var(--text-muted); margin-top:6px; font-style:italic;">
               Cited Proof: &ldquo;${escapeHtml(res.source_quotes[0])}&rdquo;
             </div>`
          : ''
      }
    `;
  } catch (err) {
    feedbackBox.innerHTML = `<span style="color:var(--rose);">Error: ${escapeHtml(err.message)}</span>`;
  }
};

async function submitCompleteExam() {
  if (!confirm('Are you ready to submit your exam paper for evaluation?')) return;
  if (examTimerInterval) clearInterval(examTimerInterval);

  const runnerCard = document.getElementById('exam-active-runner');
  const resultsCard = document.getElementById('exam-results-card');
  runnerCard.classList.add('hidden');
  resultsCard.classList.remove('hidden');
  resultsCard.innerHTML = '<div class="tool-placeholder">⏳ Computing deterministic grading, Bayesian mastery, and full report...</div>';

  try {
    const report = await apiRequest(`/quizzes/${currentExamSession}/submit`, {
      method: 'POST',
    });
    renderExamReport(report);
    showToast(`Exam completed! You scored ${report.percentage}%`, 'success');
    await loadExamAnalytics();
  } catch (err) {
    resultsCard.innerHTML = `<div class="tool-placeholder" style="color:var(--rose)">Submission failed: ${escapeHtml(err.message)}</div>`;
  }
}

function renderExamReport(report) {
  const container = document.getElementById('exam-results-card');
  if (!container) return;

  const passed = report.passed;
  const topicsHtml = (report.per_topic || [])
    .map(
      (t) => `
    <div class="topic-row">
      <span class="topic-row-name" title="${escapeHtml(t.topic_name)}">${escapeHtml(t.topic_name)}</span>
      <div class="topic-bar-track">
        <div class="topic-bar-fill" style="width: ${Math.min(100, t.percentage)}%;"></div>
      </div>
      <span class="topic-pct">${Math.round(t.percentage)}%</span>
    </div>
  `
    )
    .join('');

  const questionsReviewHtml = (report.questions || [])
    .map(
      (q, idx) => `
    <div class="quiz-card" style="margin-top:12px;">
      <div style="display:flex; justify-content:space-between;">
        <strong>Q${idx + 1}: ${escapeHtml(q.stem)}</strong>
        <span class="${q.is_correct ? 'stage-badge' : 'stage-badge'}" style="${q.is_correct ? 'color:var(--emerald); background:rgba(16,185,129,0.15);' : 'color:var(--rose); background:rgba(244,63,94,0.15);'}">
          ${q.score} / ${q.marks} Marks
        </span>
      </div>
      <div style="margin-top:8px; font-size:0.86rem;">
        <div><strong>Your Answer:</strong> ${escapeHtml(String(q.user_answer ?? 'None'))}</div>
        <div><strong>Correct Key:</strong> ${escapeHtml(String(q.correct_answer))}</div>
        <div style="color:var(--text-muted); margin-top:4px;">${escapeHtml(q.explanation)}</div>
        ${
          q.source_quotes && q.source_quotes[0]
            ? `<div style="font-size:0.78rem; color:var(--text-muted); font-style:italic; margin-top:4px;">
                 Proof: &ldquo;${escapeHtml(q.source_quotes[0])}&rdquo;
               </div>`
            : ''
        }
      </div>
    </div>
  `
    )
    .join('');

  container.innerHTML = `
    <div class="report-hero">
      <div class="report-score-box">
        <div class="score-big">${Math.round(report.percentage)}%</div>
        <div class="score-sub">${report.score} of ${report.max_score} Total Marks</div>
      </div>
      <div style="text-align:right;">
        <span class="stage-badge" style="${passed ? 'color:var(--emerald); background:var(--emerald-bg);' : 'color:var(--rose); background:var(--rose-bg);'} font-size:0.85rem; padding:4px 12px;">
          ${passed ? '✓ PASSED' : 'REVISION RECOMMENDED'}
        </span>
        <div style="font-size:0.8rem; color:var(--text-muted); margin-top:6px;">
          Duration: ${Math.floor(report.duration_s / 60)}m ${report.duration_s % 60}s
        </div>
      </div>
    </div>

    <div style="font-size:0.92rem; line-height:1.5; background:rgba(217,119,87,0.08); border-left:3px solid var(--primary); padding:10px 14px; border-radius:var(--radius-sm);">
      💡 <strong>AI Feedback:</strong> ${escapeHtml(report.encouraging_feedback)}
    </div>

    <div class="report-topics-breakdown">
      <h5 style="margin:0 0 4px; font-size:0.88rem;">Syllabus Topic Performance</h5>
      ${topicsHtml || '<div style="font-size:0.8rem; color:var(--text-muted);">General Assessment</div>'}
    </div>

    <div style="display:flex; gap:10px; flex-wrap:wrap; margin-top:8px;">
      <button class="btn-primary-sm" onclick="exportExamSession('${report.session_id}', 'anki')">Export to Anki TSV ↗</button>
      <button class="btn-ghost-sm" onclick="exportExamSession('${report.session_id}', 'markdown')">Download Exam Guide (.md) ↗</button>
      <button class="btn-ghost-sm" onclick="document.getElementById('exam-active-runner').classList.add('hidden'); document.getElementById('exam-results-card').classList.add('hidden');" style="margin-left:auto;">Back to Setup</button>
    </div>

    <div style="margin-top:16px;">
      <h5 style="margin:0 0 8px; font-size:0.9rem;">Question Review & Citations</h5>
      ${questionsReviewHtml}
    </div>
  `;
}

window.exportExamSession = function (sessId, format) {
  window.open(`${API_BASE}/quizzes/${sessId}/export?format=${format}`, '_blank');
};

function openReportQuestionModal(qId) {
  const hiddenInput = document.getElementById('report-question-id');
  if (hiddenInput) hiddenInput.value = qId;
  document.getElementById('report-question-modal')?.classList.remove('hidden');
}

async function handleReportQuestionSubmit(e) {
  e.preventDefault();
  const qId = document.getElementById('report-question-id')?.value;
  const reason = document.getElementById('report-reason-select')?.value;
  const comment = document.getElementById('report-comment-input')?.value;

  try {
    await apiRequest(`/questions/${qId}/report`, {
      method: 'POST',
      body: JSON.stringify({ reason, comment }),
    });
    document.getElementById('report-question-modal')?.classList.add('hidden');
    showToast('Question reported and retired from future exams!', 'info');
  } catch (err) {
    showToast(`Report failed: ${err.message}`, 'error');
  }
}

// Start app on DOMContentLoaded
window.addEventListener('DOMContentLoaded', initApp);

