"""Status tab observation manager: runs the REAL code between the `observation manager` markers of static/app.js in node
against a stub DOM. Skipped when node is not installed.

What matters most: observation and candidate text is written by agents, so it must reach the page as text, never markup.
Run: engine/run-tests.sh test_observation_ui
"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path
from tests.page_source import i18n_prelude  # noqa: E402
from tests.page_source import app_bundle  # noqa: E402

APP = app_bundle()   # static/app.js and its app-*.js parts (APP_SPLIT_v1)
from tests.page_source import css_source  # noqa: E402
from tests._paths import REPO  # noqa: E402
HTML = REPO / "static" / "index.html"

HARNESS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[process.argv.length - 1], 'utf8');
const a = src.indexOf('// ---- observation manager'), b = src.indexOf('// ---- end observation manager ----');
if (a < 0 || b < 0) throw new Error('markers missing');
const code = src.slice(a, b);

const created = [];
function el(tag) {
  let text = '';
  const e = {
    tag, className: '', children: [], handlers: {}, hidden: false, disabled: false, value: '', type: '', placeholder: '', maxLength: 0,
    get textContent() { return text; },
    set textContent(v) { text = String(v); if (text === '') this.children = []; },
    set innerHTML(v) { throw new Error('innerHTML must not be used on observation data'); },
    set outerHTML(v) { throw new Error('outerHTML must not be used'); },
    appendChild(c) { this.children.push(c); return c; },
    append(...cs) { cs.forEach(c => this.children.push(c)); },
    insertBefore(c, ref) { const i = this.children.indexOf(ref); if (i < 0) this.children.push(c); else this.children.splice(i, 0, c); return c; },
    querySelector(sel) { return find(this, sel.replace(/^\./, '')).filter(n => n !== this)[0] || null; },
    addEventListener(t, f) { this.handlers[t] = f; },
    setAttribute(k, v) { this['attr_' + k] = v; },
    focus() { this.focused = true; },
  };
  e.classList = {
    add(c) { if (!e.className.split(' ').includes(c)) e.className = (e.className + ' ' + c).trim(); },
    remove(c) { e.className = e.className.split(' ').filter(x => x !== c).join(' '); },
    toggle(c, f) { const has = e.className.split(' ').includes(c); const on = f === undefined ? !has : f; if (on) this.add(c); else this.remove(c); return on; },
    contains(c) { return e.className.split(' ').includes(c); },
  };
  created.push(e);
  return e;
}
// a click as the page gets it: handlers read the event
const click = (n) => n.handlers.click({ stopPropagation() {}, target: { closest: () => null } });
const all = (n, out = []) => { out.push(n); n.children.forEach(c => all(c, out)); return out; };
const find = (n, cls) => all(n).filter(x => (x.className || '').split(' ').includes(cls));
const text = n => [n.textContent].concat(n.children.map(text)).join(' ');

const calls = [], alerts = [], activity = [], notices = [];
let fetched = 0;
let apiImpl = async () => ({});
const api = (path, opts) => { calls.push({ path, opts: opts || null }); return apiImpl(path, opts); };
const box = el('div');
const tbox = el('div');
const bar = el('div');
const inputEl = el('textarea');
const tabs = [];
const body = code + `
  return { loadObservations, renderObservations, obsErrorText, loadTickets, renderTickets, parseTicketCommand, decideTicket };`;
const sentText = [], asked = [];
const mod = new Function('document', 'api', 'statusObsBoxEl', 'alertModal', 'addActivity', 'fetchSelfStatus',
                         'statusTicketBoxEl', 'inputEl', 'switchTab', 'ticketBarEl', 'addNotice',
                         'fillComposer', 'send', 'tapSendOpts', 'confirmModal', body)(
  { createElement: el, getElementById: () => null }, api, box, async m => { alerts.push(m); }, m => activity.push(m), () => { fetched++; },
  tbox, inputEl, t => tabs.push(t), bar, (kind, m) => notices.push([kind, m]),   // chat notices (#145)
  (t) => { inputEl.value = t; inputEl.focus(); },                                  // FILL_COMPOSER_v1
  async () => { sentText.push(inputEl.value); inputEl.value = ''; }, () => ({ keepFocus: false }),
  async (m) => { asked.push(m); return true; });                                  // TICKET_BUTTONS_v1: [폐기] asks

const HOSTILE = '<img src=x onerror=alert(1)>';
const overview = {
  ok: true, last_review: '2026-09-16', unreviewed_candidates: 2,
  observations: [
    { id: 1, title: HOSTILE, status: 'open', area: 'ui', date: '2026-09-20', parked_until: '' },
    { id: 2, title: 'Parked one', status: 'parked', area: 'x', date: '2026-09-19', parked_until: '2026-10-01' },
    { id: 3, title: 'Done today', status: 'actioned', area: '', date: '2026-09-18', parked_until: '' },
  ],
  candidates: [{ ref: 'candidate:1.5', ts: '2026-09-20 21:44:47', signal: 'correction', provider: 'agy', user: '왜 안돼? ' + HOSTILE },
               { ref: 'candidate:1.4', ts: 't', signal: 'stopped', provider: 'claude', user: '' }],
};
const out = {};
const tick = () => new Promise(r => setTimeout(r, 0));

(async () => {
  // 1. render: waiting rows, the paged history, hints and the review form; hostile text stays text
  const history = { ok: true, page: 1, pages: 1, total: 1, items: [{ id: 3, title: 'Done today', status: 'actioned', resolved: '2026-09-18' }] };
  apiImpl = async path => (path === '/api/observations' ? overview
    : path.startsWith('/api/observations/history/') ? history : { observation: { body: 'Body ' + HOSTILE } });
  await mod.loadObservations(); await tick();
  const rows = find(box, 'obs-row').filter(r => !r.className.includes('obs-row-done'));
  out.rowCount = rows.length;
  out.titles = find(box, 'obs-title').map(n => n.textContent);
  out.badges = rows.map(r => find(r, 'obs-badge')[0]).map(n => n.className + '|' + n.textContent);
  out.meta = find(rows[1], 'obs-meta').map(n => n.textContent);
  out.historyCall = calls.map(c => c.path).filter(p => p.startsWith('/api/observations/history/'));
  out.historyRows = find(box, 'obs-row-done').map(text);
  out.hintCount = find(find(box, 'obs-cands')[0], 'evo-count').map(n => n.textContent);
  out.lastReview = find(box, 'obs-meta').map(n => n.textContent).filter(t => t.indexOf('마지막 점검') >= 0);

  // 2. view: fetches the body and shows it as text
  const viewBtn = find(rows[0], 'art-btn').filter(b => b.textContent === '보기')[0];
  const pre = find(rows[0], 'obs-body')[0];
  out.preHiddenAtStart = pre.hidden;
  await click(viewBtn); await tick();
  out.detailCall = calls[calls.length - 1].path;
  out.preText = pre.textContent; out.preHiddenAfter = pre.hidden;
  await click(viewBtn);
  out.preHiddenAfterSecondClick = pre.hidden;

  // 3. resolve: empty reason does nothing; then a real POST; parked adds a date
  const doBtn = find(rows[0], 'art-btn').filter(b => b.textContent === '처리')[0];
  const host = find(rows[0], 'obs-formhost')[0];
  click(doBtn);
  out.formOpened = host.children.length;
  const form = host.children[0];
  const [sel, reason, until, btns] = form.children;
  out.statusOptions = sel.children.map(o => o.value);
  out.untilHiddenAtStart = until.hidden;
  const save = find(btns, 'primary')[0];
  const before = calls.length;
  await click(save);
  out.emptyReasonCalls = calls.length - before; out.emptyReasonFocused = !!reason.focused;
  sel.value = 'parked'; sel.handlers.change();
  out.untilShownForParked = !until.hidden;
  reason.value = '  나중에 볼게요  ';
  apiImpl = async () => ({ ok: true });
  await click(save);
  const post = calls[calls.length - 1];
  out.post = { path: post.path, method: post.opts.method, body: JSON.parse(post.opts.body) };
  out.activity = activity.slice(); out.refreshed = fetched;
  click(doBtn);  // toggles closed
  out.formClosedAgain = host.children.length;

  // 4. a failing save shows the server's own message and re-enables the button
  click(doBtn);
  const form2 = host.children[0];
  const [sel2, reason2, , btns2] = form2.children;
  const save2 = find(btns2, 'primary')[0];
  sel2.value = 'actioned'; reason2.value = 'x';
  apiImpl = async () => { throw new Error(JSON.stringify({ ok: false, error: 'observation 1 is already declined' })); };
  await click(save2);
  out.alert = alerts[alerts.length - 1]; out.saveReEnabled = !save2.disabled; out.saveLabel = save2.textContent;

  // 5. hints: folded until the header is clicked, shown as text
  const cands = find(box, 'obs-cands')[0];
  const candHead = find(cands, 'evo-sec-toggle')[0];
  const candList = find(cands, 'evo-fold')[0];
  out.candHidden = !candList.classList.contains('open');
  click(candHead);
  out.candShown = candList.classList.contains('open');
  out.candRows = find(candList, 'obs-cand').map(text);

  // 6. review: needs a summary, then posts it
  const review = find(box, 'obs-review')[0];
  const [summary, go] = find(review, 'obs-form')[0].children;
  const c0 = calls.length;
  await click(go);
  out.reviewEmptyCalls = calls.length - c0;
  summary.value = ' 2건 읽고 1건 닫음 ';
  apiImpl = async () => ({ ok: true });
  await click(go);
  const rp = calls[calls.length - 1];
  out.reviewPost = { path: rp.path, body: JSON.parse(rp.opts.body) };

  // 7. no waiting observation, no hint: says so
  apiImpl = async path => (path.startsWith('/api/observations/history/') ? { ok: true, page: 1, pages: 1, total: 0, items: [] }
    : { ok: true, last_review: 'never', unreviewed_candidates: 0, observations: [], candidates: [] });
  await mod.loadObservations(); await tick();
  out.emptyText = find(box, 'evo-empty').map(n => n.textContent);
  out.noHintToggle = find(find(box, 'obs-cands')[0], 'evo-sec-toggle').length;

  // 8. an old host without the API: a hint, not a crash
  apiImpl = async () => { throw new Error(JSON.stringify({ ok: false, error: 'not found' })); };
  await mod.loadObservations();
  out.degraded = box.children.map(text);

  // 9. tickets: the buttons only fill the chat box; nothing is posted
  const mk = (id, status, extra) => Object.assign({ id, title: 'T' + id, target: 'session.py', status, attempts: 1, evidence: ['event:s#1'] }, extra || {});
  apiImpl = async () => ({ ok: true, tickets: [mk(1, 'proposed', { title: HOSTILE }), mk(2, 'approved'), mk(3, 'wontfix'), mk(4, 'declined'), mk(5, 'done')] });
  const t0 = calls.length;
  await mod.loadTickets();
  out.ticketCall = calls[t0].path; out.ticketCalls = calls.length - t0;
  const chips = find(bar, 'ticket-chip');
  out.bar = { hidden: bar.hidden, titles: chips.map(c => find(c, 'ticket-chip-title')[0].textContent),
              buttons: chips.map(c => find(c, 'art-btn').map(b => b.textContent)) };
  const barBefore = calls.length;
  click(find(chips[0], 'art-btn').filter(b => b.textContent === '실행')[0]);
  await new Promise(r => setTimeout(r, 20));
  out.barFill = inputEl.value; out.barCalls = calls.length - barBefore; out.barFocused = !!inputEl.focused;
  const trows = find(tbox, 'obs-row');
  out.ticketRows = trows.map(r => find(r, 'obs-id')[0].textContent);
  out.ticketTitle = find(trows[0], 'obs-title')[0].textContent;
  out.ticketButtons = trows.map(r => find(r, 'art-btn').map(b => b.textContent));
  const pressed = (row, label) => find(row, 'art-btn').filter(b => b.textContent === label)[0];
  const c1 = calls.length, a1 = alerts.length, s1 = sentText.length;
  const settle = () => new Promise(r => setTimeout(r, 20));
  const cGo = calls.length;
  click(pressed(trows[0], '실행')); await settle();
  out.goText = inputEl.value; out.goSent = sentText.slice(s1);
  out.goPosts = calls.slice(cGo).filter(c => c.opts && c.opts.method === 'POST').map(c => c.path);
  out.approveText = inputEl.value; out.tabAfter = tabs.slice();
  const c2 = calls.length;
  click(pressed(trows[0], '폐기')); await settle();
  out.declineText = inputEl.value;
  click(pressed(trows[2], '재개')); await settle();
  out.reopenText = inputEl.value;
  out.decisionPosts = calls.slice(c2).filter(c => c.opts && c.opts.method === 'POST').map(c => c.path);
  out.asked = asked.slice();
  out.callsAfterButtons = calls.length - c1; out.alertsAfterButtons = alerts.length - a1;
  out.parsed = ['/ticket approve 3', '/ticket decline #12', ' /ticket reopen 7 ', '/ticket approve', '/ticket approve x', '/ticket claim 3',
                '/ticket approve 3 now', 'ticket approve 3', '/ticket approve 1234567', '/ticket go 5'].map(t => mod.parseTicketCommand(t));
  const d0 = calls.length;
  apiImpl = async () => ({ ok: true, ticket: { id: 3, status: 'approved' } });
  out.decideMsg = await mod.decideTicket({ action: 'approve', id: 3 });
  const dc = calls[d0];
  out.decideCall = { path: dc.path, method: dc.opts.method };
  apiImpl = async () => { throw new Error(JSON.stringify({ ok: false, error: 'ticket 3 is declined' })); };
  try { await mod.decideTicket({ action: 'approve', id: 3 }); out.decideThrew = false; } catch (e) { out.decideThrew = mod.obsErrorText(e); }
  apiImpl = async () => ({ ok: true, tickets: [1, 2, 3, 4, 5].map(i => mk(i, 'proposed')) });
  await mod.loadTickets();
  out.barMany = { chips: find(bar, 'ticket-chip').length, more: find(bar, 'obs-meta').map(n => n.textContent) };
  apiImpl = async () => ({ ok: true, tickets: [mk(4, 'declined')] });
  await mod.loadTickets();
  out.barEmptyHidden = bar.hidden;
  out.noTicketText = find(tbox, 'evo-empty').map(n => n.textContent);
  apiImpl = async () => { throw new Error(JSON.stringify({ ok: false, error: 'not found' })); };
  await mod.loadTickets();
  out.ticketDegraded = tbox.children.map(text);
  out.barDegradedHidden = bar.hidden;

  // 10. nothing anywhere set markup
  out.errorsFromHtml = 0;
  console.log(JSON.stringify(out));
})().catch(e => { console.error('HARNESS ERROR', e.stack); process.exit(1); });
"""


