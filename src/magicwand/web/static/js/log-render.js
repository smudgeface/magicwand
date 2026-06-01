// Shared rendering for event-log entries, used by the feed page (events.js)
// and the Log history page (logs.js) so both render events identically.
window.LogRender = (function() {
  function badge(type) {
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

  function detail(event) {
    const d = event.data || {};
    switch (event.type) {
      case 'gesture_recognized':
        return `${d.gesture_name} (${(d.confidence * 100).toFixed(0)}%)`;
      case 'action_fired':
        if (d.accessory) return `${d.accessory} → ${d.action} (${d.latency_ms}ms)`;
        return `${d.url} → ${d.status_code} (${d.latency_ms}ms)`;
      case 'action_failed':
        if (d.accessory) return `${d.accessory} — ${d.error}`;
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

  // Build a <div class="log-entry"> element for one event.
  function entryEl(event) {
    const entry = document.createElement('div');
    entry.className = `log-entry log-${event.type}`;
    const time = new Date(event.timestamp).toLocaleTimeString();
    entry.innerHTML =
      `<span class="log-time">${time}</span>` +
      badge(event.type) +
      `<span class="log-detail">${detail(event)}</span>`;
    return entry;
  }

  return { badge, detail, entryEl };
})();
