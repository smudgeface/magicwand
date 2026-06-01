(function() {
  let ws = null;
  let reconnectDelay = 1000;
  const MAX_VISIBLE = 100;

  document.addEventListener('DOMContentLoaded', () => {
    const logContainer = document.getElementById('event-log');
    if (!logContainer) return;
    connectWebSocket();
  });

  function connectWebSocket() {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${protocol}//${location.host}/ws/events`);

    ws.onopen = () => {
      reconnectDelay = 1000;
      const indicator = document.getElementById('ws-status');
      if (indicator) { indicator.textContent = 'connected'; indicator.className = 'ws-status connected'; }
    };

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      appendEvent(data);
    };

    ws.onerror = () => { ws.close(); };

    ws.onclose = () => {
      const indicator = document.getElementById('ws-status');
      if (indicator) { indicator.textContent = 'disconnected'; indicator.className = 'ws-status disconnected'; }
      setTimeout(() => {
        reconnectDelay = Math.min(reconnectDelay * 2, 30000);
        connectWebSocket();
      }, reconnectDelay);
    };
  }

  function appendEvent(event) {
    const log = document.getElementById('event-log');
    if (!log) return;

    log.appendChild(LogRender.entryEl(event));

    // Trim old entries
    while (log.children.length > MAX_VISIBLE) {
      log.removeChild(log.firstChild);
    }

    // Auto-scroll
    log.scrollTop = log.scrollHeight;
  }
})();
