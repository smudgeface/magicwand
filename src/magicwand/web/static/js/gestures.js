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

const SEGMENT_COLORS = { trail: '#ef4444', gesture: '#22c55e', dwell: '#3b82f6' };

function renderSegmentedSVG(points, labels, options = {}) {
  const { width = 200, height = 200, strokeWidth = 0.03 } = options;
  if (!points || points.length < 2) return document.createElementNS('http://www.w3.org/2000/svg', 'svg');

  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 1 1');
  svg.setAttribute('width', width);
  svg.setAttribute('height', height);
  svg.style.overflow = 'visible';

  if (!labels || labels.length !== points.length) {
    return renderGestureSVG(points, { width, height, color: '#c4b5fd' });
  }

  let runStart = 0;
  for (let i = 1; i <= points.length; i++) {
    if (i === points.length || labels[i] !== labels[runStart]) {
      const color = SEGMENT_COLORS[labels[runStart]] || '#c4b5fd';
      const startIdx = runStart > 0 ? runStart - 1 : runStart;
      const drawPts = points.slice(startIdx, i);
      if (drawPts.length >= 2) {
        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        const d = drawPts.map((p, j) => `${j === 0 ? 'M' : 'L'}${p.x.toFixed(4)},${p.y.toFixed(4)}`).join(' ');
        path.setAttribute('d', d);
        path.setAttribute('fill', 'none');
        path.setAttribute('stroke', color);
        path.setAttribute('stroke-width', strokeWidth);
        path.setAttribute('stroke-linecap', 'round');
        path.setAttribute('stroke-linejoin', 'round');
        svg.appendChild(path);
      }
      runStart = i;
    }
  }

  const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
  circle.setAttribute('cx', points[0].x);
  circle.setAttribute('cy', points[0].y);
  circle.setAttribute('r', 0.02);
  circle.setAttribute('fill', SEGMENT_COLORS[labels[0]] || '#c4b5fd');
  svg.appendChild(circle);

  return svg;
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

      const preview = document.createElement('div');
      preview.className = 'gesture-preview';
      try {
        const detail = await fetchJSON(`/api/gestures/${g.name}`);
        if (detail.samples && detail.samples.length > 0) {
          const s = detail.samples[0];
          const pts = s.points || s;
          const labels = s.segment_labels || null;
          let svgEl;
          if (labels) {
            svgEl = renderSegmentedSVG(pts, labels, { width: 60, height: 60 });
          } else {
            svgEl = renderGestureSVG(pts, { width: 60, height: 60 });
          }
          if (svgEl instanceof Element) preview.appendChild(svgEl);
        }
      } catch (e) { /* ignore */ }

      const info = document.createElement('div');
      info.className = 'gesture-info';
      info.innerHTML = `
        <span class="gesture-name">${g.name}</span>
        <span class="gesture-meta">${g.sample_count} sample${g.sample_count !== 1 ? 's' : ''}</span>
        <span class="gesture-action-status ${g.has_action ? 'has-action' : ''}">${g.has_action ? 'Action set' : 'No action'}</span>
      `;
      card.appendChild(preview);
      card.appendChild(info);
      list.appendChild(card);
    }
  } catch (err) {
    list.innerHTML = `<p class="error">Failed to load gestures: ${err.message}</p>`;
  }
}