@unittest.skipUnless(shutil.which("node"), "node not installed")
class ObservationUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        p = subprocess.run(["node", "-e", i18n_prelude() + HARNESS, str(APP)], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           universal_newlines=True, timeout=60)
        if p.returncode != 0:
            raise AssertionError("harness failed: " + p.stderr[-1500:])
        cls.out = json.loads(p.stdout.strip().splitlines()[-1])

    def test_waiting_observations_are_rows_and_resolved_ones_a_paged_history(self):
        o = self.out
        self.assertEqual(o["rowCount"], 2)
        self.assertEqual(o["badges"][0], "obs-badge open|열림")
        self.assertIn("보류", o["badges"][1])
        self.assertIn("보류 ~ 2026-10-01", o["meta"][0])
        self.assertEqual(o["historyCall"][:1], ["/api/observations/history/1"])      # OBS_HISTORY_v1
        self.assertEqual(len(o["historyRows"]), 1)
        for bit in ("#3", "Done today", "완료", "2026-09-18"):
            self.assertIn(bit, o["historyRows"][0])
        self.assertEqual(o["lastReview"], ["마지막 점검: 2026-09-16"])

    def test_agent_written_text_reaches_the_page_as_text_never_markup(self):
        hostile = "<img src=x onerror=alert(1)>"
        self.assertEqual(self.out["titles"][0], hostile)                 # exactly the raw string, in a text node
        self.assertEqual(self.out["preText"], "Body " + hostile)
        self.assertIn(hostile, self.out["candRows"][0])
        # the stub throws if innerHTML/outerHTML is ever assigned, so reaching this line proves none was

    def test_the_source_of_the_manager_never_touches_html_properties(self):
        src = APP.read_text(encoding="utf-8")
        region = src[src.index("// ---- observation manager"):src.index("// ---- end observation manager ----")]
        for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("):
            self.assertNotIn(banned, region, banned)

    def test_view_fetches_the_body_once_and_toggles(self):
        o = self.out
        self.assertEqual((o["preHiddenAtStart"], o["detailCall"], o["preHiddenAfter"], o["preHiddenAfterSecondClick"]),
                         (True, "/api/observations/1", False, True))

    def test_resolving_needs_a_reason_and_posts_what_was_chosen(self):
        o = self.out
        self.assertEqual(o["formOpened"], 1)
        self.assertEqual(o["statusOptions"], ["actioned", "declined", "superseded", "parked"])
        self.assertEqual((o["emptyReasonCalls"], o["emptyReasonFocused"]), (0, True))
        self.assertTrue(o["untilHiddenAtStart"] and o["untilShownForParked"])
        post = o["post"]
        self.assertEqual((post["path"], post["method"]), ("/api/observations/1/resolve", "POST"))
        self.assertEqual((post["body"]["status"], post["body"]["resolution"]), ("parked", "나중에 볼게요"))
        self.assertRegex(post["body"]["until"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertEqual((o["activity"], o["refreshed"]), (["이슈 #1 → 보류"], 1))
        self.assertEqual(o["formClosedAgain"], 0)

    def test_a_refused_save_shows_the_servers_reason_and_can_be_retried(self):
        o = self.out
        self.assertEqual(o["alert"], "처리 실패: observation 1 is already declined")
        self.assertEqual((o["saveReEnabled"], o["saveLabel"]), (True, "저장"))

    def test_candidates_are_hints_folded_until_asked(self):
        o = self.out
        self.assertEqual(o["hintCount"], ["2"])
        self.assertEqual((o["candHidden"], o["candShown"]), (True, True))
        self.assertIn("candidate:1.5", o["candRows"][0])   # the reference a ticket can cite

    def test_a_review_needs_a_summary(self):
        o = self.out
        self.assertEqual(o["reviewEmptyCalls"], 0)
        self.assertEqual(o["reviewPost"], {"path": "/api/observations/reviewed", "body": {"summary": "2건 읽고 1건 닫음"}})

    def test_no_active_observation_and_an_old_host_are_handled(self):
        o = self.out
        self.assertIn("대기 중 이슈 없음", o["emptyText"])
        self.assertIn("새 힌트 없음", o["emptyText"])
        self.assertEqual(o["noHintToggle"], 0)
        self.assertEqual(len(o["degraded"]), 1)
        self.assertIn("엔진 리부트", o["degraded"][0])
        self.assertIn("not found", o["degraded"][0])


    def test_only_tickets_waiting_for_a_decision_are_listed_with_the_fitting_buttons(self):
        o = self.out
        self.assertEqual((o["ticketCall"], o["ticketCalls"]), ("/api/tickets", 1))
        self.assertEqual(o["ticketRows"], ["#1", "#2", "#3"])     # declined and done need nothing
        self.assertEqual(o["ticketButtons"], [["실행", "폐기"], ["실행", "폐기"], ["재개"]])   # BUTTON_LOGIC_v1: no more four
        self.assertEqual(o["ticketTitle"], "<img src=x onerror=alert(1)>")

    def test_the_same_buttons_sit_above_the_composer_while_a_ticket_waits(self):
        o = self.out
        self.assertFalse(o["bar"]["hidden"])
        self.assertEqual(o["bar"]["titles"], ["#1 <img src=x onerror=alert(1)>", "#2 T2"])   # text, never markup; parked stays off the bar
        self.assertEqual(o["bar"]["buttons"], [["실행", "폐기"], ["실행", "폐기"]])
        self.assertEqual((o["barFill"], o["barCalls"] >= 1, o["barFocused"]), ("", True, False))   # acts directly, nothing typed (#145)
        self.assertEqual(o["barMany"]["chips"], 3)
        self.assertEqual(o["barMany"]["more"], ["+2건 더 (개선 탭)"])
        self.assertTrue(o["barEmptyHidden"] and o["barDegradedHidden"])

    def test_the_buttons_decide_at_once_and_only_throwing_away_asks(self):
        # TICKET_BUTTONS_v1 (operator, 2026-09-29): was "type the command, Enter decides"; now the button decides,
        # nothing lands in the box, and [폐기] asks first.
        o = self.out
        self.assertEqual((o["approveText"], o["declineText"], o["reopenText"]), ("", "", ""))
        self.assertTrue(o["tabAfter"] and set(o["tabAfter"]) == {"chat"})
        self.assertEqual(o["decisionPosts"], ["/api/tickets/1/decline", "/api/tickets/3/reopen"])
        self.assertEqual(len(o["asked"]), 1)
        self.assertIn("#1", o["asked"][0])
        self.assertEqual(o["alertsAfterButtons"], 0)

    def test_only_the_exact_operator_command_is_recognised(self):
        p = self.out["parsed"]
        self.assertEqual(p[:3], [{"action": "approve", "id": 3}, {"action": "decline", "id": 12}, {"action": "reopen", "id": 7}])
        self.assertEqual(p[3:9], [None] * 6)
        self.assertEqual(p[9], {"action": "delegate", "id": 5})   # BUTTON_LOGIC_v1: a typed go is [실행]

    def test_run_is_the_engines_and_reaches_no_model(self):
        # BUTTON_LOGIC_v1 (#806): [실행] was [승인+진행], an English instruction sent to the model to decide
        self.assertEqual(self.out["goPosts"], ["/api/delegations/1/go"])
        self.assertEqual((self.out["goText"], self.out["goSent"]), ("", []))

    def test_a_decision_is_one_post_and_a_refusal_shows_the_cores_reason(self):
        o = self.out
        self.assertEqual(o["decideCall"], {"path": "/api/tickets/3/approve", "method": "POST"})
        self.assertIn("작업 #3 승인 처리했어요", o["decideMsg"])
        self.assertIn("승인됨", o["decideMsg"])
        self.assertEqual(o["decideThrew"], "ticket 3 is declined")

    def test_no_ticket_waiting_and_an_old_host_are_handled(self):
        o = self.out
        self.assertIn("지금 결정할 작업이 없어요.", o["noTicketText"])
        self.assertIn("엔진 리부트", o["ticketDegraded"][0])


class MarkupTest(unittest.TestCase):
    def test_the_container_exists_and_the_styles_the_code_uses_are_defined(self):
        html = HTML.read_text(encoding="utf-8")
        self.assertIn('id="statusObsBox"', html)
        self.assertIn('id="statusTicketBox"', html)
        self.assertIn('id="ticketBar"', html)
        self.assertLess(html.index('id="ticketBar"'), html.index('class="composer"'))
        css = css_source()
        for cls in ("ticket-bar", "ticket-chip", "obs-row", "obs-head", "obs-id", "obs-title", "obs-badge", "obs-meta", "obs-actions", "obs-body",
                    "obs-form", "obs-cand"):
            self.assertIn("." + cls, css, cls)

    def test_the_tab_loads_the_manager_after_the_summary(self):
        src = APP.read_text(encoding="utf-8")
        evo = src[src.index("async function fetchEvolution()"):]
        self.assertIn("  loadObservations();\n  loadTickets();\n}", evo[:1200])   # the evolution tab, after its summary
        send = src[src.index("async function send("):]   # send(opts) since #161
        self.assertIn("const ticketCmd = parseTicketCommand(text);", send)
        self.assertIn("await runTicketDecision(ticketCmd, opts);", send)   # TICKET_BUTTONS_v1: one path, never the model's
        self.assertLess(send.index("parseTicketCommand(text)"), send.index("/api/chat") if "/api/chat" in send else len(send))
        self.assertIn("setInterval(loadTickets, 60000);", src)       # the bar is not only for people who open the status tab
        self.assertIn("const statusTicketBoxEl = document.getElementById('statusTicketBox');", src)
        self.assertIn("const statusObsBoxEl = document.getElementById('statusObsBox');", src)


if __name__ == "__main__":
    unittest.main()
