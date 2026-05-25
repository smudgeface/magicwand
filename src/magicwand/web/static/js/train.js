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
      samples.push(result.sample);
      // Submit to API
      await fetchJSON(`/api/gestures/${gestureName}/samples`, {
        method: 'POST',
        body: JSON.stringify(result.sample),
      });
    }
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
      const svg = renderGestureSVG(sample, { width: 80, height: 80, color: '#7c3aed' });
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

    // Poll matching status
    const pollTest = setInterval(async () => {
      try {
        const status = await fetchJSON('/api/matching/status');
        if (status.last_match && status.last_match.matched) {
          const result = document.getElementById('test-result');
          result.style.display = '';
          document.getElementById('test-match-name').textContent = status.last_match.gesture_name;
          document.getElementById('test-confidence').textContent =
            `${(status.last_match.confidence * 100).toFixed(0)}% confidence`;
          result.className = 'test-result success';
        }
      } catch (e) { /* ignore */ }
    }, 500);

    // Clean up on page leave
    window.addEventListener('beforeunload', () => clearInterval(pollTest));
  }
})();
