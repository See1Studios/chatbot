"""Composer microphone speech recognition (STT) tests (va/1, docs/plans/voice-and-audio-interaction.md).
Tests static markup/styles in index.html, chat-composer.css, chat-responsive.css,
and speech recognition lifecycle & result injection in app-speech.js using node stubs.
Run: python3 -m unittest tests.test_speech (from services/chatbot)
"""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path
from tests.page_source import i18n_prelude  # noqa: E402
from tests._paths import REPO  # noqa: E402

ROOT = REPO
STATIC = ROOT / "static"
INDEX_HTML = STATIC / "index.html"
COMPOSER_CSS = STATIC / "chat-composer.css"
RESPONSIVE_CSS = STATIC / "chat-responsive.css"
SPEECH_JS = STATIC / "app-speech.js"

NODE_HARNESS = r"""
const fs = require('fs');
const speechCode = fs.readFileSync(process.argv[1], 'utf8');

if (typeof Event === 'undefined') {
  global.Event = class Event {
    constructor(type, opts) {
      this.type = type;
      this.bubbles = Boolean(opts && opts.bubbles);
    }
  };
}

function runTest(scenario) {
  const listeners = {};
  let recInstance = null;
  const instances = [];

  class MockSpeechRecognition {
    constructor() {
      recInstance = this;
      instances.push(this);
      this.continuous = false;
      this.interimResults = false;
      this.lang = '';
      this.started = false;
      this.stopped = false;
    }
    start() {
      this.started = true;
      if (this.onstart) this.onstart();
    }
    stop() {
      this.stopped = true;
      if (!scenario.deferOnEnd) {
        if (this.onend) this.onend();
      }
    }
  }

  const btn = {
    id: 'micBtn',
    disabled: false,
    title: '',
    attrs: {},
    classList: {
      s: new Set(),
      add(c) { this.s.add(c); },
      remove(...c) { c.forEach(x => this.s.delete(x)); },
      toggle(c, force) { if (force) this.s.add(c); else this.s.delete(c); },
      contains(c) { return this.s.has(c); }
    },
    setAttribute(k, v) { this.attrs[k] = v; },
    getAttribute(k) { return this.attrs[k]; },
    addEventListener(e, fn) { (listeners[e] = listeners[e] || []).push(fn); },
    click() { (listeners.click || []).forEach(fn => fn({ preventDefault() {} })); }
  };

  const sendBtn = {
    id: 'send',
    addEventListener(e, fn) { (listeners['send:' + e] = listeners['send:' + e] || []).push(fn); }
  };

  const inputListeners = [];
  const inputEl = {
    id: 'input',
    value: scenario.initialInput || '',
    dispatched: [],
    addEventListener(e, fn) {
      if (e === 'input') inputListeners.push(fn);
    },
    dispatchEvent(e) {
      const type = (e && e.type) ? e.type : String(e);
      this.dispatched.push(type);
      if (type === 'input') {
        inputListeners.forEach(fn => fn(e));
      }
    }
  };

  let autoResizeCalls = 0;
  let updateSendCalls = 0;
  const autoResizeInput = () => { autoResizeCalls++; };
  const updateSendButton = () => { updateSendCalls++; };

  const docListeners = {};
  const document = {
    getElementById(id) {
      if (id === 'micBtn') return btn;
      if (id === 'send') return sendBtn;
      if (id === 'input') return inputEl;
      return null;
    },
    addEventListener(e, fn) { (docListeners[e] = docListeners[e] || []).push(fn); },
    readyState: 'complete'
  };

  const window = {};
  if (scenario.support) {
    window.SpeechRecognition = MockSpeechRecognition;
  }

  eval(speechCode);

  const out = {};
  out.supported = isSpeechSupported();

  if (scenario.test === 'unsupported') {
    updateMicButtonState(false);
    out.btnDisabled = btn.disabled;
    out.hasUnsupportedClass = btn.classList.contains('unsupported');
    out.title = btn.title;
    startSpeechRecognition();
    out.recording = isSpeechRecording();
    return out;
  }

  if (scenario.test === 'lifecycle') {
    out.initialRecording = isSpeechRecording();
    btn.click();
    out.afterStartRecording = isSpeechRecording();
    out.hasActiveClass = btn.classList.contains('active');
    out.hasRecordingClass = btn.classList.contains('recording');
    out.ariaPressed = btn.attrs['aria-pressed'];
    out.titleRecording = btn.title;

    // Simulate interim result
    recInstance.onresult({
      results: [
        { 0: { transcript: '첫번째 발화' }, isFinal: false }
      ]
    });
    out.valInterim = inputEl.value;
    out.autoResizeCalls1 = autoResizeCalls;
    out.updateSendCalls1 = updateSendCalls;

    // Simulate final result + new interim
    recInstance.onresult({
      results: [
        { 0: { transcript: '첫번째 발화' }, isFinal: true },
        { 0: { transcript: ' 두번째 발화' }, isFinal: false }
      ]
    });
    out.valFinalAndInterim = inputEl.value;

    btn.click(); // toggle stop
    out.afterStopRecording = isSpeechRecording();
    out.hasRecordingClassAfterStop = btn.classList.contains('recording');
    out.ariaPressedAfterStop = btn.attrs['aria-pressed'];
    return out;
  }

  if (scenario.test === 'preserve_base') {
    startSpeechRecognition();
    recInstance.onresult({
      results: [
        { 0: { transcript: '추가 발화' }, isFinal: true }
      ]
    });
    out.val = inputEl.value;
    stopSpeechRecognition();
    return out;
  }

  if (scenario.test === 'error_handling') {
    startSpeechRecognition();
    out.recordingBeforeError = isSpeechRecording();
    recInstance.onerror({ error: 'not-allowed' });
    out.recordingAfterError = isSpeechRecording();
    out.hasRecordingClass = btn.classList.contains('recording');
    out.titleAfterError = btn.title;
    return out;
  }

  if (scenario.test === 'late_result_after_stop') {
    startSpeechRecognition();
    recInstance.onresult({
      results: [
        { 0: { transcript: '보낼 메시지' }, isFinal: true }
      ]
    });
    out.valBeforeSend = inputEl.value;
    stopSpeechRecognition();
    inputEl.value = ''; // Input cleared after send

    // Late result arrives on stopped instance
    recInstance.onresult({
      results: [
        { 0: { transcript: '뒤늦게 도착한 메시지' }, isFinal: true }
      ]
    });
    out.valAfterLateResult = inputEl.value;
    return out;
  }

  if (scenario.test === 'restart_race_condition') {
    startSpeechRecognition();
    const oldRec = recInstance;
    out.recording1 = isSpeechRecording();

    stopSpeechRecognition();
    out.recordingAfterStop = isSpeechRecording();

    startSpeechRecognition();
    const newRec = recInstance;
    out.recordingAfterRestart = isSpeechRecording();
    out.instancesDifferent = (oldRec !== newRec);

    // Old instance fires onend late
    if (oldRec.onend) oldRec.onend();
    out.recordingAfterOldOnEnd = isSpeechRecording();
    out.hasRecordingClassAfterOldOnEnd = btn.classList.contains('recording');

    stopSpeechRecognition();
    if (newRec.onend) newRec.onend();
    out.recordingFinal = isSpeechRecording();
    return out;
  }

  if (scenario.test === 'clear_input_during_recording') {
    startSpeechRecognition();
    recInstance.onresult({
      results: [
        { 0: { transcript: '첫번째 발화' }, isFinal: true }
      ]
    });
    out.valBeforeClear = inputEl.value;

    // User empties input field while still recording
    inputEl.value = '';
    inputEl.dispatchEvent(new Event('input', { bubbles: true }));

    // Subsequent result arrives
    recInstance.onresult({
      results: [
        { 0: { transcript: '첫번째 발화' }, isFinal: true },
        { 0: { transcript: '두번째 발화' }, isFinal: true }
      ]
    });
    out.valAfterClear = inputEl.value;

    // User types new text manually
    inputEl.value = '새 기준문구';
    inputEl.dispatchEvent(new Event('input', { bubbles: true }));

    recInstance.onresult({
      results: [
        { 0: { transcript: '첫번째 발화' }, isFinal: true },
        { 0: { transcript: '두번째 발화' }, isFinal: true },
        { 0: { transcript: '세번째 발화' }, isFinal: true }
      ]
    });
    out.valAfterManualEdit = inputEl.value;

    stopSpeechRecognition();
    return out;
  }

  return out;
}

const scenario = JSON.parse(process.argv[2]);
console.log(JSON.stringify(runTest(scenario)));
"""


