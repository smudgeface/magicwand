(function() {
  document.addEventListener('DOMContentLoaded', () => {
    loadCurrentSettings();
    loadSystemInfo();
    setupCameraForm();
    setupDetectionForm();
    setupMatchingForm();
    setupHomebridgeForm();
    setupPowerControls();
    setInterval(loadSystemInfo, 10000);
  });

  async function setupCameraForm() {
    const modeSel = document.getElementById('cam-exposure-mode');
    const expSlider = document.getElementById('cam-exposure');
    const expVal = document.getElementById('cam-exposure-val');
    const gainSlider = document.getElementById('cam-gain');
    const gainVal = document.getElementById('cam-gain-val');

    function reflectMode() {
      const manual = modeSel.value === 'manual';
      document.getElementById('cam-manual-controls').style.display = manual ? '' : 'none';
    }
    expSlider.addEventListener('input', () => { expVal.textContent = `${expSlider.value} µs`; });
    gainSlider.addEventListener('input', () => { gainVal.textContent = `${(+gainSlider.value).toFixed(1)}×`; });
    modeSel.addEventListener('change', reflectMode);

    async function load() {
      let c;
      try { c = await fetch('/api/camera/controls').then(r => r.json()); } catch (e) { return; }
      if (!c || !c.available) {
        document.getElementById('cam-controls').style.display = 'none';
        document.getElementById('cam-unavailable').style.display = '';
        return;
      }
      expSlider.min = c.exposure_min; expSlider.max = c.exposure_max;
      gainSlider.min = c.gain_min; gainSlider.max = c.gain_max;
      modeSel.value = c.auto_exposure ? 'auto' : 'manual';
      expSlider.value = c.exposure_us; expVal.textContent = `${c.exposure_us} µs`;
      gainSlider.value = c.gain; gainVal.textContent = `${(+c.gain).toFixed(1)}×`;
      reflectMode();
      updateReadout(c);
    }

    function updateReadout(c) {
      const mode = c.auto_exposure ? 'auto' : 'manual';
      document.getElementById('cam-readout').textContent =
        `${c.exposure_us} µs · ${(+c.gain).toFixed(1)}× (${mode})`;
    }

    document.getElementById('btn-apply-camera').onclick = async () => {
      const body = { auto_exposure: modeSel.value === 'auto' };
      if (!body.auto_exposure) {
        body.exposure_us = parseInt(expSlider.value);
        body.gain = parseFloat(gainSlider.value);
      }
      try {
        const c = await fetch('/api/camera/controls', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        }).then(r => r.json());
        if (c.available) { updateReadout(c); showStatus('cam-status', 'Applied', true); }
        else showStatus('cam-status', 'Not supported', false);
      } catch (e) {
        showStatus('cam-status', 'Error', false);
      }
    };

    await load();
    // Refresh the live readout periodically (useful in auto mode to see AE).
    setInterval(async () => {
      try {
        const c = await fetch('/api/camera/controls').then(r => r.json());
        if (c && c.available) updateReadout(c);
      } catch (e) {}
    }, 3000);
  }

  async function loadCurrentSettings() {
    try {
      const det = await fetch('/api/detection/status').then(r => r.json());
      const cfg = det.config;
      document.getElementById('det-threshold').value = cfg.threshold;
      document.getElementById('det-threshold-val').textContent = cfg.threshold;
      document.getElementById('det-min-area').value = cfg.min_area;
      document.getElementById('det-max-area').value = cfg.max_area;
      document.getElementById('det-blur').value = cfg.blur_kernel;
      document.getElementById('det-trail-hold').value = cfg.trail_hold;
      document.getElementById('det-trail-fade').value = cfg.trail_fade;
      document.getElementById('det-tophat').value = cfg.tophat_kernel;
      document.getElementById('det-contrast').value = cfg.min_contrast;
      document.getElementById('det-circularity').value = cfg.min_circularity;
      document.getElementById('det-circ-area').value = cfg.circularity_min_area;
    } catch (e) {}

    try {
      const match = await fetch('/api/matching/status').then(r => r.json());
      const mc = match.config;
      document.getElementById('match-dist').value = mc.distance_threshold;
      document.getElementById('match-conf').value = mc.min_confidence;
      document.getElementById('match-gap').value = mc.gap_timeout;
      document.getElementById('match-cooldown').value = mc.cooldown_time;
      document.getElementById('match-min-pts').value = mc.min_gesture_points;
      document.getElementById('match-dwell-speed').value = mc.dwell_speed_threshold;
      document.getElementById('match-dwell-pts').value = mc.dwell_min_points;
      document.getElementById('match-linearity').value = mc.linearity_threshold;
      document.getElementById('match-curvature').value = mc.min_curvature;
      document.getElementById('match-min-dur').value = mc.min_segment_duration;
    } catch (e) {}
  }

  async function loadSystemInfo() {
    try {
      const info = await fetch('/api/system/info').then(r => r.json());
      const h = Math.floor(info.uptime_seconds / 3600);
      const m = Math.floor((info.uptime_seconds % 3600) / 60);
      document.getElementById('info-uptime').textContent = `${h}h ${m}m`;
      document.getElementById('info-cpu-temp').textContent = info.cpu_temp_c ? `${info.cpu_temp_c}°C` : 'N/A';
      document.getElementById('info-ram').textContent = info.ram_used_mb ? `${info.ram_used_mb} / ${info.ram_total_mb} MB` : 'N/A';
      document.getElementById('info-disk').textContent = `${info.disk_used_gb} / ${info.disk_total_gb} GB`;
      document.getElementById('info-camera').textContent = info.camera_source;
      document.getElementById('info-fps').textContent = `${info.detection_fps}`;
      document.getElementById('info-python').textContent = info.python_version;
      document.getElementById('info-version').textContent = info.app_version;
    } catch (e) {}
  }

  function setupDetectionForm() {
    const slider = document.getElementById('det-threshold');
    const valDisplay = document.getElementById('det-threshold-val');
    slider.addEventListener('input', () => { valDisplay.textContent = slider.value; });

    document.getElementById('btn-apply-detection').onclick = async () => {
      const body = {
        threshold: parseInt(slider.value),
        min_area: parseInt(document.getElementById('det-min-area').value),
        max_area: parseInt(document.getElementById('det-max-area').value),
        blur_kernel: parseInt(document.getElementById('det-blur').value),
        trail_hold: parseFloat(document.getElementById('det-trail-hold').value),
        trail_fade: parseFloat(document.getElementById('det-trail-fade').value),
        tophat_kernel: parseInt(document.getElementById('det-tophat').value),
        min_contrast: parseInt(document.getElementById('det-contrast').value),
        min_circularity: parseFloat(document.getElementById('det-circularity').value),
        circularity_min_area: parseInt(document.getElementById('det-circ-area').value),
      };
      try {
        await fetch('/api/settings/detection', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        showStatus('det-status', 'Applied', true);
      } catch (e) {
        showStatus('det-status', 'Error', false);
      }
    };
  }

  function setupMatchingForm() {
    document.getElementById('btn-apply-matching').onclick = async () => {
      const body = {
        distance_threshold: parseFloat(document.getElementById('match-dist').value),
        min_confidence: parseFloat(document.getElementById('match-conf').value),
        gap_timeout: parseFloat(document.getElementById('match-gap').value),
        cooldown_time: parseFloat(document.getElementById('match-cooldown').value),
        min_gesture_points: parseInt(document.getElementById('match-min-pts').value),
        dwell_speed_threshold: parseFloat(document.getElementById('match-dwell-speed').value),
        dwell_min_points: parseInt(document.getElementById('match-dwell-pts').value),
        linearity_threshold: parseFloat(document.getElementById('match-linearity').value),
        min_curvature: parseFloat(document.getElementById('match-curvature').value),
        min_segment_duration: parseFloat(document.getElementById('match-min-dur').value),
      };
      try {
        await fetch('/api/settings/matching', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        showStatus('match-status', 'Applied', true);
      } catch (e) {
        showStatus('match-status', 'Error', false);
      }
    };
  }

  async function setupHomebridgeForm() {
    try {
      const status = await fetch('/api/homebridge/status').then(r => r.json());
      document.getElementById('hb-host').value = status.host || '';
      document.getElementById('hb-port').value = status.port || 8581;
      showStatus('hb-status', status.connected ? 'Connected' : (status.configured ? 'Not connected' : ''), status.connected);
    } catch (e) {}

    document.getElementById('btn-save-hb').onclick = async () => {
      const body = {
        host: document.getElementById('hb-host').value,
        port: parseInt(document.getElementById('hb-port').value),
        username: document.getElementById('hb-username').value,
        password: document.getElementById('hb-password').value,
      };
      try {
        await fetch('/api/settings/homebridge', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        showStatus('hb-status', 'Saved', true);
      } catch (e) {
        showStatus('hb-status', 'Error', false);
      }
    };

    document.getElementById('btn-test-hb').onclick = async () => {
      showStatus('hb-status', 'Connecting...', true);
      try {
        const result = await fetch('/api/homebridge/connect', { method: 'POST' }).then(r => r.json());
        showStatus('hb-status', result.connected ? 'Connected' : 'Failed', result.connected);
      } catch (e) {
        showStatus('hb-status', 'Error', false);
      }
    };
  }

  function setupPowerControls() {
    const btn = document.getElementById('btn-reboot');
    if (!btn) return;
    const statusEl = document.getElementById('reboot-status');

    btn.onclick = async () => {
      if (!confirm('Reboot the device now? It will be unreachable for ~30–60 seconds.')) {
        return;
      }
      btn.disabled = true;
      setPersistentStatus(statusEl, 'Sending reboot command…', true);
      try {
        const res = await fetch('/api/system/reboot', { method: 'POST' });
        if (!res.ok) throw new Error('reboot request failed');
        setPersistentStatus(statusEl, 'Rebooting… waiting for the device to come back', true);
        waitForReboot(statusEl, btn);
      } catch (e) {
        setPersistentStatus(statusEl, 'Error sending reboot command', false);
        btn.disabled = false;
      }
    };
  }

  // Poll /api/health until the device goes down and comes back up.
  function waitForReboot(statusEl, btn) {
    let sawDown = false;
    const startedAt = Date.now();
    const timer = setInterval(async () => {
      // Give up after 3 minutes so the page doesn't poll forever.
      if (Date.now() - startedAt > 180000) {
        clearInterval(timer);
        setPersistentStatus(statusEl, 'Still waiting — try reloading the page', false);
        btn.disabled = false;
        return;
      }
      try {
        const r = await fetch('/api/health', { cache: 'no-store' });
        if (!r.ok) throw new Error('not ok');
        if (sawDown) {
          // It went away and is now answering again → reboot complete.
          clearInterval(timer);
          setPersistentStatus(statusEl, 'Back online — reloading…', true);
          setTimeout(() => location.reload(), 1000);
        }
        // If we never saw it go down yet, keep waiting for the drop first.
      } catch (e) {
        sawDown = true;  // device is down (rebooting)
      }
    }, 2000);
  }

  function setPersistentStatus(el, msg, success) {
    el.textContent = msg;
    el.className = `setting-status ${success ? 'success' : 'error'}`;
  }

  function showStatus(id, msg, success) {
    const el = document.getElementById(id);
    el.textContent = msg;
    el.className = `setting-status ${success ? 'success' : 'error'}`;
    setTimeout(() => { el.textContent = ''; }, 3000);
  }
})();
