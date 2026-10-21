/* Chat di Workflow Agent dentro il pannello core/partials/agent_panel.html (incluso da
   base.html per gli utenti autenticati; apertura/chiusura le gestisce base.html). Gestisce
   anche il modale informativo del tasto ℹ, che contiene "Nuova conversazione".

   Parla solo con i proxy di Workflow, /agent/chat/ e /agent/confirm/ (sessione + CSRF):
   sono loro a mettere il token API e a girare la richiesta all'agent. Risposta dell'agent:
   {conversation_id, reply, pending}. Se pending non è vuoto la run è ferma: l'utente approva
   o rifiuta ogni azione e, prese tutte le decisioni, si manda /agent/confirm/ con
   {conversation_id, approvals: {tool_call_id: bool}}; la risposta ha la stessa forma.

   Stato: conversation_id in memoria e in sessionStorage (sopravvive al cambio pagina
   nella stessa scheda), messaggi e azioni in attesa solo in memoria. Il contesto
   della commessa viene dall'attributo data-job del pannello. */
(function () {
  'use strict';

  var panel = document.getElementById('agent-panel');
  var body = document.getElementById('agent-panel-body');
  var list = document.getElementById('agent-messages');
  var placeholder = document.getElementById('agent-panel-placeholder');
  var form = document.getElementById('agent-form');
  var input = document.getElementById('agent-input');
  var sendBtn = document.getElementById('agent-send');
  var resumeNote = document.getElementById('agent-panel-resume');
  var infoBtn = document.getElementById('agent-panel-info');
  var infoBackdrop = document.getElementById('agent-info-backdrop');
  var infoClose = document.getElementById('agent-info-close');
  var newBtn = document.getElementById('agent-info-new');
  if (!panel || !body || !list || !form || !input || !sendBtn) return;

  var STORAGE_KEY = 'agent_conversation_id';
  var CSRF_COOKIE = 'workflow_csrftoken';
  var URL_CHAT = '/agent/chat/';
  var URL_CONFIRM = '/agent/confirm/';

  var state = {
    conversationId: readConversationId(),
    messages: [],   // {role: 'user' | 'assistant' | 'error', text}
    pending: [],    // [{tool_call_id, tool_name, args, summary}] in attesa di decisione
    decisions: {},  // tool_call_id -> true (approvata) / false (rifiutata)
    busy: false,    // richiesta in corso
    generation: 0,  // cresce con "Nuova conversazione": le risposte vecchie si ignorano
  };
  var typingEl = null;
  var pendingEl = null;

  /* ── Stato persistente ── */

  function readConversationId() {
    try { return sessionStorage.getItem(STORAGE_KEY) || null; } catch (e) { return null; }
  }

  function setConversationId(id) {
    state.conversationId = id || null;
    try {
      if (id) sessionStorage.setItem(STORAGE_KEY, id);
      else sessionStorage.removeItem(STORAGE_KEY);
    } catch (e) { /* storage non disponibile: resta in memoria */ }
  }

  function csrfToken() {
    var m = document.cookie.match(new RegExp('(?:^|;\\s*)' + CSRF_COOKIE + '=([^;]*)'));
    return m ? decodeURIComponent(m[1]) : (window.CSRF_TOKEN || '');
  }

  function currentJob() {
    var job = (panel.getAttribute('data-job') || '').trim();
    return job || null;
  }

  /* ── Markdown minimo, senza librerie: tutto il testo passa da escHtml ── */

  function escHtml(str) {
    return String(str == null ? '' : str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function inline(text) {
    // Il codice inline si isola prima, così ** e _ al suo interno restano com'erano.
    return text.split(/(`[^`]*`)/).map(function (part) {
      if (part.length >= 2 && part.charAt(0) === '`' && part.charAt(part.length - 1) === '`') {
        return '<code>' + escHtml(part.slice(1, -1)) + '</code>';
      }
      var h = escHtml(part);
      h = h.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
      h = h.replace(/__([^_]+)__/g, '<strong>$1</strong>');
      h = h.replace(/(^|[^*\w])\*([^*\s][^*]*?)\*(?!\w)/g, '$1<em>$2</em>');
      h = h.replace(/(^|[^_\w])_([^_\s][^_]*?)_(?!\w)/g, '$1<em>$2</em>');
      return h;
    }).join('');
  }

  var LIST_RE = /^\s*([-*•]|\d+[.)])\s+(.*)$/;
  var FENCE_RE = /^\s*```/;
  var HEADING_RE = /^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$/;
  var TABLE_SEP_RE = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/;

  function isTableRow(line) { return /^\s*\|/.test(line); }

  function splitRow(line) {
    return line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(function (c) {
      return c.trim();
    });
  }

  function renderMarkdown(text) {
    var lines = String(text == null ? '' : text).replace(/\r\n?/g, '\n').split('\n');
    var out = [];
    var i = 0;

    function blockStart(idx) {
      var l = lines[idx];
      return FENCE_RE.test(l) || HEADING_RE.test(l) || LIST_RE.test(l) ||
        (isTableRow(l) && idx + 1 < lines.length && TABLE_SEP_RE.test(lines[idx + 1]));
    }

    while (i < lines.length) {
      var line = lines[i];
      var m;
      if (!line.trim()) { i++; continue; }

      if (FENCE_RE.test(line)) {
        var code = [];
        i++;
        while (i < lines.length && !FENCE_RE.test(lines[i])) code.push(lines[i++]);
        i++;
        out.push('<pre><code>' + escHtml(code.join('\n')) + '</code></pre>');
        continue;
      }

      if ((m = HEADING_RE.exec(line))) {
        out.push('<p><strong>' + inline(m[1]) + '</strong></p>');
        i++;
        continue;
      }

      if (isTableRow(line) && i + 1 < lines.length && TABLE_SEP_RE.test(lines[i + 1])) {
        var head = splitRow(line);
        var rows = [];
        i += 2;
        while (i < lines.length && isTableRow(lines[i])) rows.push(splitRow(lines[i++]));
        var html = '<div class="agent-md-table"><table><thead><tr>' +
          head.map(function (c) { return '<th>' + inline(c) + '</th>'; }).join('') +
          '</tr></thead>';
        if (rows.length) {
          html += '<tbody>' + rows.map(function (r) {
            return '<tr>' + r.map(function (c) { return '<td>' + inline(c) + '</td>'; }).join('') + '</tr>';
          }).join('') + '</tbody>';
        }
        out.push(html + '</table></div>');
        continue;
      }

      if ((m = LIST_RE.exec(line))) {
        var ordered = /^\d/.test(m[1]);
        var items = [];
        while (i < lines.length && (m = LIST_RE.exec(lines[i])) && /^\d/.test(m[1]) === ordered) {
          var item = m[2];
          i++;
          // righe indentate sotto la voce: continuazione della stessa voce
          while (i < lines.length && lines[i].trim() && /^\s+/.test(lines[i]) && !LIST_RE.test(lines[i])) {
            item += ' ' + lines[i++].trim();
          }
          items.push('<li>' + inline(item) + '</li>');
        }
        out.push(ordered ? '<ol>' + items.join('') + '</ol>' : '<ul>' + items.join('') + '</ul>');
        continue;
      }

      var para = [];
      while (i < lines.length && lines[i].trim() && !blockStart(i)) para.push(lines[i++].trim());
      out.push('<p>' + para.map(inline).join('<br>') + '</p>');
    }
    return out.join('');
  }

  /* ── Rendering ── */

  function scrollToBottom() {
    body.scrollTop = body.scrollHeight;
  }

  function hidePlaceholder() {
    if (placeholder) placeholder.hidden = true;
  }

  function addBubble(role, text) {
    state.messages.push({ role: role, text: text });
    var el = document.createElement('div');
    el.className = 'agent-msg agent-msg-' + role;
    if (role === 'assistant') el.innerHTML = renderMarkdown(text);
    else el.textContent = text;
    hidePlaceholder();
    list.appendChild(el);
    scrollToBottom();
    return el;
  }

  function showTyping() {
    if (typingEl) return;
    typingEl = document.createElement('div');
    typingEl.className = 'agent-typing';
    typingEl.setAttribute('aria-label', 'Workflow Agent sta scrivendo');
    typingEl.innerHTML = '<span></span><span></span><span></span>';
    hidePlaceholder();
    list.appendChild(typingEl);
    scrollToBottom();
  }

  function hideTyping() {
    if (typingEl && typingEl.parentNode) typingEl.parentNode.removeChild(typingEl);
    typingEl = null;
  }

  function updateInputState() {
    var locked = state.busy || state.pending.length > 0;
    input.disabled = locked;
    sendBtn.disabled = locked;
    input.placeholder = state.pending.length > 0 && !state.busy
      ? 'Decidi sulle azioni proposte…'
      : 'Scrivi un messaggio…';
  }

  function focusInput() {
    if (!input.disabled && panel.classList.contains('open')) input.focus();
  }

  /* ── Azioni in attesa di conferma ── */

  function allDecided() {
    return state.pending.every(function (p) { return p.tool_call_id in state.decisions; });
  }

  function renderPending(items) {
    state.pending = items;
    state.decisions = {};
    pendingEl = document.createElement('div');
    pendingEl.className = 'agent-pending';

    var title = document.createElement('p');
    title.className = 'agent-pending-title';
    title.textContent = items.length === 1 ? 'Azione da confermare' : 'Azioni da confermare';
    pendingEl.appendChild(title);

    items.forEach(function (p) {
      var card = document.createElement('div');
      card.className = 'agent-pending-card';
      card.setAttribute('data-tool-call-id', p.tool_call_id);

      var tool = document.createElement('div');
      tool.className = 'agent-pending-tool';
      tool.textContent = p.tool_name || '';
      card.appendChild(tool);

      var summary = document.createElement('p');
      summary.className = 'agent-pending-summary';
      summary.textContent = p.summary || p.tool_name || 'Azione';
      card.appendChild(summary);

      var actions = document.createElement('div');
      actions.className = 'agent-pending-actions';
      actions.appendChild(button('Rifiuta', 'agent-btn agent-btn-reject', function () { decide(p.tool_call_id, false); }));
      actions.appendChild(button('Approva', 'agent-btn agent-btn-approve', function () { decide(p.tool_call_id, true); }));
      card.appendChild(actions);

      pendingEl.appendChild(card);
    });

    if (items.length > 1) {
      var all = document.createElement('div');
      all.className = 'agent-pending-actions';
      all.appendChild(button('Approva tutte', 'agent-btn agent-btn-approve', function () {
        items.forEach(function (p) {
          if (!(p.tool_call_id in state.decisions)) decide(p.tool_call_id, true);
        });
      }));
      pendingEl.appendChild(all);
    }

    hidePlaceholder();
    list.appendChild(pendingEl);
    updateInputState();
    scrollToBottom();
  }

  function button(label, className, onClick) {
    var b = document.createElement('button');
    b.type = 'button';
    b.className = className;
    b.textContent = label;
    b.addEventListener('click', onClick);
    return b;
  }

  function decide(toolCallId, approved) {
    if (!pendingEl || toolCallId in state.decisions) return;
    state.decisions[toolCallId] = approved;
    var card = pendingEl.querySelector('[data-tool-call-id="' + toolCallId + '"]');
    if (card) {
      card.classList.add(approved ? 'approved' : 'rejected');
      var actions = card.querySelector('.agent-pending-actions');
      var status = document.createElement('div');
      status.className = 'agent-pending-status';
      status.textContent = approved ? 'Approvata' : 'Rifiutata';
      if (actions) card.replaceChild(status, actions);
      else card.appendChild(status);
    }
    if (allDecided()) sendConfirm();
  }

  /* Chiude il blocco delle azioni (resta nella lista come storico) e sblocca l'input. */
  function closePending() {
    if (pendingEl) {
      pendingEl.querySelectorAll('button').forEach(function (b) { b.disabled = true; });
      var all = pendingEl.querySelector('.agent-pending > .agent-pending-actions');
      if (all) pendingEl.removeChild(all);
    }
    pendingEl = null;
    state.pending = [];
    state.decisions = {};
  }

  /* ── Richieste ── */

  function errorMessage(status, data) {
    var msg = null;
    if (data && typeof data.error === 'string') msg = data.error;
    else if (data && typeof data.detail === 'string') {
      msg = data.detail;
      if (data.expected !== undefined || data.received !== undefined) {
        msg += ' (atteso: ' + describe(data.expected) + ', ricevuto: ' + describe(data.received) + ')';
      }
    }
    if (msg === null) {
      switch (status) {
        case 0: msg = 'Assistente non raggiungibile: controlla la connessione e riprova.'; break;
        case 401: msg = 'Sessione scaduta: ricarica la pagina e accedi di nuovo.'; break;
        case 403: msg = 'Richiesta rifiutata: ricarica la pagina e riprova.'; break;
        case 404: msg = 'Conversazione non trovata.'; break;
        case 409: msg = 'Nessuna azione in attesa di conferma.'; break;
        case 503: msg = 'Assistente non disponibile.'; break;
        default: msg = 'Errore dell\'assistente (' + status + ').';
      }
    }
    if (status === 404) {
      if (!/[.!?]$/.test(msg)) msg += '.';
      msg += ' Il prossimo messaggio inizia una nuova conversazione.';
    }
    return msg;
  }

  function describe(value) {
    if (value === undefined) return '—';
    if (typeof value === 'string') return value;
    try { return JSON.stringify(value); } catch (e) { return String(value); }
  }

  function handleResponse(status, data) {
    if (status >= 200 && status < 300 && data && typeof data === 'object') {
      if (data.conversation_id) setConversationId(data.conversation_id);
      if (typeof data.reply === 'string' && data.reply.trim()) addBubble('assistant', data.reply);
      if (Array.isArray(data.pending) && data.pending.length) renderPending(data.pending);
      else if (!data.reply) addBubble('assistant', '_(nessuna risposta)_');
      return;
    }
    addBubble('error', errorMessage(status, data));
    if (status === 404) setConversationId(null);
  }

  function post(url, payload) {
    var gen = state.generation;
    state.busy = true;
    updateInputState();
    showTyping();
    return fetch(url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() },
      body: JSON.stringify(payload),
    }).then(function (res) {
      return res.json().catch(function () { return null; }).then(function (data) {
        return { status: res.status, data: data };
      });
    }).catch(function () {
      return { status: 0, data: null };
    }).then(function (r) {
      if (gen !== state.generation) return; // "Nuova conversazione" nel frattempo
      hideTyping();
      state.busy = false;
      handleResponse(r.status, r.data);
      updateInputState();
      focusInput();
    });
  }

  function sendMessage(text) {
    addBubble('user', text);
    var payload = { message: text };
    if (state.conversationId) payload.conversation_id = state.conversationId;
    var job = currentJob();
    if (job) payload.context = { job: job };
    post(URL_CHAT, payload);
  }

  function sendConfirm() {
    var approvals = {};
    state.pending.forEach(function (p) { approvals[p.tool_call_id] = !!state.decisions[p.tool_call_id]; });
    var payload = { conversation_id: state.conversationId, approvals: approvals };
    closePending();
    post(URL_CONFIRM, payload);
  }

  function newConversation() {
    state.generation += 1;
    state.busy = false;
    state.messages = [];
    hideTyping();
    closePending();
    setConversationId(null);
    list.innerHTML = '';
    if (resumeNote) resumeNote.hidden = true;
    if (placeholder) placeholder.hidden = false;
    closeInfo();
    updateInputState();
    focusInput();
  }

  /* ── Modale informativo (tasto ℹ) ── */

  function infoOpen() {
    return !!infoBackdrop && infoBackdrop.classList.contains('open');
  }

  function openInfo() {
    if (!infoBackdrop) return;
    infoBackdrop.classList.add('open');
    if (infoClose) infoClose.focus();
  }

  function closeInfo() {
    if (!infoOpen()) return;
    infoBackdrop.classList.remove('open');
    if (infoBtn) infoBtn.focus();
  }

  /* ── Collegamento al pannello ── */

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    var text = input.value.trim();
    if (!text || state.busy || state.pending.length) return;
    input.value = '';
    sendMessage(text);
  });

  if (newBtn) newBtn.addEventListener('click', newConversation);
  if (infoBtn) infoBtn.addEventListener('click', openInfo);
  if (infoClose) infoClose.addEventListener('click', closeInfo);
  if (infoBackdrop) {
    infoBackdrop.addEventListener('click', function (e) {
      if (e.target === infoBackdrop) closeInfo();
    });
    // In cattura, prima dell'handler di base.html: Esc chiude solo il modale, non la finestra
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && infoOpen()) {
        e.stopImmediatePropagation();
        closeInfo();
      }
    }, true);
  }

  if (state.conversationId && resumeNote) resumeNote.hidden = false;
  updateInputState();
})();
