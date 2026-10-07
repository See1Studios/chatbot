"""Dev and shipped instructions never mix (DEV_SPLIT_v1, prop/G; operator 2026-10-07). Both builds read one charter, the
shipped one (templates/workspace/AGENTS.md). The dev build's own rules live only in DEV-CHARTER.md
(templates/dev-workspace/), and the engine adds them as their own layer only when host_config.EDITION is dev. So:
a shipped bundle carries no dev rule and no dev word, even from the engine's own notes; a private bundle never takes
the dev layer; and neither file repeats the other, so the charter cannot fork again.
Run: python3 -m unittest tests.test_edition_instructions  (from services/chatbot)
"""
import re
import shutil
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import characters as C  # noqa: E402
import host_config  # noqa: E402
import instructions as I  # noqa: E402
from tests.test_instructions import WorkspaceCase, _write  # noqa: E402

SHIPPED = ROOT / "templates" / "workspace"
DEV = ROOT / "templates" / "dev-workspace"
# words only the dev build's machinery has: a shipped agent that reads them is told about tools it does not have
DEV_WORDS = re.compile(r"ticket|delegat|run-tests|--no-verify|engine code|\bgit\b|roles/dev|DEV-CHARTER", re.I)


def _bundles(cid):
    return {m: I.build_instruction_bundle(mode=m, character=cid)["text"] for m in I.BOTH}


class DevLayer(WorkspaceCase):
    def setUp(self):
        super().setUp()
        _write(self.ws / "DEV-CHARTER.md", "# Dev build rules\nDEV-RULE-MARK")

    def test_a_shipped_install_never_takes_the_dev_rules_even_when_the_file_is_there(self):
        with mock.patch.object(host_config, "EDITION", "shipped"):
            for mode, text in _bundles(self.card_id).items():
                self.assertNotIn("DEV-RULE-MARK", text, mode)

    def test_the_dev_build_takes_them_in_work_after_the_charter_and_never_in_private(self):
        with mock.patch.object(host_config, "EDITION", "dev"):
            got = _bundles(self.card_id)
        self.assertIn("DEV-RULE-MARK", got["work"])
        self.assertLess(got["work"].index("CHARTER-MARK"), got["work"].index("DEV-RULE-MARK"))
        self.assertNotIn("DEV-RULE-MARK", got["private"])
        ids = [layer.id for layer in I.LAYERS]
        self.assertEqual(ids[ids.index("charter") + 1], "dev_charter")


class ShippedBundle(WorkspaceCase):
    """The bundle a fresh shipped install builds from the real shipped templates."""

    def setUp(self):
        super().setUp()
        shutil.copytree(str(SHIPPED), str(self.ws), dirs_exist_ok=True)
        _write(self.ws / "DEV-CHARTER.md", "Dev rules: tickets and git.")   # present, yet never read when shipped

    def test_it_carries_no_dev_word_with_or_without_a_role(self):
        for roles in ([], ["art"]):
            C.save_team({"default": self.card_id, "members": {self.card_id: roles}}, self.ws)
            with mock.patch.object(host_config, "EDITION", "shipped"):
                for mode, text in _bundles(self.card_id).items():
                    hit = DEV_WORDS.search(text)
                    self.assertIsNone(hit, "%s bundle (roles %s) says %r: %s" % (
                        mode, roles, hit and hit.group(0), text[max(0, hit.start() - 80):hit.end() + 40] if hit else ""))


class TwoFiles(unittest.TestCase):
    def test_there_is_one_charter(self):
        self.assertTrue((SHIPPED / "AGENTS.md").is_file())
        self.assertFalse((DEV / "AGENTS.md").exists(), "templates/dev-workspace/AGENTS.md would be a second charter: "
                                                        "put dev rules in DEV-CHARTER.md")
        self.assertTrue((DEV / "DEV-CHARTER.md").is_file())

    def test_a_shipped_role_names_only_skills_that_ship(self):
        # 2026-10-07: the shipped art pack equipped image-brief, character-art and character-pipeline, all dev only
        shipped = {p.parent.name for p in (SHIPPED / ".agents" / "skills").glob("*/SKILL.md")}
        for role_md in sorted((SHIPPED / "roles").glob("*/ROLE.md")):
            role = role_md.parent.name
            named = set(C.role_pack(role, SHIPPED)["skills"])
            named |= set(re.findall(r"skill `([\w-]+)`", role_md.read_text(encoding="utf-8")))
            self.assertEqual(sorted(named - shipped), [], "templates/workspace/roles/%s names skills a shipped install "
                                                          "does not have" % role)

    def test_neither_file_repeats_the_other(self):
        def lines(p):
            return {l.strip() for l in p.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")}
        shared = lines(SHIPPED / "AGENTS.md") & lines(DEV / "DEV-CHARTER.md")
        self.assertEqual(sorted(shared), [], "a line in both the charter and DEV-CHARTER.md: keep it in one")


if __name__ == "__main__":
    unittest.main()
