'use strict';

const STAGE_FALLBACK = ['spec', 'ready', 'building', 'checks', 'validation', 'done'];

const state = {
  token: '',
  identity: null,
  actorId: null,
  actors: [],
  meta: null,
  cards: [],
  prds: [],
  comments: null,
  selectedCardId: null,
  tab: 'board',
  search: '',
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

/* Helpers ------------------------------------------------------------------ */

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[char]));
}

function stageOrder() {
  return state.meta?.stages || STAGE_FALLBACK;
}

function stageLabel(stage) {
  return stage ? stage.charAt(0).toUpperCase() + stage.slice(1) : '';
}

function actorById(id) {
  return state.actors.find((actor) => actor.id === id) || null;
}

function actorName(id) {
  return actorById(id)?.display_name || id || 'unknown';
}

function initials(name) {
  return String(name || '?')
    .replace(/\([^)]*\)/g, ' ')
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((word) => word[0] || '')
    .join('')
    .toUpperCase();
}

function formatDate(iso) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return String(iso);
  return date.toLocaleString(undefined, {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  });
}

function humanOnlySet() {
  return new Set((state.meta?.human_only_transitions || []).map(([from, to]) => `${from}->${to}`));
}

function isTyping(target) {
  return target instanceof HTMLElement
    && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.tagName === 'SELECT' || target.isContentEditable);
}

function errorText(error) {
  let text = error.message || 'Request failed.';
  if (Array.isArray(error.details)) {
    const lines = error.details.map((detail) => {
      const location = Array.isArray(detail.location)
        ? detail.location.filter((part) => part !== 'body').join('.')
        : '';
      return location ? `${location}: ${detail.message}` : detail.message;
    }).filter(Boolean);
    if (lines.length) text += `\n${lines.join('\n')}`;
  }
  return text;
}

/* HTTP --------------------------------------------------------------------- */

function authHeaders(extra = {}) {
  const headers = { ...extra };
  if (state.token) headers['Authorization'] = `Bearer ${state.token}`;
  return headers;
}

