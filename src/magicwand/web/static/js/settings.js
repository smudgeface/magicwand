(function() {
  document.addEventListener('DOMContentLoaded', () => {
    loadCurrentSettings();
    loadSystemInfo();
    setupDetectionForm();
    setupMatchingForm();
    // Refresh system info every 10s
    setInterval(loadSystemInfo, 10000);
  });

  async function loadCurrentSettings() {
    try {
      const det = await fetch('/api/detection/status').then(r => r.json());
      const cfg = det.config;
      document.getElementById('det-threshold').value = cfg.threshold;
      document.getElementById('det-threshold-val').textContent = cfg.threshold;
      document.getElementById('det-min-area').value = cfg.min_area;
      document.getElementById('det-max-area').value = cfg.max_area;
      document.getElementById('det-blur').value = cfg.blur_kernel;
      document.getElementById('det-trail').value = cfg.trail_length;
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
        trail_length: parseInt(document.getElementById('det-trail').value),
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

  function showStatus(id, msg, success) {
    const el = document.getElementById(id);
    el.textContent = msg;
    el.className = `setting-status ${success ? 'success' : 'error'}`;
    setTimeout(() => { el.textContent = ''; }, 3000);
  }
})();