class TestSpeechLayout(unittest.TestCase):
    def setUp(self):
        self.html = INDEX_HTML.read_text(encoding="utf-8")
        self.composer_css = COMPOSER_CSS.read_text(encoding="utf-8")
        self.responsive_css = RESPONSIVE_CSS.read_text(encoding="utf-8")

    @staticmethod
    def _extract_css_block(css, header_pattern):
        m = re.search(header_pattern, css)
        if not m:
            return None
        start = css.find("{", m.end() - 1)
        if start == -1:
            return None
        depth = 0
        for i in range(start, len(css)):
            if css[i] == "{":
                depth += 1
            elif css[i] == "}":
                depth -= 1
                if depth == 0:
                    return css[start + 1 : i]
        return None

    def test_mic_btn_in_html(self):
        self.assertIn('id="micBtn"', self.html)
        self.assertIn('class="geo-trigger-btn mic-trigger-btn"', self.html)
        self.assertIn('data-i18n-aria-label="mic.label"', self.html)   # I18N_v1: the words are in static/i18n
        self.assertIn('aria-pressed="false"', self.html)
        self.assertRegex(self.html, r'<button id="micBtn"[^>]*>[\s\S]*?<svg class="tab-icon-svg"')

    def test_app_speech_script_tag_in_html(self):
        self.assertIn('<script src="./app-speech.js', self.html)
        idx_speech = self.html.find('<script src="./app-speech.js')
        idx_app = self.html.find('<script src="./app.js')
        self.assertGreater(idx_speech, 0)
        self.assertGreater(idx_app, 0)
        self.assertLess(idx_speech, idx_app, "app-speech.js must load before app.js")

    def test_composer_css_styles(self):
        self.assertIn(".mic-trigger-btn", self.composer_css)
        self.assertIn(".mic-trigger-btn.recording", self.composer_css)
        self.assertIn(".mic-trigger-btn.unsupported", self.composer_css)
        self.assertIn("@keyframes mic-pulse", self.composer_css)

    def test_responsive_css_styles(self):
        self.assertIn("#micBtn", self.responsive_css)

        block_640 = self._extract_css_block(self.responsive_css, r"@media\s*\([^)]*max-width:\s*640px\)(?!\s*and)")
        self.assertIsNotNone(block_640, "@media (max-width: 640px) block missing")
        self.assertIn("#micBtn", block_640)
        self.assertIn("width: 36px", block_640)
        self.assertIn("height: 36px", block_640)

        block_500 = self._extract_css_block(self.responsive_css, r"@media\s*\([^)]*max-height:\s*500px\)")
        self.assertIsNotNone(block_500, "@media (max-height: 500px) block missing")
        self.assertIn("#micBtn", block_500)
        self.assertIn("width:32px", block_500.replace(" ", ""))

        self.assertRegex(self.responsive_css, r"body\.keyboard-open[\s\S]*?#micBtn\b")

        block_motion = self._extract_css_block(self.responsive_css, r"@media\s*\([^)]*prefers-reduced-motion:\s*reduce\)")
        self.assertIsNotNone(block_motion, "@media (prefers-reduced-motion: reduce) block missing")
        self.assertIn(".mic-trigger-btn.recording", block_motion)
        self.assertIn("animation: none", block_motion)


