"""Viewing another provider's status must never change the chat session.
Runs the app's REAL picker/label functions (extracted from static/app.js) in node
against a stub DOM. Skipped when node is not installed.
Run: python3 -m unittest tests.test_status_picker  (from services/chatbot)
"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "static" / "app.js"

HARNESS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[process.argv.length - 1], 'utf8');
function slice(from, to) {
  const a = src.indexOf(from), b = src.indexOf(to, a);
  if (a < 0 || b < 0) throw new Error('marker missing: ' + from + ' .. ' + to);
  return src.slice(a, b);
}
const credit  = slice('const PROVIDER_CREDIT = {', 'function updateBrandAvatar');
const picker  = slice('// 상태 탭이 보여 주는 제공자.', 'function fmtAge');
const helpers = "function escapeRegExp(s){return String(s).replace(/[.*+?^${}()|[\\]\\\\]/g,'\\\\$&');}";

function button() {
  const el = { type:'', className:'', textContent:'', title:'', disabled:false, attrs:{}, handlers:{},
    setAttribute(k,v){this.attrs[k]=v}, addEventListener(e,f){this.handlers[e]=f} };
  el.classList = {
    add(c){if(!el.className.split(' ').includes(c)) el.className=(el.className+' '+c).trim();},
    remove(c){el.className=el.className.split(' ').filter(x=>x!==c).join(' ');},
    toggle(c,f){const has=el.className.split(' ').includes(c); if(f===undefined?!has:f) this.add(c); else this.remove(c);}
  };
  return el;
}
const calls = { fetchAccounts: 0, fetchUsage: 0, selectProvider: 0 };
const picked = { el: { innerHTML:'', children:[], appendChild(c){ this.children.push(c); } } };
Object.defineProperty(picked.el, 'innerHTML', { get(){return ''}, set(v){ this.children = []; } });
const env = {
  providerEl: { value: 'agy' },
  providerCatalog: [ {id:'agy',name:'Antigravity',available:true}, {id:'claude',name:'Claude',available:true},
                     {id:'codex',name:'Codex',available:false}, {id:'grok',name:'Grok',available:true} ],
  currentTab: 'status',
  IDENTITY: { title:'프로듀서', persona:'냥피디', user_title:'실장님', voice:'', name:'냥피디' },
};
const body = credit + '\n' + helpers + '\n' + picker + `
  return {
    api: { get view(){return statusViewProvider}, current: currentStatusProvider, chat: chatProvider,
           render: renderStatusPicker, set: setStatusViewProvider, follow: followChatProvider,
           refresh: refreshProviderStatus, name: statusProviderName, setTab(t){currentTab=t} },
  };`;
const f = new Function('providerEl','providerCatalog','currentTab','IDENTITY','document','statusPickerEl',
  'fetchAccounts','fetchUsage','selectProvider', body);
const stubs = [ () => calls.fetchAccounts++, () => calls.fetchUsage++, () => calls.selectProvider++ ];
const { api } = f(env.providerEl, env.providerCatalog, env.currentTab, env.IDENTITY,
                  { createElement: button }, picked.el, ...stubs);

const snap = () => picked.el.children.map(b => ({ label:b.textContent, on:/ on/.test(b.className), chat:/ is-chat/.test(b.className), disabled:b.disabled }));
const out = {};
api.render();
out.initial = { view: api.view, current: api.current(), chips: snap() };

// click a chip for another provider
picked.el.children[1].handlers.click();
out.afterClickClaude = { view: api.view, current: api.current(), chatProvider: env.providerEl.value, calls: {...calls}, chips: snap(), title: api.name('claude') };

// clicking the chat's own provider goes back to "follow the chat"
picked.el.children[0].handlers.click();
out.afterClickChatProvider = { view: api.view, current: api.current() };

// view something else, then the CHAT provider changes (tray pick / session switch) -> viewer follows it
picked.el.children[3].handlers.click();
env.providerEl.value = 'claude'; api.follow();
out.afterChatSwitch = { view: api.view, current: api.current(), chips: snap() };

// off the status tab nothing is fetched
const before = { ...calls }; api.setTab('chat'); api.refresh();
out.offTab = { fetched: calls.fetchAccounts !== before.fetchAccounts || calls.fetchUsage !== before.fetchUsage };
out.selectProviderCalls = calls.selectProvider;
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class StatusPicker(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = subprocess.run(["node", "-e", HARNESS, "--", str(APP)], capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            raise AssertionError(r.stderr[-1500:])
        cls.out = json.loads(r.stdout.strip().splitlines()[-1])

    def test_defaults_to_the_chat_provider_and_lists_every_provider_by_vendor_name(self):
        o = self.out["initial"]
        self.assertEqual((o["view"], o["current"]), (None, "agy"))
        self.assertEqual([c["label"] for c in o["chips"]], ["Antigravity", "Claude", "Codex", "Grok"])
        self.assertEqual([c["on"] for c in o["chips"]], [True, False, False, False])
        self.assertEqual([c["chat"] for c in o["chips"]], [True, False, False, False])

    def test_unavailable_providers_cannot_be_picked(self):
        self.assertEqual([c["disabled"] for c in self.out["initial"]["chips"]], [False, False, True, False])

    def test_picking_another_provider_only_changes_what_is_viewed(self):
        o = self.out["afterClickClaude"]
        self.assertEqual((o["view"], o["current"]), ("claude", "claude"))
        self.assertEqual(o["chatProvider"], "agy")                      # the chat is untouched
        self.assertEqual(self.out["selectProviderCalls"], 0)            # and selectProvider() was never called
        self.assertEqual((o["calls"]["fetchAccounts"], o["calls"]["fetchUsage"]), (1, 1))
        self.assertEqual([c["on"] for c in o["chips"]], [False, True, False, False])
        self.assertEqual([c["chat"] for c in o["chips"]], [True, False, False, False])   # the dot stays on the chat's provider

    def test_picking_the_chat_provider_returns_to_following_it(self):
        o = self.out["afterClickChatProvider"]
        self.assertEqual((o["view"], o["current"]), (None, "agy"))

    def test_when_the_chat_provider_changes_the_viewer_follows_it(self):
        o = self.out["afterChatSwitch"]
        self.assertEqual((o["view"], o["current"]), (None, "claude"))
        self.assertEqual([c["on"] for c in o["chips"]], [False, True, False, False])

    def test_nothing_is_fetched_off_the_status_tab(self):
        self.assertFalse(self.out["offTab"]["fetched"])


if __name__ == "__main__":
    unittest.main()
