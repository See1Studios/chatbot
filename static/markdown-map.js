/* Leaflet-based in-app dynamic map renderer for markdown ```map blocks (CHAT_MAP_v1). */
let leafletLoadingPromise = null;

function ensureLeafletLoaded() {
  if (typeof window !== 'undefined' && window.L) return Promise.resolve(window.L);
  if (leafletLoadingPromise) return leafletLoadingPromise;
  leafletLoadingPromise = new Promise((resolve, reject) => {
    if (typeof document === 'undefined') return reject(new Error('no document'));
    if (!document.querySelector('link[data-leaflet]')) {
      const link = document.createElement('link');
      link.rel = 'stylesheet';
      link.dataset.leaflet = '1';
      link.href = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css';
      link.integrity = 'sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=';
      link.crossOrigin = 'anonymous';
      document.head.appendChild(link);
    }
    const script = document.createElement('script');
    script.src = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js';
    script.integrity = 'sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=';
    script.crossOrigin = 'anonymous';
    let timer = null;
    const cleanup = () => {
      if (timer) {
        clearTimeout(timer);
        timer = null;
      }
    };
    timer = setTimeout(() => {
      cleanup();
      reject(new Error('Leaflet load timeout'));
    }, 10000);
    script.onload = () => {
      cleanup();
      if (typeof window !== 'undefined' && window.L) resolve(window.L);
      else reject(new Error('Leaflet missing'));
    };
    script.onerror = (err) => {
      cleanup();
      reject(err || new Error('Leaflet script error'));
    };
    document.head.appendChild(script);
  }).catch((err) => {
    leafletLoadingPromise = null;
    throw err;
  });
  return leafletLoadingPromise;
}