async function api(path, { method = 'GET', body } = {}) {
  const headers = authHeaders({ Accept: 'application/json' });
  if (body !== undefined) headers['Content-Type'] = 'application/json';

  let response;
  try {
    response = await fetch(path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    const error = new Error('Could not reach the API. Is the server running?');
    error.code = 'network_error';
    throw error;
  }

  let payload = null;
  if ((response.headers.get('content-type') || '').includes('application/json')) {
    try { payload = await response.json(); } catch { payload = null; }
  }

  if (!response.ok) {
    const envelope = payload?.error || {};
    const error = new Error(envelope.message || `Request failed with HTTP ${response.status}.`);
    error.code = envelope.code || `http_${response.status}`;
    error.status = response.status;
    error.details = envelope.details;
    if (response.status === 401 && ['missing_token', 'invalid_token'].includes(error.code)) {
      clearSession();
      showLogin('Your session expired. Sign in again.');
    }
    throw error;
  }
  return payload;
}

/* Toasts and health -------------------------------------------------------- */

function toast(kind, title, message = '', code = '') {
  const wrap = $('#toasts');
  const node = document.createElement('div');
  node.className = `toast toast--${kind}`;
  node.innerHTML = `
    <div class="toast-title">
      <span>${kind === 'error' ? '✕' : '✓'}</span>
      <span>${esc(title)}</span>
      ${code ? `<span class="toast-code">${esc(code)}</span>` : ''}
    </div>
    ${message ? `<div class="toast-msg">${esc(message)}</div>` : ''}`;
  wrap.appendChild(node);
  while (wrap.children.length > 4) wrap.firstElementChild.remove();
  setTimeout(() => {
    node.classList.add('toast--leaving');
    setTimeout(() => node.remove(), 200);
  }, kind === 'error' ? 7500 : 4200);
}

async function checkHealth() {
  const pill = $('#health');
  const text = $('#health-text');
  try {
    const health = await api('/api/v1/health');
    pill.className = 'health health--ok';
    text.textContent = `online · v${health.version}`;
  } catch {
    pill.className = 'health health--down';
    text.textContent = 'offline';
  }
}

/* Authentication ----------------------------------------------------------- */

function showLogin(message = '') {
  const form = $('#login-form');
  const error = $('#login-error');
  if (form) form.hidden = false;
  if (error) {
    error.textContent = message;
    error.hidden = !message;
  }
  const identity = $('#auth-identity');
  if (identity) identity.hidden = true;
}

function clearSession() {
  state.token = '';
  state.identity = null;
  state.actorId = null;
  state.actors = [];
  state.meta = null;
  state.cards = [];
  state.prds = [];
}

function setIdentity(me) {
  state.identity = me;
  state.actorId = me.actor_id;
  const form = $('#login-form');
  const identity = $('#auth-identity');
  if (form) form.hidden = true;
  if (identity) identity.hidden = false;
  const error = $('#login-error');
  if (error) error.hidden = true;

  const avatar = $('#actor-avatar');
  if (avatar) {
    avatar.textContent = initials(me.display_name);
    avatar.className = `avatar avatar--${me.role}`;
  }
  const name = $('#auth-name');
  if (name) name.textContent = `${me.display_name} · ${me.username}`;
  const badge = $('#actor-role');
  if (badge) {
    badge.textContent = me.role;
    badge.dataset.role = me.role;
  }
  const foot = document.getElementById('gantryChatFoot');
  if (foot) foot.textContent = `Gantry AI · signed in as ${me.display_name}`;
  renderRules();
}

async function loadSession() {
  if (!state.token) {
    showLogin();
    return false;
  }
  const me = await api('/api/v1/auth/me');
  setIdentity(me);
  return true;
}

async function login(event) {
  event.preventDefault();
  const username = ($('#login-username')?.value || '').trim();
  const password = $('#login-password')?.value || '';
  const button = $('#login-button');
  if (button) button.disabled = true;
  try {
    const response = await fetch('/api/v1/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload?.error?.message || `Sign in failed (HTTP ${response.status}).`);
    }
    state.token = payload.access_token;
    const field = $('#login-password');
    if (field) field.value = '';
    await loadSession();
    if (state.identity) await refresh({ quiet: true });
    toast(
      'success',
      `Signed in as ${state.identity?.display_name || username}`,
      state.identity?.role === 'agent'
        ? 'Agents may claim work, build and comment.'
        : 'Humans approve specs, accept checks, assign and validate work.',
    );
  } catch (error) {
    showLogin(errorText(error));
  } finally {
    if (button) button.disabled = false;
  }
}

function logout() {
  clearSession();
  showLogin();
  const board = $('#board');
  const list = $('#prd-list');
  if (board) board.innerHTML = '<p class="empty-note">Sign in to load the board.</p>';
  if (list) list.innerHTML = '<p class="empty-note">Sign in to load PRDs.</p>';
  toast('success', 'Signed out', 'The token was removed from this browser.');
}

/* Board -------------------------------------------------------------------- */

function renderBoard() {
  const board = $('#board');
  if (!state.meta) {
    board.innerHTML = '<p class="empty-note">Loading the funnel…</p>';
    return;
  }

  const query = state.search.trim().toLowerCase();
  const visible = state.cards.filter((card) => (
    !query || `${card.title} ${card.goal}`.toLowerCase().includes(query)
  ));

  board.innerHTML = stageOrder().map((stage) => {
    const cards = visible.filter((card) => card.stage === stage);
    const tiles = cards.map((card) => {
      const assignee = card.assignee;
      return `
        <article class="card-tile stage-${esc(stage)}" draggable="true" tabindex="0"
                 data-id="${esc(card.id)}" role="button"
                 aria-label="Open card ${esc(card.title)}">
          <span class="card-tile-title" dir="auto">${esc(card.title)}</span>
          <div class="card-tile-meta">
            ${assignee
              ? `<span class="mini-chip"><span class="avatar avatar--${esc(assignee.role)}">${esc(initials(assignee.display_name))}</span>${esc(assignee.display_name)}</span>`
              : '<span class="mini-chip">unassigned</span>'}
            ${card.source === 'prd' ? '<span class="mini-chip mini-chip--prd">PRD</span>' : ''}
            ${card.depends_on.length ? `<span class="mini-chip mini-chip--deps">${card.depends_on.length} dep</span>` : ''}
            <span class="mono" title="${esc(card.id)}">#${esc(card.id.slice(-6))}</span>
          </div>
        </article>`;
    }).join('');

    return `
      <section class="column stage-${esc(stage)}" data-stage="${esc(stage)}" aria-label="${esc(stageLabel(stage))} stage">
        <header class="column-head">
          <span class="stage-name"><span class="stage-dot" aria-hidden="true"></span>${esc(stageLabel(stage))}</span>
          <span class="column-count">${cards.length}</span>
        </header>
        <div class="column-body">
          ${tiles || '<div class="column-empty">Drop a card here or create one.</div>'}
        </div>
      </section>`;
  }).join('');

  const done = state.cards.filter((card) => card.stage === 'done').length;
  const fromPrds = state.cards.filter((card) => card.source === 'prd').length;
  const total = state.cards.length;
  $('#board-summary').textContent = `${total} card${total === 1 ? '' : 's'} · ${done} done · ${fromPrds} from PRDs · drag a card to attempt a move`;
}

/* Drawer ------------------------------------------------------------------- */

async function openCard(cardId) {
  const card = state.cards.find((item) => item.id === cardId);
  if (!card) return;

  state.selectedCardId = cardId;
  state.comments = null;
  renderDrawer(card);

  $('#scrim').hidden = false;
  const drawer = $('#drawer');
  drawer.classList.add('is-open');
  drawer.setAttribute('aria-hidden', 'false');
  document.body.style.overflow = 'hidden';
  document.body.classList.add('overlay-open');

  try {
    const data = await api(`/api/v1/cards/${encodeURIComponent(cardId)}/comments`);
    if (state.selectedCardId === cardId) {
      state.comments = data.items;
      renderComments();
    }
  } catch (error) {
    if (state.selectedCardId === cardId) {
      state.comments = [];
      renderComments(error);
    }
  }
}

function closeDrawer() {
  state.selectedCardId = null;
  state.comments = null;
  const drawer = $('#drawer');
  drawer.classList.remove('is-open');
  drawer.setAttribute('aria-hidden', 'true');
  $('#scrim').hidden = true;
  document.body.style.overflow = '';
  document.body.classList.remove('overlay-open');
}

function renderDrawer(card) {
  const body = $('#drawer-body');
  const assignee = card.assignee;
  const current = actorById(state.actorId);
  const humanOnly = humanOnlySet();
  const targets = state.meta?.transitions?.[card.stage] || [];
  const actor = current?.role === 'human' ? 'human' : 'agent';

  const moves = targets.length
    ? targets.map((to) => {
      const locked = humanOnly.has(`${card.stage}->${to}`);
      const needsOtherHuman = card.stage === 'validation' && to === 'done';
      const title = needsOtherHuman
        ? 'Human-only: a human who did not build the card must validate it.'
        : locked
          ? 'Human-only edge: an agent gets 403 here.'
          : 'Any actor may take this edge.';
      return `
        <button class="btn btn--sm move-btn" type="button" data-move-to="${esc(to)}"
                title="${title}">
          → ${esc(stageLabel(to))}${locked ? ' <span class="lock" aria-hidden="true">🔒</span>' : ''}
        </button>`;
    }).join('')
    : '<span class="muted">Terminal stage — no outgoing moves.</span>';

  const editForm = card.stage === 'spec' ? `
    <details class="drawer-section">
      <summary class="details-toggle">Edit the spec</summary>
      <form id="edit-form" class="edit-form">
        <label class="field"><span>Title</span>
          <input class="input" name="title" required minlength="3" maxlength="80" value="${esc(card.title)}">
        </label>
        <label class="field"><span>Goal</span>
          <textarea class="input input--area" name="goal" required minlength="10" maxlength="400" rows="3">${esc(card.goal)}</textarea>
        </label>
        <label class="field"><span>Acceptance criteria <small>one per line</small></span>
          <textarea class="input input--area" name="criteria" required rows="4">${esc(card.acceptance_criteria.join('\n'))}</textarea>
        </label>
        <label class="field"><span>Out of scope <small>one per line</small></span>
          <textarea class="input input--area" name="scope" rows="2">${esc(card.out_of_scope.join('\n'))}</textarea>
        </label>
        <button class="btn btn--sm btn--primary" type="submit">Save spec</button>
      </form>
    </details>` : '';

  const assignOptions = [
    '<option value="">Unassigned</option>',
    ...state.actors.map((item) => (
      `<option value="${esc(item.id)}" ${assignee?.id === item.id ? 'selected' : ''}>${esc(item.display_name)} · ${esc(item.role)}</option>`
    )),
  ].join('');

  body.innerHTML = `
    <div class="drawer-head">
      <div>
        <span class="stage-pill stage-${esc(card.stage)}"><span class="stage-dot" aria-hidden="true"></span>${esc(stageLabel(card.stage))}</span>
        <h2 dir="auto">${esc(card.title)}</h2>
      </div>
      <button class="icon-btn" type="button" id="drawer-close" aria-label="Close detail panel">×</button>
    </div>
    <p class="drawer-id mono">${esc(card.id)} · v${card.version} · ${esc(card.source)}${card.prd_id ? ` · ${esc(card.prd_id)}` : ''}</p>
    <p class="drawer-goal" dir="auto">${esc(card.goal)}</p>

    <h3>Acceptance criteria</h3>
    <ul>${card.acceptance_criteria.map((item) => `<li>${esc(item)}</li>`).join('')}</ul>

    ${card.out_of_scope.length ? `<h3>Out of scope</h3><ul>${card.out_of_scope.map((item) => `<li>${esc(item)}</li>`).join('')}</ul>` : ''}
    ${card.depends_on.length ? `<h3>Depends on</h3><div class="edge-chips">${card.depends_on.map((item) => `<span class="edge-chip">${esc(item)}</span>`).join('')}</div>` : ''}

    <h3>Move this card</h3>
    <div class="move-grid">${moves}</div>
    <p class="assignee-hint">${card.stage === 'validation'
      ? 'Done is human-only, and it must be a human who did not build this card. If the server rejects you, switch actor in the header and try again.'
      : 'Locked edges are human-only. The server checks your role, not the button.'}</p>
    ${editForm}

    <div class="drawer-section">
      <h3>Assignee</h3>
      <div class="assignee-row">
        <select id="assignee-select" class="input" aria-label="Assignee">${assignOptions}</select>
      </div>
      <p class="assignee-hint">${actor === 'human'
        ? 'Assignment is a human decision; you can set or clear it.'
        : 'Assignment is human-only. As an agent this request returns 403.'}</p>
    </div>

    <div class="drawer-section">
      <h3>Comments</h3>
      <div id="comment-list" class="comment-list"></div>
      <form id="comment-form" class="comment-form">
        <textarea name="body" class="input input--area" rows="2" maxlength="2000"
                  placeholder="Add a comment as ${esc(actorName(state.actorId))}…" required></textarea>
        <button class="btn btn--sm" type="submit">Comment</button>
      </form>
    </div>

    <div class="drawer-section">
      <button id="delete-card" class="btn btn--danger btn--sm" type="button">Delete card</button>
    </div>`;

  $('#drawer-close', body).addEventListener('click', closeDrawer);

  $$('[data-move-to]', body).forEach((button) => {
    button.addEventListener('click', () => transitionCard(card.id, button.dataset.moveTo));
  });

  $('#assignee-select', body).addEventListener('change', (event) => {
    assignCard(card.id, event.target.value);
  });

  const edit = $('#edit-form', body);
  if (edit) {
    edit.addEventListener('submit', (event) => {
      event.preventDefault();
      saveSpec(card.id, edit);
    });
  }

  $('#comment-form', body).addEventListener('submit', (event) => {
    event.preventDefault();
    submitComment(card.id, event.currentTarget);
  });

  $('#delete-card', body).addEventListener('click', () => deleteCard(card.id, card.title));

  renderComments();
}

function renderComments(error = null) {
  const list = document.getElementById('comment-list');
  if (!list) return;
  if (error) {
    list.innerHTML = `<p class="empty-note">Could not load comments: ${esc(error.message)}</p>`;
    return;
  }
  if (state.comments === null) {
    list.innerHTML = '<p class="empty-note">Loading comments…</p>';
    return;
  }
  if (!state.comments.length) {
    list.innerHTML = '<p class="empty-note">No comments yet. Humans and agents can both comment.</p>';
    return;
  }
  list.innerHTML = state.comments.map((comment) => `
    <div class="comment">
      <div class="comment-head">
        <span class="avatar avatar--${esc(comment.author.role)}">${esc(initials(comment.author.display_name))}</span>
        <strong>${esc(comment.author.display_name)}</strong>
        <span>·</span>
        <span>${esc(formatDate(comment.created_at))}</span>
      </div>
      <div class="comment-body" dir="auto">${esc(comment.body)}</div>
    </div>`).join('');
}

/* Card mutations ----------------------------------------------------------- */

async function transitionCard(cardId, toStage) {
  const card = state.cards.find((item) => item.id === cardId);
  const drawerOpen = state.selectedCardId === cardId;
  try {
    await api(`/api/v1/cards/${encodeURIComponent(cardId)}/transition`, {
      method: 'POST',
      body: { to_stage: toStage },
    });
    toast('success', 'Card moved', `${card ? card.title : cardId} → ${stageLabel(toStage)}`);
    await refresh({ quiet: true });
    if (drawerOpen) await openCard(cardId);
  } catch (error) {
    if (error.code === 'self_validation_blocked') {
      toast(
        'error',
        'A different human must validate',
        'The actor that built this card cannot mark it Done. Switch to another human in the header, open the card and press → Done again.',
        error.code
      );
      return;
    }
    toast('error', 'Move rejected by the server', errorText(error), error.code);
  }
}

async function assignCard(cardId, assigneeId) {
  try {
    await api(`/api/v1/cards/${encodeURIComponent(cardId)}/assignee`, {
      method: 'PUT',
      body: { assignee_id: assigneeId || null },
    });
    toast('success', 'Assignment updated', assigneeId ? `Assigned to ${actorName(assigneeId)}` : 'Assignee cleared');
  } catch (error) {
    toast('error', 'Assignment rejected', errorText(error), error.code);
  }
  await refresh({ quiet: true });
  if (state.selectedCardId === cardId) await openCard(cardId);
}

async function saveSpec(cardId, form) {
  const lines = (value) => value.split('\n').map((line) => line.trim()).filter(Boolean);
  const payload = {
    title: form.elements.title.value.trim(),
    goal: form.elements.goal.value.trim(),
    acceptance_criteria: lines(form.elements.criteria.value),
    out_of_scope: lines(form.elements.scope.value),
  };
  try {
    await api(`/api/v1/cards/${encodeURIComponent(cardId)}`, { method: 'PATCH', body: payload });
    toast('success', 'Spec saved', 'The card is still in spec.');
    await refresh({ quiet: true });
    await openCard(cardId);
  } catch (error) {
    toast('error', 'Edit rejected', errorText(error), error.code);
  }
}

async function submitComment(cardId, form) {
  const body = form.elements.body.value.trim();
  if (!body) return;
  try {
    await api(`/api/v1/cards/${encodeURIComponent(cardId)}/comments`, {
      method: 'POST',
      body: { body },
    });
    form.elements.body.value = '';
    toast('success', 'Comment added');
    const data = await api(`/api/v1/cards/${encodeURIComponent(cardId)}/comments`);
    if (state.selectedCardId === cardId) {
      state.comments = data.items;
      renderComments();
    }
  } catch (error) {
    toast('error', 'Comment rejected', errorText(error), error.code);
  }
}

async function deleteCard(cardId, title) {
  if (!window.confirm(`Delete “${title}”? Its comments are deleted with it.`)) return;
  try {
    await api(`/api/v1/cards/${encodeURIComponent(cardId)}`, { method: 'DELETE' });
    toast('success', 'Card deleted', title);
    closeDrawer();
    await refresh({ quiet: true });
  } catch (error) {
    toast('error', 'Delete rejected', errorText(error), error.code);
  }
}

/* Create card dialog ------------------------------------------------------- */

function openCardDialog() {
  const form = $('#card-form');
  form.reset();
  $('#card-error').hidden = true;
  $('#card-assignee').innerHTML = [
    '<option value="">Unassigned</option>',
    ...state.actors.map((actor) => (
      `<option value="${esc(actor.id)}">${esc(actor.display_name)} · ${esc(actor.role)}</option>`
    )),
  ].join('');
  $('#card-dialog').showModal();
  setTimeout(() => $('#card-title').focus(), 30);
}

async function createCard(event) {
  event.preventDefault();
  const box = $('#card-error');
  box.hidden = true;
  const lines = (value) => value.split('\n').map((line) => line.trim()).filter(Boolean);
  const payload = {
    title: $('#card-title').value.trim(),
    goal: $('#card-goal').value.trim(),
    acceptance_criteria: lines($('#card-criteria').value),
    out_of_scope: lines($('#card-scope').value),
    assignee_id: $('#card-assignee').value || null,
  };
  try {
    const card = await api('/api/v1/cards', { method: 'POST', body: payload });
    $('#card-dialog').close();
    $('#card-form').reset();
    toast('success', 'Card created', card.title);
    await refresh({ quiet: true });
    await openCard(card.id);
  } catch (error) {
    box.hidden = false;
    box.textContent = errorText(error);
  }
}

/* PRDs --------------------------------------------------------------------- */

const SAMPLE_PRD_BODY = `# Card comments

Users need a way to discuss a card without leaving the board.

- Add comments to every card with a body and an author.
- Reject empty comments with HTTP 422 and an error code.
- List comments oldest first.
- Let both humans and agents add comments.`;

function renderPrds() {
  const list = $('#prd-list');
  const count = $('#prd-count');
  count.textContent = `${state.prds.length} saved`;

  if (!state.prds.length) {
    list.innerHTML = '<p class="empty-note">No PRDs yet. Write one on the left, then run a breakdown.</p>';
    return;
  }

  list.innerHTML = state.prds.map((prd) => `
    <article class="prd-item">
      <div class="prd-item-head">
        <div>
          <h3>${esc(prd.title)}</h3>
          <div class="prd-meta">${esc(prd.created_by.display_name)} · ${esc(formatDate(prd.created_at))} · <span class="mono">${esc(prd.id)}</span></div>
        </div>
      </div>
      <p class="prd-preview">${esc(prd.body)}</p>
      <details class="prd-details">
        <summary class="details-toggle">Read body</summary>
        <div class="prd-full">${esc(prd.body)}</div>
      </details>
      <div class="prd-actions">
        <button class="btn btn--primary btn--sm" type="button" data-breakdown="${esc(prd.id)}">Break down</button>
      </div>
    </article>`).join('');

  $$('[data-breakdown]', list).forEach((button) => {
    button.addEventListener('click', () => runBreakdown(button.dataset.breakdown, button));
  });
}

function renderBreakdownResult(data, error) {
  const box = $('#breakdown-result');
  box.hidden = false;
  box.classList.toggle('result--error', Boolean(error));

  if (error) {
    box.innerHTML = `
      <h3>Breakdown failed</h3>
      <p class="muted">${esc(errorText(error))}</p>
      ${error.code ? `<p style="margin-top:6px"><span class="toast-code">${esc(error.code)}</span></p>` : ''}`;
    return;
  }

  const usage = data.usage;
  const links = data.cards.map((card) => (
    `<button class="btn btn--sm" type="button" data-open-card="${esc(card.id)}">${esc(card.title)}</button>`
  )).join('');

  box.innerHTML = `
    <h3>Breakdown complete</h3>
    <div class="result-stats">
      <span class="mini-chip">model ${esc(data.model_used)}</span>
      <span class="mini-chip">prompt ${esc(data.prompt_version)}</span>
      <span class="mini-chip">${data.cards.length} cards</span>
      <span class="mini-chip">${data.attempts} attempt${data.attempts === 1 ? '' : 's'}</span>
      <span class="mini-chip">fallback ${data.fallback_used ? 'yes' : 'no'}</span>
      <span class="mini-chip">${usage.input_tokens} in / ${usage.output_tokens} out</span>
      <span class="mini-chip">$${Number(usage.estimated_cost_usd).toFixed(6)}</span>
      <span class="mini-chip">${data.duration_ms} ms</span>
    </div>
    ${data.warnings.length ? `<p class="muted">Warnings: ${data.warnings.map(esc).join(' · ')}</p>` : ''}
    <div class="result-card-links">${links}</div>`;

  $$('[data-open-card]', box).forEach((button) => {
    button.addEventListener('click', () => {
      switchTab('board');
      openCard(button.dataset.openCard);
    });
  });
}

async function runBreakdown(prdId, button) {
  const model = $('#breakdown-model').value || null;
  const promptVersion = $('#prompt-version').value || null;
  const original = button.textContent;
  button.disabled = true;
  button.textContent = 'Breaking down…';

  try {
    const data = await api(`/api/v1/prds/${encodeURIComponent(prdId)}/breakdown`, {
      method: 'POST',
      body: { prompt_version: promptVersion, model },
    });
    await refresh({ quiet: true });
    renderBreakdownResult(data, null);
    toast('success', 'Breakdown complete', `${data.cards.length} cards created in spec · ${data.model_used}`);
  } catch (error) {
    renderBreakdownResult(null, error);
    toast('error', 'Breakdown failed', errorText(error), error.code);
  } finally {
    button.disabled = false;
    button.textContent = original;
  }
}

async function createPrd(event) {
  event.preventDefault();
  const box = $('#prd-error');
  box.hidden = true;
  const payload = {
    title: $('#prd-title').value.trim(),
    body: $('#prd-body').value.trim(),
  };
  try {
    const prd = await api('/api/v1/prds', { method: 'POST', body: payload });
    $('#prd-form').reset();
    toast('success', 'PRD saved', prd.title);
    await refresh({ quiet: true });
  } catch (error) {
    box.hidden = false;
    box.textContent = errorText(error);
  }
}

function useSamplePrd() {
  $('#prd-title').value = 'Card comments';
  $('#prd-body').value = SAMPLE_PRD_BODY;
  $('#prd-body').focus();
}

/* Rules and metadata ------------------------------------------------------- */

function renderRules() {
  if (!state.meta) return;
  const humanOnly = humanOnlySet();

  $('#transition-table').innerHTML = stageOrder().map((from) => {
    const targets = state.meta.transitions[from] || [];
    const chips = targets.length
      ? targets.map((to) => {
        const locked = humanOnly.has(`${from}->${to}`);
        return `<span class="edge-chip ${locked ? 'edge-chip--human' : ''}">→ ${esc(to)}${locked ? ' 🔒' : ''}</span>`;
      }).join('')
      : '<span class="edge-chip edge-chip--none">terminal</span>';
    return `<tr><td>${esc(from)}</td><td><div class="edge-chips">${chips}</div></td></tr>`;
  }).join('');

  $('#limits').innerHTML = `<dl class="kv">${Object.entries(state.meta.limits).map(([key, value]) => (
    `<dt>${esc(key.replaceAll('_', ' '))}</dt><dd>${esc(value)}</dd>`
  )).join('')}</dl>`;

  $('#actor-list').innerHTML = state.actors.map((actor) => `
    <div class="actor-row ${actor.id === state.actorId ? 'is-current' : ''}">
      <span class="avatar avatar--${esc(actor.role)}">${esc(initials(actor.display_name))}</span>
      <div>
        <strong>${esc(actor.display_name)}</strong>
        <div class="muted mono">${esc(actor.id)} · ${esc(actor.role)}</div>
      </div>
    </div>`).join('');

  $('#models').innerHTML = `
    <dl class="kv">
      <dt>models</dt>
      <dd>${state.meta.models.map((model) => `<span class="mini-chip">${esc(model)}</span>`).join(' ')}</dd>
      <dt>defaults</dt>
      <dd>${state.meta.default_models.map(esc).join(' → ')}</dd>
      <dt>prompts</dt>
      <dd>${state.meta.prompt_versions.map((version) => `<span class="mini-chip">${esc(version)}</span>`).join(' ')}</dd>
    </dl>`;
}

function fillModelSelect() {
  if (!state.meta) return;
  const select = $('#breakdown-model');
  const defaults = state.meta.default_models;
  select.innerHTML = state.meta.models.map((model) => (
    `<option value="${esc(model)}">${esc(model)}${model === defaults[0] ? ' · primary' : ''}</option>`
  )).join('');
  select.value = defaults[0] || state.meta.models[0] || '';
}

/* Data loading ------------------------------------------------------------- */

async function refresh({ quiet = false } = {}) {
  try {
    const [cards, prds] = await Promise.all([
      api('/api/v1/cards?limit=100'),
      api('/api/v1/prds'),
    ]);
    state.cards = cards.items;
    state.prds = prds.items;
    renderBoard();
    renderPrds();
    renderRules();
  } catch (error) {
    if (!quiet) toast('error', 'Could not refresh', errorText(error), error.code);
  }
}

/* Tabs --------------------------------------------------------------------- */

function switchTab(tab, { sync = true } = {}) {
  state.tab = tab;
  $$('.tab').forEach((button) => {
    const active = button.dataset.tab === tab;
    button.classList.toggle('is-active', active);
    button.setAttribute('aria-selected', String(active));
  });
  $$('.panel-view').forEach((panel) => { panel.hidden = panel.id !== `tab-${tab}`; });
  if (sync && location.hash !== `#${tab}`) history.replaceState(null, '', `#${tab}`);
  if (tab === 'rules') renderRules();
  if (tab === 'prds') renderPrds();
}

function tabFromHash() {
  const tab = location.hash.replace('#', '');
  return ['board', 'prds', 'rules'].includes(tab) ? tab : 'board';
}

/* Wiring ------------------------------------------------------------------- */

function wire() {
  $$('.tab').forEach((button) => button.addEventListener('click', () => switchTab(button.dataset.tab)));

  $('#refresh').addEventListener('click', async () => {
    await Promise.all([checkHealth(), refresh()]);
    toast('success', 'Refreshed');
  });

  $('#search').addEventListener('input', (event) => {
    state.search = event.target.value;
    renderBoard();
  });

  $('#new-card').addEventListener('click', openCardDialog);
  $('#login-form').addEventListener('submit', login);
  $('#logout-button').addEventListener('click', logout);

  $('#card-form').addEventListener('submit', createCard);
  $$('[data-close-dialog]').forEach((button) => {
    button.addEventListener('click', () => $('#card-dialog').close());
  });
  $('#card-dialog').addEventListener('click', (event) => {
    if (event.target === $('#card-dialog')) $('#card-dialog').close();
  });

  $('#prd-form').addEventListener('submit', createPrd);
  $('#prd-sample').addEventListener('click', useSamplePrd);

  $('#scrim').addEventListener('click', closeDrawer);

  $('#board').addEventListener('click', (event) => {
    const tile = event.target.closest('.card-tile');
    if (tile) openCard(tile.dataset.id);
  });
  $('#board').addEventListener('keydown', (event) => {
    if ((event.key === 'Enter' || event.key === ' ') && event.target.classList.contains('card-tile')) {
      event.preventDefault();
      openCard(event.target.dataset.id);
    }
  });

  $('#board').addEventListener('dragstart', (event) => {
    const tile = event.target.closest('.card-tile');
    if (!tile) return;
    event.dataTransfer.setData('text/plain', tile.dataset.id);
    event.dataTransfer.effectAllowed = 'move';
    tile.classList.add('dragging');
  });
  $('#board').addEventListener('dragend', () => {
    $$('.card-tile.dragging').forEach((tile) => tile.classList.remove('dragging'));
    $$('.column.drag-over').forEach((column) => column.classList.remove('drag-over'));
  });
  $('#board').addEventListener('dragover', (event) => {
    const column = event.target.closest('.column');
    if (!column) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
    $$('.column.drag-over').forEach((other) => { if (other !== column) other.classList.remove('drag-over'); });
    column.classList.add('drag-over');
  });
  $('#board').addEventListener('dragleave', (event) => {
    const column = event.target.closest('.column');
    if (column && !column.contains(event.relatedTarget)) column.classList.remove('drag-over');
  });
  $('#board').addEventListener('drop', (event) => {
    const column = event.target.closest('.column');
    if (!column) return;
    event.preventDefault();
    column.classList.remove('drag-over');
    const cardId = event.dataTransfer.getData('text/plain');
    const card = state.cards.find((item) => item.id === cardId);
    if (!card || card.stage === column.dataset.stage) return;
    transitionCard(cardId, column.dataset.stage);
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      if ($('#card-dialog').open) $('#card-dialog').close();
      else closeDrawer();
      return;
    }
    if (isTyping(event.target) || event.ctrlKey || event.metaKey || event.altKey) return;
    if (event.key === '/') {
      event.preventDefault();
      switchTab('board');
      $('#search').focus();
      return;
    }
    if (event.key.toLowerCase() === 'n') openCardDialog();
    if (event.key.toLowerCase() === 'r') {
      checkHealth();
      refresh();
      toast('success', 'Refreshed');
    }
  });

  window.addEventListener('hashchange', () => switchTab(tabFromHash(), { sync: false }));
  window.addEventListener('online', checkHealth);
  window.addEventListener('offline', checkHealth);
}

