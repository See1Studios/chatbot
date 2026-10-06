"""CONTEXT_LAYERS_v1 (docs/plans/layered-context-architecture.md lca/A): one layer list assembles every instruction
bundle. The list's rows are well formed, a private session takes no work layer (D-6), and a fixture's bundles keep
their exact bytes -- a changed bundle re-injects into every live session, so a change here is on purpose.
Run: python3 -m unittest tests.test_context_layers  (from services/chatbot)
"""
import hashlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import characters as C  # noqa: E402
import instructions as I  # noqa: E402
from tests.test_instructions import WorkspaceCase, _write  # noqa: E402


class LayerList(unittest.TestCase):
    def test_every_row_is_well_formed(self):
        ids = [layer.id for layer in I.LAYERS]
        self.assertEqual(len(ids), len(set(ids)), "one row per layer id")
        for layer in I.LAYERS:
            self.assertIn(layer.kind, ("rules", "index", "dynamic"), layer.id)
            self.assertTrue(layer.modes and set(layer.modes) <= set(I.BOTH), layer.id)
            self.assertTrue(callable(layer.text), layer.id)


class Fixture(WorkspaceCase):
    def setUp(self):
        super().setUp()
        _write(self.ws / "AGENTS.md", "# 헌장\nCHARTER-MARK\n\n## Scope\nSCOPE-MARK\n\n## Work\nWORK-CHARTER-MARK\n")
        _write(self.ws / "memory/MEMORY.md", "# 기억\n- HOUSE-MEMORY-MARK\n")
        card = C.load(self.card_id, self.ws)
        card["data"]["system_prompt"] = "PRIVATE-RULES-MARK {{char}}"
        C.ext(card).setdefault("work", {})["instructions"] = "WORK-HOW-MARK"
        C.save(self.card_id, card, self.ws)
        C.remember_private(self.card_id, ["PRIVATE-MEMORY-MARK"], ws=self.ws)

    def test_a_private_session_takes_no_work_layer(self):
        # D-6: checked against the list, so a new work layer is checked too
        private = I.build_instruction_bundle(mode="private", character=self.card_id)["text"]
        self.assertIn("PRIVATE-RULES-MARK", private)
        self.assertIn("PRIVATE-MEMORY-MARK", private)
        for layer, text in I.layer_texts("work", self.card_id):
            if "private" not in layer.modes and text.strip():
                self.assertNotIn(text.strip(), private, "work layer %r is in a private bundle" % layer.id)
        work = I.build_instruction_bundle(mode="work", character=self.card_id)["text"]
        for mark in ("PRIVATE-RULES-MARK", "PRIVATE-MEMORY-MARK"):
            self.assertNotIn(mark, work)

    def test_each_mode_takes_only_its_rows_in_list_order(self):
        for mode in I.BOTH:
            got = [layer.id for layer, _t in I.layer_texts(mode, self.card_id)]
            self.assertEqual(got, [layer.id for layer in I.LAYERS if mode in layer.modes])

    def test_the_hash_covers_the_static_layers_only(self):
        h0 = I.build_instruction_bundle(character=self.card_id)["hash"]
        _write(self.ws / "memory/MEMORY.md", "# 기억\n- ANOTHER-FACT\n")
        self.assertEqual(I.build_instruction_bundle(character=self.card_id)["hash"], h0)

    def test_the_bundle_says_what_each_layer_gave(self):
        # CONTEXT_LOG_v1: the injection record's source
        b = I.build_instruction_bundle(character=self.card_id)
        ids = [x["id"] for x in b["layers"]]
        self.assertEqual(ids, [layer.id for layer, t in I.layer_texts("work", self.card_id) if t])
        self.assertIn("house_memory", ids)
        charter = next(x for x in b["layers"] if x["id"] == "charter")
        self.assertEqual((charter["kind"], len(charter["hash"])), ("rules", 8))
        self.assertGreater(charter["chars"], 0)

    def test_an_injection_is_logged_once_with_its_layers_and_why(self):
        import obslog
        import session as S
        from unittest import mock
        s = S.AgentSession.__new__(S.AgentSession)
        s.sid, s.provider, s.mode, s.character = "sid-1", "agy", "work", self.card_id
        b = I.build_instruction_bundle(character=self.card_id)
        with mock.patch.object(obslog, "event") as ev:
            s._log_context(b)
            s.persona_injected = True
            s._log_context(b)
        (name1, f1), (name2, f2) = [(c.args[0], c.kwargs) for c in ev.call_args_list]
        self.assertEqual((name1, f1["why"], f2["why"]), ("context.inject", "first", "rules_changed"))
        self.assertEqual((f1["sid"], f1["mode"], f1["hash"]), ("sid-1", "work", b["hash"]))
        self.assertEqual(f1["chars"], len(b["text"]))
        self.assertEqual([x["id"] for x in f1["layers"]], [x["id"] for x in b["layers"]])

    def test_the_turn_logs_where_it_injects(self):
        src = (Path(I.__file__).parent / "session_turn.py").read_text(encoding="utf-8")
        block = src[src.index("if header:"):src.index("self.persona_injected = True", src.index("if header:"))]
        self.assertIn("self._log_context(bundle)", block)

    def test_a_sound_bundle_raises_no_alert(self):
        # CONTEXT_ALERT_v1
        from unittest import mock
        with mock.patch.object(I, "_budget", return_value=100000):
            for mode in I.BOTH:
                b = I.build_instruction_bundle(mode=mode, character=self.card_id)
                self.assertEqual(I.context_alerts(b, self.card_id), [], mode)

    def test_static_layers_past_the_budget_raise_an_alert(self):
        from unittest import mock
        b = I.build_instruction_bundle(character=self.card_id)
        with mock.patch.object(I, "_budget", return_value=b["static_bytes"] - 1):
            self.assertEqual(I.context_alerts(b, self.card_id),
                             [{"kind": "over_budget", "static_bytes": b["static_bytes"], "limit": b["static_bytes"] - 1}])
        self.assertGreater(I._budget(), 0, "bundle_budget.json is read")

    def test_an_empty_required_layer_raises_an_alert(self):
        from unittest import mock
        b = I.build_instruction_bundle(character=self.card_id)
        b = dict(b, layers=[x for x in b["layers"] if x["id"] != "charter"])
        with mock.patch.object(I, "_budget", return_value=100000):
            self.assertEqual(I.context_alerts(b, self.card_id), [{"kind": "missing", "layers": ["charter"]}])

    def test_a_work_layer_in_a_private_bundle_raises_an_alert(self):
        from unittest import mock
        b = I.build_instruction_bundle(mode="private", character=self.card_id)
        house = next(t for layer, t in I.layer_texts("work", self.card_id) if layer.id == "house_memory")
        b = dict(b, text=b["text"] + "\n\n" + house)
        with mock.patch.object(I, "_budget", return_value=100000):
            self.assertEqual(I.context_alerts(b, self.card_id), [{"kind": "leak", "layers": ["house_memory"]}])

    def test_the_turn_writes_each_alert(self):
        import obslog
        import session as S
        from unittest import mock
        s = S.AgentSession.__new__(S.AgentSession)
        s.sid, s.provider, s.mode, s.character = "sid-1", "agy", "work", self.card_id
        b = I.build_instruction_bundle(character=self.card_id)
        with mock.patch.object(obslog, "event") as ev, mock.patch.object(I, "_budget", return_value=10):
            s._log_context(b)
        alert = [c for c in ev.call_args_list if c.args[0] == "context.alert"]
        self.assertEqual(len(alert), 1)
        self.assertEqual((alert[0].kwargs["kind"], alert[0].kwargs["lvl"], alert[0].kwargs["limit"]), ("over_budget", "warn", 10))

    def test_the_bundles_keep_their_bytes(self):
        got = {}
        for mode in I.BOTH:
            text = I.build_instruction_bundle(mode=mode, character=self.card_id)["text"]
            got[mode] = hashlib.sha256(text.replace(str(self.ws), "<ws>").replace(self.card_id, "<cid>")
                                       .encode("utf-8")).hexdigest()[:16]
        self.assertEqual(got, GOLDEN, "the bundle text changed: every live session re-injects it. If that is on "
                                      "purpose, update GOLDEN in the same change and say so in DEVLOG")


GOLDEN = {"work": "f1e31d0d9e9dd0c6", "private": "4163fdd265f019f3"}   # = the code before lca/A (checked)


if __name__ == "__main__":
    unittest.main()