function parseMapConfig(text) {
  let lat, lon, zoom = 13, marker = '';
  const markers = [];
  const s = String(text || '').trim();
  if (!s) return null;

  if (s.startsWith('{') && s.endsWith('}')) {
    try {
      const o = JSON.parse(s);
      lat = parseFloat(o.lat ?? o.latitude);
      lon = parseFloat(o.lon ?? o.lng ?? o.longitude);
      if (o.zoom != null) zoom = parseInt(o.zoom, 10);
      marker = String(o.marker ?? o.text ?? o.label ?? o.title ?? '').trim();
      if (Array.isArray(o.markers)) {
        for (const mk of o.markers) {
          const mLat = parseFloat(mk.lat ?? mk.latitude);
          const mLon = parseFloat(mk.lon ?? mk.lng ?? mk.longitude);
          if (!isNaN(mLat) && !isNaN(mLon) && mLat >= -90 && mLat <= 90 && mLon >= -180 && mLon <= 180) {
            markers.push({ lat: mLat, lon: mLon, label: String(mk.label ?? mk.marker ?? mk.text ?? mk.title ?? '').trim() });
          }
        }
      }
    } catch (_) {}
  }

  if (isNaN(lat) || isNaN(lon)) {
    const lines = s.split(/\r?\n/);
    for (const ln of lines) {
      const m = ln.match(/^\s*([a-zA-Z_-]+)\s*[:=]\s*(.+)$/);
      if (!m) continue;
      const k = m[1].toLowerCase();
      const v = m[2].trim().replace(/^["']|["']$/g, '');
      if (k === 'lat' || k === 'latitude') lat = parseFloat(v);
      else if (k === 'lon' || k === 'lng' || k === 'longitude') lon = parseFloat(v);
      else if (k === 'zoom') zoom = parseInt(v, 10);
      else if (/^(markers?|text|label|title)$/.test(k)) {
        const pipeIdx = v.indexOf('|');
        if (pipeIdx !== -1) {
          const coords = v.substring(0, pipeIdx).trim();
          const lbl = v.substring(pipeIdx + 1).trim();
          const parts = coords.split(/\s*,\s*/);
          if (parts.length === 2) {
            const mLat = parseFloat(parts[0]);
            const mLon = parseFloat(parts[1]);
            if (!isNaN(mLat) && !isNaN(mLon) && mLat >= -90 && mLat <= 90 && mLon >= -180 && mLon <= 180) {
              markers.push({ lat: mLat, lon: mLon, label: lbl });
            }
          } else {
            marker = v;
          }
        } else {
          const parts = v.split(/\s*,\s*/);
          if (parts.length === 2 && !isNaN(parseFloat(parts[0])) && !isNaN(parseFloat(parts[1]))) {
            const mLat = parseFloat(parts[0]);
            const mLon = parseFloat(parts[1]);
            if (mLat >= -90 && mLat <= 90 && mLon >= -180 && mLon <= 180) {
              markers.push({ lat: mLat, lon: mLon, label: '' });
            }
          } else {
            marker = v;
          }
        }
      }
    }
  }

  if (markers.length > 0) {
    if (isNaN(lat) || isNaN(lon)) {
      lat = markers[0].lat;
      lon = markers[0].lon;
    }
    if (!marker && markers.length === 1 && markers[0].label) {
      marker = markers[0].label;
    }
  }

  if (isNaN(lat) || isNaN(lon) || lat < -90 || lat > 90 || lon < -180 || lon > 180) {
    return null;
  }
  return {
    lat,
    lon,
    zoom: (isNaN(zoom) || zoom < 1 || zoom > 20) ? 13 : zoom,
    marker,
    markers
  };
}

function decodeMapEntities(s) {
  return String(s || '')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&amp;/g, '&');
}

function escapeMapHtml(s) {
  return String(s || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function renderMapBlock(code) {
  const decoded = decodeMapEntities(code);
  const cfg = parseMapConfig(decoded);
  if (!cfg) {
    return '<pre><code class="language-map">' + code + '</code></pre>';
  }
  let labelText = cfg.marker ? escapeMapHtml(cfg.marker) : '';
  if (!labelText && cfg.markers && cfg.markers.length > 1) {
    const labels = cfg.markers.map(mk => mk.label).filter(Boolean);
    if (labels.length > 0) {
      labelText = escapeMapHtml(labels.join(' \u00B7 '));
    }
  }
  const markerAttr = cfg.marker ? ' data-marker="' + escapeMapHtml(cfg.marker) + '"' : '';
  const labelHtml = labelText ? '<div class="chat-map-label">' + labelText + '</div>' : '';
  /* Multi-marker data stored in a hidden span that DOMPurify preserves (text content, no attrs needed). */
  const markersSpan = cfg.markers && cfg.markers.length > 0
    ? '<span class="chat-map-markers">' + escapeMapHtml(JSON.stringify(cfg.markers)) + '</span>'
    : '';
  return '<div class="chat-map-box" data-lat="' + cfg.lat + '" data-lon="' + cfg.lon + '" data-zoom="' + cfg.zoom + '"' + markerAttr + '>' +
    '<div class="chat-map-canvas"></div>' +
    markersSpan +
    labelHtml +
  '</div>';
}

function buildPopupContent(lat, lon, label) {
  if (typeof document === 'undefined') return null;
  const wrap = document.createElement('div');
  wrap.className = 'chat-map-popup';
  if (label) {
    const txt = document.createElement('div');
    txt.className = 'chat-map-popup-label';
    txt.textContent = label;
    wrap.appendChild(txt);
  }
  const link = document.createElement('a');
  link.className = 'chat-map-popup-btn';
  link.href = 'https://www.google.com/maps/search/?api=1&query=' + encodeURIComponent(lat + ',' + lon);
  link.target = '_blank';
  link.rel = 'noopener';
  link.textContent = 'Google \uC9C0\uB3C4';
  wrap.appendChild(link);
  return wrap;
}

function applyMapFallback(el) {
  if (!el || el.getAttribute('data-processed') === 'true') return;
  el.setAttribute('data-processed', 'true');
  if (el.classList && typeof el.classList.add === 'function') {
    el.classList.add('chat-map-fallback');
  } else if (typeof el.className === 'string') {
    el.className += ' chat-map-fallback';
  }
  const lat = el.getAttribute('data-lat') || '';
  const lon = el.getAttribute('data-lon') || '';
  const marker = el.getAttribute('data-marker') || '';

  el.textContent = '';
  if (typeof document !== 'undefined' && typeof document.createElement === 'function') {
    const fallbackDiv = document.createElement('div');
    fallbackDiv.className = 'chat-map-fallback-body';

    const icon = document.createElement('span');
    icon.className = 'chat-map-fallback-icon';
    icon.textContent = '📍 ';
    fallbackDiv.appendChild(icon);

    if (marker) {
      const markerEl = document.createElement('strong');
      markerEl.className = 'chat-map-fallback-marker';
      markerEl.textContent = marker;
      fallbackDiv.appendChild(markerEl);

      const coordsEl = document.createElement('span');
      coordsEl.className = 'chat-map-fallback-coords';
      coordsEl.textContent = ' (' + lat + ', ' + lon + ')';
      fallbackDiv.appendChild(coordsEl);
    } else {
      const coordsEl = document.createElement('span');
      coordsEl.className = 'chat-map-fallback-coords';
      coordsEl.textContent = lat + ', ' + lon;
      fallbackDiv.appendChild(coordsEl);
    }
    if (typeof el.appendChild === 'function') {
      el.appendChild(fallbackDiv);
    } else {
      el.textContent = marker ? (marker + ' (' + lat + ', ' + lon + ')') : (lat + ', ' + lon);
    }
  } else {
    el.textContent = marker ? (marker + ' (' + lat + ', ' + lon + ')') : (lat + ', ' + lon);
  }
}

function readMarkersFromEl(el) {
  const span = el.querySelector && el.querySelector('.chat-map-markers');
  if (!span) return [];
  try {
    const raw = span.textContent || '';
    const txt = raw.includes('&quot;') ? decodeMapEntities(raw) : raw;
    return JSON.parse(txt || '[]');
  } catch (_) { return []; }
}

/* Toggle fullscreen: enable/disable dragging and touch interactions so the
   default embedded state lets page scroll pass through (touch-action: pan-y)
   while fullscreen mode unlocks full map interaction. */
function toggleMapFullscreen(el, mapObj, fsBtn) {
  const entering = !el.classList.contains('chat-map-fullscreen');
  el.classList.toggle('chat-map-fullscreen');
  if (fsBtn) {
    fsBtn.textContent = entering ? '\u2715' : '\u26F6';
    if (typeof fsBtn.setAttribute === 'function') {
      fsBtn.setAttribute('aria-label', entering ? 'Close fullscreen map' : 'Open fullscreen map');
    }
    fsBtn.title = entering ? 'Close' : 'Fullscreen';
  }
  if (typeof document !== 'undefined') {
    if (entering) {
      if (!el._mapEscHandler && typeof document.addEventListener === 'function') {
        el._mapEscHandler = (e) => {
          if (typeof document !== 'undefined' && document.body && typeof document.body.contains === 'function' && !document.body.contains(el)) {
            if (typeof document.removeEventListener === 'function') {
              document.removeEventListener('keydown', el._mapEscHandler);
            }
            el._mapEscHandler = null;
            return;
          }
          if (e.key === 'Escape' && el.classList.contains('chat-map-fullscreen')) {
            toggleMapFullscreen(el, mapObj, fsBtn);
          }
        };
        document.addEventListener('keydown', el._mapEscHandler);
      }
    } else {
      if (el._mapEscHandler && typeof document.removeEventListener === 'function') {
        document.removeEventListener('keydown', el._mapEscHandler);
        el._mapEscHandler = null;
      }
    }
  }
  try {
    if (entering) {
      if (mapObj.dragging) mapObj.dragging.enable();
      if (mapObj.touchZoom) mapObj.touchZoom.enable();
      if (mapObj.doubleClickZoom) mapObj.doubleClickZoom.enable();
      if (mapObj.scrollWheelZoom) mapObj.scrollWheelZoom.enable();
    } else {
      if (mapObj.dragging) mapObj.dragging.disable();
      if (mapObj.touchZoom) mapObj.touchZoom.disable();
      if (mapObj.doubleClickZoom) mapObj.doubleClickZoom.disable();
      if (mapObj.scrollWheelZoom) mapObj.scrollWheelZoom.disable();
    }
    mapObj.invalidateSize();
  } catch (_) {}
}

async function renderMapsIn(container) {
  if (!container) return;
  const nodes = Array.from(container.querySelectorAll('.chat-map-box:not([data-processed="true"])'));
  if (!nodes.length) return;
  try {
    await ensureLeafletLoaded();
  } catch (_) {
    nodes.forEach(applyMapFallback);
    return;
  }
  if (typeof window === 'undefined' || !window.L) {
    nodes.forEach(applyMapFallback);
    return;
  }
  nodes.forEach(el => {
    if (el.getAttribute('data-processed') === 'true') return;
    const lat = parseFloat(el.getAttribute('data-lat'));
    const lon = parseFloat(el.getAttribute('data-lon'));
    if (isNaN(lat) || isNaN(lon)) {
      applyMapFallback(el);
      return;
    }
    const zoom = parseInt(el.getAttribute('data-zoom'), 10) || 13;
    const markerLabel = el.getAttribute('data-marker') || '';
    const extraMarkers = readMarkersFromEl(el);
    const canvas = el.querySelector('.chat-map-canvas') || el;

    let mapObj;
    try {
      mapObj = window.L.map(canvas, {
        zoomControl: true,
        attributionControl: true,
        scrollWheelZoom: false,
        dragging: false,
        touchZoom: false,
        doubleClickZoom: false
      });
      window.L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors'
      }).addTo(mapObj);

      if (extraMarkers.length > 1) {
        const allCoords = [];
        for (const mk of extraMarkers) {
          const mLat = parseFloat(mk.lat);
          const mLon = parseFloat(mk.lon);
          if (isNaN(mLat) || isNaN(mLon)) continue;
          allCoords.push([mLat, mLon]);
          const popup = buildPopupContent(mLat, mLon, mk.label || '');
          const m = window.L.marker([mLat, mLon]).addTo(mapObj);
          if (popup) m.bindPopup(popup);
        }
        if (allCoords.length > 1) {
          const bounds = window.L.latLngBounds(allCoords);
          mapObj.fitBounds(bounds, { padding: [30, 30] });
        } else if (allCoords.length === 1) {
          mapObj.setView(allCoords[0], zoom);
        }
      } else {
        const hasExtra = extraMarkers.length === 1 && !isNaN(parseFloat(extraMarkers[0].lat)) && !isNaN(parseFloat(extraMarkers[0].lon));
        const markerLat = hasExtra ? parseFloat(extraMarkers[0].lat) : lat;
        const markerLon = hasExtra ? parseFloat(extraMarkers[0].lon) : lon;
        const targetCenter = hasExtra ? [markerLat, markerLon] : [lat, lon];
        mapObj.setView(targetCenter, zoom);
        if (markerLabel || hasExtra) {
          const label = (hasExtra && extraMarkers[0].label) || markerLabel || '';
          const popup = buildPopupContent(markerLat, markerLon, label);
          const m = window.L.marker([markerLat, markerLon]).addTo(mapObj);
          if (popup) m.bindPopup(popup).openPopup();
        }
      }

      /* Fullscreen toggle button */
      if (typeof document !== 'undefined' && typeof document.createElement === 'function') {
        const fsBtn = document.createElement('button');
        fsBtn.className = 'chat-map-fs-btn';
        fsBtn.type = 'button';
        fsBtn.textContent = '\u26F6';
        fsBtn.title = 'Fullscreen';
        if (typeof fsBtn.setAttribute === 'function') {
          fsBtn.setAttribute('aria-label', 'Open fullscreen map');
        }
        fsBtn.addEventListener('click', () => {
          toggleMapFullscreen(el, mapObj, fsBtn);
        });
        el.appendChild(fsBtn);
      }

      setTimeout(() => {
        try { mapObj.invalidateSize(); } catch (_) {}
      }, 250);
      el.setAttribute('data-processed', 'true');
    } catch (_) {
      applyMapFallback(el);
    }
  });
}

if (typeof window !== 'undefined') {
  window.ensureLeafletLoaded = ensureLeafletLoaded;
  window.parseMapConfig = parseMapConfig;
  window.renderMapBlock = renderMapBlock;
  window.buildPopupContent = buildPopupContent;
  window.applyMapFallback = applyMapFallback;
  window.renderMapsIn = renderMapsIn;
  window.toggleMapFullscreen = toggleMapFullscreen;
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    ensureLeafletLoaded,
    parseMapConfig,
    renderMapBlock,
    buildPopupContent,
    applyMapFallback,
    renderMapsIn,
    toggleMapFullscreen,
  };
}
