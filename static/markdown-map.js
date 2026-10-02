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
  const s = String(text || '').trim();
  if (!s) return null;

  if (s.startsWith('{') && s.endsWith('}')) {
    try {
      const o = JSON.parse(s);
      lat = parseFloat(o.lat ?? o.latitude);
      lon = parseFloat(o.lon ?? o.lng ?? o.longitude);
      if (o.zoom != null) zoom = parseInt(o.zoom, 10);
      marker = String(o.marker ?? o.text ?? o.label ?? o.title ?? '').trim();
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
      else if (/^(marker|text|label|title)$/.test(k)) marker = v;
    }
  }

  if (isNaN(lat) || isNaN(lon) || lat < -90 || lat > 90 || lon < -180 || lon > 180) {
    return null;
  }
  return {
    lat,
    lon,
    zoom: (isNaN(zoom) || zoom < 1 || zoom > 20) ? 13 : zoom,
    marker
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
  const m = cfg.marker ? escapeMapHtml(cfg.marker) : '';
  const markerAttr = m ? ' data-marker="' + m + '"' : '';
  const labelHtml = m ? '<div class="chat-map-label">' + m + '</div>' : '';
  return '<div class="chat-map-box" data-lat="' + cfg.lat + '" data-lon="' + cfg.lon + '" data-zoom="' + cfg.zoom + '"' + markerAttr + '>' +
    '<div class="chat-map-canvas"></div>' +
    labelHtml +
  '</div>';
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
    const marker = el.getAttribute('data-marker') || '';
    const canvas = el.querySelector('.chat-map-canvas') || el;
    try {
      const map = window.L.map(canvas, {
        zoomControl: true,
        attributionControl: true,
        scrollWheelZoom: false
      }).setView([lat, lon], zoom);
      window.L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors'
      }).addTo(map);
      if (marker) {
        const popup = document.createElement('div');
        popup.textContent = marker;
        window.L.marker([lat, lon]).addTo(map).bindPopup(popup).openPopup();
      }
      setTimeout(() => {
        try { map.invalidateSize(); } catch (_) {}
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
  window.applyMapFallback = applyMapFallback;
  window.renderMapsIn = renderMapsIn;
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    ensureLeafletLoaded,
    parseMapConfig,
    renderMapBlock,
    applyMapFallback,
    renderMapsIn,
  };
}
