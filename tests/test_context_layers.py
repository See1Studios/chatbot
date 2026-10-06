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
