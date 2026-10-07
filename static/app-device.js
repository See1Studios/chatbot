// app-device.js -- split out of app.js (APP_SPLIT_v1, docs/plans/archive/2026/monolith-split.md Phase 5). Declarations only: it
// loads before app.js, which runs everything that happens at load (listeners, timers, boot). Top-level code
// here may use the page's DOM, never a binding from a later file.
// ---- Browser & Device Context (GPS, timezone, device type) ----
const GEO_ENABLED_KEY = 'chatbot.geoEnabled';
let geoEnabled = localStorage.getItem(GEO_ENABLED_KEY) === 'true';
let cachedCoords = null;
let coordPromise = null;

// ---- Background return detection ----
let _lastHiddenAt = 0;
let _returnedFromBackground = false;
let _returnedAfterSec = 0;
try {
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') {
      _lastHiddenAt = Date.now();
      _returnedFromBackground = false;
    } else if (document.visibilityState === 'visible' && _lastHiddenAt) {
      _returnedAfterSec = Math.round((Date.now() - _lastHiddenAt) / 1000);
      _returnedFromBackground = true;
      _lastHiddenAt = 0;
    }
  });
  window.addEventListener('focus', () => {
    if (_lastHiddenAt && !_returnedFromBackground) {
      _returnedAfterSec = Math.round((Date.now() - _lastHiddenAt) / 1000);
      _returnedFromBackground = true;
      _lastHiddenAt = 0;
    }
  });
} catch(e) {}

function updateGeoButtonState() {
  if (!geoBtn) return;
  geoBtn.classList.toggle('active', geoEnabled);
  geoBtn.setAttribute('aria-pressed', String(geoEnabled));
  geoBtn.title = geoEnabled
    ? tr('composer.geo_active')
    : tr('composer.geo_toggle_on');
}

function fetchCoordinates() {
  if (!navigator.geolocation) return Promise.resolve(null);
  if (coordPromise) return coordPromise;
  coordPromise = new Promise(resolve => {
    navigator.geolocation.getCurrentPosition(
      pos => {
        cachedCoords = {
          lat: Number(pos.coords.latitude.toFixed(4)),
          lon: Number(pos.coords.longitude.toFixed(4)),
        };
        if (Number.isFinite(pos.coords.accuracy)) cachedCoords.accuracy = Math.round(pos.coords.accuracy);
        coordPromise = null;
        resolve(cachedCoords);
      },
      err => {
        cachedCoords = null;
        coordPromise = null;
        resolve(null);
      },
      { timeout: 5000, maximumAge: 60000 }
    );
  });
  return coordPromise;
}


async function getClientContext() {
  if (!geoEnabled) return null;
  if (!cachedCoords) {
    // In-flight fetch, or a retry after the page-load/toggle fetch failed.
    await Promise.race([
      fetchCoordinates(),
      new Promise(r => setTimeout(r, 1000))
    ]);
  }
  const isMobile = Boolean(/Mobi|Android|iPhone|iPad|iPod/i.test(navigator.userAgent));
  let timezone = '';
  try {
    timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || '';
  } catch(e) {}
  const ctx = {
    is_mobile: isMobile,
    device: isMobile ? 'mobile' : 'desktop',   // a code; the server writes the agent's note
  };
  if (timezone) ctx.timezone = timezone;
  if (cachedCoords) {
    ctx.lat = cachedCoords.lat;
    ctx.lon = cachedCoords.lon;
    if (Number.isFinite(cachedCoords.accuracy)) ctx.accuracy = cachedCoords.accuracy;
  }
  // Battery (navigator.getBattery is async; skip if unsupported)
  try {
    if (navigator.getBattery) {
      const batt = await navigator.getBattery();
      ctx.battery = Math.round(batt.level * 100);
      ctx.charging = batt.charging;
    }
  } catch(e) {}
  // Network info
  try {
    const conn = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
    if (conn && conn.type) {
      ctx.net_type = conn.type;
    } else {
      ctx.online = navigator.onLine;
    }
  } catch(e) {}
  // Background return detection
  try {
    if (_returnedFromBackground) {
      ctx.resumed = _returnedAfterSec > 0 ? _returnedAfterSec : true;
      _returnedFromBackground = false;
      _returnedAfterSec = 0;
    }
  } catch(e) {}
  // Visibility / focus (fallback when no return event fired)
  try {
    if (document.visibilityState && document.visibilityState !== 'visible') {
      ctx.visibility = document.visibilityState;
    }
    if (!document.hasFocus()) ctx.focused = false;
  } catch(e) {}
  return ctx;
}