@unittest.skipUnless(shutil.which("node"), "node not installed")
class TestSpeechExecution(unittest.TestCase):
    def _run_node(self, scenario):
        cmd = ["node", "-e", i18n_prelude() + NODE_HARNESS, str(SPEECH_JS), json.dumps(scenario)]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        self.assertEqual(res.returncode, 0, res.stderr)
        return json.loads(res.stdout.strip())

    def test_unsupported_environment(self):
        res = self._run_node({"support": False, "test": "unsupported"})
        self.assertFalse(res["supported"])
        self.assertTrue(res["btnDisabled"])
        self.assertTrue(res["hasUnsupportedClass"])
        self.assertIn("지원하지 않는", res["title"])
        self.assertFalse(res["recording"])

    def test_supported_lifecycle_and_text_injection(self):
        res = self._run_node({"support": True, "test": "lifecycle", "initialInput": ""})
        self.assertTrue(res["supported"])
        self.assertFalse(res["initialRecording"])
        self.assertTrue(res["afterStartRecording"])
        self.assertTrue(res["hasActiveClass"])
        self.assertTrue(res["hasRecordingClass"])
        self.assertEqual(res["ariaPressed"], "true")
        self.assertIn("멈추기", res["titleRecording"])

        # Check interim injection
        self.assertEqual(res["valInterim"], "첫번째 발화")
        self.assertGreaterEqual(res["autoResizeCalls1"], 1)
        self.assertGreaterEqual(res["updateSendCalls1"], 1)

        # Check final + interim injection
        self.assertEqual(res["valFinalAndInterim"], "첫번째 발화 두번째 발화")

        # Check stopping
        self.assertFalse(res["afterStopRecording"])
        self.assertFalse(res["hasRecordingClassAfterStop"])
        self.assertEqual(res["ariaPressedAfterStop"], "false")

    def test_preserve_base_text(self):
        res = self._run_node({"support": True, "test": "preserve_base", "initialInput": "기존 내용"})
        self.assertEqual(res["val"], "기존 내용 추가 발화")

    def test_error_handling_not_allowed(self):
        res = self._run_node({"support": True, "test": "error_handling"})
        self.assertTrue(res["recordingBeforeError"])
        self.assertFalse(res["recordingAfterError"])
        self.assertFalse(res["hasRecordingClass"])
        self.assertIn("권한이 거부", res["titleAfterError"])

    def test_late_result_after_stop_does_not_modify_input(self):
        res = self._run_node({"support": True, "test": "late_result_after_stop"})
        self.assertEqual(res["valBeforeSend"], "보낼 메시지")
        self.assertEqual(res["valAfterLateResult"], "")

    def test_restart_race_condition_old_onend_ignored(self):
        res = self._run_node({"support": True, "test": "restart_race_condition", "deferOnEnd": True})
        self.assertTrue(res["recording1"])
        self.assertFalse(res["recordingAfterStop"])
        self.assertTrue(res["recordingAfterRestart"])
        self.assertTrue(res["instancesDifferent"])
        self.assertTrue(res["recordingAfterOldOnEnd"], "old onend must not terminate new session")
        self.assertTrue(res["hasRecordingClassAfterOldOnEnd"])
        self.assertFalse(res["recordingFinal"])

    def test_clear_input_during_recording_prevents_resurrection(self):
        res = self._run_node({
            "support": True,
            "test": "clear_input_during_recording",
            "initialInput": "시작 base"
        })
        self.assertEqual(res["valBeforeClear"], "시작 base 첫번째 발화")
        self.assertEqual(res["valAfterClear"], "두번째 발화")
        self.assertEqual(res["valAfterManualEdit"], "새 기준문구 세번째 발화")


if __name__ == "__main__":
    unittest.main()