/* Gantry Inline Chat ------------------------------------------------------- */

const gantryChat = {
  open: false,
  min: false,
  messages: [],
  model: '',
  generating: false,
  notice: '',
};

// The transcript is a scratch pad, not an archive: keep a week and the last
// few hundred turns so localStorage cannot grow without bound.
const CHAT_RETENTION_DAYS = 7;
const CHAT_MAX_MESSAGES = 200;

function gantryChatPrune(list) {
  const cutoff = Date.now() - CHAT_RETENTION_DAYS * 24 * 60 * 60 * 1000;
  return list.filter((message) => !message.at || message.at >= cutoff).slice(-CHAT_MAX_MESSAGES);
}

function gantryChatScrollToEnd() {
  const body = document.getElementById('gantryChatBody');
  if (body) body.scrollTop = body.scrollHeight;
}

function gantryChatLoadHistory() {
  try {
    const saved = localStorage.getItem('gantry-inline-chat');
    if (!saved) return;
    const data = JSON.parse(saved);
    if (Array.isArray(data.messages)) gantryChat.messages = gantryChatPrune(data.messages);
    if (data.model) gantryChat.model = data.model;
  } catch {}
}

function gantryChatSaveHistory() {
  const now = Date.now();
  gantryChat.messages = gantryChatPrune(
    gantryChat.messages.map((message) => (message.at ? message : { ...message, at: now }))
  );
  localStorage.setItem('gantry-inline-chat', JSON.stringify({ messages: gantryChat.messages, model: gantryChat.model }));
}

