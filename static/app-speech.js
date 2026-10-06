// app-speech.js -- Speech recognition (STT) for composer (va/1, docs/plans/voice-and-audio-interaction.md).
// Declarations and listeners: loads before app.js.

const SPEECH_TEXT = i18nTable('speechinput');   // I18N_v1: words by key from the catalog

let speechRecognitionInstance = null;
let speechIsRecording = false;
let speechBaseText = '';
let speechLang = 'ko-KR';
let lastInjectedText = '';
let speechResultOffset = 0;
let speechLastResultCount = 0;

function getSpeechRecognitionClass() {
  if (typeof window === 'undefined') return null;
  return window.SpeechRecognition || window.webkitSpeechRecognition || null;
}

function isSpeechSupported() {
  return Boolean(getSpeechRecognitionClass());
}

function isSpeechRecording() {
  return speechIsRecording;
}

function setSpeechLang(lang) {
  if (lang) speechLang = String(lang);
}

function updateMicButtonState(recording) {
  const btn = document.getElementById('micBtn');
  if (!btn) return;
  const supported = isSpeechSupported();
  if (!supported) {
    btn.disabled = true;
    btn.classList.add('unsupported');
    btn.classList.remove('active', 'recording');
    btn.setAttribute('aria-pressed', 'false');
    btn.title = SPEECH_TEXT.unsupported;
    return;
  }
  btn.disabled = false;
  btn.classList.remove('unsupported');
  const isRec = Boolean(recording);
  btn.classList.toggle('active', isRec);
  btn.classList.toggle('recording', isRec);
  btn.setAttribute('aria-pressed', String(isRec));
  btn.title = isRec ? SPEECH_TEXT.stop : SPEECH_TEXT.start;
}

function handleComposerInput() {
  const inputEl = document.getElementById('input');
  if (!inputEl || !speechIsRecording) return;
  if (inputEl.value === lastInjectedText) return;
  speechBaseText = inputEl.value;
  lastInjectedText = inputEl.value;
  speechResultOffset = speechLastResultCount;
}

function bindSpeechInputElement() {
  const inputEl = document.getElementById('input');
  if (inputEl && !inputEl._speechInputBound) {
    inputEl._speechInputBound = true;
    inputEl.addEventListener('input', handleComposerInput);
  }
}

function applyRecognizedText(inputEl, baseText, recognizedText) {
  if (!inputEl) return;
  let combined = baseText || '';
  const text = String(recognizedText || '').trim();
  if (text) {
    if (combined && !/\s$/.test(combined)) {
      combined += ' ';
    }
    combined += text;
  }
  lastInjectedText = combined;
  inputEl.value = combined;
  if (typeof autoResizeInput === 'function') autoResizeInput();
  if (typeof updateSendButton === 'function') updateSendButton();
  try {
    inputEl.dispatchEvent(new Event('input', { bubbles: true }));
  } catch (_) {}
}

function handleSpeechResult(event) {
  if (!speechRecognitionInstance || !speechIsRecording) return;
  const inputEl = document.getElementById('input');
  if (!inputEl || !event || !event.results) return;

  if (inputEl.value !== lastInjectedText) {
    speechBaseText = inputEl.value;
    lastInjectedText = inputEl.value;
    speechResultOffset = speechLastResultCount;
  }

  speechLastResultCount = event.results.length;

  let finalTranscript = '';
  let interimTranscript = '';
  const startIdx = Math.min(speechResultOffset, event.results.length);
  for (let i = startIdx; i < event.results.length; ++i) {
    const res = event.results[i];
    const text = (res[0] && res[0].transcript) ? res[0].transcript : '';
    if (res.isFinal) {
      if (finalTranscript && !/\s$/.test(finalTranscript) && !/^\s/.test(text)) {
        finalTranscript += ' ';
      }
      finalTranscript += text;
    } else {
      if (interimTranscript && !/\s$/.test(interimTranscript) && !/^\s/.test(text)) {
        interimTranscript += ' ';
      }
      interimTranscript += text;
    }
  }
  let recognized = finalTranscript;
  if (interimTranscript) {
    if (recognized && !/\s$/.test(recognized) && !/^\s/.test(interimTranscript)) {
      recognized += ' ';
    }
    recognized += interimTranscript;
  }
  applyRecognizedText(inputEl, speechBaseText, recognized);
}

