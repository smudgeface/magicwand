// Log history page: load persisted events from /api/logs, then stream new
// ones live over the same /ws/events WebSocket the feed page uses.
(function() {
  const HISTORY_LIMIT = 1000;
  let ws = null;
  let reconnectDelay = 1000;
  let currentType = '';   // '' = all
  let count = 0;

  document.addEventListener('DOMContentLoaded', () => {
    if (!document.getElementById('log-list')) return;
    setupFilters();
    loadHistory().then(connectWebSocket);
  });

  function setupFilters() {
    document.querySelectorAll('#log-filter-bar .filter-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('#log-filter-bar .filter-btn')
          .forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        currentType = btn.dataset.type || '';
        loadHistory();
      });
    });
  }

  async function loadHistory() {
    const list = document.getElementById('log-list');
    list.innerHTML = '<div class="log-empty">Loading…</div>';
    const qs = new URLSearchParams({ limit: HISTORY_LIMIT });
    if (currentType) qs.set('type', currentType);
    try {
      const events = await fetch(`/api/logs?${qs}`).then(r => r.json());
      list.innerHTML = '';
      if (!events.length) {
        list.innerHTML = '<div class="log-empty">No events recorded yet.</div>';
      } else {
        events.forEach(e => list.appendChild(LogRender.entryEl(e)));
      }
      count = events.length;
      updateCount();
      list.scrollTop = list.scrollHeight;
    } catch (e) {
      list.innerHTML = '<div class="log-empty">Failed to load history.</div>';
    }
  }

  function updateCount() {
    const el = document.getElementById('log-count');
    if (el) el.textContent = `${count} event${count === 1 ? '' : 's'}`;
  }

  function appendLive(event) {
    // Respect the active filter for live events.
    if (currentType && event.type !== currentType) return;
    const list = document.getElementById('log-list');
    if (!list) return;
    // Clear the "no events" placeholder on first live event.
    const empty = list.querySelector('.log-empty');
    if (empty) empty.remove();
    // Only auto-scroll if the user is already near the bottom.
    const atBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 40;
    list.appendChild(LogRender.entryEl(event));
    count += 1;
    updateCount();
    if (atBottom) list.scrollTop = list.scrollHeight;
  }

  function connectWebSocket() {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${protocol}//${location.host}/ws/events`);

    ws.onopen = () => {
      reconnectDelay = 1000;
      setStatus('connected', 'ws-status connected');
    };
    ws.onmessage = (event) => appendLive(JSON.parse(event.data));
    ws.onerror = () => { ws.close(); };
    ws.onclose = () => {
      setStatus('disconnected', 'ws-status disconnected');
      setTimeout(() => {
        reconnectDelay = Math.min(reconnectDelay * 2, 30000);
        connectWebSocket();
      }, reconnectDelay);
    };
  }

  function setStatus(text, cls) {
    const el = document.getElementById('ws-status');
    if (el) { el.textContent = text; el.className = cls; }
  }
})();