async function gantryChatLoadModels() {
  const select = document.getElementById('gantryChatModel');
  if (!select) return;
  try {
    const res = await fetch('/api/v1/chat/models', { headers: authHeaders() });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const message = data?.error?.message || 'The chat model is not configured.';
      gantryChat.notice = message;
      select.innerHTML = '<option value="">unavailable</option>';
      return;
    }
    select.innerHTML = '';
    (data.models || []).forEach((m) => {
      const opt = document.createElement('option');
      opt.value = m;
      opt.textContent = m;
      if (m === data.default) opt.selected = true;
      select.appendChild(opt);
    });
    gantryChat.model = select.value || data.default || '';
    if (gantryChat.model) select.value = gantryChat.model;
  } catch {
    gantryChat.notice = 'Could not reach the chat API.';
    select.innerHTML = '<option value="">offline</option>';
  }
}

function gantryChatRenderMessages() {
  const wrap = document.getElementById('gantryChatMessages');
  const welcome = document.getElementById('gantryChatWelcome');
  if (!wrap) return;
  if (gantryChat.messages.length === 0) {
    if (welcome) {
      welcome.hidden = false;
      const text = document.getElementById('gantryChatWelcomeText');
      if (text) {
        text.textContent = gantryChat.notice || 'Ask about the board, or tell me to create a spec, move a card, or comment.';
        text.classList.toggle('gantry-chat-welcome-error', Boolean(gantryChat.notice));
      }
    }
    wrap.innerHTML = '';
    return;
  }
  if (welcome) welcome.hidden = true;
  wrap.innerHTML = gantryChat.messages.map((msg, idx) => {
    if (msg.role === 'proposal') {
      const p = msg.proposal || {};
      const status = msg.status || 'pending';
      const statusText = status === 'confirmed' ? 'Confirmed' : status === 'cancelled' ? 'Cancelled' : status === 'error' ? 'Failed' : 'Needs confirmation';
      const buttons = status === 'pending'
        ? `<div class="gantry-chat-proposal-actions"><button class="gantry-btn gantry-btn-primary gantry-chat-confirm" data-proposal-idx="${idx}">Confirm</button><button class="gantry-btn gantry-chat-cancel" data-proposal-idx="${idx}">Cancel</button></div>`
        : '';
      const args = esc(JSON.stringify(p.arguments || {}, null, 2));
      return `<div class="gantry-chat-msg assistant"><div class="gantry-chat-avatar"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><rect x="3" y="4" width="18" height="12" rx="2"/><path d="M7 20h10M9 16v4M15 16v4"/></svg></div><div class="gantry-chat-bubble-wrap"><div class="gantry-chat-role">Gantry AI</div><div class="gantry-chat-bubble gantry-chat-proposal"><div><strong>Proposal:</strong> ${esc(p.summary || p.tool || 'Action')}</div><div style="font-size:12px;opacity:.8;margin:4px 0">Tool: ${esc(p.tool || '')} · ${esc(statusText)}</div><pre style="white-space:pre-wrap;font-size:12px;margin:6px 0">${args}</pre>${buttons}</div></div></div>`;
    }
    const isUser = msg.role === 'user';
    const avatar = isUser ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="12" cy="8" r="4"/><path d="M20 21a8 8 0 1 0-16 0"/></svg>' : '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><rect x="3" y="4" width="18" height="12" rx="2"/><path d="M7 20h10M9 16v4M15 16v4"/></svg>';
    const content = isUser ? esc(msg.content).replace(/\n/g, '<br>') : DOMPurify.sanitize(marked.parse(msg.content || ''));
    return `<div class="gantry-chat-msg ${isUser ? 'user' : 'assistant'}"><div class="gantry-chat-avatar">${avatar}</div><div class="gantry-chat-bubble-wrap"><div class="gantry-chat-role">${isUser ? 'You' : 'Gantry AI'}</div><div class="gantry-chat-bubble">${content}</div></div></div>`;
  }).join('');
  const body = document.getElementById('gantryChatBody');
  if (body) body.scrollTop = body.scrollHeight;
}

