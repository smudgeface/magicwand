(function() {
  document.addEventListener('DOMContentLoaded', async () => {
    await loadGesture();
    await loadAccessories();
    setupActionForm();
  });

  async function loadGesture() {
    try {
      const g = await fetchJSON(`/api/gestures/${gestureName}`);
      document.getElementById('gesture-name-header').textContent = g.name;
      document.getElementById('sample-count').textContent = g.samples.length;
      document.getElementById('btn-add-samples').href = `/train?name=${g.name}`;

      const list = document.getElementById('sample-list');
      list.innerHTML = '';
      g.samples.forEach((sample, i) => {
        const card = document.createElement('div');
        card.className = 'sample-card';
        const pts = sample.points || sample;
        const labels = sample.segment_labels || null;
        let svg;
        if (labels && typeof renderSegmentedSVG === 'function') {
          svg = renderSegmentedSVG(pts, labels, { width: 100, height: 100 });
        } else {
          svg = renderGestureSVG(pts, { width: 100, height: 100 });
        }
        if (svg instanceof Element) card.appendChild(svg);

        const removeBtn = document.createElement('button');
        removeBtn.className = 'btn btn-danger btn-sm';
        removeBtn.textContent = 'Remove';
        removeBtn.onclick = async () => {
          await fetchJSON(`/api/gestures/${gestureName}/samples/${i}`, { method: 'DELETE' });
          await loadGesture();
        };
        card.appendChild(removeBtn);
        list.appendChild(card);
      });

      // Load existing action into form
      if (g.action) {
        if (g.action.type === 'homebridge') {
          document.getElementById('hb-accessory').value = g.action.accessory_id || '';
          document.getElementById('hb-action').value = g.action.action || 'toggle';
        } else {
          document.getElementById('action-url').value = g.action.url || '';
          document.getElementById('action-method').value = g.action.method || 'GET';
          document.getElementById('action-timeout').value = g.action.timeout || 5;
          document.getElementById('action-body').value = g.action.body || '';
          document.getElementById('http-action-section').open = true;
        }
      }
    } catch (err) {
      document.getElementById('gesture-name-header').textContent = 'Error loading gesture';
    }
  }

  async function loadAccessories() {
    const select = document.getElementById('hb-accessory');
    try {
      const status = await fetchJSON('/api/homebridge/status');
      if (!status.configured) {
        select.innerHTML = '<option value="">Not configured</option>';
        document.getElementById('hb-not-connected').style.display = '';
        return;
      }
      if (!status.connected) {
        await fetchJSON('/api/homebridge/connect', { method: 'POST' });
      }
      const accessories = await fetchJSON('/api/homebridge/accessories');
      select.innerHTML = '<option value="">— Select accessory —</option>';
      for (const a of accessories) {
        const opt = document.createElement('option');
        opt.value = a.uniqueId;
        const state = a.values.On !== undefined ? (a.values.On ? ' (on)' : ' (off)') : '';
        opt.textContent = `${a.serviceName} [${a.type}]${state}`;
        select.appendChild(opt);
      }
      // Re-select if gesture already has a Homebridge action
      const g = await fetchJSON(`/api/gestures/${gestureName}`);
      if (g.action && g.action.type === 'homebridge') {
        select.value = g.action.accessory_id || '';
      }
    } catch (e) {
      select.innerHTML = '<option value="">Failed to load</option>';
      document.getElementById('hb-not-connected').style.display = '';
    }
  }

  function setupActionForm() {
    document.getElementById('btn-save-action').onclick = async () => {
      const hbAccessory = document.getElementById('hb-accessory').value;
      const httpUrl = document.getElementById('action-url').value;

      let action;
      if (hbAccessory) {
        const selectedOpt = document.getElementById('hb-accessory').selectedOptions[0];
        action = {
          type: 'homebridge',
          accessory_id: hbAccessory,
          accessory_name: selectedOpt ? selectedOpt.textContent.split(' [')[0] : '',
          action: document.getElementById('hb-action').value,
        };
      } else if (httpUrl) {
        action = {
          type: 'http',
          url: httpUrl,
          method: document.getElementById('action-method').value,
          timeout: parseFloat(document.getElementById('action-timeout').value) || 5,
          body: document.getElementById('action-body').value || null,
        };
      } else {
        showActionResult('Select an accessory or enter a URL', false);
        return;
      }

      try {
        await fetchJSON(`/api/gestures/${gestureName}/action`, {
          method: 'PUT',
          body: JSON.stringify(action),
        });
        showActionResult('Action saved', true);
      } catch (err) {
        showActionResult(`Error: ${err.message}`, false);
      }
    };

    document.getElementById('btn-test-action').onclick = async () => {
      const resultDiv = document.getElementById('action-result');
      resultDiv.style.display = '';
      resultDiv.className = 'action-result pending';
      resultDiv.textContent = 'Firing...';
      try {
        const result = await fetchJSON(`/api/gestures/${gestureName}/action/test`, { method: 'POST' });
        if (result.success) {
          showActionResult(`Success — ${result.status_code || result.action || 'ok'} (${result.latency_ms}ms)`, true);
        } else {
          showActionResult(`Failed — ${result.error} (${result.latency_ms}ms)`, false);
        }
      } catch (err) {
        showActionResult(`Error: ${err.message}`, false);
      }
    };

    document.getElementById('btn-clear-action').onclick = async () => {
      try {
        await fetchJSON(`/api/gestures/${gestureName}/action`, { method: 'DELETE' });
        document.getElementById('hb-accessory').value = '';
        document.getElementById('action-url').value = '';
        document.getElementById('action-body').value = '';
        showActionResult('Action cleared', true);
      } catch (err) {
        showActionResult(`Error: ${err.message}`, false);
      }
    };

    document.getElementById('btn-delete').onclick = async () => {
      if (confirm(`Delete gesture "${gestureName}"?`)) {
        await fetchJSON(`/api/gestures/${gestureName}`, { method: 'DELETE' });
        window.location.href = '/gestures';
      }
    };
  }

  function showActionResult(msg, success) {
    const div = document.getElementById('action-result');
    div.style.display = '';
    div.textContent = msg;
    div.className = `action-result ${success ? 'success' : 'error'}`;
    setTimeout(() => { div.style.display = 'none'; }, 5000);
  }
})();
