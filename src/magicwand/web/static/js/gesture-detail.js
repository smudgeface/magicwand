(function() {
  // gestureName is defined in the template via inline script

  document.addEventListener('DOMContentLoaded', async () => {
    await loadGesture();
    await loadPresets();
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
        const svg = renderGestureSVG(sample, { width: 100, height: 100 });
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

      // Load action if set
      if (g.action) {
        document.getElementById('action-url').value = g.action.url || '';
        document.getElementById('action-method').value = g.action.method || 'GET';
        document.getElementById('action-timeout').value = g.action.timeout || 5;
        document.getElementById('action-body').value = g.action.body || '';
      }
    } catch (err) {
      document.getElementById('gesture-name-header').textContent = 'Error loading gesture';
    }
  }

  async function loadPresets() {
    try {
      const presets = await fetchJSON('/api/homebridge/presets');
      const select = document.getElementById('preset-select');
      presets.forEach(p => {
        const opt = document.createElement('option');
        opt.value = JSON.stringify(p);
        opt.textContent = p.name;
        select.appendChild(opt);
      });
      select.addEventListener('change', () => {
        if (select.value) {
          const preset = JSON.parse(select.value);
          document.getElementById('action-url').value = preset.url_template;
          document.getElementById('action-method').value = preset.method;
        }
      });
    } catch (e) { /* ignore */ }
  }

  function setupActionForm() {
    document.getElementById('btn-save-action').onclick = async () => {
      const action = {
        url: document.getElementById('action-url').value,
        method: document.getElementById('action-method').value,
        timeout: parseFloat(document.getElementById('action-timeout').value) || 5,
        body: document.getElementById('action-body').value || null,
      };
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
          showActionResult(`Success — ${result.status_code} (${result.latency_ms}ms)`, true);
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