function gantryChatAddTyping() {
  const wrap = document.getElementById('gantryChatMessages');
  if (!wrap || document.getElementById('gantryChatTyping')) return;
  const el = document.createElement('div');
  el.id = 'gantryChatTyping';
  el.className = 'gantry-chat-msg assistant';
  el.innerHTML = '<div class="gantry-chat-avatar"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><rect x="3" y="4" width="18" height="12" rx="2"/><path d="M7 20h10M9 16v4M15 16v4"/></svg></div><div class="gantry-chat-bubble-wrap"><div class="gantry-chat-role">Gantry AI</div><div class="gantry-chat-bubble"><div class="gantry-chat-typing"><div class="gantry-chat-typing-dot"></div><div class="gantry-chat-typing-dot"></div><div class="gantry-chat-typing-dot"></div></div></div></div>';
  wrap.appendChild(el);
  const body = document.getElementById('gantryChatBody');
  if (body) body.scrollTop = body.scrollHeight;
}

function gantryChatRemoveTyping() {
  const el = document.getElementById('gantryChatTyping');
  if (el) el.remove();
}

async function gantryChatConfirmProposal(idx) {
  const msg = gantryChat.messages[idx];
  if (!msg || msg.role !== 'proposal' || msg.status !== 'pending') return;
  msg.status = 'confirming';
  gantryChatRenderMessages();
  try {
    const res = await fetch('/api/v1/chat/confirm', {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json', Accept: 'application/json' }),
      body: JSON.stringify({ token: msg.proposal.token }),
    });
    const payload = await res.json().catch(() => null);
    if (res.ok && payload && payload.ok) {
      msg.status = 'confirmed';
      toast('success', 'Proposal confirmed', payload.summary || 'Action executed.', payload.code || '');
      if (payload.view === 'prds') switchTab('prds');
      else switchTab('board');
      refresh({ quiet: true });
    } else {
      msg.status = 'error';
      const err = payload?.error || payload;
      toast('error', 'Proposal failed', err?.message || payload?.message || 'Confirmation failed.', err?.code || payload?.code || '');
    }
  } catch (e) {
    msg.status = 'error';
    toast('error', 'Proposal failed', e.message || 'Confirmation failed.', 'network_error');
  }
  gantryChatSaveHistory();
  gantryChatRenderMessages();
}

