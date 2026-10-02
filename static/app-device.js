// app-device.js -- split out of app.js (APP_SPLIT_v1, docs/plans/monolith-split.md Phase 5). Declarations only: it
// loads before app.js, which runs everything that happens at load (listeners, timers, boot). Top-level code
// here may use the page's DOM, never a binding from a later file.
// ---- Browser & Device Context (GPS, timezone, device type) ----
const GEO_ENABLED_KEY = 'chatbot.geoEnabled';
let geoEnabled = localStorage.getItem(GEO_ENABLED_KEY) === 'true';
let cachedCoords = null;
let coordPromise = null;

function updateGeoButtonState() {
  if (!geoBtn) return;
  geoBtn.classList.toggle('active', geoEnabled);
  geoBtn.setAttribute('aria-pressed', String(geoEnabled));
  geoBtn.title = geoEnabled
    ? '기기 환경 및 위치 정보 동기화 활성 중 (클릭하여 끄기)'
    : '기기 환경 및 위치 정보 동기화 (클릭하여 켜기)';
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
    device: isMobile ? '모바일' : '데스크톱',
  };
  if (timezone) ctx.timezone = timezone;
  if (cachedCoords) {
    ctx.lat = cachedCoords.lat;
    ctx.lon = cachedCoords.lon;
  }
  return ctx;
}