function startSpeechRecognition() {
  if (speechIsRecording || speechRecognitionInstance) return;
  const SR = getSpeechRecognitionClass();
  if (!SR) {
    updateMicButtonState(false);
    return;
  }
  bindSpeechInputElement();
  const inputEl = document.getElementById('input');
  speechBaseText = inputEl ? inputEl.value : '';
  lastInjectedText = speechBaseText;
  speechResultOffset = 0;
  speechLastResultCount = 0;

  try {
    const rec = new SR();
    rec.continuous = true;
    rec.interimResults = true;
    rec.lang = speechLang;
    rec.maxAlternatives = 1;

    rec.onstart = function() {
      if (rec !== speechRecognitionInstance) return;
      speechIsRecording = true;
      updateMicButtonState(true);
    };

    rec.onresult = function(event) {
      if (rec !== speechRecognitionInstance) return;
      handleSpeechResult(event);
    };

    rec.onerror = function(event) {
      if (rec !== speechRecognitionInstance) return;
      const err = event && event.error;
      speechIsRecording = false;
      speechRecognitionInstance = null;
      updateMicButtonState(false);
      const btn = document.getElementById('micBtn');
      if (btn && err === 'not-allowed') {
        btn.title = SPEECH_TEXT.denied;
      }
    };

    rec.onend = function() {
      if (rec !== speechRecognitionInstance) return;
      speechIsRecording = false;
      speechRecognitionInstance = null;
      updateMicButtonState(false);
      const input = document.getElementById('input');
      if (input) {
        if (typeof autoResizeInput === 'function') autoResizeInput();
        if (typeof updateSendButton === 'function') updateSendButton();
      }
    };

    speechRecognitionInstance = rec;
    rec.start();
  } catch (_) {
    speechIsRecording = false;
    speechRecognitionInstance = null;
    updateMicButtonState(false);
  }
}

function stopSpeechRecognition() {
  if (!speechRecognitionInstance && !speechIsRecording) return;
  speechIsRecording = false;
  const rec = speechRecognitionInstance;
  speechRecognitionInstance = null;
  if (rec) {
    try {
      rec.stop();
    } catch (_) {}
  }
  updateMicButtonState(false);
  const inputEl = document.getElementById('input');
  if (inputEl) {
    if (typeof autoResizeInput === 'function') autoResizeInput();
    if (typeof updateSendButton === 'function') updateSendButton();
  }
}

function toggleSpeechRecognition() {
  if (speechIsRecording) {
    stopSpeechRecognition();
  } else {
    startSpeechRecognition();
  }
}

function initSpeechRecognition() {
  const btn = document.getElementById('micBtn');
  if (btn && !btn._speechBound) {
    btn._speechBound = true;
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      toggleSpeechRecognition();
    });
  }
  const sendBtn = document.getElementById('send');
  if (sendBtn && !sendBtn._speechSendBound) {
    sendBtn._speechSendBound = true;
    sendBtn.addEventListener('click', () => {
      if (speechIsRecording) stopSpeechRecognition();
    });
  }
  bindSpeechInputElement();
  updateMicButtonState(speechIsRecording);
}

if (typeof document !== 'undefined') {
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initSpeechRecognition);
  } else {
    initSpeechRecognition();
  }
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey && speechIsRecording) {
      stopSpeechRecognition();
    }
  }, true);
}

if (typeof window !== 'undefined') {
  window.isSpeechSupported = isSpeechSupported;
  window.isSpeechRecording = isSpeechRecording;
  window.startSpeechRecognition = startSpeechRecognition;
  window.stopSpeechRecognition = stopSpeechRecognition;
  window.toggleSpeechRecognition = toggleSpeechRecognition;
  window.updateMicButtonState = updateMicButtonState;
  window.initSpeechRecognition = initSpeechRecognition;
  window.setSpeechLang = setSpeechLang;
  window.applyRecognizedText = applyRecognizedText;
  window.handleSpeechResult = handleSpeechResult;
}