function gantryChatCancelProposal(idx) {
  const msg = gantryChat.messages[idx];
  if (!msg || msg.role !== 'proposal' || msg.status !== 'pending') return;
  msg.status = 'cancelled';
  gantryChatSaveHistory();
  gantryChatRenderMessages();
}

async function gantryChatSend() {
  const input = document.getElementById('gantryChatInput');
  const btn = document.getElementById('gantryChatSend');
  const content = (input.value || '').trim();
  if (!content || gantryChat.generating) return;
  if (!gantryChat.model) {
    gantryChat.messages.push({ role: 'user', content });
    gantryChat.messages.push({
      role: 'assistant',
      content:
        gantryChat.notice ||
        'The chat model is unavailable. Check CHAT_API_KEY in .env and restart the server.',
    });
    input.value = '';
    input.style.height = 'auto';
    if (btn) btn.disabled = true;
    gantryChatRenderMessages();
    return;
  }
  gantryChat.generating = true;
  if (btn) btn.disabled = true;

  gantryChat.messages.push({ role: 'user', content });
  gantryChatSaveHistory();
  gantryChatRenderMessages();

  input.value = '';
  input.style.height = 'auto';

  gantryChatAddTyping();

  try {
    const headers = authHeaders({ 'Content-Type': 'application/json' });
    const res = await fetch('/api/v1/chat/completions', {
      method: 'POST',
      headers,
      body: JSON.stringify({
        messages: gantryChat.messages,
        model: gantryChat.model || undefined,
        temperature: 0.7,
        max_tokens: 2048,
      }),
    });
    gantryChatRemoveTyping();
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      const message = err?.error?.message || `Request failed with HTTP ${res.status}.`;
      gantryChat.messages.push({ role: 'assistant', content: 'Error: ' + message });
      gantryChatSaveHistory();
      gantryChatRenderMessages();
      gantryChat.generating = false;
      if (btn) btn.disabled = input.value.trim() === '';
      return;
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let text = '';
    let failed = false;
    let finished = false;
    let buffer = '';
    const wrap = document.getElementById('gantryChatMessages');
    const msg = document.createElement('div');
    msg.className = 'gantry-chat-msg assistant';
    msg.innerHTML = '<div class="gantry-chat-avatar"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><rect x="3" y="4" width="18" height="12" rx="2"/><path d="M7 20h10M9 16v4M15 16v4"/></svg></div><div class="gantry-chat-bubble-wrap"><div class="gantry-chat-role">Gantry AI</div><div class="gantry-chat-bubble"></div></div>';
    wrap.appendChild(msg);
    const bubble = msg.querySelector('.gantry-chat-bubble');
    const body = document.getElementById('gantryChatBody');

    const handleFrame = (line) => {
      if (!line.startsWith('data: ')) return;
      const data = line.slice(6).trim();
      if (data === '[DONE]') { finished = true; return; }
      try {
        const parsed = JSON.parse(data);
        if (parsed.error) { text = 'Error: ' + parsed.error; failed = true; finished = true; return; }
        if (parsed.gantry_tool) {
          const tool = parsed.gantry_tool;
          const hint = tool.code === 'missing_actor'
            ? 'Reload this page once: the open tab is running an older script.'
            : '';
          toast(
            tool.ok ? 'success' : 'error',
            tool.ok ? 'Board updated' : 'Board refused the action',
            [tool.summary || tool.name, hint].filter(Boolean).join(' — '),
            tool.code || ''
          );
          if (tool.ok) {
            if (tool.view === 'prds') switchTab('prds');
            else if (tool.view === 'board') switchTab('board');
            refresh({ quiet: true });
          }
          return;
        }
        if (parsed.gantry_proposal) {
          gantryChat.messages.push({ role: 'proposal', proposal: parsed.gantry_proposal, status: 'pending' });
          gantryChatSaveHistory();
          gantryChatRenderMessages();
          return;
        }
        const delta = parsed.choices?.[0]?.delta?.content || '';
        if (delta) {
          text += delta;
          bubble.innerHTML = DOMPurify.sanitize(marked.parse(text));
          if (body) body.scrollTop = body.scrollHeight;
        }
      } catch {}
    };

    // A network read can split an SSE frame in half; keep the tail and join it
    // with the next read instead of dropping the event.
    while (!finished) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';
      lines.forEach(handleFrame);
    }
    if (buffer) handleFrame(buffer);
    if (text) {
      bubble.innerHTML = DOMPurify.sanitize(marked.parse(text));
      gantryChat.messages.push({ role: 'assistant', content: text });
      gantryChatSaveHistory();
    }
  } catch (e) {
    gantryChatRemoveTyping();
    gantryChat.messages.push({ role: 'assistant', content: 'Error: ' + e.message });
    gantryChatSaveHistory();
    gantryChatRenderMessages();
  }

  gantryChat.generating = false;
  const input2 = document.getElementById('gantryChatInput');
  const btn2 = document.getElementById('gantryChatSend');
  if (btn2) btn2.disabled = (input2.value || '').trim() === '';
  const body2 = document.getElementById('gantryChatBody');
  if (body2) body2.scrollTop = body2.scrollHeight;
}

