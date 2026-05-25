(function() {
  let gestureName = '';
  let samples = [];
  let recordingPollInterval = null;
  const MAX_SAMPLES = 5;
  const MIN_SAMPLES = 3;

  document.addEventListener('DOMContentLoaded', () => {
    // Check if name was passed via URL
    const params = new URLSearchParams(window.location.search);
    const urlName = params.get('name');
    if (urlName) {
      gestureName = urlName;
      showRecordStep();
    } else {
      showNameStep();
    }
  });

  function showNameStep() {
    document.getElementById('step-name').style.display = '';
    document.getElementById('step-record').style.display = 'none';
    document.getElementById('step-test').style.display = 'none';

    const input = document.getElementById('gesture-name');
    const btn = document.getElementById('btn-next');
    const error = document.getElementById('name-error');

    input.addEventListener('input', () => {
      const valid = /^[a-z][a-z0-9-]{0,29}$/.test(input.value);
      btn.disabled = !valid;
      error.style.display = 'none';
    });

    btn.addEventListener('click', async () => {
      gestureName = input.value;
      try {
        await fetchJSON('/api/gestures', {
          method: 'POST',
          body: JSON.stringify({ name: gestureName }),
        });
        showRecordStep();
      } catch (err) {
        error.textContent = err.message;
        error.style.display = '';
      }
    });
  }

  function showRecordStep() {
    document.getElementById('step-name').style.display = 'none';
    document.getElementById('step-record').style.display = '';
    document.getElementById('step-test').style.display = 'none';
    document.getElementById('display-name').textContent = gestureName;
    updateSampleUI();

    const btnRecord = document.getElementById('btn-record');
    const btnStop = document.getElementById('btn-stop');

    btnRecord.onclick = startRecording;
    btnStop.onclick = stopRecording;

    document.getElementById('btn-save').onclick = () => saveGesture(false);
    document.getElementById('btn-save-test').onclick = () => saveGesture(true);
  }

  async function startRecording() {
    document.getElementById('btn-record').style.display = 'none';
    document.getElementById('btn-stop').style.display = '';
    document.getElementById('recording-indicator').style.display = '';
    document.getElementById('recording-card').classList.add('is-recording');

    await fetchJSON('/api/recording/start', { method: 'POST' });

    recordingPollInterval = setInterval(async () => {
      try {
        const status = await fetchJSON('/api/recording/status');
        document.getElementById('point-count').textContent = status.point_count;
        if (status.state === 'review' || status.state === 'idle') {
          clearInterval(recordingPollInterval);
          await handleRecordingComplete();
        }
      } catch (e) { /* ignore */ }
    }, 200);
  }

  async function stopRecording() {
    clearInterval(recordingPollInterval);
    const result = await fetchJSON('/api/recording/stop', { method: 'POST' });
    await handleRecordingComplete(result);
  }

  async function handleRecordingComplete(result) {
    document.getElementById('btn-record').style.display = '';
    document.getElementById('btn-stop').style.display = 'none';
    document.getElementById('recording-indicator').style.display = 'none';
    document.getElementById('recording-card').classList.remove('is-recording');

    if (!result) {
      result = await fetchJSON('/api/recording/stop', { method: 'POST' });
    }

    if (result.sample && result.point_count >= 5) {
      try {
        await fetchJSON(`/api/gestures/${gestureName}/samples`, {
          method: 'POST',
          body: JSON.stringify(result.sample),
        });
        // Fetch back the stored sample (segmented) for colored preview
        const detail = await fetchJSON(`/api/gestures/${gestureName}`);
        const stored = detail.samples[detail.samples.length - 1];
        samples.push(stored);
      } catch (e) {
        // Segmentation rejected the sample — show error briefly
        const counter = document.getElementById('sample-counter');
        counter.textContent = `Sample rejected: ${e.message}`;
        setTimeout(() => updateSampleUI(), 3000);
      }
    }
    // Return recorder to IDLE so the watcher resumes processing
    await fetchJSON('/api/recording/discard', { method: 'POST' });
    updateSampleUI();
  }

  function updateSampleUI() {
    const counter = document.getElementById('sample-counter');
    counter.textContent = `Sample ${samples.length} / ${MAX_SAMPLES}`;

    const previews = document.getElementById('sample-previews');
    previews.innerHTML = '';
    samples.forEach((sample, i) => {
      const div = document.createElement('div');
      div.className = 'sample-preview-card';
      const pts = sample.points || sample;
      const labels = sample.segment_labels || null;
      let svg;
      if (labels) {
        svg = renderSegmentedSVG(pts, labels, { width: 80, height: 80 });
      } else {
        svg = renderGestureSVG(pts, { width: 80, height: 80, color: '#7c3aed' });
      }
      if (svg instanceof Element) div.appendChild(svg);
      else div.innerHTML = `<span>Sample ${i + 1}</span>`;
      previews.appendChild(div);
    });

    const btnSave = document.getElementById('btn-save');
    const btnSaveTest = document.getElementById('btn-save-test');
    const btnRecord = document.getElementById('btn-record');

    if (samples.length >= MIN_SAMPLES) {
      btnSave.style.display = '';
      btnSaveTest.style.display = '';
    }
    if (samples.length >= MAX_SAMPLES) {
      btnRecord.style.display = 'none';
    }
  }

  async function saveGesture(andTest) {
    if (andTest) {
      showTestStep();
    } else {
      window.location.href = '/gestures';
    }
  }

  function showTestStep() {
    document.getElementById('step-record').style.display = 'none';
    document.getElementById('step-test').style.display = '';
    document.getElementById('test-name').textContent = gestureName;

    let lastSeenId = 0;
    // Get the current latest capture ID so we only react to new ones
    fetchJSON('/api/captures?limit=1').then(data => {
      if (data.captures && data.captures.length > 0) {
        lastSeenId = data.captures[0].id;
      }
    }).catch(() => {});

    const pollTest = setInterval(async () => {
      try {
        const data = await fetchJSON('/api/captures?limit=1');
        if (!data.captures || data.captures.length === 0) return;
        const latest = data.captures[0];
        if (latest.id <= lastSeenId) return;
        lastSeenId = latest.id;

        const resultDiv = document.getElementById('test-result');
        resultDiv.style.display = '';
        const mr = latest.match_result;
        if (mr.matched) {
          document.getElementById('test-match-name').textContent = mr.gesture_name;
          document.getElementById('test-confidence').textContent =
            `${(mr.confidence * 100).toFixed(0)}% confidence`;
          resultDiv.className = 'test-result success';
        } else {
          document.getElementById('test-match-name').textContent = 'No match';
          const reason = mr.distance != null
            ? `dist=${mr.distance.toFixed(3)}, conf=${(mr.confidence * 100).toFixed(0)}%`
            : 'no gesture segment found';
          document.getElementById('test-confidence').textContent = reason;
          resultDiv.className = 'test-result error';
        }
      } catch (e) { /* ignore */ }
    }, 500);

    window.addEventListener('beforeunload', () => clearInterval(pollTest));
  }
})();
