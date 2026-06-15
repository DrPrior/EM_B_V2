// ── State ─────────────────────────────────────────────────────────────────────
let sessionId    = null;
let isStreaming  = false;
let streamBubble = null;   // current assistant bubble element while streaming
let streamTokens = '';     // accumulated raw text during streaming

// ── DOM refs ──────────────────────────────────────────────────────────────────
const messagesEl = document.getElementById('messages');
const inputEl    = document.getElementById('question-input');
const sendBtn    = document.getElementById('send-btn');
const newChatBtn = document.getElementById('new-chat-btn');
const sourcesEl  = document.getElementById('sources-list');

// ── marked.js ─────────────────────────────────────────────────────────────────
marked.setOptions({ breaks: true, gfm: true });

// ── Helpers ───────────────────────────────────────────────────────────────────

function setStreaming(active) {
  isStreaming           = active;
  inputEl.disabled      = active;
  sendBtn.disabled      = active;
  sendBtn.textContent   = active ? '…' : 'Send';
}

function scrollToBottom() {
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function escape(str) {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function addUserBubble(text) {
  const wrapper = document.createElement('div');
  wrapper.className = 'flex justify-end';
  wrapper.innerHTML = `<div class="user-bubble">${escape(text)}</div>`;
  messagesEl.appendChild(wrapper);
  scrollToBottom();
}

function addAssistantBubble() {
  const wrapper = document.createElement('div');
  wrapper.className = 'flex justify-start';
  const bubble = document.createElement('div');
  bubble.className = 'assistant-bubble';
  bubble.innerHTML = '<span class="cursor">▍</span>';
  wrapper.appendChild(bubble);
  messagesEl.appendChild(wrapper);
  scrollToBottom();
  return bubble;
}

function scoreClass(score) {
  if (score >= 0.85) return 'text-emerald-600';
  if (score >= 0.78) return 'text-amber-500';
  return 'text-slate-400';
}

function renderSources(sources) {
  if (!sources?.length) {
    sourcesEl.innerHTML =
      '<p class="text-xs text-slate-400 italic">No sources retrieved for this response.</p>';
    return;
  }
  sourcesEl.innerHTML = sources
    .map(s => `
      <div class="rounded-lg border border-slate-100 bg-slate-50 p-2.5">
        <div class="flex items-start gap-2">
          <span class="text-slate-400 shrink-0 mt-px">📄</span>
          <span class="text-xs text-slate-700 font-medium leading-snug break-all">
            ${escape(s.filename)}
          </span>
        </div>
        <div class="mt-1 ml-6 font-mono text-xs ${scoreClass(s.score)}">
          ${s.score.toFixed(4)}
        </div>
        ${s.superseded_by ? `
        <div class="mt-1 ml-6 text-xs text-amber-600 italic">
          ⚠ Superseded by ${escape(s.superseded_by)} — shown for historical reference
        </div>` : ''}
      </div>`)
    .join('');
}

// ── Send ──────────────────────────────────────────────────────────────────────

async function send() {
  const question = inputEl.value.trim();
  if (!question || isStreaming) return;

  inputEl.value = '';
  inputEl.style.height = 'auto';
  setStreaming(true);

  addUserBubble(question);
  streamBubble = addAssistantBubble();
  streamTokens = '';

  try {
    const res = await fetch('/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, session_id: sessionId }),
    });

    if (!res.ok) {
      throw new Error(`Server error ${res.status}: ${await res.text()}`);
    }

    const reader  = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer    = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split('\n\n');
      buffer = parts.pop();   // hold back any incomplete trailing event

      for (const raw of parts) {
        if (!raw.startsWith('data: ')) continue;
        let evt;
        try { evt = JSON.parse(raw.slice(6)); } catch { continue; }

        switch (evt.type) {
          case 'metadata':
            sessionId = evt.session_id;
            renderSources(evt.sources);
            break;

          case 'token':
            streamTokens += evt.token;
            // show plain text while streaming — avoids partial markdown artifacts
            streamBubble.textContent = streamTokens;
            scrollToBottom();
            break;

          case 'done':
            // final render with markdown
            streamBubble.innerHTML = marked.parse(streamTokens);
            scrollToBottom();
            break;

          case 'error':
            streamBubble.innerHTML =
              `<span class="text-red-600">⚠ ${escape(evt.message)}</span>`;
            break;
        }
      }
    }
  } catch (err) {
    if (streamBubble) {
      streamBubble.innerHTML =
        `<span class="text-red-600">⚠ ${escape(err.message)}</span>`;
    }
  } finally {
    setStreaming(false);
    streamBubble = null;
  }
}

// ── New chat ──────────────────────────────────────────────────────────────────

function newChat() {
  sessionId    = null;
  streamTokens = '';
  streamBubble = null;

  messagesEl.innerHTML = `
    <div class="flex justify-start">
      <div class="assistant-bubble">
        Hello! I'm your Emergency Management Knowledge Assistant. Ask me about NIMS, ICS,
        FEMA doctrine, hazard mitigation planning, or any other emergency management topic.
      </div>
    </div>`;

  sourcesEl.innerHTML =
    '<p class="text-xs text-slate-400 italic">Sources will appear after your first question.</p>';
}

// ── Event listeners ───────────────────────────────────────────────────────────

sendBtn.addEventListener('click', send);

inputEl.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    send();
  }
});

inputEl.addEventListener('input', () => {
  inputEl.style.height = 'auto';
  inputEl.style.height = `${Math.min(inputEl.scrollHeight, 160)}px`;
});

newChatBtn.addEventListener('click', newChat);