function gantryChatWire() {
  const fab = document.getElementById('gantryChatFab');
  const panel = document.getElementById('gantryChatPanel');
  const close = document.getElementById('gantryChatClose');
  const min = document.getElementById('gantryChatMin');
  const input = document.getElementById('gantryChatInput');
  const send = document.getElementById('gantryChatSend');
  const model = document.getElementById('gantryChatModel');
  const nw = document.getElementById('gantryChatNew');

  if (fab) fab.addEventListener('click', () => {
    panel.classList.add('is-open');
    panel.setAttribute('aria-hidden', 'false');
    panel.classList.remove('is-min');
    gantryChat.open = true;
    gantryChat.min = false;
    gantryChatScrollToEnd();
    setTimeout(() => {
      gantryChatScrollToEnd();
      input?.focus();
    }, 50);
  });
  if (close) close.addEventListener('click', () => {
    panel.classList.remove('is-open');
    panel.setAttribute('aria-hidden', 'true');
    gantryChat.open = false;
  });
  if (min) min.addEventListener('click', () => {
    panel.classList.toggle('is-min');
    gantryChat.min = panel.classList.contains('is-min');
  });
  if (nw) nw.addEventListener('click', () => {
    if (!confirm('Start a new chat? The current transcript is cleared.')) return;
    gantryChat.messages = [];
    localStorage.removeItem('gantry-inline-chat');
    gantryChatRenderMessages();
    input.value = '';
    input.style.height = 'auto';
    if (send) send.disabled = true;
    input?.focus();
  });
  const chatWrap = document.getElementById('gantryChatMessages');
  if (chatWrap) chatWrap.addEventListener('click', (e) => {
    const confirmBtn = e.target.closest('.gantry-chat-confirm');
    const cancelBtn = e.target.closest('.gantry-chat-cancel');
    if (confirmBtn) gantryChatConfirmProposal(Number(confirmBtn.dataset.proposalIdx));
    if (cancelBtn) gantryChatCancelProposal(Number(cancelBtn.dataset.proposalIdx));
    input?.focus();
  });
  if (model) model.addEventListener('change', () => {
    gantryChat.model = model.value;
    gantryChatSaveHistory();
  });
  if (input) {
    input.addEventListener('input', () => {
      input.style.height = 'auto';
      input.style.height = Math.min(input.scrollHeight, 110) + 'px';
      if (send) send.disabled = input.value.trim() === '' || gantryChat.generating;
    });
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        if (!send.disabled) gantryChatSend();
      }
    });
  }
  if (send) send.addEventListener('click', gantryChatSend);
}

document.addEventListener('DOMContentLoaded', () => {
  gantryChatLoadHistory();
  gantryChatLoadModels().then(() => {
    gantryChatRenderMessages();
    gantryChatScrollToEnd();
  });
  gantryChatWire();
});

/* Boot --------------------------------------------------------------------- */

async function boot() {
  wire();
  await checkHealth();

  try {
    if (!(await loadSession())) {
      const board = $('#board');
      if (board) board.innerHTML = '<p class="empty-note">Sign in to load the board.</p>';
      return;
    }

    const [actors, meta] = await Promise.all([
      api('/api/v1/actors'),
      api('/api/v1/meta'),
    ]);
    state.actors = actors.items;
    state.meta = meta;

    fillModelSelect();
    await refresh({ quiet: true });
    renderRules();
    switchTab(tabFromHash(), { sync: false });
  } catch (error) {
    if (!state.token) return; // loadSession already showed the sign-in form.
    toast('error', 'Could not load the console', errorText(error), error.code);
    $('#board').innerHTML = '<p class="empty-note">The API is not reachable. Start it with <code>uvicorn app.main:app</code>, then refresh.</p>';
  }
}

document.addEventListener('DOMContentLoaded', boot);
