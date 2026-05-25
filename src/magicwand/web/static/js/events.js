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

    const entry = document.createElement('div');
    entry.className = `log-entry log-${event.type}`;

    const time = new Date(event.timestamp).toLocaleTimeString();
    const badge = eventBadge(event.type);
    const detail = eventDetail(event);

    entry.innerHTML = `<span class="log-time">${time}</span>${badge}<span class="log-detail">${detail}</span>`;
    log.appendChild(entry);

    // Trim old entries
    while (log.children.length > MAX_VISIBLE) {
      log.removeChild(log.firstChild);
    }

    // Auto-scroll
    log.scrollTop = log.scrollHeight;
  }

  function eventBadge(type) {
    const colors = {
      gesture_recognized: 'badge-success',
      action_fired: 'badge-success',
      action_failed: 'badge-error',
      gesture_rejected: 'badge-warning',
      system_start: 'badge-info',
      system_error: 'badge-error',
    };
    const labels = {
      gesture_recognized: 'recognized',
      action_fired: 'action',
      action_failed: 'action failed',
      gesture_rejected: 'rejected',
      system_start: 'start',
      system_error: 'error',
    };
    return `<span class="log-badge ${colors[type] || ''}">${labels[type] || type}</span>`;
  }

  function eventDetail(event) {
    const d = event.data;
    switch (event.type) {
      case 'gesture_recognized':
        return `${d.gesture_name} (${(d.confidence * 100).toFixed(0)}%)`;
      case 'action_fired':
        return `${d.url} → ${d.status_code} (${d.latency_ms}ms)`;
      case 'action_failed':
        return `${d.url} — ${d.error}`;
      case 'gesture_rejected':
        return d.reason;
      case 'system_start':
        return `camera: ${d.camera_source}, port: ${d.server_port}`;
      case 'system_error':
        return d.message;
      default:
        return JSON.stringify(d);
    }
  }
})();
