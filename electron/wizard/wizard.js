'use strict';

/*
 * Wizard renderer. Renders a per-step checklist and drives it from the main
 * process's `progress` events. Two modes:
 *   - first run  → full provisioning checklist
 *   - subsequent → compact startup (Docker → Ollama → Start)
 * Only window.api (from preload.js) is available — no Node access.
 */

const FIRST_RUN_STEPS = [
  ['gpu', 'Detect hardware'],
  ['docker', 'Docker'],
  ['ollama', 'Ollama'],
  ['models', 'Language models'],
  ['image', 'Application image'],
  ['data', 'Source documents'],
  ['snapshot', 'Knowledge graph'],
  ['start', 'Start assistant'],
];

const QUICK_STEPS = [
  ['docker', 'Docker'],
  ['ollama', 'Ollama'],
  ['start', 'Start assistant'],
];

const els = {
  subtitle: document.getElementById('subtitle'),
  steps: document.getElementById('steps'),
  banner: document.getElementById('banner'),
  primary: document.getElementById('primary'),
  hint: document.getElementById('hint'),
};

const nodes = {}; // step id → { root, icon, msg, bar, fill }

function renderSteps(steps) {
  els.steps.innerHTML = '';
  for (const [id, label] of steps) {
    const li = document.createElement('li');
    li.className = 'step';
    li.innerHTML = `
      <div class="icon" data-icon>•</div>
      <div class="body">
        <div class="label">${label}</div>
        <div class="msg" data-msg></div>
        <div class="bar" data-bar><span data-fill></span></div>
      </div>`;
    els.steps.appendChild(li);
    nodes[id] = {
      root: li,
      icon: li.querySelector('[data-icon]'),
      msg: li.querySelector('[data-msg]'),
      bar: li.querySelector('[data-bar]'),
      fill: li.querySelector('[data-fill]'),
    };
  }
}

function applyProgress({ step, status, message, progress }) {
  const n = nodes[step];
  if (!n) return;
  n.root.classList.remove('active', 'done', 'error', 'needs-user');
  if (status) n.root.classList.add(status);
  if (message) n.msg.textContent = message;

  if (status === 'done') n.icon.textContent = '✓';
  else if (status === 'error') n.icon.textContent = '!';
  else if (status === 'needs-user') n.icon.textContent = '!';
  else if (status === 'active') {
    // Only (re)create the spinner when entering active, so frequent progress
    // ticks don't restart its CSS animation.
    if (!n.icon.querySelector('.spinner')) n.icon.innerHTML = '<div class="spinner"></div>';
  } else n.icon.textContent = '•';

  if (status === 'active') {
    n.bar.classList.add('show');
    if (typeof progress === 'number') {
      n.bar.classList.remove('indeterminate');
      n.fill.style.width = `${Math.round(progress * 100)}%`;
    } else {
      n.bar.classList.add('indeterminate');
    }
  } else {
    n.bar.classList.remove('show', 'indeterminate');
  }
}

function showBanner(kind, html) {
  els.banner.className = `banner ${kind}`;
  els.banner.innerHTML = html;
  els.banner.classList.remove('hidden');
}

function setButton(label, enabled, onClick) {
  els.primary.textContent = label;
  els.primary.disabled = !enabled;
  els.primary.onclick = enabled ? onClick : null;
}

async function begin() {
  setButton('Working…', false, null);
  els.banner.classList.add('hidden');
  const res = await window.api.begin();
  if (!res.ok && !res.reboot) {
    // error banner already shown by onError; offer retry
    setButton('Retry', true, begin);
  }
  // On success the main process navigates the window away to the app.
}

async function init() {
  const state = await window.api.getState();
  const firstRun = !state.firstRunComplete;

  renderSteps(firstRun ? FIRST_RUN_STEPS : QUICK_STEPS);
  els.subtitle.textContent = firstRun
    ? 'First-time setup will install Docker, Ollama, the language models (~10 GB), and the knowledge graph. This can take a while on the first run.'
    : 'Starting the assistant…';
  els.hint.textContent = firstRun
    ? 'You only need to do this once. A network connection is required.'
    : '';

  window.api.onProgress(applyProgress);
  window.api.onError(({ message }) => showBanner('err', `Setup failed: ${message}`));
  window.api.onReboot(({ message }) =>
    showBanner('warn',
      `Docker Desktop needs to finish installing before setup can continue ` +
      `(this usually requires a restart). Once Docker is installed and running, ` +
      `reopen this app and setup will resume where it left off.<br><small>${message || ''}</small>`));

  if (firstRun) {
    setButton('Begin setup', true, begin);
  } else {
    // Subsequent launches: start automatically, no button needed.
    setButton('Starting…', false, null);
    begin();
  }
}

init();
