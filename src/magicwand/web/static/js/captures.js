(function() {
  let currentFilter = 'all';

  document.addEventListener('DOMContentLoaded', () => {
    loadCaptures();
    setupFilters();
    document.getElementById('btn-clear').onclick = clearCaptures;
    document.getElementById('btn-close-detail').onclick = closeDetail;
  });

  async function loadCaptures() {
    const list = document.getElementById('captures-list');
    const empty = document.getElementById('empty-state');

    const matchedParam = currentFilter === 'matched' ? '&matched=true' :
                         currentFilter === 'unmatched' ? '&matched=false' : '';

    try {
      const data = await fetchJSON(`/api/captures?limit=100${matchedParam}`);
      const captures = data.captures;

      if (captures.length === 0) {
        list.style.display = 'none';
        empty.style.display = 'block';
        return;
      }

      empty.style.display = 'none';
      list.style.display = '';
      list.innerHTML = '';

      for (const c of captures) {
        const row = document.createElement('div');
        row.className = 'capture-row';
        row.onclick = () => showDetail(c.id);

        const time = new Date(c.timestamp).toLocaleTimeString();
        const matchBadge = c.match_result.matched
          ? `<span class="log-badge badge-success">${c.match_result.gesture_name} (${(c.match_result.confidence * 100).toFixed(0)}%)</span>`
          : '<span class="log-badge badge-warning">no match</span>';

        row.innerHTML = `
          <span class="capture-time">${time}</span>
          <span class="capture-points">${c.point_count} pts / ${c.duration_s.toFixed(1)}s</span>
          ${c.trimmed_points > 0 ? `<span class="capture-trimmed">-${c.trimmed_points} trimmed</span>` : ''}
          ${matchBadge}
        `;
        list.appendChild(row);
      }
    } catch (err) {
      list.innerHTML = `<p class="error">Failed to load: ${err.message}</p>`;
    }
  }

  async function showDetail(id) {
    try {
      const capture = await fetchJSON(`/api/captures/${id}`);
      document.getElementById('detail-id').textContent = capture.id;
      document.getElementById('detail-time').textContent = new Date(capture.timestamp).toLocaleString();
      document.getElementById('detail-points').textContent = `${capture.point_count} raw points`;
      document.getElementById('detail-duration').textContent = `${capture.duration_s.toFixed(2)}s`;
      document.getElementById('detail-trimmed').textContent = `${capture.trimmed_points} points removed`;

      const mr = capture.match_result;
      document.getElementById('detail-match').textContent = mr.matched ? mr.gesture_name : 'no match';
      document.getElementById('detail-confidence').textContent = mr.matched ? `${(mr.confidence * 100).toFixed(1)}%` : '—';

      // Render SVG
      const svgContainer = document.getElementById('detail-svg');
      svgContainer.innerHTML = '';
      if (capture.raw_points && capture.raw_points.length > 1) {
        const svg = renderGestureSVG(capture.raw_points, { width: 200, height: 200, color: '#c4b5fd' });
        if (svg instanceof Element) svgContainer.appendChild(svg);
      }

      document.getElementById('capture-detail').style.display = '';
    } catch (err) {
      alert('Failed to load capture: ' + err.message);
    }
  }

  function closeDetail() {
    document.getElementById('capture-detail').style.display = 'none';
  }

  function setupFilters() {
    document.querySelectorAll('.filter-btn').forEach(btn => {
      btn.onclick = () => {
        document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        currentFilter = btn.dataset.filter;
        loadCaptures();
      };
    });
  }

  async function clearCaptures() {
    if (!confirm('Clear all capture history?')) return;
    await fetchJSON('/api/captures', { method: 'DELETE' });
    loadCaptures();
  }
})();
