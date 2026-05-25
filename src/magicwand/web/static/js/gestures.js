// === Utilities ===

async function fetchJSON(url, options = {}) {
  const resp = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ error: resp.statusText }));
    throw new Error(err.error || resp.statusText);
  }
  return resp.json();
}

function renderGestureSVG(points, options = {}) {
  const {
    width = 80, height = 80,
    color = '#22c55e', strokeWidth = 0.03,
  } = options;

  if (!points || points.length < 2) return '<svg></svg>';

  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 1 1');
  svg.setAttribute('width', width);
  svg.setAttribute('height', height);
  svg.style.overflow = 'visible';

  // Draw path
  const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  const d = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(4)},${p.y.toFixed(4)}`).join(' ');
  path.setAttribute('d', d);
  path.setAttribute('fill', 'none');
  path.setAttribute('stroke', color);
  path.setAttribute('stroke-width', strokeWidth);
  path.setAttribute('stroke-linecap', 'round');
  path.setAttribute('stroke-linejoin', 'round');
  svg.appendChild(path);

  // Start marker
  const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
  circle.setAttribute('cx', points[0].x);
  circle.setAttribute('cy', points[0].y);
  circle.setAttribute('r', 0.02);
  circle.setAttribute('fill', color);
  svg.appendChild(circle);

  return svg;
}

function formatConfidence(value) {
  return `${(value * 100).toFixed(0)}%`;
}

// === Gesture list page ===

async function loadGestureList() {
  const list = document.getElementById('gesture-list');
  const empty = document.getElementById('empty-state');
  if (!list) return;

  try {
    const gestures = await fetchJSON('/api/gestures');
    if (gestures.length === 0) {
      list.style.display = 'none';
      empty.style.display = 'block';
      return;
    }
    empty.style.display = 'none';
    list.style.display = '';
    list.innerHTML = '';

    for (const g of gestures) {
      const card = document.createElement('a');
      card.href = `/gesture/${g.name}`;
      card.className = 'gesture-card';

      // Try to get sample preview
      let svgHtml = '<div class="gesture-preview-placeholder"></div>';
      try {
        const detail = await fetchJSON(`/api/gestures/${g.name}`);
        if (detail.samples && detail.samples.length > 0) {
          const svgEl = renderGestureSVG(detail.samples[0], { width: 60, height: 60 });
          if (svgEl instanceof Element) {
            const wrapper = document.createElement('div');
            wrapper.appendChild(svgEl);
            svgHtml = wrapper.innerHTML;
          }
        }
      } catch (e) { /* ignore */ }

      card.innerHTML = `
        <div class="gesture-preview">${svgHtml}</div>
        <div class="gesture-info">
          <span class="gesture-name">${g.name}</span>
          <span class="gesture-meta">${g.sample_count} sample${g.sample_count !== 1 ? 's' : ''}</span>
          <span class="gesture-action-status ${g.has_action ? 'has-action' : ''}">${g.has_action ? 'Action set' : 'No action'}</span>
        </div>
      `;
      list.appendChild(card);
    }
  } catch (err) {
    list.innerHTML = `<p class="error">Failed to load gestures: ${err.message}</p>`;
  }
}
