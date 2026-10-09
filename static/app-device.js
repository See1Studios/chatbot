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

// ---- Web Push Notification Helpers ----
function _pushBasePath() {
  if (typeof BASE_PATH === 'string') return BASE_PATH;
  const p = (typeof window !== 'undefined' && window.location && window.location.pathname) || '';
  const dir = p.replace(/\/[^\/]*\.[^\/]+$/, '');
  return dir.replace(/\/+$/, '') || '';
}

function _urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
  const rawData = window.atob(base64);
  const outputArray = new Uint8Array(rawData.length);
  for (let i = 0; i < rawData.length; ++i) {
    outputArray[i] = rawData.charCodeAt(i);
  }
  return outputArray;
}

async function requestPushSubscription() {
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
    const msg = typeof tr === 'function' ? tr('shelltext.notifications_unsupported') : 'Web Push unsupported';
    if (typeof alertModal === 'function') await alertModal(msg);
    else alert(msg);
    return false;
  }
  try {
    const permission = await Notification.requestPermission();
    if (permission !== 'granted') {
      const msg = permission === 'denied'
        ? (typeof tr === 'function' ? tr('shelltext.notifications_blocked') : 'Notification permission blocked')
        : (typeof tr === 'function' ? tr('shelltext.notifications_denied') : 'Notification permission denied');
      if (typeof alertModal === 'function') await alertModal(msg);
      else alert(msg);
      return false;
    }
    const base = _pushBasePath();
    let reg = await navigator.serviceWorker.getRegistration();
    if (!reg) {
      reg = await navigator.serviceWorker.register(base + '/sw.js', { scope: base + '/' });
    }
    if (!reg.active) {
      reg = await Promise.race([
        navigator.serviceWorker.ready,
        new Promise((_, r) => setTimeout(() => r(new Error('timeout')), 4000))
      ]).catch(() => reg);
    }
    let sub = await reg.pushManager.getSubscription();
    if (!sub) {
      const res = await fetch(base + '/api/push/vapid-public-key');
      const data = await res.json();
      if (!data.ok || !data.publicKey) throw new Error('VAPID public key fetch failed');
      sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: _urlBase64ToUint8Array(data.publicKey),
      });
    }
    const subJson = sub.toJSON();
    await fetch(base + '/api/push/subscribe', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ subscription: subJson }),
    });
    return true;
  } catch (err) {
    console.warn('Push subscription failed:', err);
    const prefix = typeof tr === 'function' ? tr('shelltext.notifications_failed') : 'Push registration failed: ';
    const msg = prefix + (err.message || err);
    if (typeof alertModal === 'function') await alertModal(msg);
    else alert(msg);
    return false;
  }
}

async function checkAndSyncPushSubscription() {
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) return;
  if (typeof Notification === 'undefined' || Notification.permission !== 'granted') return;
  try {
    const reg = await navigator.serviceWorker.ready;
    const sub = await reg.pushManager.getSubscription();
    if (sub) {
      const base = _pushBasePath();
      await fetch(base + '/api/push/subscribe', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ subscription: sub.toJSON() }),
      });
    }
  } catch (err) {
    // silent fallback
  }
}

async function unsubscribePush() {
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) return false;
  try {
    const reg = await navigator.serviceWorker.ready;
    const sub = await reg.pushManager.getSubscription();
    if (sub) {
      const endpoint = sub.endpoint;
      await sub.unsubscribe();
      const base = _pushBasePath();
      await fetch(base + '/api/push/unsubscribe', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ endpoint }),
      });
    }
    localStorage.setItem('chatbot.pushEnabled', 'false');
    return true;
  } catch (err) {
    console.warn('Push unsubscribe failed:', err);
    return false;
  }
}

function isPushEnabled() {
  return localStorage.getItem('chatbot.pushEnabled') === 'true' &&
         typeof Notification !== 'undefined' && Notification.permission === 'granted';
}

async function togglePushNotification(enable, done) {
  if (enable) {
    const ok = await requestPushSubscription();
    localStorage.setItem('chatbot.pushEnabled', ok ? 'true' : 'false');
  } else {
    await unsubscribePush();
    localStorage.setItem('chatbot.pushEnabled', 'false');
  }
  if (typeof done === 'function') done();
}

if (typeof window !== 'undefined') {
  window.requestPushSubscription = requestPushSubscription;
  window.unsubscribePush = unsubscribePush;
  window.isPushEnabled = isPushEnabled;
  window.togglePushNotification = togglePushNotification;
  window.checkAndSyncPushSubscription = checkAndSyncPushSubscription;
  setTimeout(() => checkAndSyncPushSubscription(), 3000);
}
