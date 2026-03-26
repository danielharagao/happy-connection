const APP_BASE_PATH = (() => {
  const p = window.location.pathname || '/';
  const marker = '/mission-control';
  const idx = p.indexOf(marker);
  return idx >= 0 ? marker : '';
})();

function withAppBase(path) {
  if (!path) return path;
  if (/^https?:\/\//i.test(path)) return path;
  if (APP_BASE_PATH && path.startsWith('/') && !path.startsWith(APP_BASE_PATH + '/')) return `${APP_BASE_PATH}${path}`;
  if (APP_BASE_PATH && !path.startsWith('/')) return `${APP_BASE_PATH}/${path}`;
  return path;
}

async function api(path, options = {}) {
  const res = await fetch(withAppBase(path), {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Request failed: ${res.status}`);
  return data;
}

function setStatus(id, msg, isError = false) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = msg || '';
  el.className = isError ? 'status error' : 'status';
}

function escapeHtml(value) {
  return String(value || '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function activateTab(tabKey) {
  const tabs = Array.from(document.querySelectorAll('.tabs .tab[data-target]'));
  const panels = Array.from(document.querySelectorAll('.tab-panel[data-panel]'));
  const targetTab = tabs.find((el) => el.dataset.target === tabKey);
  const targetPanel = panels.find((el) => el.dataset.panel === tabKey);
  if (!targetTab || !targetPanel) return;

  tabs.forEach((tab) => {
    const active = tab === targetTab;
    tab.classList.toggle('active', active);
    tab.setAttribute('aria-selected', active ? 'true' : 'false');
  });
  panels.forEach((panel) => panel.classList.toggle('is-hidden', panel !== targetPanel));
  window.location.hash = `#${tabKey}`;
  setStatus('nav-status', '');
  if (tabKey === 'knowledge') loadKnowledge(knowledgeState.selectedId).catch(() => {});
  if (tabKey === 'albert') loadAlbertSessions().catch(() => {});
  if (tabKey === 'fluxo') loadFluxo().catch(() => {});
  if (tabKey === 'sdr') loadSDRDashboard().catch(() => {});
  if (tabKey === 'sdr-scripts') loadSDRScripts().catch(() => {});
}

function initTabs() {
  document.querySelector('.tabs')?.addEventListener('click', (evt) => {
    const btn = evt.target.closest('.tab[data-target]');
    if (!btn) return;
    activateTab(btn.dataset.target);
  });
  const hashTab = String(window.location.hash || '').replace(/^#/, '').trim();
  activateTab(hashTab || 'crm');
}

function initNavToggle() {
  const shell = document.querySelector('.app-shell');
  const btn = document.getElementById('nav-toggle-btn');
  if (!shell || !btn) return;

  const key = 'crm.navCollapsed';
  const apply = (collapsed) => {
    shell.classList.toggle('nav-collapsed', !!collapsed);
    btn.textContent = collapsed ? '▶' : '◀';
    btn.title = collapsed ? 'Expandir menu' : 'Comprimir menu';
    btn.setAttribute('aria-label', collapsed ? 'Expandir menu' : 'Comprimir menu');
  };

  let collapsed = false;
  try {
    collapsed = localStorage.getItem(key) === '1';
  } catch (_) {}
  apply(collapsed);

  btn.addEventListener('click', () => {
    collapsed = !shell.classList.contains('nav-collapsed');
    apply(collapsed);
    try { localStorage.setItem(key, collapsed ? '1' : '0'); } catch (_) {}
  });
}

function setText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value;
}

const knowledgeState = {
  docs: [],
  selectedId: '',
  loading: false,
  saving: false,
  saveTimer: null,
  lastSavedContent: '',
  suppressInput: false,
};

function renderKnowledgePanel(data = null) {
  const statusEl = document.getElementById('knowledge-status');
  const listEl = document.getElementById('knowledge-list');
  const pageEl = document.getElementById('knowledge-page');
  if (!statusEl || !listEl || !pageEl) return;

  if (data && Array.isArray(data.docs)) knowledgeState.docs = data.docs;
  if (data && data.selected && data.selected.id) knowledgeState.selectedId = String(data.selected.id);

  const docs = Array.isArray(knowledgeState.docs) ? knowledgeState.docs : [];
  listEl.innerHTML = docs.map((doc) => {
    const id = String(doc?.id || '');
    const active = id && id === knowledgeState.selectedId;
    const disabled = !doc?.exists;
    const title = String(doc?.title || id || 'Documento');
    return `<button type="button" class="crm-tag-chip ${active ? 'active' : ''}" data-action="knowledge-doc" data-doc-id="${escapeHtml(id)}" ${disabled ? 'disabled' : ''}>${escapeHtml(title)}</button>`;
  }).join('');

  if (knowledgeState.loading) {
    statusEl.className = 'status';
    statusEl.textContent = 'Carregando KB...';
  }

  if (data && typeof data.content === 'string') {
    const selected = data.selected || {};
    const updatedAt = selected?.updatedAt ? new Date(selected.updatedAt).toLocaleString('pt-BR', { hour12: false }) : '-';
    knowledgeState.suppressInput = true;
    pageEl.textContent = data.content || '';
    knowledgeState.suppressInput = false;
    knowledgeState.lastSavedContent = data.content || '';
    statusEl.className = 'status';
    statusEl.textContent = `Doc: ${selected?.title || 'Documento'} · Atualizado: ${updatedAt}`;
  }
}

async function loadKnowledge(docId = '') {
  if (knowledgeState.loading) return;
  knowledgeState.loading = true;
  renderKnowledgePanel();
  try {
    const q = docId ? `?doc=${encodeURIComponent(docId)}` : '';
    const out = await api(`/api/knowledge/mission-control${q}`);
    renderKnowledgePanel(out);
  } catch (err) {
    const statusEl = document.getElementById('knowledge-status');
    if (statusEl) {
      statusEl.className = 'status error';
      statusEl.textContent = err?.message || 'Falha ao carregar Knowledge Base.';
    }
  } finally {
    knowledgeState.loading = false;
  }
}

async function saveKnowledgeNow() {
  const pageEl = document.getElementById('knowledge-page');
  const statusEl = document.getElementById('knowledge-status');
  if (!pageEl || !knowledgeState.selectedId) return;
  const content = String(pageEl.textContent || '');
  if (content === knowledgeState.lastSavedContent) return;

  knowledgeState.saving = true;
  if (statusEl) {
    statusEl.className = 'status';
    statusEl.textContent = 'Salvando KB...';
  }

  try {
    const out = await api('/api/knowledge/mission-control/save', {
      method: 'POST',
      body: JSON.stringify({ doc: knowledgeState.selectedId, content }),
    });
    knowledgeState.lastSavedContent = content;
    if (statusEl) {
      statusEl.className = 'status';
      statusEl.textContent = `Salvo automaticamente (${new Date(out?.updatedAt || Date.now()).toLocaleTimeString('pt-BR')})`;
    }
  } catch (err) {
    if (statusEl) {
      statusEl.className = 'status error';
      statusEl.textContent = err?.message || 'Falha ao salvar KB.';
    }
  } finally {
    knowledgeState.saving = false;
  }
}

async function createKnowledgeDoc() {
  const title = window.prompt('Nome do novo arquivo no Mission KB:');
  if (!title || !String(title).trim()) return;
  const statusEl = document.getElementById('knowledge-status');
  try {
    if (statusEl) {
      statusEl.className = 'status';
      statusEl.textContent = 'Criando arquivo...';
    }
    const out = await api('/api/knowledge/mission-control/create', {
      method: 'POST',
      body: JSON.stringify({ title: String(title).trim(), content: `# ${String(title).trim()}\n\n` }),
    });
    const docId = String(out?.doc?.id || '').trim();
    knowledgeState.selectedId = docId;
    await loadKnowledge(docId);
  } catch (err) {
    if (statusEl) {
      statusEl.className = 'status error';
      statusEl.textContent = err?.message || 'Falha ao criar arquivo.';
    }
  }
}

async function deleteKnowledgeDoc() {
  const docId = String(knowledgeState.selectedId || '').trim();
  if (!docId) return;
  const selected = (knowledgeState.docs || []).find((d) => String(d?.id || '') === docId);
  const label = selected?.title || docId;
  const ok = window.confirm(`Deletar o arquivo "${label}"? Essa ação não pode ser desfeita.`);
  if (!ok) return;

  const statusEl = document.getElementById('knowledge-status');
  try {
    if (statusEl) {
      statusEl.className = 'status';
      statusEl.textContent = 'Deletando arquivo...';
    }
    await api(`/api/knowledge/mission-control/doc/${encodeURIComponent(docId)}`, { method: 'DELETE' });
    knowledgeState.selectedId = '';
    await loadKnowledge('');
  } catch (err) {
    if (statusEl) {
      statusEl.className = 'status error';
      statusEl.textContent = err?.message || 'Falha ao deletar arquivo.';
    }
  }
}

function scheduleKnowledgeAutosave() {
  if (knowledgeState.saveTimer) window.clearTimeout(knowledgeState.saveTimer);
  knowledgeState.saveTimer = window.setTimeout(() => {
    saveKnowledgeNow().catch(() => {});
  }, 1200);
}

const fluxoState = {
  loading: false,
  saving: false,
  updatedAt: null,
  cadences: [],
  selectedCadenceId: null,
  options: { statuses: [], labels: [], origins: [] },
};

function fluxoDefaultStep(index = 0) {
  return {
    id: `step-${Date.now()}-${index}-${Math.random().toString(36).slice(2, 8)}`,
    order: index,
    message: '',
    intervalValue: 1,
    intervalUnit: 'minutes',
  };
}

function defaultCadence(index = 0) {
  return {
    id: `cad-${Date.now()}-${index}-${Math.random().toString(36).slice(2, 8)}`,
    name: `Cadência ${index + 1}`,
    isActive: false,
    stopWhenReply: true,
    audience: { status: '', label: '', origin: '' },
    messages: [],
    __isNew: true,
  };
}

function selectedCadence() {
  return (fluxoState.cadences || []).find((c) => String(c?.id || '') === String(fluxoState.selectedCadenceId || '')) || null;
}

function cadenceAudienceSummary(cadence) {
  const audience = cadence?.audience || {};
  const chunks = [];
  if (audience.status) chunks.push(`Status: ${audience.status}`);
  if (audience.label) chunks.push(`Label: ${audience.label}`);
  if (audience.origin) chunks.push(`Origem: ${audience.origin}`);
  return chunks.length ? chunks.join(' · ') : 'Sem audiência definida';
}

function renderCadenceOptionsSelect(el, items, value) {
  if (!el) return;
  const safeItems = Array.isArray(items) ? items : [];
  el.innerHTML = `<option value="">Selecione…</option>${safeItems.map((item) => `<option value="${escapeHtml(item)}">${escapeHtml(item)}</option>`).join('')}`;
  el.value = String(value || '');
}

function renderCadenciasList() {
  const root = document.getElementById('cadencias-list');
  if (!root) return;
  const cadences = Array.isArray(fluxoState.cadences) ? fluxoState.cadences : [];
  if (!cadences.length) {
    root.innerHTML = '<p class="muted">Nenhuma cadência criada ainda.</p>';
    return;
  }

  root.innerHTML = cadences.map((cad) => `
    <article class="fluxo-step" data-cadence-id="${escapeHtml(cad.id || '')}">
      <div class="fluxo-step-head">
        <span class="fluxo-step-title">${escapeHtml(cad.name || 'Cadência')}</span>
        <div class="fluxo-step-actions">
          <button type="button" class="quick-action" data-action="cadencia-open" data-cadence-id="${escapeHtml(cad.id || '')}">Abrir</button>
          <button type="button" class="quick-action" data-action="cadencia-toggle" data-cadence-id="${escapeHtml(cad.id || '')}">${cad.isActive ? 'ON' : 'OFF'}</button>
          <button type="button" class="quick-action danger" data-action="cadencia-delete" data-cadence-id="${escapeHtml(cad.id || '')}">Excluir</button>
        </div>
      </div>
      <p class="muted">${escapeHtml(cadenceAudienceSummary(cad))}</p>
      <p class="muted">Mensagens: ${(Array.isArray(cad.messages) ? cad.messages.length : 0)}</p>
    </article>
  `).join('');
}

function validateSelectedCadence() {
  const cad = selectedCadence();
  if (!cad) return ['Cadência não encontrada.'];
  const audience = cad.audience || {};
  const hasAudience = !!(audience.status || audience.label || audience.origin);
  const hasMessages = Array.isArray(cad.messages) && cad.messages.length > 0;
  const errors = [];
  if (!hasAudience) errors.push('Selecione pelo menos 1 critério de audiência.');
  if (!hasMessages) errors.push('Cadência precisa ter pelo menos 1 mensagem.');
  return errors;
}

function renderCadenciaDetail() {
  const cad = selectedCadence();
  const listEl = document.getElementById('fluxo-steps-list');
  const validationEl = document.getElementById('cadencia-validation');
  if (!cad || !listEl) return;

  const nameEl = document.getElementById('cadencia-name');
  const activeEl = document.getElementById('fluxo-toggle-active');
  const stopOnReplyEl = document.getElementById('fluxo-toggle-stop-on-reply');
  if (nameEl) nameEl.value = String(cad.name || '');
  if (activeEl) activeEl.checked = !!cad.isActive;
  if (stopOnReplyEl) stopOnReplyEl.checked = !!cad.stopWhenReply;

  renderCadenceOptionsSelect(document.getElementById('cadencia-audience-status'), fluxoState.options.statuses, cad?.audience?.status || '');
  renderCadenceOptionsSelect(document.getElementById('cadencia-audience-label'), fluxoState.options.labels, cad?.audience?.label || '');
  renderCadenceOptionsSelect(document.getElementById('cadencia-audience-origin'), fluxoState.options.origins, cad?.audience?.origin || '');

  const messages = Array.isArray(cad.messages) ? cad.messages : [];
  if (!messages.length) {
    listEl.innerHTML = '<p class="muted">Nenhuma mensagem ainda.</p>';
  } else {
    listEl.innerHTML = messages.map((step, idx) => `
      <article class="fluxo-step" data-step-id="${escapeHtml(step.id || '')}">
        <div class="fluxo-step-head">
          <span class="fluxo-step-title">Mensagem ${idx + 1}</span>
          <div class="fluxo-step-actions">
            <button type="button" class="quick-action" data-action="fluxo-step-up" data-step-id="${escapeHtml(step.id || '')}" ${idx === 0 ? 'disabled' : ''}>↑</button>
            <button type="button" class="quick-action" data-action="fluxo-step-down" data-step-id="${escapeHtml(step.id || '')}" ${idx === messages.length - 1 ? 'disabled' : ''}>↓</button>
            <button type="button" class="quick-action danger" data-action="fluxo-step-remove" data-step-id="${escapeHtml(step.id || '')}">Remover</button>
          </div>
        </div>
        <div class="fluxo-step-grid">
          <label>Texto
            <textarea data-field="message" data-step-id="${escapeHtml(step.id || '')}">${escapeHtml(step.message || '')}</textarea>
          </label>
          <label>Intervalo
            <input type="number" min="1" max="9999" step="1" data-field="intervalValue" data-step-id="${escapeHtml(step.id || '')}" value="${Number(step.intervalValue || 1)}" />
          </label>
          <label>Unidade
            <select data-field="intervalUnit" data-step-id="${escapeHtml(step.id || '')}">
              <option value="minutes" ${String(step.intervalUnit) === 'minutes' ? 'selected' : ''}>Minutos</option>
              <option value="hours" ${String(step.intervalUnit) === 'hours' ? 'selected' : ''}>Horas</option>
              <option value="days" ${String(step.intervalUnit) === 'days' ? 'selected' : ''}>Dias</option>
            </select>
          </label>
        </div>
      </article>
    `).join('');
  }

  const errors = validateSelectedCadence();
  if (validationEl) {
    validationEl.textContent = errors.join(' ');
    validationEl.className = errors.length ? 'status error' : 'status';
  }
}

function renderFluxo() {
  const listScreen = document.getElementById('cadencias-list-screen');
  const detailScreen = document.getElementById('cadencias-detail-screen');
  const inDetail = !!selectedCadence();
  if (listScreen) listScreen.classList.toggle('is-hidden', inDetail);
  if (detailScreen) detailScreen.classList.toggle('is-hidden', !inDetail);
  if (inDetail) renderCadenciaDetail(); else renderCadenciasList();
}

function moveFluxoStepById(stepId, direction) {
  const cad = selectedCadence();
  if (!cad) return;
  const steps = Array.isArray(cad.messages) ? [...cad.messages] : [];
  const idx = steps.findIndex((s) => String(s.id || '') === String(stepId || ''));
  if (idx < 0) return;
  const nextIdx = direction === 'up' ? idx - 1 : idx + 1;
  if (nextIdx < 0 || nextIdx >= steps.length) return;
  const current = steps[idx];
  steps[idx] = steps[nextIdx];
  steps[nextIdx] = current;
  cad.messages = steps.map((item, order) => ({ ...item, order }));
  renderCadenciaDetail();
}

function updateFluxoStepField(stepId, field, value) {
  const cad = selectedCadence();
  if (!cad) return;
  const idx = (cad.messages || []).findIndex((s) => String(s.id || '') === String(stepId || ''));
  if (idx < 0) return;
  const current = { ...(cad.messages[idx] || {}) };
  if (field === 'message') current.message = String(value || '').slice(0, 4000);
  if (field === 'intervalValue') {
    const n = Number.parseInt(String(value || '1'), 10);
    current.intervalValue = Number.isFinite(n) ? Math.min(9999, Math.max(1, n)) : 1;
  }
  if (field === 'intervalUnit') current.intervalUnit = ['minutes', 'hours', 'days'].includes(String(value || '')) ? String(value) : 'minutes';
  cad.messages[idx] = current;
}

function buildCadencePayload(cadence) {
  return {
    id: String(cadence?.id || ''),
    name: String(cadence?.name || '').trim() || 'Cadência sem nome',
    isActive: !!cadence?.isActive,
    stopWhenReply: !!cadence?.stopWhenReply,
    audience: {
      status: String(cadence?.audience?.status || '').trim(),
      label: String(cadence?.audience?.label || '').trim(),
      origin: String(cadence?.audience?.origin || '').trim(),
    },
    messages: (cadence?.messages || []).map((step, index) => ({
      id: String(step.id || `step-${index + 1}`),
      order: index,
      message: String(step.message || '').trim(),
      intervalValue: Math.max(1, Number.parseInt(String(step.intervalValue || '1'), 10) || 1),
      intervalUnit: ['minutes', 'hours', 'days'].includes(String(step.intervalUnit || '')) ? String(step.intervalUnit) : 'minutes',
    })).filter((m) => m.message),
  };
}

async function loadFluxo() {
  if (fluxoState.loading) return;
  fluxoState.loading = true;
  const statusEl = document.getElementById('fluxo-status');
  if (statusEl) setStatus('fluxo-status', 'Carregando cadências...');
  try {
    const [cadOut, optOut] = await Promise.all([
      api('/api/crm/bridge/cadences'),
      api('/api/crm/bridge/cadences/options').catch(() => ({ options: { statuses: [], labels: [], origins: [] } })),
    ]);
    fluxoState.cadences = Array.isArray(cadOut?.cadences) ? cadOut.cadences : [];
    fluxoState.updatedAt = cadOut?.updatedAt || null;
    fluxoState.options = optOut?.options || { statuses: [], labels: [], origins: [] };
    renderFluxo();
    if (statusEl) setStatus('fluxo-status', fluxoState.updatedAt ? `Atualizado em ${new Date(fluxoState.updatedAt).toLocaleString('pt-BR')}` : 'Cadências carregadas.');
  } catch (err) {
    if (statusEl) setStatus('fluxo-status', err?.message || 'Falha ao carregar cadências.', true);
  } finally {
    fluxoState.loading = false;
  }
}

async function saveSelectedCadence() {
  const cad = selectedCadence();
  if (!cad) return;
  const statusEl = document.getElementById('fluxo-status');
  const payload = buildCadencePayload(cad);
  const errors = validateSelectedCadence();
  if (errors.length) {
    const validationEl = document.getElementById('cadencia-validation');
    if (validationEl) {
      validationEl.textContent = errors.join(' ');
      validationEl.className = 'status error';
    }
    return;
  }

  fluxoState.saving = true;
  if (statusEl) setStatus('fluxo-status', 'Salvando cadência...');
  try {
    const method = cad.__isNew ? 'POST' : 'PUT';
    const path = method === 'PUT'
      ? `/api/crm/bridge/cadences/${encodeURIComponent(payload.id)}`
      : '/api/crm/bridge/cadences';
    await api(path, { method, body: JSON.stringify({ cadence: payload }) });
    await loadFluxo();
    fluxoState.selectedCadenceId = payload.id;
    renderFluxo();
    if (statusEl) setStatus('fluxo-status', 'Cadência salva com sucesso.');
  } catch (err) {
    if (statusEl) setStatus('fluxo-status', err?.message || 'Falha ao salvar cadência.', true);
  } finally {
    fluxoState.saving = false;
  }
}

function initFluxoListeners() {
  document.getElementById('cadencia-new-btn')?.addEventListener('click', () => {
    const cad = defaultCadence((fluxoState.cadences || []).length);
    fluxoState.cadences.push(cad);
    fluxoState.selectedCadenceId = cad.id;
    renderFluxo();
  });

  document.getElementById('cadencia-back-btn')?.addEventListener('click', () => {
    fluxoState.selectedCadenceId = null;
    renderFluxo();
  });

  document.getElementById('cadencia-save-btn')?.addEventListener('click', () => {
    saveSelectedCadence().catch(() => {});
  });

  document.getElementById('cadencias-list')?.addEventListener('click', (evt) => {
    const btn = evt.target.closest('[data-action][data-cadence-id]');
    if (!btn) return;
    const cadenceId = String(btn.dataset.cadenceId || '');
    const cad = (fluxoState.cadences || []).find((x) => String(x.id || '') === cadenceId);
    if (!cad) return;

    if (btn.dataset.action === 'cadencia-open') {
      fluxoState.selectedCadenceId = cadenceId;
      renderFluxo();
      return;
    }

    if (btn.dataset.action === 'cadencia-toggle') {
      cad.isActive = !cad.isActive;
      api(`/api/crm/bridge/cadences/${encodeURIComponent(cadenceId)}`, {
        method: 'PUT',
        body: JSON.stringify({ cadence: buildCadencePayload(cad) }),
      }).then(() => loadFluxo())
        .catch((err) => setStatus('fluxo-status', err?.message || 'Falha ao atualizar cadência.', true));
      renderFluxo();
      return;
    }

    if (btn.dataset.action === 'cadencia-delete') {
      if (!window.confirm('Excluir esta cadência?')) return;
      api(`/api/crm/bridge/cadences/${encodeURIComponent(cadenceId)}`, { method: 'DELETE' })
        .then(() => loadFluxo())
        .catch((err) => setStatus('fluxo-status', err?.message || 'Falha ao excluir cadência.', true));
    }
  });

  document.getElementById('cadencia-name')?.addEventListener('input', (evt) => {
    const cad = selectedCadence();
    if (!cad) return;
    cad.name = String(evt.target?.value || '');
  });

  document.getElementById('fluxo-toggle-active')?.addEventListener('change', (evt) => {
    const cad = selectedCadence();
    if (!cad) return;
    cad.isActive = !!evt.target?.checked;
  });

  document.getElementById('fluxo-toggle-stop-on-reply')?.addEventListener('change', (evt) => {
    const cad = selectedCadence();
    if (!cad) return;
    cad.stopWhenReply = !!evt.target?.checked;
  });

  ['status', 'label', 'origin'].forEach((field) => {
    document.getElementById(`cadencia-audience-${field}`)?.addEventListener('change', (evt) => {
      const cad = selectedCadence();
      if (!cad) return;
      cad.audience = { ...(cad.audience || {}), [field]: String(evt.target?.value || '') };
      renderCadenciaDetail();
    });
  });

  document.getElementById('fluxo-add-step-btn')?.addEventListener('click', () => {
    const cad = selectedCadence();
    if (!cad) return;
    cad.messages = Array.isArray(cad.messages) ? cad.messages : [];
    cad.messages.push(fluxoDefaultStep(cad.messages.length));
    renderCadenciaDetail();
  });

  document.getElementById('fluxo-steps-list')?.addEventListener('click', (evt) => {
    const target = evt.target.closest('[data-action][data-step-id]');
    if (!target) return;
    const stepId = String(target.dataset.stepId || '');
    const cad = selectedCadence();
    if (!cad) return;
    if (target.dataset.action === 'fluxo-step-remove') {
      cad.messages = (cad.messages || []).filter((s) => String(s.id || '') !== stepId).map((item, order) => ({ ...item, order }));
      renderCadenciaDetail();
      return;
    }
    if (target.dataset.action === 'fluxo-step-up') moveFluxoStepById(stepId, 'up');
    if (target.dataset.action === 'fluxo-step-down') moveFluxoStepById(stepId, 'down');
  });

  document.getElementById('fluxo-steps-list')?.addEventListener('input', (evt) => {
    const input = evt.target.closest('[data-field][data-step-id]');
    if (!input) return;
    updateFluxoStepField(String(input.dataset.stepId || ''), String(input.dataset.field || ''), input.value);
  });

  document.getElementById('fluxo-steps-list')?.addEventListener('change', (evt) => {
    const input = evt.target.closest('[data-field][data-step-id]');
    if (!input) return;
    updateFluxoStepField(String(input.dataset.stepId || ''), String(input.dataset.field || ''), input.value);
    renderCadenciaDetail();
  });
}

const CRM_COLUMNS = [
  'Novos',
  'Primeira Mensagem Enviada',
  'Agendamento Realizado',
  'Reunião Realizada',
  'Oferta Enviada',
  'Interessado',
  'Quer Agendar',
  'Proposta Enviada',
  'Promessa Pagamento',
  'Parceria Interesse',
  'Parceria Sem Interess',
  'Alunos/Suporte',
  'Sem Resposta',
];

const CRM_IS_BA_FILTER_KEY = 'crm.quickFilter.isBa';
const CRM_LEADS_SEARCH_KEY = 'crm.leads.searchText';
const CRM_IS_BA_FILTER_VALUES = ['all', 'ba', 'nao-ba'];

function crmReadIsBaFilterFromStorage() {
  try {
    const raw = String(localStorage.getItem(CRM_IS_BA_FILTER_KEY) || '').trim();
    return CRM_IS_BA_FILTER_VALUES.includes(raw) ? raw : 'all';
  } catch (_) {
    return 'all';
  }
}

function crmPersistIsBaFilter(value) {
  try { localStorage.setItem(CRM_IS_BA_FILTER_KEY, value); } catch (_) {}
}

function crmReadLeadsSearchTextFromStorage() {
  try {
    return String(localStorage.getItem(CRM_LEADS_SEARCH_KEY) || '').trim().slice(0, 120);
  } catch (_) {
    return '';
  }
}

function crmPersistLeadsSearchText(value) {
  try { localStorage.setItem(CRM_LEADS_SEARCH_KEY, String(value || '').trim().slice(0, 120)); } catch (_) {}
}

const crmState = {
  leads: [],
  selectedLeadId: null,
  selectedLeadIds: [],
  trayTab: 'details',
  operationalByLeadId: {},
  operationalErrorByLeadId: {},
  operationalLoadingLeadId: null,
  notesByLeadId: {},
  notesErrorByLeadId: {},
  notesLoadingLeadId: null,
  noteDraftByLeadId: {},
  noteSavingLeadId: null,
  editingLeadId: null,
  editDraft: null,
  savingLead: false,
  mergeContext: null,
  draggingLeadId: null,
  dragOverColumn: null,
  updatingLeadIds: new Set(),
  quickFilterIsBa: crmReadIsBaFilterFromStorage(),
  searchText: crmReadLeadsSearchTextFromStorage(),
};

function closeCrmLeadTray() {
  if (!crmState.selectedLeadId) return;
  crmState.selectedLeadId = null;
  crmState.editingLeadId = null;
  crmState.editDraft = null;
  crmState.savingLead = false;
  renderCrmBoard();
  renderCrmLeadTray();
}

function onDocumentClickCloseTray(evt) {
  if (!crmState.selectedLeadId) return;
  if (!document.getElementById('crm-merge-modal')?.classList.contains('is-hidden')) return;
  const inTray = evt.target.closest('#crm-lead-tray');
  const inCard = evt.target.closest('.crm-lead-card[data-lead-id]');
  if (inTray || inCard) return;
  closeCrmLeadTray();
}

function crmLeadById(leadId) {
  return (crmState.leads || []).find((lead) => String(lead.id || '') === String(leadId || '')) || null;
}

function crmSelectedLeadIds() {
  const valid = new Set((crmState.leads || []).map((lead) => String(lead.id || '')));
  crmState.selectedLeadIds = (crmState.selectedLeadIds || []).map((x) => String(x || '')).filter((x) => x && valid.has(x));
  return crmState.selectedLeadIds;
}

function crmIsLeadChecked(leadId) {
  const id = String(leadId || '').trim();
  return crmSelectedLeadIds().includes(id);
}

function crmSetLeadChecked(leadId, checked) {
  const id = String(leadId || '').trim();
  if (!id) return;
  const set = new Set(crmSelectedLeadIds());
  if (checked) set.add(id);
  else set.delete(id);
  crmState.selectedLeadIds = Array.from(set);
}

function crmRenderSelectionActions() {
  const selected = crmSelectedLeadIds();
  const count = selected.length;
  const countEl = document.getElementById('crm-selection-count');
  const delBtn = document.getElementById('crm-delete-selected-btn');
  const mergeBtn = document.getElementById('crm-merge-selected-btn');

  const hasSelection = count > 0;
  if (countEl) {
    countEl.textContent = `${count} selecionado${count === 1 ? '' : 's'}`;
    countEl.classList.toggle('is-hidden', !hasSelection);
  }

  if (delBtn) {
    delBtn.disabled = !hasSelection;
    delBtn.textContent = count <= 1 ? 'Excluir selecionado' : `Bulk delete (${count})`;
    delBtn.classList.toggle('is-hidden', !hasSelection);
  }

  if (mergeBtn) {
    const canMerge = count === 2;
    mergeBtn.disabled = !canMerge;
    mergeBtn.classList.toggle('is-hidden', !canMerge);
  }
}

function isEditingCurrentLead(leadId) {
  return String(crmState.editingLeadId || '') === String(leadId || '');
}

function startEditingCurrentLead() {
  const lead = crmLeadById(crmState.selectedLeadId);
  if (!lead) return;
  crmState.editingLeadId = String(lead.id || '');
  crmState.editDraft = {
    name: String(lead.name || lead.full_name || '').trim(),
    nome_whatsapp: String(lead.nome_whatsapp || '').trim(),
    email: String(lead.email || '').trim(),
    phone: String(lead.phone || lead.whatsapp || '').trim(),
    source: String(lead.source || '').trim(),
  };
  renderCrmLeadTray();
}

function cancelLeadEditMode() {
  crmState.editingLeadId = null;
  crmState.editDraft = null;
  crmState.savingLead = false;
  renderCrmLeadTray();
}

function crmIsWhatsappPlaceholderName(value) {
  const txt = String(value || '').trim().toLowerCase().replace(/\s+/g, ' ');
  return /^contato\s+whats ?app\s+[\w-]{2,}$/.test(txt);
}

function crmIsWhatsappProxyEmail(value) {
  const txt = String(value || '').trim().toLowerCase();
  return txt.startsWith('wa-') && txt.endsWith('@whatsapp.local');
}

function crmSanitizeLead(lead) {
  if (!lead || typeof lead !== 'object') return lead;
  const out = { ...lead };
  ['name', 'full_name', 'nome_whatsapp'].forEach((field) => {
    if (crmIsWhatsappPlaceholderName(out[field])) out[field] = '';
  });
  if (crmIsWhatsappProxyEmail(out.email)) out.email = '';
  return out;
}

function crmPatchLeadLocal(leadId, patch) {
  const idx = (crmState.leads || []).findIndex((item) => String(item.id || '') === String(leadId || ''));
  if (idx < 0) return;
  crmState.leads[idx] = crmSanitizeLead({
    ...crmState.leads[idx],
    ...patch,
    ...(patch.phone ? { whatsapp: patch.phone } : {}),
  });
}

function crmRemoveLeadLocal(leadId) {
  const id = String(leadId || '').trim();
  if (!id) return false;

  const before = Array.isArray(crmState.leads) ? crmState.leads.length : 0;
  crmState.leads = (crmState.leads || []).filter((item) => String(item.id || '') !== id);
  const removed = (crmState.leads || []).length !== before;
  if (!removed) return false;

  delete crmState.operationalByLeadId[id];
  delete crmState.operationalErrorByLeadId[id];
  delete crmState.notesByLeadId[id];
  delete crmState.notesErrorByLeadId[id];
  delete crmState.noteDraftByLeadId[id];

  crmState.selectedLeadIds = crmSelectedLeadIds().filter((x) => x !== id);

  if (String(crmState.selectedLeadId || '') === id) {
    const nextLead = (crmState.leads || [])[0] || null;
    crmState.selectedLeadId = nextLead ? String(nextLead.id || '') : null;
    crmState.editingLeadId = null;
    crmState.editDraft = null;
    crmState.savingLead = false;
  }

  crmRenderSelectionActions();
  return true;
}

function crmLeadUpdatePayload(lead, draft) {
  const payload = { id: Number(lead.id) };
  const pairs = [
    ['name', String(lead.name || lead.full_name || '').trim(), String(draft?.name || '').trim()],
    ['nome_whatsapp', String(lead.nome_whatsapp || '').trim(), String(draft?.nome_whatsapp || '').trim()],
    ['email', String(lead.email || '').trim(), String(draft?.email || '').trim()],
    ['phone', String(lead.phone || lead.whatsapp || '').trim(), String(draft?.phone || '').trim()],
    ['source', String(lead.source || '').trim(), String(draft?.source || '').trim()],
  ];

  for (const [field, before, after] of pairs) {
    if (after && after !== before) payload[field] = after;
  }
  return payload;
}

function validateEmail(value) {
  const v = String(value || '').trim();
  if (!v || crmIsWhatsappProxyEmail(v)) return { valid: true, error: '' };
  const ok = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v);
  return { valid: ok, error: ok ? '' : 'Email inválido.' };
}

function validatePhoneIntl(value) {
  const raw = String(value || '').trim();
  if (!raw) return { valid: true, normalized: '', error: '' };
  const digits = raw.replace(/\D/g, '');
  if (digits.length < 10 || digits.length > 15) {
    return { valid: false, normalized: '', error: 'Telefone inválido (10-15 dígitos).' };
  }
  const normalized = `+${digits}`;
  return { valid: true, normalized, error: '' };
}

function crmValidateDraft(draft) {
  const errors = {};
  const cleaned = {
    name: String(draft?.name || '').trim(),
    nome_whatsapp: String(draft?.nome_whatsapp || '').trim(),
    email: String(draft?.email || '').trim(),
    phone: String(draft?.phone || '').trim(),
    source: String(draft?.source || '').trim(),
  };

  if (crmIsWhatsappProxyEmail(cleaned.email)) cleaned.email = '';

  const ev = validateEmail(cleaned.email);
  if (!ev.valid) errors.email = ev.error;

  const pv = validatePhoneIntl(cleaned.phone);
  if (!pv.valid) errors.phone = pv.error;
  if (pv.valid && pv.normalized) cleaned.phone = pv.normalized;

  return { valid: Object.keys(errors).length === 0, errors, cleaned };
}

function crmEditableRows(draft) {
  return [
    ['Nome', 'name', draft?.name || '', 'Nome do lead'],
    ['Nome WhatsApp', 'nome_whatsapp', draft?.nome_whatsapp || '', 'Nome exibido no WhatsApp'],
    ['Email', 'email', draft?.email || '', 'email@exemplo.com'],
    ['Telefone', 'phone', draft?.phone || '', '+55...'],
    ['Origem', 'source', draft?.source || '', 'lp / grupo / campanha'],
  ];
}

function crmEditInputRow(label, field, value, placeholder = '', errors = {}) {
  const err = String(errors[field] || '');
  const cls = err ? 'is-invalid' : (String(value || '').trim() ? 'is-valid' : '');
  return `<div class="crm-tray-row"><span>${escapeHtml(label)}</span><div><input class="crm-edit-input ${cls}" data-edit-field="${escapeHtml(field)}" value="${escapeHtml(value)}" placeholder="${escapeHtml(placeholder)}" />${err ? `<div class="crm-edit-field-error">${escapeHtml(err)}</div>` : ''}</div></div>`;
}

function crmReadOnlyRow(label, value) {
  return `<div class="crm-tray-row"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`;
}

function crmSetEditButtonsState({ hasLead = false, editing = false, saving = false, leadId = '', ids = {} } = {}) {
  const editBtn = document.getElementById(ids.editBtnId || 'crm-edit-lead-btn');
  const saveBtn = document.getElementById(ids.saveBtnId || 'crm-save-lead-btn');
  const cancelBtn = document.getElementById(ids.cancelBtnId || 'crm-cancel-edit-btn');

  if (editBtn) {
    editBtn.classList.toggle('is-hidden', !hasLead || editing);
    editBtn.disabled = !hasLead || saving;
    if (hasLead && leadId) editBtn.setAttribute('data-lead-id', leadId);
    else editBtn.removeAttribute('data-lead-id');
  }

  if (saveBtn) {
    saveBtn.classList.toggle('is-hidden', !hasLead || !editing);
    saveBtn.disabled = !editing || saving;
    if (hasLead && leadId) saveBtn.setAttribute('data-lead-id', leadId);
    else saveBtn.removeAttribute('data-lead-id');
  }

  if (cancelBtn) {
    cancelBtn.classList.toggle('is-hidden', !hasLead || !editing);
    cancelBtn.disabled = !editing || saving;
    if (hasLead && leadId) cancelBtn.setAttribute('data-lead-id', leadId);
    else cancelBtn.removeAttribute('data-lead-id');
  }
}

function crmFormatDate(value) {
  const raw = String(value || '').trim();
  if (!raw) return '-';
  const d = new Date(raw);
  if (!Number.isNaN(d.getTime())) return d.toLocaleString('pt-BR', { hour12: false });
  const fallback = raw.includes(' ') ? new Date(raw.replace(' ', 'T')) : null;
  if (fallback && !Number.isNaN(fallback.getTime())) return fallback.toLocaleString('pt-BR', { hour12: false });
  return raw;
}

function crmSortEventsDesc(items = []) {
  const toEpoch = (value) => {
    const raw = String(value || '').trim();
    if (!raw) return 0;
    const direct = new Date(raw).getTime();
    if (!Number.isNaN(direct)) return direct;
    const fixed = raw.includes(' ') ? new Date(raw.replace(' ', 'T')).getTime() : NaN;
    return Number.isNaN(fixed) ? 0 : fixed;
  };

  return [...items].sort((a, b) => toEpoch(b?.event_at || b?.createdAt || b?.at) - toEpoch(a?.event_at || a?.createdAt || a?.at));
}

function crmTimelineMetaToMessage(meta) {
  if (!meta || typeof meta !== 'object') return '';
  const entries = Object.entries(meta)
    .filter(([, v]) => v != null && String(v).trim() !== '' && typeof v !== 'object')
    .slice(0, 4)
    .map(([k, v]) => `${k}: ${String(v)}`);
  return entries.join(' · ');
}

async function ensureLeadOperationalData(leadId, { force = false } = {}) {
  const id = String(leadId || '').trim();
  if (!id) return;
  if (!force && Object.prototype.hasOwnProperty.call(crmState.operationalByLeadId, id)) return;
  if (crmState.operationalLoadingLeadId === id) return;

  crmState.operationalLoadingLeadId = id;
  crmState.operationalErrorByLeadId[id] = '';
  renderCrmLeadTray();

  try {
    const out = await api(`/api/crm/bridge/lead-operational/${encodeURIComponent(id)}`);
    crmState.operationalByLeadId[id] = {
      status: out?.status || {},
      timeline: crmSortEventsDesc(Array.isArray(out?.timeline) ? out.timeline.map((item) => ({
        id: item?.id || '',
        event_type: item?.eventType || item?.event_type || 'evento',
        event_at: item?.eventAt || item?.event_at || item?.createdAt || '',
        message: item?.message || crmTimelineMetaToMessage(item?.data || {}),
        source: item?.source || '',
      })) : []),
    };
    crmState.operationalErrorByLeadId[id] = '';
  } catch (err) {
    crmState.operationalErrorByLeadId[id] = err?.message || 'Falha ao carregar visão operacional do lead.';
  }

  if (crmState.operationalLoadingLeadId === id) crmState.operationalLoadingLeadId = null;
  renderCrmLeadTray();
}

async function ensureLeadNotesData(leadId, { force = false } = {}) {
  const id = String(leadId || '').trim();
  if (!id) return;
  if (!force && Object.prototype.hasOwnProperty.call(crmState.notesByLeadId, id)) return;
  if (crmState.notesLoadingLeadId === id) return;

  crmState.notesLoadingLeadId = id;
  crmState.notesErrorByLeadId[id] = '';
  renderCrmLeadTray();

  try {
    const out = await api(`/api/crm/bridge/notes/${encodeURIComponent(id)}`);
    const items = Array.isArray(out?.items) ? out.items : [];
    crmState.notesByLeadId[id] = [...items].sort((a, b) => String(b?.createdAt || '').localeCompare(String(a?.createdAt || '')));
    crmState.notesErrorByLeadId[id] = '';
  } catch (err) {
    crmState.notesErrorByLeadId[id] = err?.message || 'Falha ao carregar observações do lead.';
  }

  if (crmState.notesLoadingLeadId === id) crmState.notesLoadingLeadId = null;
  renderCrmLeadTray();
}

async function createLeadNote(leadId, content) {
  const id = String(leadId || '').trim();
  const text = String(content || '').trim();
  if (!id) throw new Error('Lead inválido');
  if (!text) throw new Error('Digite uma observação antes de salvar.');

  crmState.noteSavingLeadId = id;
  crmState.notesErrorByLeadId[id] = '';
  renderCrmLeadTray();

  try {
    await api('/api/crm/bridge/notes', {
      method: 'POST',
      body: JSON.stringify({ leadId: Number(id), content: text, source: 'cockpit-ui', createdBy: 'operator' }),
    });
    crmState.noteDraftByLeadId[id] = '';
    await ensureLeadNotesData(id, { force: true });
  } finally {
    if (crmState.noteSavingLeadId === id) crmState.noteSavingLeadId = null;
    renderCrmLeadTray();
  }
}

function crmLeadField(value, fallback = '-') {
  const normalized = String(value ?? '').trim();
  return normalized || fallback;
}

function crmNormalizeTags(value) {
  const raw = Array.isArray(value) ? value : String(value || '').split(/[\s,]+/);
  const out = [];
  const seen = new Set();
  for (const item of raw) {
    const t = String(item || '').trim().replace(/^#/, '');
    if (!t) continue;
    const k = t.toLowerCase();
    if (seen.has(k)) continue;
    seen.add(k);
    out.push(t.slice(0, 40));
    if (out.length >= 30) break;
  }
  return out;
}

function crmColumnFromRawStage(rawStage) {
  const s = String(rawStage || '').trim().toLowerCase();
  if (!s) return 'Novos';

  const map = {
    'novos': 'Novos',
    'novo': 'Novos',
    'new': 'Novos',
    'lead': 'Novos',

    'primeira mensagem enviada': 'Primeira Mensagem Enviada',
    'primeira_mensagem_enviada': 'Primeira Mensagem Enviada',
    'first message sent': 'Primeira Mensagem Enviada',
    'first_message_sent': 'Primeira Mensagem Enviada',

    'agendamento realizado': 'Agendamento Realizado',
    'agendamento_realizado': 'Agendamento Realizado',
    'appointment scheduled': 'Agendamento Realizado',
    'appointment_scheduled': 'Agendamento Realizado',

    'reunião realizada': 'Reunião Realizada',
    'reuniao realizada': 'Reunião Realizada',
    'reuniao_realizada': 'Reunião Realizada',
    'meeting done': 'Reunião Realizada',
    'meeting_done': 'Reunião Realizada',

    'oferta enviada': 'Oferta Enviada',
    'oferta_enviada': 'Oferta Enviada',
    'offer sent': 'Oferta Enviada',
    'offer_sent': 'Oferta Enviada',

    'sem resposta': 'Sem Resposta',
    'sem_resposta': 'Sem Resposta',
    'no response': 'Sem Resposta',
    'no_response': 'Sem Resposta',
    'scheduled': 'Sem Resposta',

    'interessado': 'Interessado',
    'approved': 'Interessado',

    'quer agendar': 'Quer Agendar',
    'quer_agendar': 'Quer Agendar',
    'agendar': 'Quer Agendar',
    'doing': 'Quer Agendar',

    'proposta enviada': 'Proposta Enviada',
    'proposta_enviada': 'Proposta Enviada',
    'proposal sent': 'Proposta Enviada',
    'proposal_sent': 'Proposta Enviada',
    'review': 'Proposta Enviada',

    'promessa pagamento': 'Promessa Pagamento',
    'promessa_pagamento': 'Promessa Pagamento',
    'payment promise': 'Promessa Pagamento',
    'payment_promise': 'Promessa Pagamento',

    'parceria interesse': 'Parceria Interesse',
    'parceria_interesse': 'Parceria Interesse',
    'partnership interest': 'Parceria Interesse',
    'partnership_interest': 'Parceria Interesse',

    'parceria sem interess': 'Parceria Sem Interess',
    'parceria_sem_interess': 'Parceria Sem Interess',
    'partnership no interest': 'Parceria Sem Interess',
    'partnership_no_interest': 'Parceria Sem Interess',
    'rejected': 'Parceria Sem Interess',

    'alunos/suporte': 'Alunos/Suporte',
    'alunos': 'Alunos/Suporte',
    'suporte': 'Alunos/Suporte',
    'support': 'Alunos/Suporte',
    'enrolled': 'Alunos/Suporte',
    'paid': 'Alunos/Suporte',
    'done': 'Alunos/Suporte',
  };

  return map[s] || 'Novos';
}

function crmColumnForLead(lead) {
  const rawStage = lead?.current_stage || lead?.stage || lead?.status || lead?.applicationStatus || '';
  return crmColumnFromRawStage(rawStage);
}

function crmResolveIsBa(lead) {
  const direct = lead?.is_ba;
  if (typeof direct === 'boolean') return direct;

  const normalizedDirect = String(direct || '').trim().toLowerCase();
  if (['true', '1', 'sim', 'yes'].includes(normalizedDirect)) return true;
  if (['false', '0', 'nao', 'não', 'no'].includes(normalizedDirect)) return false;

  const atua = String(lead?.atua || '').trim().toLowerCase();
  if (['sim', 'true', '1', 'yes'].includes(atua)) return true;
  if (['nao', 'não', 'false', '0', 'no'].includes(atua)) return false;
  return null;
}

function crmLeadMatchesQuickFilterIsBa(lead) {
  const filter = CRM_IS_BA_FILTER_VALUES.includes(crmState.quickFilterIsBa) ? crmState.quickFilterIsBa : 'all';
  if (filter === 'all') return true;
  const isBa = crmResolveIsBa(lead);
  if (filter === 'ba') return isBa === true;
  if (filter === 'nao-ba') return isBa === false;
  return true;
}

function crmNormalizeDigits(value) {
  return String(value || '').replace(/\D/g, '');
}

function crmLeadMatchesSearchText(lead, searchText) {
  const q = String(searchText || '').trim().toLowerCase();
  if (!q) return true;

  const name = String(lead?.name || lead?.full_name || lead?.nome_whatsapp || '').toLowerCase();
  if (name.includes(q)) return true;

  const qDigits = crmNormalizeDigits(q);
  if (!qDigits) return false;

  const phoneDigits = crmNormalizeDigits(
    lead?.whatsapp || lead?.phone || lead?.phone_number || lead?.mobile || lead?.telefone || ''
  );
  return phoneDigits.includes(qDigits);
}

function crmGetVisibleLeads() {
  const leads = Array.isArray(crmState.leads) ? crmState.leads : [];
  const query = String(crmState.searchText || '').trim();
  return leads.filter((lead) => crmLeadMatchesQuickFilterIsBa(lead) && crmLeadMatchesSearchText(lead, query));
}

function renderCrmQuickFilterIsBa() {
  const root = document.getElementById('crm-is-ba-quick-filter');
  if (!root) return;
  const activeValue = CRM_IS_BA_FILTER_VALUES.includes(crmState.quickFilterIsBa) ? crmState.quickFilterIsBa : 'all';
  root.querySelectorAll('[data-action="crm-is-ba-filter"][data-value]').forEach((btn) => {
    const isActive = String(btn.dataset.value || '') === activeValue;
    btn.classList.toggle('active', isActive);
    btn.setAttribute('aria-pressed', isActive ? 'true' : 'false');
  });
}

function crmRenderSearchInput() {
  const input = document.getElementById('crm-leads-search');
  const clearBtn = document.getElementById('crm-leads-search-clear');
  const value = String(crmState.searchText || '').trim();
  if (input && input.value !== value) input.value = value;
  if (clearBtn) {
    clearBtn.classList.toggle('is-hidden', !value);
    clearBtn.disabled = !value;
  }
}

function crmSetQuickFilterIsBa(value) {
  const normalized = CRM_IS_BA_FILTER_VALUES.includes(String(value || '').trim()) ? String(value || '').trim() : 'all';
  if (crmState.quickFilterIsBa === normalized) {
    renderCrmQuickFilterIsBa();
    return;
  }
  crmState.quickFilterIsBa = normalized;
  crmPersistIsBaFilter(normalized);
  crmSelectedLeadIds();
  renderCrmBoard();
  renderCrmLeadTray();
}

function crmSetSearchText(value) {
  const normalized = String(value || '').trim().slice(0, 120);
  if (crmState.searchText === normalized) {
    crmRenderSearchInput();
    return;
  }
  crmState.searchText = normalized;
  crmPersistLeadsSearchText(normalized);
  crmSelectedLeadIds();
  renderCrmBoard();
  renderCrmLeadTray();
}

function crmStageFieldsForColumn(column) {
  const col = String(column || '').trim();
  if (!col) return null;
  return {
    current_stage: col,
    stage: col,
    status: col,
    applicationStatus: col,
  };
}

function crmLeadCard(lead) {
  const leadId = crmLeadField(lead.id, '');
  const name = lead.name || lead.full_name || lead.email || `Lead #${lead.id || '-'}`;

  const whatsapp = String(
    lead.whatsapp || lead.phone || lead.phone_number || lead.mobile || lead.telefone || ''
  ).trim();
  const email = String(lead.email || '').trim();
  const contactText = whatsapp
    ? `WhatsApp: ${whatsapp}`
    : (email ? `Email: ${email}` : 'Contato não informado');

  const selected = String(crmState.selectedLeadId || '') === String(leadId);
  const column = crmColumnForLead(lead);
  const updating = crmState.updatingLeadIds.has(String(leadId));
  return `
    <article class="crm-lead-card minimal clickable ${selected ? 'is-selected' : ''} ${updating ? 'is-updating' : ''}" data-lead-id="${escapeHtml(leadId)}" data-column="${escapeHtml(column)}" data-draggable-card="crm" draggable="true" role="button" tabindex="0" aria-label="Abrir detalhes do lead ${escapeHtml(name)}">
      <div class="crm-lead-header">
        <div class="crm-select-wrap">
          <input type="checkbox" class="crm-lead-select" data-action="select-lead" data-lead-id="${escapeHtml(leadId)}" ${crmIsLeadChecked(leadId) ? 'checked' : ''} aria-label="Selecionar lead ${escapeHtml(name)}" />
          <strong class="crm-lead-title">${escapeHtml(name)}</strong>
        </div>
        <button type="button" class="crm-card-delete-btn" data-action="delete-lead" data-lead-id="${escapeHtml(leadId)}" aria-label="Excluir lead ${escapeHtml(name)}" title="Excluir lead">🗑</button>
      </div>
      <div class="crm-lead-subline">${escapeHtml(contactText)}</div>
      <div class="crm-drag-handle" aria-hidden="true">↕ Arraste para mover de etapa</div>
    </article>
  `;
}

function renderLeadTray({
  trayId = 'crm-lead-tray',
  bodyId = 'crm-lead-tray-body',
  layoutSelector = '.crm-layout',
  tabSelector = '.crm-tray-tab[data-tray-tab]',
  tabAttr = 'data-tray-tab',
  emptyWithoutSelection = 'Clique em um lead para ver os detalhes nesta tray.',
  emptyWithoutLeadLink = 'Sem lead vinculado para esta conversa.',
  ids = {},
  leadId = null,
  useSelectedFallback = true,
} = {}) {
  const body = document.getElementById(bodyId);
  const tray = document.getElementById(trayId);
  const layout = layoutSelector ? document.querySelector(layoutSelector) : null;
  if (!body) return;

  const resolvedInputLeadId = (leadId !== null && leadId !== undefined && String(leadId).trim())
    ? String(leadId).trim()
    : (useSelectedFallback ? String(crmState.selectedLeadId || '').trim() : '');
  const lead = crmLeadById(resolvedInputLeadId);
  if (!lead) {
    if (tray) tray.classList.add('is-collapsed');
    if (layout) layout.classList.add('is-tray-collapsed');
    crmSetEditButtonsState({ hasLead: false, ids });
    body.innerHTML = `<p class="muted">${escapeHtml(resolvedInputLeadId ? emptyWithoutLeadLink : emptyWithoutSelection)}</p>`;
    return;
  }

  if (tray) tray.classList.remove('is-collapsed');
  if (layout) layout.classList.remove('is-tray-collapsed');

  const resolvedLeadId = String(lead.id || '').trim();
  const editing = isEditingCurrentLead(resolvedLeadId);
  crmSetEditButtonsState({ hasLead: true, editing, saving: crmState.savingLead, leadId: resolvedLeadId, ids });
  document.querySelectorAll(tabSelector).forEach((tabBtn) => {
    const active = tabBtn.getAttribute(tabAttr) === crmState.trayTab;
    tabBtn.classList.toggle('active', active);
    tabBtn.setAttribute('aria-selected', active ? 'true' : 'false');
  });

  const operational = crmState.operationalByLeadId[resolvedLeadId] || { status: {}, timeline: [] };
  const status = operational.status || {};
  const timeline = Array.isArray(operational.timeline) ? operational.timeline : [];
  const loadingOperational = crmState.operationalLoadingLeadId === resolvedLeadId;
  const operationalError = crmState.operationalErrorByLeadId[resolvedLeadId];

  const timelineHtml = loadingOperational
    ? '<div class="crm-operational-loading muted">Carregando visão operacional...</div>'
    : operationalError
      ? `<div class="crm-operational-error">${escapeHtml(operationalError)}</div>`
      : timeline.length
        ? timeline.slice(0, 20).map((item) => {
            const eventLabel = item.event_type || item.channel || 'interação';
            const when = crmFormatDate(item.event_at || item.createdAt || item.created_at);
            const msg = item.message || item.note || '';
            return `
              <article class="crm-operational-item">
                <header><strong>${escapeHtml(eventLabel)}</strong><time>${escapeHtml(when)}</time></header>
                ${msg ? `<p>${escapeHtml(msg)}</p>` : ''}
              </article>
            `;
          }).join('')
        : '<div class="crm-operational-empty muted">Sem eventos registrados para este lead.</div>';

  const leadBa = crmLeadField(lead.is_ba || lead.atua || lead.ba_profile || lead.ba || '-');
  const leadXp = crmLeadField(lead.experience || lead.xp || lead.xp_years || lead.tempo_experiencia || '-');

  let trayGridHtml = '';
  if (editing) {
    const draft = crmState.editDraft || {};
    const validation = crmValidateDraft(draft);
    const editableRows = crmEditableRows(draft).map(([label, field, value, placeholder]) => crmEditInputRow(label, field, value, placeholder, validation.errors));
    const readOnlyRows = [
      crmReadOnlyRow('ID', crmLeadField(lead.id)),
      crmReadOnlyRow('É BA?', leadBa),
      crmReadOnlyRow('Tempo de XP', leadXp),
      crmReadOnlyRow('Signups', crmLeadField(lead.signup_count, '1')),
      crmReadOnlyRow('Primeiro contato', crmLeadField(lead.first_seen || lead.created_at)),
      crmReadOnlyRow('Último contato', crmLeadField(lead.last_seen || lead.created_at)),
      crmReadOnlyRow('Status', crmColumnForLead(lead)),
      crmReadOnlyRow('Owner', crmLeadField(lead.owner)),
    ];
    trayGridHtml = `
      <div class="crm-edit-hint">Modo edição ativo. Edite os campos e clique em 💾 para salvar.</div>
      <div class="crm-edit-danger-actions">
        <button type="button" class="quick-action danger" data-action="delete-lead" data-lead-id="${escapeHtml(resolvedLeadId)}">🗑 Excluir lead</button>
      </div>
      <div class="crm-tray-grid">
        ${editableRows.join('')}
        ${readOnlyRows.join('')}
      </div>
    `;
  } else {
    const rows = [
      ['ID', crmLeadField(lead.id)], ['Nome', crmLeadField(lead.name || lead.full_name)], ['Nome WhatsApp', crmLeadField(lead.nome_whatsapp)],
      ['Email', crmLeadField(lead.email)], ['Telefone', crmLeadField(lead.phone)], ['Origem', crmLeadField(lead.source)],
      ['É BA?', leadBa], ['Tempo de XP', leadXp],
      ['Signups', crmLeadField(lead.signup_count, '1')], ['Primeiro contato', crmLeadField(lead.first_seen || lead.created_at)],
      ['Último contato', crmLeadField(lead.last_seen || lead.created_at)], ['Status', crmColumnForLead(lead)], ['Owner', crmLeadField(lead.owner)],
    ];
    trayGridHtml = `<div class="crm-tray-grid">${rows.map(([k, v]) => crmReadOnlyRow(k, v)).join('')}</div>`;
  }

  const inGroup = status.inGroup === true;
  const emailOpened = status.emailOpened === true;
  const tags = crmNormalizeTags(status.tags || []);
  const tagsChipsHtml = tags.length
    ? tags.map((tag) => `<button type="button" class="crm-tag-chip" data-action="remove-tag" data-lead-id="${escapeHtml(resolvedLeadId)}" data-tag="${escapeHtml(tag)}">#${escapeHtml(tag)} ✕</button>`).join('')
    : '<span class="muted">Sem tags</span>';
  const detailsPane = `
    <div class="crm-tray-title">${escapeHtml(lead.name || lead.full_name || lead.email || `Lead #${lead.id || '-'}`)}</div>
    ${trayGridHtml}
    <section class="crm-tags-block">
      <div class="crm-operational-header"><h4>Tags</h4></div>
      <div class="crm-tags-input-row">
        <input type="text" data-action="tags-input" data-lead-id="${escapeHtml(resolvedLeadId)}" placeholder="Digite tags separadas por vírgula ou espaço" />
        <button type="button" class="quick-action" data-action="save-tags" data-lead-id="${escapeHtml(resolvedLeadId)}">Salvar tags</button>
      </div>
      <div class="crm-tags-chips">${tagsChipsHtml}</div>
    </section>
  `;
  const operationalPane = `
    <section class="crm-operational-block" data-testid="crm-operational-block">
      <div class="crm-operational-header">
        <h4>Visão Operacional</h4>
        <button type="button" class="quick-action" data-action="refresh-operational" data-lead-id="${escapeHtml(resolvedLeadId)}">Atualizar</button>
      </div>
      <div class="crm-operational-meta">
        <span class="crm-chip">No grupo: ${inGroup ? 'Sim' : 'Não'}</span>
        <span class="crm-chip">Abriu e-mail: ${emailOpened ? 'Sim' : 'Não'}</span>
      </div>
      <div class="crm-operational-actions">
        <button type="button" class="quick-action" data-action="toggle-group" data-lead-id="${escapeHtml(resolvedLeadId)}" data-value="${inGroup ? '0' : '1'}">Marcar grupo: ${inGroup ? 'Não' : 'Sim'}</button>
        <button type="button" class="quick-action" data-action="toggle-email" data-lead-id="${escapeHtml(resolvedLeadId)}" data-value="${emailOpened ? '0' : '1'}">Marcar e-mail: ${emailOpened ? 'Não' : 'Sim'}</button>
      </div>
      <div class="crm-operational-meta"><span class="crm-chip">Eventos: ${timeline.length}</span></div>
      <div class="crm-operational-list">${timelineHtml}</div>
    </section>
  `;

  const notes = Array.isArray(crmState.notesByLeadId[resolvedLeadId]) ? crmState.notesByLeadId[resolvedLeadId] : [];
  const notesLoading = crmState.notesLoadingLeadId === resolvedLeadId;
  const notesSaving = crmState.noteSavingLeadId === resolvedLeadId;
  const notesError = crmState.notesErrorByLeadId[resolvedLeadId];
  const noteDraft = String(crmState.noteDraftByLeadId[resolvedLeadId] || '');

  const notesListHtml = notesLoading
    ? '<div class="muted">Carregando observações...</div>'
    : notesError
      ? `<div class="crm-operational-error">${escapeHtml(notesError)}</div>`
      : notes.length
        ? notes.map((item) => `<article class="crm-note-item"><header><time>${escapeHtml(crmFormatDate(item.createdAt))}</time></header><p>${escapeHtml(item.content || '')}</p></article>`).join('')
        : '<div class="muted">Sem observações para este lead.</div>';

  const notesPane = `
    <section class="crm-notes-block" data-testid="crm-notes-block">
      <div class="crm-operational-header">
        <h4>Observações</h4>
        <button type="button" class="quick-action" data-action="refresh-notes" data-lead-id="${escapeHtml(resolvedLeadId)}">Atualizar</button>
      </div>
      <div class="crm-notes-create">
        <textarea data-action="note-draft" data-lead-id="${escapeHtml(resolvedLeadId)}" placeholder="Escreva uma observação interna sobre este lead..." rows="4">${escapeHtml(noteDraft)}</textarea>
        <button type="button" class="quick-action" data-action="save-note" data-lead-id="${escapeHtml(resolvedLeadId)}" ${notesSaving ? 'disabled' : ''}>${notesSaving ? 'Salvando...' : 'Salvar observação'}</button>
      </div>
      <div class="crm-notes-list">${notesListHtml}</div>
    </section>
  `;

  body.innerHTML = crmState.trayTab === 'operational' ? operationalPane : (crmState.trayTab === 'notes' ? notesPane : detailsPane);
}

function renderCrmLeadTray() {
  renderLeadTray({
    trayId: 'crm-lead-tray', bodyId: 'crm-lead-tray-body', layoutSelector: '.crm-layout', tabSelector: '.crm-tray-tab[data-tray-tab]', tabAttr: 'data-tray-tab',
    emptyWithoutSelection: 'Clique em um lead para ver os detalhes nesta tray.',
    ids: { editBtnId: 'crm-edit-lead-btn', saveBtnId: 'crm-save-lead-btn', cancelBtnId: 'crm-cancel-edit-btn' },
    leadId: crmState.selectedLeadId,
  });
  renderChatLeadTray(chatState?.selectedLeadId || null);
}

function renderChatLeadTray(leadId) {
  renderLeadTray({
    trayId: 'chat-lead-tray', bodyId: 'chat-lead-tray-body', layoutSelector: '', tabSelector: '#chat-lead-tray-tabs .crm-tray-tab[data-chat-tray-tab]', tabAttr: 'data-chat-tray-tab',
    emptyWithoutSelection: 'Selecione uma conversa para ver detalhes do lead vinculado.',
    emptyWithoutLeadLink: 'Sem lead vinculado para esta conversa.',
    ids: { editBtnId: 'chat-edit-lead-btn', saveBtnId: 'chat-save-lead-btn', cancelBtnId: 'chat-cancel-edit-btn' },
    leadId,
    useSelectedFallback: false,
  });

  const shell = document.querySelector('.chat-shell');
  if (shell) {
    const hasLeadTray = !!String(leadId || '').trim();
    shell.classList.toggle('no-tray', !hasLeadTray);
  }
}

function renderCrmBoard() {
  const cols = document.getElementById('crm-board-columns');
  if (!cols) return;

  const allLeads = Array.isArray(crmState.leads) ? crmState.leads : [];
  const leads = crmGetVisibleLeads();
  const grouped = Object.fromEntries(CRM_COLUMNS.map((c) => [c, []]));

  for (const lead of leads) {
    const column = crmColumnForLead(lead);
    if (!grouped[column]) grouped[column] = [];
    grouped[column].push(lead);
  }

  cols.innerHTML = CRM_COLUMNS.map((column) => {
    const items = grouped[column] || [];
    const isDropTarget = String(crmState.dragOverColumn || '') === String(column);
    return `<section class="crm-board-column ${isDropTarget ? 'is-drop-target' : ''}" data-column="${escapeHtml(column)}"><h3>${escapeHtml(column)} <span class="muted">(${items.length})</span></h3>${items.slice(0, 400).map(crmLeadCard).join('')}</section>`;
  }).join('');

  const titleEl = document.getElementById('crm-title-count');
  if (titleEl) {
    titleEl.textContent = `Leads (${leads.length}/${allLeads.length})`;
  }

  renderCrmQuickFilterIsBa();
  crmRenderSearchInput();
  crmRenderSelectionActions();
}

function onCrmBoardActivateLead(evt) {
  const selectInput = evt.target.closest('input[data-action="select-lead"][data-lead-id]');
  if (selectInput) {
    evt.stopPropagation();
    const leadId = String(selectInput.dataset.leadId || '').trim();
    if (!leadId) return;
    crmSetLeadChecked(leadId, !!selectInput.checked);
    crmRenderSelectionActions();
    return;
  }

  const deleteBtn = evt.target.closest('button[data-action="delete-lead"][data-lead-id]');
  if (deleteBtn) {
    evt.preventDefault();
    evt.stopPropagation();
    const leadId = String(deleteBtn.dataset.leadId || '').trim();
    if (!leadId) return;
    onDeleteLeadClick(leadId);
    return;
  }

  const card = evt.target.closest('.crm-lead-card[data-lead-id]');
  if (!card) return;
  const leadId = String(card.dataset.leadId || '').trim();
  if (!leadId) return;

  if (String(crmState.selectedLeadId || '') !== String(leadId)) {
    crmState.editingLeadId = null;
    crmState.editDraft = null;
    crmState.savingLead = false;
  }
  crmState.selectedLeadId = leadId;
  renderCrmBoard();
  renderCrmLeadTray();
  ensureLeadOperationalData(leadId).catch(() => {});
  ensureLeadNotesData(leadId).catch(() => {});
}

function onCrmBoardKeydown(evt) {
  if (evt.key !== 'Enter' && evt.key !== ' ') return;
  if (evt.target.closest('button[data-action="delete-lead"][data-lead-id]')) return;
  if (evt.target.closest('input[data-action="select-lead"][data-lead-id]')) return;
  const card = evt.target.closest('.crm-lead-card[data-lead-id]');
  if (!card) return;
  evt.preventDefault();
  const leadId = String(card.dataset.leadId || '').trim();
  if (!leadId) return;
  if (String(crmState.selectedLeadId || '') !== String(leadId)) {
    crmState.editingLeadId = null;
    crmState.editDraft = null;
    crmState.savingLead = false;
  }
  crmState.selectedLeadId = leadId;
  renderCrmBoard();
  renderCrmLeadTray();
  ensureLeadOperationalData(leadId).catch(() => {});
  ensureLeadNotesData(leadId).catch(() => {});
}

function applyCrmDragOverVisual(columnName) {
  document.querySelectorAll('.crm-board-column[data-column]').forEach((el) => {
    const isTarget = columnName && String(el.dataset.column || '') === String(columnName);
    el.classList.toggle('is-drop-target', !!isTarget);
  });
}

function onCrmBoardDragStart(evt) {
  const card = evt.target.closest('.crm-lead-card[data-lead-id]');
  if (!card) return;
  const leadId = String(card.dataset.leadId || '').trim();
  if (!leadId) return;

  crmState.draggingLeadId = leadId;
  crmState.dragOverColumn = card.dataset.column || null;
  card.classList.add('is-dragging');
  applyCrmDragOverVisual(crmState.dragOverColumn);

  if (evt.dataTransfer) {
    evt.dataTransfer.effectAllowed = 'move';
    evt.dataTransfer.setData('text/plain', leadId);
  }
}

function onCrmBoardDragOver(evt) {
  const columnEl = evt.target.closest('.crm-board-column[data-column]');
  if (!columnEl || !crmState.draggingLeadId) return;
  evt.preventDefault();
  if (evt.dataTransfer) evt.dataTransfer.dropEffect = 'move';
  const column = String(columnEl.dataset.column || '').trim();
  if (column && crmState.dragOverColumn !== column) {
    crmState.dragOverColumn = column;
    applyCrmDragOverVisual(column);
  }
}

function onCrmBoardDragLeave(evt) {
  const columnEl = evt.target.closest('.crm-board-column[data-column]');
  if (!columnEl || !crmState.draggingLeadId) return;
  const nextInside = evt.relatedTarget && columnEl.contains(evt.relatedTarget);
  if (nextInside) return;
}

function resetCrmDragState() {
  crmState.draggingLeadId = null;
  crmState.dragOverColumn = null;
  document.querySelectorAll('.crm-lead-card.is-dragging').forEach((el) => el.classList.remove('is-dragging'));
  applyCrmDragOverVisual(null);
}

async function onCrmBoardDrop(evt) {
  const columnEl = evt.target.closest('.crm-board-column[data-column]');
  if (!columnEl || !crmState.draggingLeadId) return;
  evt.preventDefault();

  const leadId = String(crmState.draggingLeadId || '').trim();
  const targetColumn = String(columnEl.dataset.column || '').trim();
  resetCrmDragState();
  if (!leadId || !targetColumn) return;

  const lead = crmLeadById(leadId);
  if (!lead) return;
  const fromColumn = crmColumnForLead(lead);
  if (fromColumn === targetColumn) {
    renderCrmBoard();
    return;
  }

  const rollback = {
    current_stage: lead.current_stage,
    stage: lead.stage,
    status: lead.status,
    applicationStatus: lead.applicationStatus,
  };

  const nextFields = crmStageFieldsForColumn(targetColumn);
  if (!nextFields) return;

  crmState.updatingLeadIds.add(leadId);
  crmPatchLeadLocal(leadId, nextFields);
  renderCrmBoard();
  renderCrmLeadTray();

  try {
    await api('/api/crm/bridge/lead-update', {
      method: 'POST',
      body: JSON.stringify({ id: Number(leadId), ...nextFields }),
    });
    setStatus('crm-status', `Lead movido para ${targetColumn}.`);
  } catch (err) {
    crmPatchLeadLocal(leadId, rollback);
    setStatus('crm-status', `Falha ao mover lead: ${err.message}`, true);
  } finally {
    crmState.updatingLeadIds.delete(leadId);
    renderCrmBoard();
    renderCrmLeadTray();
  }
}

function onCrmBoardDragEnd() {
  resetCrmDragState();
  renderCrmBoard();
}

async function onCrmTrayClick(evt) {
  const deleteBtn = evt.target.closest('button[data-action="delete-lead"][data-lead-id]');
  if (deleteBtn) {
    const leadId = String(deleteBtn.dataset.leadId || '').trim();
    if (!leadId) return;
    await onDeleteLeadClick(leadId);
    return;
  }

  const refreshBtn = evt.target.closest('button[data-action="refresh-operational"][data-lead-id]');
  if (refreshBtn) {
    const leadId = String(refreshBtn.dataset.leadId || '').trim();
    if (!leadId) return;
    ensureLeadOperationalData(leadId, { force: true }).catch(() => {});
    return;
  }

  const refreshNotesBtn = evt.target.closest('button[data-action="refresh-notes"][data-lead-id]');
  if (refreshNotesBtn) {
    const leadId = String(refreshNotesBtn.dataset.leadId || '').trim();
    if (!leadId) return;
    ensureLeadNotesData(leadId, { force: true }).catch(() => {});
    return;
  }

  const saveNoteBtn = evt.target.closest('button[data-action="save-note"][data-lead-id]');
  if (saveNoteBtn) {
    const leadId = String(saveNoteBtn.dataset.leadId || '').trim();
    if (!leadId) return;
    const content = String(crmState.noteDraftByLeadId[leadId] || '');
    try {
      await createLeadNote(leadId, content);
      setStatus('crm-status', 'Observação salva.');
    } catch (err) {
      setStatus('crm-status', err.message || 'Falha ao salvar observação.', true);
    }
    return;
  }

  const saveTagsBtn = evt.target.closest('button[data-action="save-tags"][data-lead-id]');
  if (saveTagsBtn) {
    const leadId = String(saveTagsBtn.dataset.leadId || '').trim();
    if (!leadId) return;
    const input = document.querySelector(`input[data-action="tags-input"][data-lead-id="${leadId}"]`);
    const tags = crmNormalizeTags(input?.value || '');
    try {
      await api(`/api/crm/bridge/lead-operational/${encodeURIComponent(leadId)}`, {
        method: 'POST',
        body: JSON.stringify({ source: 'cockpit-ui', actor: 'operator', tags }),
      });
      await ensureLeadOperationalData(leadId, { force: true });
      if (input) input.value = '';
      setStatus('crm-status', 'Tags atualizadas.');
    } catch (err) {
      setStatus('crm-status', `Falha ao salvar tags: ${err.message}`, true);
    }
    return;
  }

  const removeTagBtn = evt.target.closest('button[data-action="remove-tag"][data-lead-id][data-tag]');
  if (removeTagBtn) {
    const leadId = String(removeTagBtn.dataset.leadId || '').trim();
    const tag = String(removeTagBtn.dataset.tag || '').trim();
    if (!leadId || !tag) return;
    const current = crmState.operationalByLeadId[leadId]?.status?.tags || [];
    const tags = crmNormalizeTags(current).filter((x) => x.toLowerCase() !== tag.toLowerCase());
    try {
      await api(`/api/crm/bridge/lead-operational/${encodeURIComponent(leadId)}`, {
        method: 'POST',
        body: JSON.stringify({ source: 'cockpit-ui', actor: 'operator', tags }),
      });
      await ensureLeadOperationalData(leadId, { force: true });
      setStatus('crm-status', 'Tag removida.');
    } catch (err) {
      setStatus('crm-status', `Falha ao remover tag: ${err.message}`, true);
    }
    return;
  }

  const toggleBtn = evt.target.closest('button[data-action][data-lead-id][data-value]');
  if (!toggleBtn) return;
  const leadId = String(toggleBtn.dataset.leadId || '').trim();
  if (!leadId) return;

  const action = String(toggleBtn.dataset.action || '');
  const value = String(toggleBtn.dataset.value || '0') === '1';
  if (!['toggle-group', 'toggle-email'].includes(action)) return;

  const payload = { source: 'cockpit-ui', actor: 'operator' };
  if (action === 'toggle-group') payload.inGroup = value;
  if (action === 'toggle-email') payload.emailOpened = value;

  try {
    await api(`/api/crm/bridge/lead-operational/${encodeURIComponent(leadId)}`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    await ensureLeadOperationalData(leadId, { force: true });
  } catch (err) {
    setStatus('crm-status', `Falha ao atualizar status operacional: ${err.message}`, true);
  }
}

function onEditLeadClick() {
  const lead = crmLeadById(crmState.selectedLeadId);
  if (!lead) return;
  startEditingCurrentLead();
}

function onCancelEditClick() {
  cancelLeadEditMode();
}

function onCrmTrayInput(evt) {
  const noteInput = evt.target.closest('textarea[data-action="note-draft"][data-lead-id]');
  if (noteInput) {
    const leadId = String(noteInput.dataset.leadId || '').trim();
    if (!leadId) return;
    crmState.noteDraftByLeadId[leadId] = String(noteInput.value || '');
    return;
  }

  const input = evt.target.closest('input[data-edit-field]');
  if (!input) return;
  if (!crmState.editDraft) crmState.editDraft = {};
  const field = String(input.dataset.editField || '').trim();
  if (!field) return;
  crmState.editDraft[field] = String(input.value || '');

  if (field === 'email' || field === 'phone') {
    const validation = crmValidateDraft(crmState.editDraft);
    input.classList.remove('is-invalid', 'is-valid');
    if (validation.errors[field]) input.classList.add('is-invalid');
    else if (String(input.value || '').trim()) input.classList.add('is-valid');
  }
}

async function onSaveLeadClick() {
  const lead = crmLeadById(crmState.selectedLeadId);
  if (!lead || !isEditingCurrentLead(lead.id)) return;

  const validation = crmValidateDraft(crmState.editDraft || {});
  if (!validation.valid) {
    setStatus('crm-status', 'Corrija os campos inválidos antes de salvar.', true);
    renderCrmLeadTray();
    return;
  }

  crmState.editDraft = {
    ...(crmState.editDraft || {}),
    ...validation.cleaned,
  };

  const payload = crmLeadUpdatePayload(lead, crmState.editDraft || {});
  if (Object.keys(payload).length === 1) {
    setStatus('crm-status', 'Nenhuma alteração detectada.');
    cancelLeadEditMode();
    return;
  }

  crmState.savingLead = true;
  crmSetEditButtonsState({ hasLead: true, editing: true, saving: true, leadId: String(lead.id || '') });

  try {
    const out = await api('/api/crm/bridge/lead-update', {
      method: 'POST',
      body: JSON.stringify(payload),
    });

    const upstreamLead = out?.upstream?.data?.lead || out?.upstream?.lead || null;
    crmPatchLeadLocal(lead.id, {
      ...(payload.name ? { name: payload.name } : {}),
      ...(payload.email ? { email: payload.email } : {}),
      ...(payload.phone ? { phone: payload.phone } : {}),
      ...(payload.nome_whatsapp ? { nome_whatsapp: payload.nome_whatsapp } : {}),
      ...(payload.source ? { source: payload.source } : {}),
      ...(upstreamLead || {}),
    });

    setStatus('crm-status', `Lead #${lead.id} atualizado com sucesso.`);
    crmState.savingLead = false;
    cancelLeadEditMode();
    renderCrmBoard();
    renderCrmLeadTray();
  } catch (err) {
    crmState.savingLead = false;
    crmSetEditButtonsState({ hasLead: true, editing: true, saving: false, leadId: String(lead.id || '') });
    setStatus('crm-status', `Falha ao editar lead: ${err.message}`, true);
  }
}

async function onDeleteLeadClick(leadId, opts = {}) {
  const id = String(leadId || '').trim();
  if (!id) return false;
  const lead = crmLeadById(id);
  const label = lead?.name || lead?.full_name || lead?.email || `#${id}`;

  if (!opts.skipConfirm) {
    const ok = window.confirm(`Tem certeza que deseja excluir o lead ${label}?`);
    if (!ok) return false;
  }

  try {
    await api('/api/crm/bridge/lead-delete', {
      method: 'POST',
      body: JSON.stringify({ id: Number(id) }),
    });

    crmRemoveLeadLocal(id);
    renderCrmBoard();
    renderCrmLeadTray();
    if (!opts.silent) setStatus('crm-status', `Lead ${label} excluído com sucesso.`);
    return true;
  } catch (err) {
    setStatus('crm-status', `Falha ao excluir lead: ${err.message}`, true);
    return false;
  }
}

function crmMergeFieldValue(lead, field) {
  if (!lead) return '';
  if (field === 'phone') return String(lead.phone || lead.whatsapp || '').trim();
  return String(lead[field] || '').trim();
}

function crmOpenMergeModal(leadA, leadB) {
  const modal = document.getElementById('crm-merge-modal');
  const body = document.getElementById('crm-merge-body');
  if (!modal || !body) return false;

  const fields = [
    ['name', 'Nome'],
    ['nome_whatsapp', 'Nome WhatsApp'],
    ['email', 'Email'],
    ['phone', 'Telefone'],
    ['source', 'Origem'],
  ];

  const rows = [];
  for (const [field, label] of fields) {
    const a = crmMergeFieldValue(leadA, field);
    const b = crmMergeFieldValue(leadB, field);
    const conflict = a && b && a !== b;
    const preferred = a || b || '';
    rows.push(`
      <div class="crm-merge-row" data-field="${escapeHtml(field)}">
        <h4>${escapeHtml(label)} ${conflict ? '⚠ conflito' : ''}</h4>
        <div class="crm-merge-options">
          <label><input type="radio" name="merge-${escapeHtml(field)}" value="a" ${preferred === a ? 'checked' : ''} /> Lead A: ${escapeHtml(a || '(vazio)')}</label>
          <label><input type="radio" name="merge-${escapeHtml(field)}" value="b" ${preferred === b ? 'checked' : ''} /> Lead B: ${escapeHtml(b || '(vazio)')}</label>
        </div>
      </div>
    `);
  }

  body.innerHTML = `
    <p class="muted">Selecione os dados que devem persistir no lead final.</p>
    <p class="muted">A: <strong>${escapeHtml(leadA.name || leadA.email || '#' + leadA.id)}</strong> · B: <strong>${escapeHtml(leadB.name || leadB.email || '#' + leadB.id)}</strong></p>
    ${rows.join('')}
  `;

  crmState.mergeContext = { leadA, leadB, fields: fields.map(([f]) => f) };
  modal.classList.remove('is-hidden');
  modal.setAttribute('aria-hidden', 'false');
  return true;
}

function crmCloseMergeModal() {
  const modal = document.getElementById('crm-merge-modal');
  if (!modal) return;
  modal.classList.add('is-hidden');
  modal.setAttribute('aria-hidden', 'true');
  crmState.mergeContext = null;
}

function crmMergePayloadFromModal() {
  const ctx = crmState.mergeContext;
  if (!ctx?.leadA || !ctx?.leadB) return null;
  const merged = {};
  for (const field of ctx.fields || []) {
    const selected = document.querySelector(`input[name="merge-${field}"]:checked`)?.value || 'a';
    merged[field] = selected === 'b' ? crmMergeFieldValue(ctx.leadB, field) : crmMergeFieldValue(ctx.leadA, field);
  }
  return {
    primaryId: Number(ctx.leadA.id),
    secondaryId: Number(ctx.leadB.id),
    merged,
  };
}

async function onMergeSelectedClick() {
  const selected = crmSelectedLeadIds();
  if (selected.length !== 2) {
    setStatus('crm-status', 'Selecione exatamente 2 leads para merge.', true);
    return;
  }

  const leadA = crmLeadById(selected[0]);
  const leadB = crmLeadById(selected[1]);
  if (!leadA || !leadB) {
    setStatus('crm-status', 'Leads selecionados inválidos.', true);
    return;
  }

  crmOpenMergeModal(leadA, leadB);
}

async function onConfirmMergeClick() {
  const payload = crmMergePayloadFromModal();
  if (!payload) return;

  try {
    const out = await api('/api/crm/bridge/lead-merge', {
      method: 'POST',
      body: JSON.stringify(payload),
    });

    const mergedLead = out?.mergedLead || out?.upstream?.data?.lead || null;
    if (mergedLead && payload.primaryId) crmPatchLeadLocal(payload.primaryId, mergedLead);

    crmRemoveLeadLocal(payload.secondaryId);
    crmState.selectedLeadIds = [String(payload.primaryId)];
    crmState.selectedLeadId = String(payload.primaryId);
    crmCloseMergeModal();
    renderCrmBoard();
    renderCrmLeadTray();
    setStatus('crm-status', `Merge concluído: #${payload.primaryId} + #${payload.secondaryId}.`);
    ensureLeadOperationalData(String(payload.primaryId), { force: true }).catch(() => {});
  } catch (err) {
    setStatus('crm-status', `Falha no merge: ${err.message}`, true);
  }
}

async function onDeleteSelectedClick() {
  const selected = crmSelectedLeadIds();
  if (!selected.length) return;
  if (selected.length === 1) {
    await onDeleteLeadClick(selected[0]);
    return;
  }

  const ok = window.confirm(`Tem certeza que deseja excluir ${selected.length} leads selecionados?`);
  if (!ok) return;

  let deleted = 0;
  for (const id of selected) {
    // eslint-disable-next-line no-await-in-loop
    const done = await onDeleteLeadClick(id, { skipConfirm: true, silent: true });
    if (done) deleted += 1;
  }
  renderCrmBoard();
  renderCrmLeadTray();
  setStatus('crm-status', `${deleted}/${selected.length} lead(s) excluído(s).`, deleted !== selected.length);
}

async function loadCrmBridge() {
  const data = await api('/api/crm/bridge');
  const status = data.status || {};
  const payload = data.payload || {};
  const leads = Array.isArray(payload.leads) ? payload.leads.map(crmSanitizeLead) : [];

  crmState.leads = leads;
  crmSelectedLeadIds();
  if (!crmLeadById(crmState.selectedLeadId)) {
    crmState.selectedLeadId = leads.length ? String(leads[0].id || '') : null;
    crmState.editingLeadId = null;
    crmState.editDraft = null;
    crmState.savingLead = false;
  }

  renderCrmBoard();
  renderCrmLeadTray();
  if (agendaState.createModalOpen) renderAgendaLeadOptions();
  if (crmState.selectedLeadId) {
    ensureLeadOperationalData(crmState.selectedLeadId).catch(() => {});
    ensureLeadNotesData(crmState.selectedLeadId).catch(() => {});
  }

  const dotEl = document.getElementById('crm-conn-dot');
  if (dotEl) {
    dotEl.classList.toggle('online', !!status.ok);
    dotEl.classList.toggle('offline', !status.ok);
    dotEl.title = status.ok ? 'Online' : 'Offline';
  }

  setStatus('crm-status', status.ok ? '' : 'Instabilidade. Tentando sincronizar...', !status.ok);
}

const chatState = {
  conversations: [],
  selectedConversationId: null,
  selectedLeadId: null,
  messagesByConversation: {},
  loading: false,
  connection: { online: false, state: 'offline' },
  messagesRequestSeq: 0,
  sendRequestSeq: 0,
};

const agendaState = {
  selectedDate: new Date().toISOString().slice(0, 10),
  viewYear: new Date().getFullYear(),
  viewMonth: new Date().getMonth(),
  itemsByDate: {},
  loading: false,
  createModalOpen: false,
  submitting: false,
};

function agendaStatusLabel(status) {
  const s = String(status || '').toLowerCase();
  if (s === 'concluido' || s === 'concluído') return 'concluído';
  if (s === 'atrasado') return 'atrasado';
  return 'pendente';
}

function agendaFmtDateLabel(isoDate) {
  const dt = new Date(`${isoDate}T00:00:00`);
  if (Number.isNaN(dt.getTime())) return isoDate;
  return dt.toLocaleDateString('pt-BR', { weekday: 'long', day: '2-digit', month: 'long', year: 'numeric' });
}

function agendaGoToToday() {
  const now = new Date();
  agendaState.selectedDate = now.toISOString().slice(0, 10);
  agendaState.viewYear = now.getFullYear();
  agendaState.viewMonth = now.getMonth();
  renderAgenda();
  loadAgendaByDate(agendaState.selectedDate).catch(() => {});
}

async function loadAgendaByDate(dateKey) {
  const date = String(dateKey || '').trim();
  if (!date) return;
  agendaState.loading = true;
  try {
    const out = await api(`/api/agenda?date=${encodeURIComponent(date)}`);
    agendaState.itemsByDate[date] = Array.isArray(out?.items) ? out.items : [];
    setStatus('agenda-status', '');
  } catch (err) {
    setStatus('agenda-status', err.message || 'Falha ao carregar agenda.', true);
  } finally {
    agendaState.loading = false;
    renderAgendaList();
    renderAgendaCalendar();
  }
}

function agendaLeadLabel(lead) {
  const id = String(lead?.id || '').trim();
  const name = String(lead?.name || lead?.full_name || '').trim();
  const phone = String(lead?.phone || lead?.whatsapp || '').trim();
  const parts = [name || `#${id}`];
  if (phone) parts.push(phone);
  return parts.join(' • ');
}

function renderAgendaLeadOptions(selectedLeadId = '') {
  const select = document.getElementById('agenda-form-lead');
  if (!select) return;
  const leads = Array.isArray(crmState.leads) ? crmState.leads : [];
  const options = ['<option value="">Selecione um lead</option>'];
  for (const lead of leads) {
    const id = String(lead?.id || '').trim();
    if (!id) continue;
    options.push(`<option value="${escapeHtml(id)}" ${id === selectedLeadId ? 'selected' : ''}>${escapeHtml(agendaLeadLabel(lead))}</option>`);
  }
  select.innerHTML = options.join('');
}

function agendaSetCreateFeedback(message, isError = false) {
  const el = document.getElementById('agenda-create-feedback');
  if (!el) return;
  setStatus('agenda-create-feedback', message, isError);
}

function agendaCloseCreateModal() {
  const modal = document.getElementById('agenda-create-modal');
  const form = document.getElementById('agenda-create-form');
  if (!modal) return;
  modal.classList.add('is-hidden');
  modal.setAttribute('aria-hidden', 'true');
  agendaState.createModalOpen = false;
  if (form) form.reset();
  agendaSetCreateFeedback('');
}

function agendaOpenCreateModal() {
  const modal = document.getElementById('agenda-create-modal');
  const form = document.getElementById('agenda-create-form');
  const dateInput = document.getElementById('agenda-form-date');
  const timeInput = document.getElementById('agenda-form-time');
  const typeInput = document.getElementById('agenda-form-type');
  const statusInput = document.getElementById('agenda-form-status');
  if (!modal || !form || !dateInput || !timeInput || !typeInput || !statusInput) return;

  form.reset();
  dateInput.value = agendaState.selectedDate;
  timeInput.value = '09:00';
  typeInput.value = 'call';
  statusInput.value = 'pendente';
  renderAgendaLeadOptions();
  for (const input of form.querySelectorAll('input, select')) input.setAttribute('aria-invalid', 'false');

  agendaSetCreateFeedback('');
  modal.classList.remove('is-hidden');
  modal.setAttribute('aria-hidden', 'false');
  agendaState.createModalOpen = true;
  window.setTimeout(() => dateInput.focus(), 20);
}

function agendaValidateCreateForm(formData) {
  const errors = [];
  const date = String(formData.get('date') || '').trim();
  const time = String(formData.get('time') || '').trim();
  const type = String(formData.get('type') || '').trim();
  const status = String(formData.get('status') || '').trim();
  const leadId = String(formData.get('lead') || '').trim();

  const allowedTypes = new Set(['call', 'follow-up', 'reunião']);
  const allowedStatus = new Set(['pendente', 'concluido', 'atrasado']);

  if (!date) errors.push({ field: 'agenda-form-date', msg: 'Informe uma data válida.' });
  if (!time) errors.push({ field: 'agenda-form-time', msg: 'Informe um horário válido.' });
  if (!allowedTypes.has(type)) errors.push({ field: 'agenda-form-type', msg: 'Selecione um tipo válido.' });
  if (!allowedStatus.has(status)) errors.push({ field: 'agenda-form-status', msg: 'Selecione um status válido.' });
  if (!leadId) errors.push({ field: 'agenda-form-lead', msg: 'Selecione um lead para o compromisso.' });

  return errors;
}

async function submitAgendaCreateForm(evt) {
  evt.preventDefault();
  const form = evt.currentTarget;
  if (!form || agendaState.submitting) return;

  const formData = new FormData(form);
  const errors = agendaValidateCreateForm(formData);
  for (const input of form.querySelectorAll('input, select')) input.setAttribute('aria-invalid', 'false');

  if (errors.length) {
    for (const err of errors) document.getElementById(err.field)?.setAttribute('aria-invalid', 'true');
    agendaSetCreateFeedback(errors[0].msg, true);
    document.getElementById(errors[0].field)?.focus();
    return;
  }

  const leadId = String(formData.get('lead') || '').trim();
  const lead = crmLeadById(leadId);
  if (!lead) {
    agendaSetCreateFeedback('Lead selecionado não encontrado. Atualize os leads e tente novamente.', true);
    return;
  }

  const submitBtn = document.getElementById('agenda-form-submit-btn');
  if (submitBtn) submitBtn.disabled = true;
  agendaState.submitting = true;

  try {
    await api('/api/agenda', {
      method: 'POST',
      body: JSON.stringify({
        date: String(formData.get('date') || '').trim(),
        time: String(formData.get('time') || '').trim(),
        type: String(formData.get('type') || '').trim(),
        status: String(formData.get('status') || '').trim(),
        leadId: Number(leadId),
        leadName: String(lead?.name || lead?.full_name || '').trim(),
        leadPhone: String(lead?.phone || lead?.whatsapp || '').trim(),
        note: String(formData.get('note') || '').trim(),
      }),
    });

    agendaSetCreateFeedback('Compromisso salvo com sucesso.');
    setStatus('agenda-status', 'Compromisso criado com sucesso.');
    agendaCloseCreateModal();
    await loadAgendaByDate(agendaState.selectedDate);
  } catch (err) {
    const msg = err.message || 'Falha ao criar compromisso.';
    agendaSetCreateFeedback(msg, true);
    setStatus('agenda-status', msg, true);
  } finally {
    agendaState.submitting = false;
    if (submitBtn) submitBtn.disabled = false;
  }
}

async function patchAgendaItem(itemId, patch) {
  try {
    await api(`/api/agenda/${encodeURIComponent(itemId)}`, { method: 'PATCH', body: JSON.stringify(patch || {}) });
    await loadAgendaByDate(agendaState.selectedDate);
  } catch (err) {
    setStatus('agenda-status', err.message || 'Falha ao atualizar compromisso.', true);
  }
}

function openLeadTrayFromAgenda(item) {
  const leadId = String(item?.leadId || '').trim();
  if (!leadId) return;
  crmState.selectedLeadId = leadId;
  crmState.trayTab = 'details';
  activateTab('crm');
  renderCrmBoard();
  renderCrmLeadTray();
}

function renderAgendaCalendar() {
  const root = document.getElementById('agenda-mini-calendar');
  const label = document.getElementById('agenda-month-label');
  if (!root || !label) return;

  const year = Number(agendaState.viewYear);
  const month = Number(agendaState.viewMonth);
  const first = new Date(year, month, 1);
  const firstDow = (first.getDay() + 6) % 7;
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  label.textContent = first.toLocaleDateString('pt-BR', { month: 'long', year: 'numeric' });

  const week = ['S', 'T', 'Q', 'Q', 'S', 'S', 'D'];
  const cells = [];
  for (let i = 0; i < firstDow; i += 1) cells.push('<div class="agenda-day muted"></div>');
  for (let day = 1; day <= daysInMonth; day += 1) {
    const iso = `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
    const selected = iso === agendaState.selectedDate;
    const hasItems = (agendaState.itemsByDate[iso] || []).length > 0;
    cells.push(`<button type="button" class="agenda-day ${selected ? 'is-selected' : ''} ${hasItems ? 'has-items' : ''}" data-action="agenda-select-date" data-date="${escapeHtml(iso)}">${day}</button>`);
  }

  root.innerHTML = `
    <div class="agenda-weekdays">${week.map((w) => `<span>${w}</span>`).join('')}</div>
    <div class="agenda-days-grid">${cells.join('')}</div>
  `;
}

function renderAgendaList() {
  const root = document.getElementById('agenda-list');
  const title = document.getElementById('agenda-selected-date');
  if (!root || !title) return;
  title.textContent = `Compromissos • ${agendaFmtDateLabel(agendaState.selectedDate)}`;

  const items = Array.isArray(agendaState.itemsByDate[agendaState.selectedDate]) ? agendaState.itemsByDate[agendaState.selectedDate] : [];
  if (!items.length) {
    root.innerHTML = '<div class="agenda-empty-state">Sem compromissos para este dia. Clique em <strong>+ Novo compromisso</strong> para criar o primeiro.</div>';
    return;
  }

  root.innerHTML = items.map((item) => {
    const status = agendaStatusLabel(item.status);
    const overdue = !!item.isOverdue || status === 'atrasado';
    return `
      <article class="agenda-item ${overdue ? 'is-overdue' : ''}" data-action="agenda-open-lead" data-lead-id="${escapeHtml(item.leadId || '')}" data-item-id="${escapeHtml(item.id || '')}">
        <div class="agenda-item-top">
          <strong>${escapeHtml(item.time || '--:--')}</strong>
          <span class="agenda-pill">${escapeHtml(item.type || '')}</span>
          <span class="agenda-pill ${overdue ? 'is-overdue' : ''}">${escapeHtml(status)}</span>
        </div>
        <div class="agenda-item-lead">Lead: ${escapeHtml(item.leadName || '—')} ${item.leadPhone ? `• ${escapeHtml(item.leadPhone)}` : ''}</div>
        <div class="agenda-item-actions">
          <button type="button" class="quick-action" data-action="agenda-mark-status" data-item-id="${escapeHtml(item.id || '')}" data-status="pendente">Pendente</button>
          <button type="button" class="quick-action" data-action="agenda-mark-status" data-item-id="${escapeHtml(item.id || '')}" data-status="concluido">Concluir</button>
          <button type="button" class="quick-action" data-action="agenda-mark-status" data-item-id="${escapeHtml(item.id || '')}" data-status="atrasado">Atrasado</button>
        </div>
      </article>
    `;
  }).join('');
}

function renderAgenda() {
  renderAgendaCalendar();
  renderAgendaList();
}

const albertState = {
  sessions: [],
  loading: false,
};

function albertStatusLabel(status) {
  const s = String(status || '').toLowerCase();
  const labels = {
    created: 'aguardando',
    joining: 'entrando',
    recording: 'gravando',
    processing: 'processando',
    done: 'concluído',
    failed: 'erro',
  };
  return labels[s] || s || 'aguardando';
}

function albertFmtDate(value) {
  if (!value) return '—';
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) return String(value);
  return dt.toLocaleString('pt-BR');
}

function albertCopyText(text) {
  const content = String(text || '').trim();
  if (!content) return;
  if (navigator.clipboard?.writeText) {
    navigator.clipboard.writeText(content).then(() => setStatus('albert-status', 'Resumo copiado.')).catch(() => {});
    return;
  }
  window.prompt('Copie o resumo manualmente:', content);
}

function renderAlbertPanel() {
  const live = document.getElementById('albert-live-status');
  const list = document.getElementById('albert-sessions-list');
  if (!live || !list) return;

  const sessions = Array.isArray(albertState.sessions) ? albertState.sessions : [];
  const current = sessions[0] || null;
  if (!current) {
    live.innerHTML = '<p class="muted">Sem sessão ativa no momento.</p>';
    list.innerHTML = '<div class="agenda-empty-state">Nenhuma sessão ainda. Use o link do Meet acima para começar.</div>';
    return;
  }

  live.innerHTML = `
    <div class="albert-session-item-top">
      <strong>Status em tempo real</strong>
      <span class="status-pill ${escapeHtml(String(current.status || '').toLowerCase())}">${escapeHtml(albertStatusLabel(current.status))}</span>
    </div>
    <div class="albert-session-meta">Atualizado: ${escapeHtml(albertFmtDate(current.updatedAt))}</div>
    <div class="muted">${escapeHtml(current.meetLink || '')}</div>
  `;

  list.innerHTML = sessions.map((item) => `
    <article class="albert-session-item">
      <div class="albert-session-item-top">
        <strong>${escapeHtml(item.id || 'sessão')}</strong>
        <span class="status-pill ${escapeHtml(String(item.status || '').toLowerCase())}">${escapeHtml(albertStatusLabel(item.status))}</span>
      </div>
      <div class="albert-session-meta">Criada: ${escapeHtml(albertFmtDate(item.createdAt))}${item.scheduledFor ? ` • Agendada: ${escapeHtml(albertFmtDate(item.scheduledFor))}` : ''}</div>
      <div class="muted">${escapeHtml(item.meetLink || '')}</div>
      <div class="albert-session-actions">
        <button type="button" class="quick-action" data-action="albert-view-transcript" data-id="${escapeHtml(item.id || '')}">Ver transcrição</button>
        <button type="button" class="quick-action" data-action="albert-view-insights" data-id="${escapeHtml(item.id || '')}">Ver insights</button>
        <button type="button" class="quick-action" data-action="albert-copy-summary" data-id="${escapeHtml(item.id || '')}">Copiar resumo</button>
      </div>
    </article>
  `).join('');
}

async function loadAlbertSessions() {
  if (albertState.loading) return;
  albertState.loading = true;
  try {
    const out = await api('/api/albert/sessions');
    albertState.sessions = Array.isArray(out?.items) ? out.items : [];
    renderAlbertPanel();
  } catch (err) {
    setStatus('albert-status', err.message || 'Falha ao carregar sessões do Albert.', true);
  } finally {
    albertState.loading = false;
  }
}

async function startAlbertSessionNow() {
  const input = document.getElementById('albert-meet-link');
  const link = String(input?.value || '').trim();
  if (!link) {
    setStatus('albert-status', 'Cole um link do Meet para iniciar.', true);
    input?.focus();
    return;
  }
  try {
    await api('/api/albert/session/start', { method: 'POST', body: JSON.stringify({ meetLink: link }) });
    setStatus('albert-status', 'Sessão iniciada. Albert está entrando no Meet.');
    await loadAlbertSessions();
  } catch (err) {
    setStatus('albert-status', err.message || 'Falha ao iniciar sessão.', true);
  }
}

async function scheduleAlbertSession() {
  const input = document.getElementById('albert-meet-link');
  const dt = document.getElementById('albert-schedule-datetime');
  const link = String(input?.value || '').trim();
  const scheduledFor = String(dt?.value || '').trim();
  if (!link) {
    setStatus('albert-status', 'Cole um link do Meet para agendar.', true);
    input?.focus();
    return;
  }
  try {
    await api('/api/albert/session/schedule', { method: 'POST', body: JSON.stringify({ meetLink: link, scheduledFor }) });
    setStatus('albert-status', 'Sessão agendada com sucesso.');
    await loadAlbertSessions();
  } catch (err) {
    setStatus('albert-status', err.message || 'Falha ao agendar sessão.', true);
  }
}

const CHAT_SNIPPET_GROUPS = [
  { id: 'abertura', label: 'Abertura', stage: 'Novos', items: [
    { id: 'abertura-1', label: 'Abertura direta', text: 'Oi, {{nome}}! Quero entender seu cenário em 2 minutos e te indicar o melhor caminho. Hoje, qual é o principal desafio no seu trabalho?' },
    { id: 'abertura-2', label: 'Quebra de gelo', text: 'Perfeito, {{nome}}. Obrigado por chamar. Pra eu ser assertivo: você está hoje em BA/produto/projetos e qual desafio mais está te travando agora?' },
  ]},
  { id: 'diagnostico', label: 'Diagnóstico', stage: 'Interessado', items: [
    { id: 'diag-1', label: 'Dor principal', text: 'Entendi. Onde você sente maior insegurança hoje: priorização, stakeholder, escopo, dependências ou tomada de decisão?' },
    { id: 'diag-2', label: 'Implicação', text: 'Se isso continuar pelos próximos 3 a 6 meses, o que pode impactar na sua rotina e crescimento?' },
    { id: 'diag-3', label: 'Need-payoff', text: 'Se você tivesse método claro para conduzir isso com segurança, o que mudaria no seu dia a dia?' },
  ]},
  { id: 'oferta', label: 'Oferta', stage: 'Proposta Enviada', items: [
    { id: 'oferta-1', label: 'Pitch mentoria', text: 'Pelo seu cenário, faz sentido uma mentoria prática e personalizada para aplicar método no seu caso real e acelerar sua segurança de execução.' },
    { id: 'oferta-2', label: 'Faixa de investimento', text: 'O investimento fica entre R$ 3.000 e R$ 4.500, conforme o formato ideal para o seu momento.' },
  ]},
  { id: 'objecoes', label: 'Objeções', stage: '', items: [
    { id: 'obj-preco', label: 'Preço', text: 'Faz sentido. Comparado ao custo de continuar nesse cenário por mais 6 meses, como você enxerga esse investimento?' },
    { id: 'obj-tempo', label: 'Tempo', text: 'Perfeito. A proposta é aplicada no seu caso real justamente para gerar resultado no trabalho, não carga extra.' },
    { id: 'obj-pensar', label: 'Vou pensar', text: 'Combinado. O que você precisa validar para decidir com segurança hoje?' },
  ]},
  { id: 'fechamento', label: 'Fechamento', stage: 'Promessa Pagamento', items: [
    { id: 'fecha-1', label: 'Commit', text: 'Faz sentido começarmos agora para resolver isso com método nas próximas semanas?' },
    { id: 'fecha-2', label: 'Pagamento', text: 'Perfeito. Te envio agora a forma de pagamento. Você prefere PIX ou cartão?' },
  ]},
  { id: 'followup', label: 'Follow-up', stage: 'Sem Resposta', items: [
    { id: 'fu-d1', label: 'D+1', text: '{{nome}}, fiquei pensando no seu cenário de {{dor}}. Quer que eu te mande um plano objetivo de evolução em 90 dias?' },
    { id: 'fu-d3', label: 'D+3', text: 'Passando aqui porque esse ponto costuma piorar sem método. Ainda faz sentido avançar agora?' },
    { id: 'fu-d7', label: 'D+7', text: 'Último toque da semana: seguimos com sua entrada ou prefere que eu encerre por agora?' },
  ]},
];

const chatSnippetState = { groupId: 'abertura' };

function chatSnippetContext() {
  const conv = chatConversationById(chatState.selectedConversationId) || {};
  const lead = crmLeadById(chatState.selectedLeadId) || {};
  const name = String(lead?.name || lead?.full_name || conv?.lead?.name || conv?.name || '').trim();
  return {
    nome: name || 'Nome',
    dor: 'desafio atual',
    prazo: '90 dias',
    valor: 'R$ 3.000 a R$ 4.500',
  };
}

function fillSnippetTemplate(text, ctx) {
  let out = String(text || '');
  Object.entries(ctx || {}).forEach(([k, v]) => {
    out = out.replaceAll(`{{${k}}}`, String(v || ''));
  });
  return out;
}

async function chatTryAutoStage(groupId) {
  const group = CHAT_SNIPPET_GROUPS.find((g) => g.id === groupId);
  const stage = String(group?.stage || '').trim();
  const leadId = String(chatState.selectedLeadId || '').trim();
  if (!stage || !leadId) return;
  try {
    const fields = crmStageFieldsForColumn(stage);
    if (!fields) return;
    await api('/api/crm/bridge/lead-update', {
      method: 'POST',
      body: JSON.stringify({ id: Number(leadId), ...fields }),
    });
    crmPatchLeadLocal(leadId, fields);
    renderCrmBoard();
    renderCrmLeadTray();
  } catch (_) {}
}

function chatInsertSnippet(text) {
  const input = document.getElementById('chat-input');
  if (!input) return;
  const current = String(input.value || '');
  input.value = current ? `${current}

${text}` : text;
  input.focus();
  input.selectionStart = input.selectionEnd = input.value.length;
}

function renderChatSnippets() {
  const groupsEl = document.getElementById('chat-snippet-groups');
  const itemsEl = document.getElementById('chat-snippet-items');
  if (!groupsEl || !itemsEl) return;

  const activeId = chatSnippetState.groupId || CHAT_SNIPPET_GROUPS[0].id;
  groupsEl.innerHTML = CHAT_SNIPPET_GROUPS.map((g) =>
    `<button type="button" class="chat-snippet-btn ${g.id === activeId ? 'active' : ''}" data-action="chat-snippet-group" data-group-id="${escapeHtml(g.id)}">${escapeHtml(g.label)}</button>`
  ).join('');

  const active = CHAT_SNIPPET_GROUPS.find((g) => g.id === activeId) || CHAT_SNIPPET_GROUPS[0];
  itemsEl.innerHTML = (active?.items || []).map((item) =>
    `<button type="button" class="chat-snippet-btn item" data-action="chat-snippet-item" data-group-id="${escapeHtml(active.id)}" data-item-id="${escapeHtml(item.id)}">${escapeHtml(item.label)}</button>`
  ).join('');
}

function chatConversationById(id) {
  return (chatState.conversations || []).find((x) => String(x.id || '') === String(id || '')) || null;
}

function chatFriendlyPhone(value) {
  const digits = String(value || '').replace(/\D/g, '');
  if (!digits) return '';
  return `+${digits}`;
}



function chatFriendlyTitle(item) {
  const name = String(item?.name || '').trim();
  if (name && !name.includes('@') && name.toLowerCase() !== 'conversa whatsapp') return name;
  const phone = String(item?.phone || '').trim();
  if (phone) return phone;
  const rawId = String(item?.id || '').trim();
  const fromId = chatFriendlyPhone(rawId);
  if (fromId) return fromId;
  return 'Conversa WhatsApp';
}

function chatAvatarInitials(title = '') {
  const txt = String(title || '').trim();
  if (!txt) return '👤';
  const words = txt.replace(/\+\d+/g, '').trim().split(/\s+/).filter(Boolean);
  if (words.length >= 2) return (words[0][0] + words[1][0]).toUpperCase();
  if (words.length === 1 && /[A-Za-zÀ-ÿ]/.test(words[0][0])) return words[0].slice(0, 2).toUpperCase();
  return '👤';
}

function chatAvatarClass(item) {
  const isGroup = String(item?.id || '').endsWith('@g.us');
  return isGroup ? 'group' : 'direct';
}

function renderChatConversations() {
  const root = document.getElementById('chat-conversations-list');
  if (!root) return;
  if (!Array.isArray(chatState.conversations) || !chatState.conversations.length) {
    root.innerHTML = '<div class="chat-empty-state"><strong>Sem conversas reais no WhatsApp</strong><span>Assim que o Baileys retornar chats, eles aparecem aqui automaticamente.</span></div>';
    return;
  }
  root.innerHTML = (chatState.conversations || []).map((item) => {
    const active = String(chatState.selectedConversationId || '') === String(item.id || '');
    const title = chatFriendlyTitle(item);
    const subtitleRaw = String(item.lastMessage || 'Sem mensagens').replace(/\s+/g, ' ').trim();
    const subtitle = subtitleRaw.length > 120 ? `${subtitleRaw.slice(0, 120)}…` : subtitleRaw;
    const isGroup = String(item?.id || '').endsWith('@g.us');
    const badge = isGroup ? 'Grupo' : 'Direto';
    const badgeCls = isGroup ? 'group' : 'direct';
    const avatar = chatAvatarInitials(title);
    const avatarCls = chatAvatarClass(item);
    return `
      <button type="button" class="chat-conv-item ${active ? 'is-active' : ''}" data-conversation-id="${escapeHtml(item.id)}">
        <div class="chat-conv-avatar ${avatarCls}">${escapeHtml(avatar)}</div>
        <div class="chat-conv-content">
          <div class="chat-conv-top"><strong>${escapeHtml(title)}</strong><div class="chat-conv-top-right"><span class="chat-conv-badge ${badgeCls}">${badge}</span><time>${escapeHtml(item.lastAtLabel || '')}</time></div></div>
          <div class="chat-conv-bottom"><span>${escapeHtml(subtitle)}</span>${item.unreadCount ? `<em>${escapeHtml(item.unreadCount)}</em>` : ''}</div>
        </div>
      </button>
    `;
  }).join('');
}

function renderChatConnection() {
  const dotEl = document.getElementById('chat-conn-dot');
  if (!dotEl) return;
  const online = !!chatState.connection?.online;
  const state = String(chatState.connection?.state || (online ? 'online' : 'offline'));
  dotEl.classList.toggle('online', online);
  dotEl.classList.toggle('offline', !online);
  dotEl.title = online ? `Online (${state})` : `Offline (${state})`;
}

function renderChatThread() {
  const title = document.getElementById('chat-thread-title');
  const lead = document.getElementById('chat-thread-lead');
  const msgsEl = document.getElementById('chat-messages');
  const conv = chatConversationById(chatState.selectedConversationId);
  if (!title || !lead || !msgsEl) return;

  if (!conv) {
    chatState.selectedLeadId = null;
    title.textContent = 'Selecione uma conversa';
    lead.textContent = 'Sem lead vinculado';
    msgsEl.innerHTML = '<p class="muted">Escolha uma conversa na lista para ver as mensagens.</p>';
    const linkBtn = document.getElementById('chat-link-lead-btn');
    if (linkBtn) linkBtn.classList.add('is-hidden');
    renderChatLeadTray(null);
    return;
  }

  title.textContent = chatFriendlyTitle(conv);
  const linkedLeadId = Number(conv?.lead?.id || 0);
  chatState.selectedLeadId = linkedLeadId > 0 ? String(linkedLeadId) : null;
  const linkBtn = document.getElementById('chat-link-lead-btn');
  if (linkBtn) linkBtn.classList.toggle('is-hidden', linkedLeadId > 0);
  lead.innerHTML = linkedLeadId > 0
    ? `Lead vinculado: #${escapeHtml(linkedLeadId)} · ${escapeHtml(conv?.lead?.name || '-')}`
    : '<span class="chat-link-cta">Sem lead vinculado.</span>';

  const messages = Array.isArray(chatState.messagesByConversation[conv.id]) ? chatState.messagesByConversation[conv.id] : [];
  const visibleMessages = messages.filter((m) => {
    const txt = String(m?.text || '').trim();
    if (!txt) return false;
    if (/^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2})?$/.test(txt)) return false;
    return true;
  });
  msgsEl.innerHTML = visibleMessages.map((m) => `
    <article class="chat-msg ${m.direction === 'outbound' ? 'out' : 'in'}">
      <p>${escapeHtml(m.text || '')}</p>
      <time>${escapeHtml((m.timestamp || '').replace('T', ' ').slice(0, 16))}</time>
    </article>
  `).join('') || '<p class="muted">Sem mensagens de texto nessa conversa.</p>';
  msgsEl.scrollTop = msgsEl.scrollHeight;

  renderChatLeadTray(chatState.selectedLeadId);
  if (chatState.selectedLeadId) {
    ensureLeadOperationalData(chatState.selectedLeadId).catch(() => {});
    ensureLeadNotesData(chatState.selectedLeadId).catch(() => {});
  }
  renderChatSnippets();
}

async function loadChatConversations({ keepSelection = true } = {}) {
  if (chatState.loading) return;
  chatState.loading = true;
  try {
    const out = await api('/api/chat/conversations');
    const items = Array.isArray(out?.items) ? out.items : [];
    chatState.conversations = items;
    if (out?.connection && typeof out.connection === 'object') {
      chatState.connection = out.connection;
    }
    if (!keepSelection || !chatConversationById(chatState.selectedConversationId)) {
      chatState.selectedConversationId = items.length ? String(items[0].id || '') : null;
    }
    renderChatConnection();
    renderChatConversations();
    renderChatThread();
    if (chatState.selectedConversationId) {
      await loadChatMessages(chatState.selectedConversationId);
    }
    if (!chatState.connection?.online) {
      setStatus('chat-status', 'WhatsApp offline. Conexão será retomada automaticamente.', true);
    } else {
      setStatus('chat-status', '');
    }
  } catch (err) {
    chatState.connection = { online: false, state: 'offline' };
    chatState.conversations = [];
    chatState.selectedConversationId = null;
    renderChatConnection();
    renderChatConversations();
    renderChatThread();
    setStatus('chat-status', err.message || 'Falha ao carregar conversas.', true);
  } finally {
    chatState.loading = false;
  }
}

async function loadChatMessages(conversationId) {
  const cid = String(conversationId || '').trim();
  if (!cid) return;
  const requestSeq = ++chatState.messagesRequestSeq;
  try {
    const out = await api(`/api/chat/conversations/${encodeURIComponent(cid)}/messages`);
    const normalizedConversationId = String(out?.conversationId || cid).trim() || cid;

    // Ignore stale responses from older requests or a different selected thread.
    if (requestSeq !== chatState.messagesRequestSeq) return;
    const currentSelected = String(chatState.selectedConversationId || '').trim();
    if (currentSelected !== cid && currentSelected !== normalizedConversationId) return;

    chatState.messagesByConversation[normalizedConversationId] = Array.isArray(out?.items) ? out.items : [];
    if (normalizedConversationId !== cid) {
      delete chatState.messagesByConversation[cid];
      chatState.selectedConversationId = normalizedConversationId;
      renderChatConversations();
    }
    renderChatThread();
  } catch (err) {
    if (requestSeq === chatState.messagesRequestSeq) {
      setStatus('chat-status', err.message || 'Falha ao carregar mensagens.', true);
    }
  }
}

async function sendChatMessage(evt) {
  evt.preventDefault();
  const selectedAtClick = String(chatState.selectedConversationId || '').trim();
  const input = document.getElementById('chat-input');
  const text = String(input?.value || '').trim();
  if (!selectedAtClick || !text) return;
  if (!chatState.connection?.online) {
    setStatus('chat-status', 'WhatsApp está offline. Aguarde reconexão para enviar.', true);
    return;
  }

  const sendBtn = document.getElementById('chat-send-btn');
  if (sendBtn) sendBtn.disabled = true;
  const sendSeq = ++chatState.sendRequestSeq;
  try {
    const out = await api('/api/chat/send', { method: 'POST', body: JSON.stringify({ conversationId: selectedAtClick, text }) });
    const sentConversationId = String(out?.conversationId || selectedAtClick).trim() || selectedAtClick;
    if (sentConversationId !== selectedAtClick) {
      throw new Error('Falha de integridade: conversa de envio divergente.');
    }
    if (input) input.value = '';

    // Do not overwrite UI if user switched chats while request was in flight.
    if (sendSeq !== chatState.sendRequestSeq) return;
    if (String(chatState.selectedConversationId || '') !== selectedAtClick) return;

    setStatus('chat-status', 'Atualizando conversa...');
    await loadChatMessages(selectedAtClick).catch(() => {});
    await loadChatConversations({ keepSelection: true }).catch(() => {});
    setStatus('chat-status', '');
  } catch (err) {
    setStatus('chat-status', err.message || 'Falha ao enviar mensagem.', true);
  } finally {
    if (sendBtn) sendBtn.disabled = false;
  }
}

async function promptLinkLead() {
  const cid = String(chatState.selectedConversationId || '').trim();
  if (!cid) return;
  const leadIdTxt = window.prompt('Digite o ID do lead para vincular com esta conversa.\n\nSe o lead ainda não existir, crie no board de Leads e volte aqui para vincular.');
  const leadId = Number(leadIdTxt);
  if (!leadId || Number.isNaN(leadId)) return;
  try {
    await api('/api/chat/link-lead', { method: 'POST', body: JSON.stringify({ conversationId: cid, leadId }) });
    await loadChatConversations({ keepSelection: true });
    await loadChatMessages(cid);
  } catch (err) {
    setStatus('chat-status', err.message || 'Falha ao vincular lead.', true);
  }
}

document.getElementById('crm-board-columns')?.addEventListener('click', onCrmBoardActivateLead);
document.getElementById('crm-board-columns')?.addEventListener('keydown', onCrmBoardKeydown);
document.getElementById('crm-board-columns')?.addEventListener('dragstart', onCrmBoardDragStart);
document.getElementById('crm-board-columns')?.addEventListener('dragover', onCrmBoardDragOver);
document.getElementById('crm-board-columns')?.addEventListener('dragleave', onCrmBoardDragLeave);
document.getElementById('crm-board-columns')?.addEventListener('drop', onCrmBoardDrop);
document.getElementById('crm-board-columns')?.addEventListener('dragend', onCrmBoardDragEnd);
document.getElementById('crm-lead-tray-body')?.addEventListener('click', onCrmTrayClick);
document.getElementById('crm-lead-tray-body')?.addEventListener('input', onCrmTrayInput);
document.getElementById('chat-lead-tray-body')?.addEventListener('click', onCrmTrayClick);
document.getElementById('chat-lead-tray-body')?.addEventListener('input', onCrmTrayInput);
document.querySelector('.crm-lead-tray-tabs')?.addEventListener('click', (evt) => {
  const tab = evt.target.closest('.crm-tray-tab[data-tray-tab]');
  if (!tab) return;
  const requestedTab = String(tab.dataset.trayTab || 'details');
  crmState.trayTab = ['details', 'operational', 'notes'].includes(requestedTab) ? requestedTab : 'details';
  renderCrmLeadTray();
  if (crmState.trayTab === 'operational' && crmState.selectedLeadId) ensureLeadOperationalData(crmState.selectedLeadId).catch(() => {});
  if (crmState.trayTab === 'notes' && crmState.selectedLeadId) ensureLeadNotesData(crmState.selectedLeadId).catch(() => {});
});
document.getElementById('chat-lead-tray-tabs')?.addEventListener('click', (evt) => {
  const tab = evt.target.closest('.crm-tray-tab[data-chat-tray-tab]');
  if (!tab) return;
  const requestedTab = String(tab.dataset.chatTrayTab || 'details');
  crmState.trayTab = ['details', 'operational', 'notes'].includes(requestedTab) ? requestedTab : 'details';
  renderChatLeadTray(chatState.selectedLeadId);
  if (crmState.trayTab === 'operational' && chatState.selectedLeadId) ensureLeadOperationalData(chatState.selectedLeadId).catch(() => {});
  if (crmState.trayTab === 'notes' && chatState.selectedLeadId) ensureLeadNotesData(chatState.selectedLeadId).catch(() => {});
});
document.getElementById('crm-edit-lead-btn')?.addEventListener('click', onEditLeadClick);
document.getElementById('crm-save-lead-btn')?.addEventListener('click', onSaveLeadClick);
document.getElementById('crm-cancel-edit-btn')?.addEventListener('click', onCancelEditClick);
document.getElementById('chat-edit-lead-btn')?.addEventListener('click', () => {
  if (!chatState.selectedLeadId) return;
  crmState.selectedLeadId = chatState.selectedLeadId;
  onEditLeadClick();
  renderChatLeadTray(chatState.selectedLeadId);
});
document.getElementById('chat-save-lead-btn')?.addEventListener('click', async () => {
  if (!chatState.selectedLeadId) return;
  crmState.selectedLeadId = chatState.selectedLeadId;
  await onSaveLeadClick();
  renderChatLeadTray(chatState.selectedLeadId);
});
document.getElementById('chat-cancel-edit-btn')?.addEventListener('click', () => {
  onCancelEditClick();
  renderChatLeadTray(chatState.selectedLeadId);
});
document.getElementById('crm-delete-selected-btn')?.addEventListener('click', onDeleteSelectedClick);
document.getElementById('crm-merge-selected-btn')?.addEventListener('click', onMergeSelectedClick);
document.getElementById('crm-is-ba-quick-filter')?.addEventListener('click', (evt) => {
  const btn = evt.target.closest('[data-action="crm-is-ba-filter"][data-value]');
  if (!btn) return;
  crmSetQuickFilterIsBa(btn.dataset.value);
});
document.getElementById('crm-leads-search')?.addEventListener('input', (evt) => {
  crmSetSearchText(evt?.target?.value || '');
});
document.getElementById('crm-leads-search-clear')?.addEventListener('click', () => {
  crmSetSearchText('');
  document.getElementById('crm-leads-search')?.focus();
});
document.getElementById('crm-merge-confirm-btn')?.addEventListener('click', onConfirmMergeClick);
document.getElementById('crm-merge-modal')?.addEventListener('click', (evt) => {
  const closeBtn = evt.target.closest('[data-action="close-merge-modal"]');
  if (closeBtn) crmCloseMergeModal();
});
document.getElementById('agenda-create-modal')?.addEventListener('click', (evt) => {
  const closeBtn = evt.target.closest('[data-action="close-agenda-modal"]');
  if (closeBtn) agendaCloseCreateModal();
});
document.getElementById('agenda-create-form')?.addEventListener('submit', submitAgendaCreateForm);
document.getElementById('chat-refresh-btn')?.addEventListener('click', () => {
  loadChatConversations({ keepSelection: true }).catch(() => {});
});
document.getElementById('chat-conversations-list')?.addEventListener('click', (evt) => {
  const btn = evt.target.closest('.chat-conv-item[data-conversation-id]');
  if (!btn) return;
  const cid = String(btn.dataset.conversationId || '').trim();
  if (!cid) return;
  chatState.selectedConversationId = cid;
  renderChatConversations();
  loadChatMessages(cid).catch(() => {});
});
document.getElementById('chat-composer')?.addEventListener('submit', sendChatMessage);
document.getElementById('chat-link-lead-btn')?.addEventListener('click', promptLinkLead);
document.getElementById('chat-snippet-groups')?.addEventListener('click', (evt) => {
  const btn = evt.target.closest('[data-action="chat-snippet-group"][data-group-id]');
  if (!btn) return;
  chatSnippetState.groupId = String(btn.dataset.groupId || 'abertura');
  renderChatSnippets();
});
document.getElementById('chat-snippet-items')?.addEventListener('click', (evt) => {
  const btn = evt.target.closest('[data-action="chat-snippet-item"][data-group-id][data-item-id]');
  if (!btn) return;
  const groupId = String(btn.dataset.groupId || '').trim();
  const itemId = String(btn.dataset.itemId || '').trim();
  const group = CHAT_SNIPPET_GROUPS.find((g) => g.id === groupId);
  const item = (group?.items || []).find((x) => x.id === itemId);
  if (!item) return;
  const text = fillSnippetTemplate(item.text, chatSnippetContext());
  chatInsertSnippet(text);
  chatTryAutoStage(groupId).catch(() => {});
});
document.getElementById('knowledge-refresh-btn')?.addEventListener('click', () => {
  loadKnowledge(knowledgeState.selectedId).catch(() => {});
});
document.getElementById('knowledge-new-btn')?.addEventListener('click', () => {
  createKnowledgeDoc().catch(() => {});
});
document.getElementById('knowledge-delete-btn')?.addEventListener('click', () => {
  deleteKnowledgeDoc().catch(() => {});
});
document.getElementById('knowledge-save-btn')?.addEventListener('click', () => {
  saveKnowledgeNow().catch(() => {});
});
document.getElementById('knowledge-undo-btn')?.addEventListener('click', () => {
  document.execCommand('undo');
});
document.getElementById('knowledge-page')?.addEventListener('input', () => {
  if (knowledgeState.suppressInput) return;
  scheduleKnowledgeAutosave();
});
document.getElementById('knowledge-list')?.addEventListener('click', (evt) => {
  const btn = evt.target.closest('[data-action="knowledge-doc"][data-doc-id]');
  if (!btn || btn.disabled) return;
  const docId = String(btn.dataset.docId || '').trim();
  if (!docId) return;
  knowledgeState.selectedId = docId;
  loadKnowledge(docId).catch(() => {});
});
document.getElementById('agenda-today-btn')?.addEventListener('click', agendaGoToToday);
document.getElementById('agenda-add-btn')?.addEventListener('click', agendaOpenCreateModal);
document.getElementById('agenda-prev-month')?.addEventListener('click', () => {
  const d = new Date(agendaState.viewYear, agendaState.viewMonth - 1, 1);
  agendaState.viewYear = d.getFullYear();
  agendaState.viewMonth = d.getMonth();
  renderAgendaCalendar();
});
document.getElementById('agenda-next-month')?.addEventListener('click', () => {
  const d = new Date(agendaState.viewYear, agendaState.viewMonth + 1, 1);
  agendaState.viewYear = d.getFullYear();
  agendaState.viewMonth = d.getMonth();
  renderAgendaCalendar();
});
document.getElementById('agenda-mini-calendar')?.addEventListener('click', (evt) => {
  const btn = evt.target.closest('[data-action="agenda-select-date"][data-date]');
  if (!btn) return;
  agendaState.selectedDate = String(btn.dataset.date || '').trim();
  renderAgenda();
  loadAgendaByDate(agendaState.selectedDate).catch(() => {});
});
document.getElementById('agenda-list')?.addEventListener('click', (evt) => {
  const statusBtn = evt.target.closest('[data-action="agenda-mark-status"][data-item-id][data-status]');
  if (statusBtn) {
    patchAgendaItem(String(statusBtn.dataset.itemId || ''), { status: String(statusBtn.dataset.status || '') }).catch(() => {});
    return;
  }
  const card = evt.target.closest('[data-action="agenda-open-lead"][data-item-id]');
  if (!card) return;
  const itemId = String(card.dataset.itemId || '').trim();
  const items = agendaState.itemsByDate[agendaState.selectedDate] || [];
  const item = items.find((x) => String(x.id || '') === itemId);
  if (item) openLeadTrayFromAgenda(item);
});
document.getElementById('albert-start-btn')?.addEventListener('click', () => {
  startAlbertSessionNow().catch(() => {});
});
document.getElementById('albert-schedule-btn')?.addEventListener('click', () => {
  scheduleAlbertSession().catch(() => {});
});
document.getElementById('albert-sessions-list')?.addEventListener('click', (evt) => {
  const btn = evt.target.closest('[data-action][data-id]');
  if (!btn) return;
  const sessionId = String(btn.dataset.id || '').trim();
  const item = (albertState.sessions || []).find((x) => String(x.id || '') === sessionId);
  if (!item) return;

  if (btn.dataset.action === 'albert-view-transcript') {
    window.alert(item.transcript || 'Transcrição ainda não disponível.');
    return;
  }
  if (btn.dataset.action === 'albert-view-insights') {
    const insights = Array.isArray(item.insights) ? item.insights : [];
    window.alert(insights.length ? insights.map((x, i) => `${i + 1}. ${x}`).join('\n') : 'Insights ainda não disponíveis.');
    return;
  }
  if (btn.dataset.action === 'albert-copy-summary') {
    albertCopyText(item.summary || '');
  }
});
document.addEventListener('click', onDocumentClickCloseTray);
document.addEventListener('keydown', (evt) => {
  if (evt.key !== 'Escape') return;
  if (agendaState.createModalOpen) agendaCloseCreateModal();
});
window.addEventListener('hashchange', () => {
  const hashTab = String(window.location.hash || '').replace(/^#/, '').trim();
  if (hashTab) activateTab(hashTab);
});

try {
  const forcedDoc = new URLSearchParams(window.location.search).get('doc');
  if (forcedDoc && String(forcedDoc).trim()) {
    knowledgeState.selectedId = String(forcedDoc).trim();
  }
} catch (_) {}

initTabs();
initNavToggle();
initFluxoListeners();
renderFluxo();
renderChatSnippets();

loadCrmBridge().catch((err) => {
  setStatus('crm-status', err.message, true);
});
loadChatConversations().catch((err) => {
  setStatus('chat-status', err.message, true);
});
renderAgenda();
loadAgendaByDate(agendaState.selectedDate).catch((err) => {
  setStatus('agenda-status', err.message, true);
});
renderAlbertPanel();
loadAlbertSessions().catch((err) => {
  setStatus('albert-status', err.message, true);
});

setInterval(() => {
  loadCrmBridge().catch(() => {});
}, 30000);
setInterval(() => {
  loadChatConversations({ keepSelection: true }).catch(() => {});
}, 12000);
setInterval(() => {
  loadAgendaByDate(agendaState.selectedDate).catch(() => {});
}, 30000);
setInterval(() => {
  loadAlbertSessions().catch(() => {});
}, 5000);

// ═══════════════════════════════════════════════════════════════
// SDR — AI Sales Development Representative
// ═══════════════════════════════════════════════════════════════

async function loadSDRDashboard() {
  try {
    const [metrics, convRes] = await Promise.all([
      api('/api/sdr/dashboard'),
      api('/api/sdr/conversations'),
    ]);

    const funnelEl = document.getElementById('sdr-funnel');
    const convsEl = document.getElementById('sdr-conversations');

    const states = metrics.by_state || {};
    const funnelStages = [
      { label: 'Total Leads', value: metrics.total_leads || 0, color: '#7c3aed' },
      { label: 'Qualificando', value: states.qualifying || 0, color: '#eab308' },
      { label: 'Qualificados', value: states.qualified || 0, color: '#22c55e' },
      { label: 'Agendados', value: states.scheduled || 0, color: '#3b82f6' },
      { label: 'Nurture', value: states.nurture || 0, color: '#6b7280' },
      { label: 'Escalados', value: states.escalated || 0, color: '#ef4444' },
      { label: 'Sem Resposta', value: states.no_response || 0, color: '#6b7280' },
    ];

    funnelEl.innerHTML = funnelStages.map(s =>
      `<div style="background:#1a1a1a;border:1px solid #333;border-radius:10px;padding:16px 20px;min-width:120px;text-align:center">
        <div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px">${s.label}</div>
        <div style="font-size:28px;font-weight:700;color:${s.color}">${s.value}</div>
      </div>`
    ).join('') +
    `<div style="background:#1a1a1a;border:1px solid #333;border-radius:10px;padding:16px 20px;min-width:120px;text-align:center">
      <div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px">Conversao</div>
      <div style="font-size:28px;font-weight:700;color:#22c55e">${metrics.conversion_rate || 0}%</div>
    </div>`;

    const items = convRes.items || [];
    if (!items.length) {
      convsEl.innerHTML = '<p style="color:#888;padding:20px;text-align:center">Nenhuma conversa SDR ainda.</p>';
      return;
    }

    convsEl.innerHTML = `<table style="width:100%;border-collapse:collapse;font-size:13px">
      <thead><tr style="border-bottom:1px solid #333">
        <th style="text-align:left;padding:8px;color:#888;font-size:11px;text-transform:uppercase">Lead</th>
        <th style="text-align:left;padding:8px;color:#888;font-size:11px;text-transform:uppercase">Telefone</th>
        <th style="text-align:left;padding:8px;color:#888;font-size:11px;text-transform:uppercase">Estado</th>
        <th style="text-align:left;padding:8px;color:#888;font-size:11px;text-transform:uppercase">Produto</th>
        <th style="text-align:left;padding:8px;color:#888;font-size:11px;text-transform:uppercase">Msgs</th>
        <th style="text-align:left;padding:8px;color:#888;font-size:11px;text-transform:uppercase">Atualizado</th>
      </tr></thead>
      <tbody>${items.map(c => {
        const qual = c.qualification || {};
        const stateColors = { qualifying: '#eab308', qualified: '#22c55e', scheduled: '#3b82f6', escalated: '#ef4444', nurture: '#6b7280', no_response: '#6b7280', new: '#7c3aed' };
        const color = stateColors[c.state] || '#888';
        const product = qual.product_route || '-';
        const updated = c.updated_at ? new Date(c.updated_at).toLocaleString('pt-BR') : '-';
        return `<tr style="border-bottom:1px solid #222">
          <td style="padding:8px"><strong>${escapeHtml(c.name || c.lead_id)}</strong></td>
          <td style="padding:8px;color:#888;font-size:12px">${escapeHtml(c.phone || '')}</td>
          <td style="padding:8px"><span style="color:${color};font-weight:600;font-size:12px">${escapeHtml(c.state)}</span></td>
          <td style="padding:8px;font-size:12px">${escapeHtml(product)}</td>
          <td style="padding:8px;font-size:12px">${(c.messages || []).length}</td>
          <td style="padding:8px;color:#888;font-size:11px">${updated}</td>
        </tr>`;
      }).join('')}</tbody>
    </table>`;
  } catch (err) {
    document.getElementById('sdr-funnel').innerHTML = `<p style="color:#ef4444">Erro: ${escapeHtml(err.message)}</p>`;
  }
}

// ── SDR Scripts ──

let _sdrEditingId = null;

async function loadSDRScripts() {
  try {
    const data = await api('/api/sdr/scripts');
    const scripts = data.scripts || [];
    const listEl = document.getElementById('sdr-scripts-list');

    if (!scripts.length) {
      listEl.innerHTML = '<p style="color:#888;padding:20px;text-align:center">Nenhum script criado.</p>';
      return;
    }

    listEl.innerHTML = scripts.map(s =>
      `<div style="background:#1a1a1a;border:1px solid #333;border-radius:10px;padding:16px;margin-bottom:10px;display:flex;align-items:center;justify-content:space-between">
        <div>
          <strong>${escapeHtml(s.name)}</strong>
          <span style="margin-left:8px;font-size:11px;padding:2px 8px;border-radius:10px;background:${s.active ? 'rgba(34,197,94,.15)' : 'rgba(107,114,128,.15)'};color:${s.active ? '#22c55e' : '#888'}">${s.active ? 'ativo' : 'inativo'}</span>
          <span style="margin-left:8px;font-size:11px;color:#888">${escapeHtml(s.product || 'both')}</span>
        </div>
        <div style="display:flex;gap:6px">
          <button class="quick-action" style="font-size:12px;padding:4px 10px" onclick="sdrEditScript('${escapeHtml(s.id)}')">Editar</button>
          <button class="quick-action" style="font-size:12px;padding:4px 10px;background:transparent;border:1px solid #333;color:#888" onclick="sdrToggleScript('${escapeHtml(s.id)}', ${!s.active})">${s.active ? 'Desativar' : 'Ativar'}</button>
          <button class="quick-action" style="font-size:12px;padding:4px 10px;background:rgba(239,68,68,.15);color:#ef4444;border:1px solid rgba(239,68,68,.3)" onclick="sdrDeleteScript('${escapeHtml(s.id)}')">Excluir</button>
        </div>
      </div>`
    ).join('');
  } catch (err) {
    document.getElementById('sdr-scripts-list').innerHTML = `<p style="color:#ef4444">Erro: ${escapeHtml(err.message)}</p>`;
  }
}

async function sdrEditScript(scriptId) {
  try {
    const s = await api(`/api/sdr/scripts/${scriptId}`);
    _sdrEditingId = scriptId;
    document.getElementById('sdr-script-id').value = scriptId;
    document.getElementById('sdr-script-name').value = s.name || '';
    document.getElementById('sdr-script-product').value = s.product || 'both';
    document.getElementById('sdr-script-prompt').value = s.system_prompt || '';
    document.getElementById('sdr-script-first-msg').value = s.first_message_template || '';
    document.getElementById('sdr-script-triggers').value = (s.escalation_triggers || []).join('\n');
    document.getElementById('sdr-script-editor').classList.remove('is-hidden');
  } catch (err) {
    alert('Erro ao carregar script: ' + err.message);
  }
}

function sdrNewScript() {
  _sdrEditingId = null;
  document.getElementById('sdr-script-id').value = '';
  document.getElementById('sdr-script-name').value = '';
  document.getElementById('sdr-script-product').value = 'both';
  document.getElementById('sdr-script-prompt').value = '';
  document.getElementById('sdr-script-first-msg').value = '';
  document.getElementById('sdr-script-triggers').value = '';
  document.getElementById('sdr-script-editor').classList.remove('is-hidden');
}

function sdrCancelEdit() {
  _sdrEditingId = null;
  document.getElementById('sdr-script-editor').classList.add('is-hidden');
}

async function sdrSaveScript() {
  const payload = {
    name: document.getElementById('sdr-script-name').value,
    product: document.getElementById('sdr-script-product').value,
    system_prompt: document.getElementById('sdr-script-prompt').value,
    first_message_template: document.getElementById('sdr-script-first-msg').value,
    escalation_triggers: document.getElementById('sdr-script-triggers').value.split('\n').map(s => s.trim()).filter(Boolean),
  };

  try {
    if (_sdrEditingId) {
      await api(`/api/sdr/scripts/${_sdrEditingId}`, { method: 'PUT', body: JSON.stringify(payload) });
    } else {
      await api('/api/sdr/scripts', { method: 'POST', body: JSON.stringify(payload) });
    }
    sdrCancelEdit();
    await loadSDRScripts();
  } catch (err) {
    alert('Erro ao salvar: ' + err.message);
  }
}

async function sdrToggleScript(scriptId, active) {
  try {
    await api(`/api/sdr/scripts/${scriptId}`, { method: 'PUT', body: JSON.stringify({ active }) });
    await loadSDRScripts();
  } catch (err) {
    alert('Erro: ' + err.message);
  }
}

async function sdrDeleteScript(scriptId) {
  if (!confirm('Excluir este script?')) return;
  try {
    await api(`/api/sdr/scripts/${scriptId}`, { method: 'DELETE' });
    await loadSDRScripts();
  } catch (err) {
    alert('Erro: ' + err.message);
  }
}
