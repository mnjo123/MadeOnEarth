/* Sky in Motion — Aladin Lite v3 + SPHEREx SIA2 (IRSA) */
(() => {
  'use strict';
  const $ = (selector) => document.querySelector(selector);
  const API_BASE = String(window.CEM_SPHEREX_API_BASE || '').replace(/\/+$/, '');
  let aladin = null;
  let aladinPromise = null;
  let aladinNode = null;
  let wiredNode = null;

  const setStatus = (message, isError = false) => {
    const node = $('#cemLiveStatus');
    if (!node) return;
    node.textContent = message;
    node.classList.toggle('error', Boolean(isError));
  };

  const apiUrl = (path) => `${API_BASE}${path}`;

  async function initAladin() {
    const currentNode = $('#cemAladin');
    if (!currentNode) throw new Error('The map container is not available yet.');
    if (aladin && aladinNode === currentNode) return aladin;
    if (aladinPromise && aladinNode === currentNode) return aladinPromise;
    if (aladin && aladinNode !== currentNode) {
      try { aladin.remove(); } catch (_) {}
      aladin = null;
      aladinPromise = null;
    }
    aladinNode = currentNode;
    aladinPromise = (async () => {
      const start = Date.now();
      while (!(window.A && window.A.init) && Date.now() - start < 20000) {
        await new Promise((resolve) => setTimeout(resolve, 120));
      }
      if (!window.A || !window.A.init) {
        throw new Error('Aladin Lite could not be loaded. Check your Internet connection and open SPHEREx Data again.');
      }
      await window.A.init;
      const ra = Number($('#cemRa')?.value ?? 133.795);
      const dec = Number($('#cemDec')?.value ?? -7.245);
      aladin = window.A.aladin('#cemAladin', {
        target: `${ra} ${dec}`,
        fov: 8,
        cooFrame: 'ICRS',
        projection: 'AIT',
        survey: 'https://irsa.ipac.caltech.edu/data/hips/CDS/DSS2/color',
        showCooGrid: true,
        showCooGridControl: true,
        showReticle: true,
        showLayersControl: true,
        showFullscreenControl: true,
        showProjectionControl: true,
        showSimbadPointerControl: true,
        mode: document.documentElement.dataset.theme === 'light' ? 'light' : 'dark'
      });
      return aladin;
    })();
    try { return await aladinPromise; }
    catch (error) { aladinPromise = null; aladinNode = null; throw error; }
  }

  function setCoords(ra, dec, moveMap = true) {
    const raInput = $('#cemRa');
    const decInput = $('#cemDec');
    if (raInput) raInput.value = Number(ra).toFixed(6);
    if (decInput) decInput.value = Number(dec).toFixed(6);
    if (moveMap && aladin) aladin.gotoRaDec(Number(ra), Number(dec));
  }

  function wireControls() {
    const mapNode = $('#cemAladin');
    if (!mapNode || wiredNode === mapNode) return;
    wiredNode = mapNode;
    const body = $('#cemBody');
    const center = $('#cemCenter');
    const search = $('#cemSearch');
    if (!body || !center || !search) return;
    body.addEventListener('change', async () => {
      // Coordinates are stored in attributes of the selected option.
      const option = body.selectedOptions[0];
      const ra = Number(option.dataset.ra);
      const dec = Number(option.dataset.dec);
      if (Number.isFinite(ra) && Number.isFinite(dec)) {
        setCoords(ra, dec, false);
        try {
          const map = await initAladin();
          map.gotoRaDec(ra, dec);
          map.setFoV(8);
          setStatus(`Map centered on ${option.textContent}. You can now query its SPHEREx observations.`);
        } catch (error) { setStatus(error.message, true); }
      }
    });

    center.addEventListener('click', async () => {
      try {
        const map = await initAladin();
        const coords = map.getRaDec();
        if (!coords || coords.length < 2) throw new Error('Aladin did not return valid coordinates.');
        setCoords(coords[0], coords[1], false);
        setStatus(`Map center: RA ${Number(coords[0]).toFixed(5)}° · Dec ${Number(coords[1]).toFixed(5)}°.`);
      } catch (error) { setStatus(error.message, true); }
    });

    search.addEventListener('click', runSearch);
    ['cemRa', 'cemDec'].forEach((id) => {
      const input = $(`#${id}`);
      input?.addEventListener('change', async () => {
        const ra = Number($('#cemRa').value);
        const dec = Number($('#cemDec').value);
        if (!validCoordinates(ra, dec)) return;
        try { (await initAladin()).gotoRaDec(ra, dec); }
        catch (error) { setStatus(error.message, true); }
      });
    });
  }

  function validCoordinates(ra, dec) {
    if (!Number.isFinite(ra) || ra < 0 || ra >= 360 || !Number.isFinite(dec) || dec < -90 || dec > 90) {
      setStatus('Invalid coordinates. RA must be between 0° and 360°; Dec between −90° and +90°.', true);
      return false;
    }
    return true;
  }

  async function runSearch() {
    const button = $('#cemSearch');
    const results = $('#cemLiveResults');
    const ra = Number($('#cemRa').value);
    const dec = Number($('#cemDec').value);
    const radius = Number($('#cemRadius').value);
    const collection = $('#cemCollection').value;
    if (!validCoordinates(ra, dec)) return;
    if (!Number.isFinite(radius) || radius <= 0 || radius > 5) {
      setStatus('The radius must be greater than 0° and no larger than 5°.', true);
      return;
    }
    if (!API_BASE && location.hostname.endsWith('github.io')) {
      setStatus('The backend URL is not configured. Open config.js and set CEM_SPHEREX_API_BASE to the public API address.', true);
      return;
    }
    button.disabled = true;
    results.replaceChildren();
    setStatus('Querying SPHEREx collections at NASA/IPAC-IRSA…');
    try {
      await initAladin();
      const params = new URLSearchParams({ ra: String(ra), dec: String(dec), radius: String(radius), collection });
      const response = await fetch(apiUrl(`/api/search?${params.toString()}`), { headers: { Accept: 'application/json' } });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || `The API responded with status ${response.status}.`);
      const observations = Array.isArray(payload.observations) ? payload.observations : [];
      if (!observations.length) {
        const irsaNote = payload.warnings?.some((w) => /IRSA|502|503|504/i.test(w))
          ? ' IRSA may be temporarily down — wait and search again.'
          : '';
        const warn = payload.warnings?.length ? ` (${payload.warnings[0]})` : '';
        setStatus(`No observations for this region. Try a larger radius (e.g. 0.25°).${irsaNote}${warn}`, true);
        results.textContent = 'No observations were found for the selected criteria.';
        return;
      }
      setStatus(`${payload.count ?? observations.length} SPHEREx observation(s) found. Select one to load its FITS image.`);
      if (payload.warnings?.length) {
        const warning = document.createElement('p');
        warning.className = 'cem-live-foot';
        warning.textContent = `Notice: ${payload.warnings.join(' · ')}`;
        results.appendChild(warning);
      }
      observations.forEach((observation, index) => {
        const item = document.createElement('button');
        item.type = 'button';
        const metadata = [
          observation.obs_id || `Observation ${index + 1}`,
          observation.collection,
          observation.ra != null ? `RA ${Number(observation.ra).toFixed(4)}°` : '',
          observation.dec != null ? `Dec ${Number(observation.dec).toFixed(4)}°` : '',
          observation.band ? `Band ${observation.band}` : '',
          observation.date ? `t_min ${observation.date}` : ''
        ].filter(Boolean);
        item.textContent = metadata.join(' · ');
        item.addEventListener('click', () => loadObservation(observation, ra, dec, radius, item));
        results.appendChild(item);
      });
    } catch (error) {
      console.error('SPHEREx search error:', error);
      setStatus(`${error.message} ${error.message.includes('IRSA') ? 'Try again later.' : 'Check that the local backend is running.'}`, true);
    } finally {
      button.disabled = false;
    }
  }

  async function loadObservation(observation, ra, dec, radius, button) {
    const results = $('#cemLiveResults');
    results.querySelectorAll('button').forEach((node) => { node.disabled = true; });
    setStatus('Requesting a FITS cutout from IRSA and preparing the image layer…');
    try {
      const map = await initAladin();
      const preview = new URL(observation.preview_url, API_BASE || location.origin);
      preview.searchParams.set('ra', String(ra));
      preview.searchParams.set('dec', String(dec));
      preview.searchParams.set('size', String(Math.min(radius * 2, 0.5)));
      map.displayFITS(
        preview.href,
        { colormap: 'inferno', label: `SPHEREx ${observation.collection || ''}` },
        (centerRa, centerDec, fov) => {
          map.gotoRaDec(centerRa, centerDec);
          map.setFoV(fov);
          setStatus(`SPHEREx image loaded from ${observation.collection}. The layer is overlaid on the Aladin context map.`);
        },
        (error) => {
          console.error('FITS display error:', error);
          setStatus('Aladin could not prepare this FITS file. Try another observation or a different region.', true);
        }
      );
    } catch (error) {
      console.error('FITS preview error:', error);
      setStatus(`Could not load the observation: ${error.message}`, true);
    } finally {
      results.querySelectorAll('button').forEach((node) => { node.disabled = false; });
      if (button) button.focus();
    }
  }

  function activateViewer() {
    const mapNode = $('#cemAladin');
    if (!mapNode) { wiredNode = null; return; }
    wireControls();
    initAladin()
      .then(() => setStatus('Aladin Lite is ready. Select a region and query SPHEREx observations.'))
      .catch((error) => setStatus(error.message, true));
  }

  document.addEventListener('cem:live-viewer-ready', activateViewer);
  // Covers the case where the app opened directly on the Interactive map tab.
  if ($('#cemAladin')) activateViewer();

  // Time comparison: blink, slider, and difference over the aligned SPHEREx sequence.
  const TRACK_OBJECTS = {
    "WISE 0855": [133.795, -7.245],
    "Barnard’s Star": [269.452, 4.693],
    "ε Indi B": [330.84, -56.79],
    "RW Aur": [76.96, 30.4],
    "R Dra": [248.18, 66.76]
  };
  let trackState = {frames: [], detector: 'all', mode: 'blink', a: 0, b: 1, current: 0, timer: null, images: [], trackId: null, diffKey: null, diffImage: null, blinkFlip: false};
  const trackNode = (id) => document.getElementById(id);
  const trackStatus = (message, error = false) => {
    const node = trackNode('cemTrackStatus');
    if (!node) return;
    node.textContent = message;
    node.classList.toggle('error', !!error);
  };
  const visibleTrackFrames = () => trackState.frames.filter(frame => trackState.detector === 'all' || frame.detector === trackState.detector);
  function drawTrackCanvas(frameIndex) {
    const frames = visibleTrackFrames();
    const canvas = trackNode('cemTrackCanvas');
    if (!canvas || !frames.length) return;
    const blinkIndex = trackState.blinkFlip ? trackState.b : trackState.a;
    const effectiveIndex = trackState.mode === 'blink' ? blinkIndex : frameIndex;
    const frame = frames[Math.max(0, Math.min(effectiveIndex, frames.length - 1))];
    const image = trackState.images[trackState.frames.indexOf(frame)];
    if (!image || !image.complete || !image.naturalWidth) return;
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = '#02040a'; ctx.fillRect(0, 0, canvas.width, canvas.height);
    const mode = trackState.mode;
    if (mode === 'difference') {
      const a = visibleTrackFrames()[trackState.a], b = visibleTrackFrames()[trackState.b];
      trackNode('cemTrackCaption').textContent = `Linear subtraction B − A · ${a?.date || 'A'} (${a?.detector || ''}) vs ${b?.date || 'B'}`;
      if (a && b && a.index !== b.index && a.detector === b.detector && trackState.trackId) {
        const key = `${trackState.trackId}:${a.index}:${b.index}`;
        if (trackState.diffKey !== key) {
          trackState.diffKey = key; trackState.diffImage = null;
          const diff = new Image();
          diff.onload = () => { if (trackState.diffKey === key) { trackState.diffImage = diff; drawTrackCanvas(trackState.current); } };
          diff.onerror = () => trackStatus('Could not generate the linear subtraction of these images.', true);
          diff.src = apiUrl(`/api/tracks/${trackState.trackId}/difference.png?a=${a.index}&b=${b.index}`);
        }
        if (trackState.diffImage?.complete) ctx.drawImage(trackState.diffImage, 0, 0, canvas.width, canvas.height);
      } else {
        trackStatus('Select two different dates from the same detector to compute the subtraction.');
      }
    } else if (mode === 'slider') {
      const framesNow = visibleTrackFrames(), a = framesNow[trackState.a], b = framesNow[trackState.b];
      const ia = trackState.images[trackState.frames.indexOf(a)], ib = trackState.images[trackState.frames.indexOf(b)];
      const blend = Number(trackNode('cemTrackBlend')?.value || 50) / 100;
      if (ia?.complete && ib?.complete) {
        ctx.globalAlpha = 1; ctx.drawImage(ia, 0, 0, canvas.width, canvas.height);
        ctx.save(); ctx.beginPath(); ctx.rect(0, 0, canvas.width * blend, canvas.height); ctx.clip();
        ctx.drawImage(ib, 0, 0, canvas.width, canvas.height); ctx.restore();
        ctx.strokeStyle = '#2dd4bf'; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(canvas.width * blend, 0); ctx.lineTo(canvas.width * blend, canvas.height); ctx.stroke();
      }
      trackNode('cemTrackCaption').textContent = `Slider · A ${a?.date || ''} ↔ B ${b?.date || ''}`;
    } else {
      ctx.drawImage(image, 0, 0, canvas.width, canvas.height);
      trackNode('cemTrackCaption').textContent = mode === 'blink' ? `Blink · ${trackState.blinkFlip ? 'B' : 'A'} · ${frame.date} · ${frame.detector}` : `${frame.date} · ${frame.detector} · ${frame.collection}`;
    }
    const slider = trackNode('cemTrackFrame');
    if (slider && mode === 'blink') slider.value = String(frameIndex);
  }
  function updateTrackControls() {
    const frames = visibleTrackFrames();
    const frameSlider = trackNode('cemTrackFrame');
    const detector = trackNode('cemTrackDetector');
    const aSelect = trackNode('cemTrackA'), bSelect = trackNode('cemTrackB');
    if (!frames.length) return;
    frameSlider.disabled = false; frameSlider.max = String(frames.length - 1); frameSlider.value = String(Math.min(trackState.current, frames.length - 1));
    const options = frames.map((f, i) => `<option value="${i}">${f.date} · ${f.detector}</option>`).join('');
    aSelect.innerHTML = options; bSelect.innerHTML = options;
    trackState.a = Math.min(trackState.a, frames.length - 1);
    trackState.b = Math.min(Math.max(trackState.a + 1, trackState.b), frames.length - 1);
    aSelect.value = String(trackState.a); bSelect.value = String(trackState.b);
    aSelect.disabled = bSelect.disabled = frames.length < 2;
    const detectors = [...new Set(trackState.frames.map(f => f.detector))];
    if (!detectors.includes(trackState.detector)) trackState.detector = detectors[0];
    detector.innerHTML = detectors.map(d => `<option value="${d}">${d}</option>`).join('');
    detector.disabled = false; detector.value = trackState.detector;
    ['cemTrackPrev','cemTrackPlay','cemTrackNext'].forEach(id => { const n = trackNode(id); if (n) n.disabled = frames.length < 2; });
    trackNode('cemTrackFrames').innerHTML = frames.map((f, i) => `<button type="button" data-frame="${i}" class="${i === trackState.current ? 'on' : ''}"><img loading="lazy" src="${apiUrl(f.image_url)}" alt="SPHEREx image ${f.date}"><b>${f.date}</b><small>${f.detector} · ${f.quality} · ${f.collection}</small></button>`).join('');
    trackNode('cemTrackTable').innerHTML = '<thead><tr><th>Date</th><th>Detector</th><th>Collection</th><th>Quality</th><th>Coverage</th></tr></thead><tbody>' + frames.map(f => `<tr><td>${f.date}</td><td>${f.detector}</td><td>${f.collection}</td><td>${f.quality}</td><td>${Math.round(f.coverage * 100)}%</td></tr>`).join('') + '</tbody>';
    drawTrackCanvas(trackState.current);
    trackNode('cemTrackAnalysis').textContent = `${frames.length} images available for detector ${trackState.detector}. Select two dates to compare. Quality and coverage are shown in the table.`;
  }
  async function applyTrackPayload(payload) {
    trackState.frames = payload.frames; trackState.images = new Array(payload.frames.length); trackState.trackId = payload.track_id; trackState.diffKey = null; trackState.diffImage = null;
    await Promise.all(payload.frames.map((frame, index) => new Promise(resolve => {
      const img = new Image(); img.onload = () => resolve(); img.onerror = () => resolve();
      img.src = apiUrl(frame.image_url); trackState.images[index] = img;
    })));
    trackState.detector = [...new Set(payload.frames.map(f => f.detector))][0] || 'all';
    trackState.mode = 'blink'; trackState.blinkFlip = false; trackState.current = 0; trackState.a = 0; trackState.b = Math.min(1, payload.frames.length - 1);
    const modes = trackNode('cemTrackModes');
    if (modes) modes.querySelectorAll('button').forEach(b => b.classList.toggle('on', b.dataset.mode === 'blink'));
    const blendLabel = trackNode('cemTrackBlendLabel');
    if (blendLabel) blendLabel.classList.add('hide');
    updateTrackControls();
  }
  function clearTrackSequence() {
    clearInterval(trackState.timer); trackState.timer = null;
    trackState.frames = []; trackState.images = []; trackState.trackId = null; trackState.diffKey = null; trackState.diffImage = null;
    const canvas = trackNode('cemTrackCanvas');
    if (canvas) { const ctx = canvas.getContext('2d'); ctx.clearRect(0, 0, canvas.width, canvas.height); }
    const frames = trackNode('cemTrackFrames'); if (frames) frames.innerHTML = '';
    const table = trackNode('cemTrackTable'); if (table) table.innerHTML = '<tbody><tr><td>No observations loaded.</td></tr></tbody>';
    const caption = trackNode('cemTrackCaption'); if (caption) caption.textContent = 'The first processed image will appear here.';
    ['cemTrackFrame','cemTrackPrev','cemTrackPlay','cemTrackNext','cemTrackDetector','cemTrackA','cemTrackB'].forEach(id => { const node = trackNode(id); if (node) node.disabled = true; });
  }
  async function fetchPreload(ra, dec) {
    const response = await fetch(apiUrl(`/api/track/preload?${new URLSearchParams({ra, dec})}`));
    if (response.status === 404) return null;
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || `The API responded ${response.status}.`);
    return payload.frames?.length ? payload : null;
  }
  async function showPreloadedSequence() {
    const ra = Number(trackNode('cemTrackRa').value), dec = Number(trackNode('cemTrackDec').value);
    if (!Number.isFinite(ra) || !Number.isFinite(dec)) return;
    try {
      const preloaded = await fetchPreload(ra, dec);
      if (!preloaded) {
        clearTrackSequence();
        trackStatus('These coordinates are not preloaded. Press Search sequence to download SPHEREx images from NASA. That can take a couple of minutes.');
        return;
      }
      await applyTrackPayload(preloaded);
      trackStatus(`${preloaded.count} SPHEREx images for ${preloaded.name} are already on this computer. The sequence is ready.`);
    } catch (error) {
      console.error('SPHEREx preload error:', error);
      trackStatus(error.message, true);
    }
  }
  async function loadTrackSequence() {
    const button = trackNode('cemTrackSearch');
    const ra = Number(trackNode('cemTrackRa').value), dec = Number(trackNode('cemTrackDec').value);
    const radius = Number(trackNode('cemTrackRadius').value), maxFrames = Number(trackNode('cemTrackMax').value);
    if (!validCoordinates(ra, dec)) return;
    if (!Number.isFinite(radius) || radius < .01 || radius > .5) { trackStatus('The radius must be between 0.01° and 0.5°.', true); return; }
    clearInterval(trackState.timer); trackState.timer = null; button.disabled = true;
    try {
      const preloaded = await fetchPreload(ra, dec);
      if (preloaded) {
        await applyTrackPayload(preloaded);
        trackStatus(`${preloaded.count} SPHEREx images for ${preloaded.name} are already on this computer. The sequence is ready.`);
        return;
      }
      trackStatus('Searching SPHEREx observations and downloading FITS cutouts to build the sequence…');
      const params = new URLSearchParams({ra, dec, radius, max_frames: maxFrames, collection: 'current'});
      const response = await fetch(apiUrl(`/api/track?${params}`));
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || `The API responded ${response.status}.`);
      if (!payload.frames?.length) {
        trackState.frames = [];
        const irsaNote = payload.warnings?.some(w => /IRSA|502|503|504/i.test(w))
          ? ' IRSA may be temporarily unavailable — wait a moment and search again.'
          : '';
        const warn = payload.warnings?.length ? ` (${payload.warnings[0]})` : '';
        trackStatus(`No SPHEREx images for these coordinates. Try a larger radius or another object.${irsaNote}${warn}`, true);
        return;
      }
      await applyTrackPayload(payload);
      const warningText = payload.warnings?.length ? ` Notices: ${payload.warnings.slice(0, 2).join(' · ')}` : '';
      trackStatus(`${payload.count} images processed and aligned. Sequence ready to analyze.${warningText}`);
    } catch (error) { console.error('SPHEREx tracking error:', error); trackStatus(`${error.message} ${String(error.message).includes('IRSA') ? 'Try again later.' : 'Check that the local backend is running.'}`, true); }
    finally { button.disabled = false; }
  }
  function activateComparison() {
    const objectSelect = trackNode('cemTrackObject');
    if (!objectSelect || objectSelect.dataset.wired) return;
    objectSelect.dataset.wired = '1';
    const syncObject = () => {
      const key = objectSelect.value, coords = TRACK_OBJECTS[key];
      if (coords) { trackNode('cemTrackRa').value = coords[0]; trackNode('cemTrackDec').value = coords[1]; }
    };
    objectSelect.addEventListener('change', () => { syncObject(); showPreloadedSequence(); });
    syncObject();
    showPreloadedSequence();
    trackNode('cemTrackSearch').addEventListener('click', loadTrackSequence);
    trackNode('cemTrackDetector').addEventListener('change', e => { trackState.detector = e.target.value; trackState.current = 0; trackState.a = 0; trackState.b = Math.min(1, visibleTrackFrames().length - 1); updateTrackControls(); });
    trackNode('cemTrackFrame').addEventListener('input', e => { trackState.current = Number(e.target.value); if (trackState.mode === 'blink') { trackState.a = trackState.current; trackState.b = Math.min(trackState.current + 1, visibleTrackFrames().length - 1); trackState.blinkFlip = false; trackNode('cemTrackA').value = String(trackState.a); trackNode('cemTrackB').value = String(trackState.b); } drawTrackCanvas(trackState.current); trackNode('cemTrackFrames').querySelectorAll('button').forEach(b => b.classList.toggle('on', Number(b.dataset.frame) === trackState.current)); });
    trackNode('cemTrackFrames').addEventListener('click', e => { const button = e.target.closest('button[data-frame]'); if (!button) return; trackState.current = Number(button.dataset.frame); if (trackState.mode === 'blink') { trackState.a = trackState.current; trackState.b = Math.min(trackState.current + 1, visibleTrackFrames().length - 1); trackState.blinkFlip = false; trackNode('cemTrackA').value = String(trackState.a); trackNode('cemTrackB').value = String(trackState.b); } trackNode('cemTrackFrame').value = String(trackState.current); drawTrackCanvas(trackState.current); trackNode('cemTrackFrames').querySelectorAll('button').forEach(b => b.classList.toggle('on', b === button)); });
    trackNode('cemTrackA').addEventListener('change', e => { trackState.a = Number(e.target.value); if (trackState.a === trackState.b && visibleTrackFrames().length > 1) trackState.b = (trackState.a + 1) % visibleTrackFrames().length; trackNode('cemTrackB').value = String(trackState.b); trackState.diffKey = null; drawTrackCanvas(trackState.current); });
    trackNode('cemTrackB').addEventListener('change', e => { trackState.b = Number(e.target.value); if (trackState.a === trackState.b && visibleTrackFrames().length > 1) trackState.a = (trackState.b + visibleTrackFrames().length - 1) % visibleTrackFrames().length; trackNode('cemTrackA').value = String(trackState.a); trackState.diffKey = null; drawTrackCanvas(trackState.current); });
    trackNode('cemTrackBlend').addEventListener('input', () => drawTrackCanvas(trackState.current));
    trackNode('cemTrackModes').addEventListener('click', e => { const button = e.target.closest('button[data-mode]'); if (!button) return; trackState.mode = button.dataset.mode; trackState.blinkFlip = false; trackNode('cemTrackModes').querySelectorAll('button').forEach(b => b.classList.toggle('on', b === button)); trackNode('cemTrackBlendLabel').classList.toggle('hide', trackState.mode !== 'slider'); trackNode('cemTrackModeHelp').textContent = trackState.mode === 'blink' ? 'Switch between the selected images to spot changes.' : trackState.mode === 'slider' ? 'Move the control to reveal one date over the other.' : 'Absolute subtraction highlights pixels that changed between the two dates.'; drawTrackCanvas(trackState.current); });
    trackNode('cemTrackPrev').addEventListener('click', () => { trackState.current = Math.max(0, trackState.current - 1); trackNode('cemTrackFrame').value = String(trackState.current); drawTrackCanvas(trackState.current); });
    trackNode('cemTrackNext').addEventListener('click', () => { const n = visibleTrackFrames().length; trackState.current = Math.min(n - 1, trackState.current + 1); trackNode('cemTrackFrame').value = String(trackState.current); drawTrackCanvas(trackState.current); });
    trackNode('cemTrackPlay').addEventListener('click', () => { if (trackState.timer) { clearInterval(trackState.timer); trackState.timer = null; trackNode('cemTrackPlay').textContent = 'Play'; return; } trackNode('cemTrackPlay').textContent = 'Pause'; trackState.timer = setInterval(() => { const n = visibleTrackFrames().length; if (trackState.mode === 'blink') { trackState.blinkFlip = !trackState.blinkFlip; } else { trackState.current = (trackState.current + 1) % n; trackNode('cemTrackFrame').value = String(trackState.current); } drawTrackCanvas(trackState.current); }, 700); });
    syncObject();
  }
  document.addEventListener('cem:comparison-ready', activateComparison);
  if (trackNode('cemTrackObject')) activateComparison();

})();
