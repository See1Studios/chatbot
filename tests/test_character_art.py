"""Character images follow one format (CHARACTER_ART_v1, skill `character-art`): a 512 avatar, optional wigs per
provider, optional transparent bust/full sprites per expression with `neutral` first, and a visual.md lock sheet.
Run: engine/run-tests.sh test_character_art
"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from tests._paths import ENGINE  # noqa: E402
sys.path.insert(0, str(ENGINE))
import characters as C  # noqa: E402
from tests._paths import REPO  # noqa: E402

try:
    from PIL import Image
except ImportError:  # the checker skips sizes without Pillow; so does this test
    Image = None

ROOT = REPO


@unittest.skipIf(Image is None, "Pillow not installed")
class ArtFormat(unittest.TestCase):
    def setUp(self):
        self.ws = Path(tempfile.mkdtemp()).resolve()
        self.cid = C.new_id()
        C.save(self.cid, C.new_card("L", "staff"), self.ws)
        self.base = C.card_path(self.cid, self.ws).parent

    def tearDown(self):
        shutil.rmtree(self.ws, ignore_errors=True)

    def img(self, rel, size, alpha=False):
        path = self.base / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGBA" if alpha else "RGB", size).save(path)

    def check(self):
        return C.check_art(self.cid, ["agy", "claude"], self.ws)

    def test_a_new_character_needs_its_avatar_and_lock_sheet(self):
        self.assertEqual(self.check(), ["avatar.webp is missing (the base look)",
                                        "visual.md is missing (the visual lock sheet)"])
        self.img("avatar.webp", (512, 512))
        (self.base / "visual.md").write_text("# L\n", encoding="utf-8")
        self.assertEqual(self.check(), [])

    def test_wigs_and_sprites(self):
        self.img("avatar.webp", (512, 512))
        (self.base / "visual.md").write_text("# L\n", encoding="utf-8")
        self.img("avatar/agy.webp", (512, 512))
        self.img("avatar/nope.webp", (512, 512))
        self.img("avatar/claude.webp", (256, 256))
        self.img("sprites/bust/joy.webp", (1024, 1024), alpha=True)
        self.img("sprites/full/neutral.webp", (1024, 2048), alpha=False)
        self.img("sprites/full/grin.webp", (1024, 2048), alpha=True)
        self.img("sprites/side/neutral.webp", (1024, 1024), alpha=True)
        self.img("sprites/full/joy.png", (1024, 2048), alpha=True)
        self.img("stage/agy.webp", (1024, 1024))
        self.img("stage/claude.webp", (512, 512))
        self.assertEqual(sorted(self.check()), sorted([
            "avatar/nope.webp: unknown provider 'nope'",
            "avatar/claude.webp: 256x256, must be 512x512",
            "sprites/side: unknown framing (bust, full)",
            "sprites/bust/neutral.webp is missing (required once a framing exists)",
            "sprites/full/neutral.webp: needs a transparent background",
            "sprites/full/grin.webp: unknown expression 'grin'",
            "sprites/full/joy.png: a .png master needs its .webp beside it (the page serves .webp)",
            "stage/claude.webp: 512x512, must be 1024x1024",
        ]))

    def test_avatar_empty_corner_padding_is_rejected(self):
        (self.base / "visual.md").write_text("# L\n", encoding="utf-8")
        from PIL import ImageDraw
        badge = Image.new("RGB", (512, 512), (255, 255, 255))
        ImageDraw.Draw(badge).ellipse((8, 8, 503, 503), fill=(200, 80, 80))
        badge.save(self.base / "avatar.webp")
        self.assertIn(
            "avatar.webp: empty corner padding; fill the square so the face reads in a 56px circle",
            self.check(),
        )
        Image.new("RGB", (512, 512), (40, 40, 40)).save(self.base / "avatar.webp")
        self.assertEqual(self.check(), [])

    def test_the_skill_and_the_code_agree(self):
        skill = (ROOT / "templates/dev-workspace/.agents/skills/character-art/SKILL.md").read_text(encoding="utf-8")
        for framing, ((w, h), _, _) in C.FRAMINGS.items():
            self.assertIn("sprites/%s/<label>.webp` | %dx%d" % (framing, w, h), skill)
        self.assertIn("512x512", skill)
        for label in C.EXPRESSIONS:
            self.assertIn(label, skill)


if __name__ == "__main__":
    unittest.main()
