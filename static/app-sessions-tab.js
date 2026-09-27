// app-sessions-tab.js -- split out of app.js (APP_SPLIT_v1, docs/plans/monolith-split.md Phase 5). Declarations only: it
// loads before app.js, which runs everything that happens at load (listeners, timers, boot). Top-level code
// here may use the page's DOM, never a binding from a later file.
async function fetchSessionsList(retryCount = 0) {
  if (!sessionsListEl) return;
  sessionsListEl.innerHTML = '<div class="status-hint">불러오는 중…' + (retryCount > 0 ? ' (재시도 중)' : '') + '</div>';
  try {
    const res = await api('/api/sessions');
    renderSessionsList(res.sessions || []);
  } catch (e) {
    if (retryCount < 1) {
      setTimeout(() => fetchSessionsList(retryCount + 1), 600);
      return;
    }
    sessionsListEl.innerHTML =
      '<div class="status-hint">' +
      '세션 목록 로드 실패: ' + escapeHtml(e.message) + ' ' +
      '<button type="button" class="btn-xs" style="margin-left:6px;cursor:pointer;" onclick="fetchSessionsList(0)">다시 시도 ↻</button>' +
      '</div>';
  }
}

function sessionRowWho(s) {
  if (!s || !s.character) return '';
  const c = characterCatalog.find(x => x.id === s.character);
  return (c ? c.name : s.character.slice(0, 10)) + ' · ';
}

function renderSessionsList(sessions) {
  if (!sessionsListEl) return;
  sessionsListEl.innerHTML = '';
  // Hide empty throwaway sessions (e.g. repeated "새 세션" clicks nobody
  // typed into) -- they clutter the list with nothing useful to open --
  // but never hide the one currently open, even if it happens to be empty.
  const visible = sessions.filter(s => s.preview || s.id === sessionId);
  if (!visible.length) {
    sessionsListEl.innerHTML = '<div class="status-hint">세션이 없습니다.</div>';
    return;
  }
  visible.forEach(s => {
    const isCurrent = s.id === sessionId;
    const item = document.createElement('div');
    item.className = 'status-item session-row' + (isCurrent ? ' current' : '');
    let when = s.updated_at || '';
    try { when = new Date(_scrollbackEpochMs(s.updated_at)).toLocaleString('ko-KR'); } catch (_) {}
    item.innerHTML =
      '<div class="status-item-head">' +
      '<span class="session-row-id">' + (s.mode === 'private' ? '🔒 ' : '') + escapeHtml(sessionRowWho(s)) + escapeHtml(s.id) + (isCurrent ? ' (현재)' : '') + '</span>' +
      '<span class="status-item-meta">' + (s.turns || 0) + '턴 · ' + escapeHtml(s.model || '') + ' · ' + escapeHtml(when) + '</span>' +
      '<div class="status-item-actions">' +
      '<button class="session-import-btn" data-import-sid="' + escapeHtml(s.id) + '" type="button">' + getActionSvg('pin') + ' 가져오기</button>' +
      '<button class="session-import-btn session-delete-btn" data-delete-sid="' + escapeHtml(s.id) + '" type="button">' + getActionSvg('trash', 'text-danger') + ' 삭제</button>' +
      '</div>' +
      '</div>' +
      '<div class="session-row-preview">' + escapeHtml(s.preview || '(내용 없음)') + '</div>';
    item.addEventListener('click', (ev) => {
      if (ev.target.closest('[data-import-sid], [data-delete-sid]')) return;
      if (s.id !== sessionId) openSession(s.id, 0, null, true);
      switchTab('chat');
    });
    sessionsListEl.appendChild(item);
  });
  sessionsListEl.querySelectorAll('[data-import-sid]').forEach(btn => {
    btn.addEventListener('click', (ev) => {
      ev.stopPropagation();
      importSessionContext(btn.getAttribute('data-import-sid'));
    });
  });
  sessionsListEl.querySelectorAll('[data-delete-sid]').forEach(btn => {
    btn.addEventListener('click', (ev) => {
      ev.stopPropagation();
      deleteSession(btn.getAttribute('data-delete-sid'));
    });
  });
}

async function deleteSession(sid) {
  if (!sid) return;
  if (!(await confirmModal('세션 ' + sid + '을(를) 완전히 삭제할까요? 대화 기록과 생성된 이미지가 전부 사라지며 되돌릴 수 없습니다.', { confirmLabel: '삭제' }))) return;
  try {
    const res = await api('/api/sessions/' + encodeURIComponent(sid), { method: 'DELETE' });
    if (!res || res.ok === false) throw new Error((res && res.error) || '삭제 실패');
    if (sid === sessionId) {
      // The session we're currently looking at just got deleted -- fall
      // back exactly the way a fresh page load would (ensureSession's own
      // active/localStorage/latest/create chain), instead of a separate,
      // narrower reimplementation of just its "latest or create" tail.
      rememberSession('');
      await ensureSession();
    }
    fetchSessionsList();
  } catch (e) {
    await alertModal('세션 삭제 실패: ' + (e.message || e));
  }
}

// Fetches a read-only handover-style summary of an arbitrary (often archived)
// session and prefills the composer with it, labeled by source session id.
// Never auto-sends -- operator reviews/edits before it becomes part of the live
// conversation, and the target session itself is never modified.
async function importSessionContext(sid) {
  if (!sid) return;
  const prevPlaceholder = inputEl ? inputEl.placeholder : '';
  if (inputEl) inputEl.placeholder = '세션 ' + sid + ' 요약 가져오는 중…';
  try {
    const res = await api('/api/sessions/' + encodeURIComponent(sid) + '/summary');
    const summary = (res && res.summary) || '(요약할 내용이 없습니다)';
    const note = '[이전 세션 ' + sid + ' 내용 참고]\n' + summary + '\n\n';
    if (inputEl) {
      inputEl.value = note + (inputEl.value || '');
      inputEl.focus();
      inputEl.style.height = 'auto';
      inputEl.style.height = inputEl.scrollHeight + 'px';
      updateSendButton();
    }
    switchTab('chat');
  } catch (e) {
    await alertModal('세션 요약 가져오기 실패: ' + (e.message || e));
  } finally {
    if (inputEl) inputEl.placeholder = prevPlaceholder;
  }
}

// STATUS_INSTRUCTIONS_v1: everything the agent reads as instructions, whole and scrollable, in the order it reaches
