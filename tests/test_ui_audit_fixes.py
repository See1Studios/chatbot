"""Verification test for UI audit fixes (impeccable harden & polish).

Checks that:
1. Static HTML has no <img> without a valid src attribute and has static accessible names.
2. The service finding card uses a clean perimeter border rather than a side-tab border.
3. Hover labels on session navigation chips adhere to the theme accent contrast token.
4. Shell icon buttons and touch controls provide expanded touch target hitboxes.

Run: engine/run-tests.sh test_ui_audit_fixes
"""
import re
import unittest
from pathlib import Path

from tests._paths import REPO  # noqa: E402

STATIC = REPO / "static"


def text(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def block(css: str, selector: str) -> str:
    m = re.search(r"(?m)^[ \t]*" + re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert m, f"selector not found: {selector}"
    return m.group(1)


class TestStaticAccessibility(unittest.TestCase):
    def test_no_image_without_src(self):
        html = text("index.html")
        # Every <img> tag must include a non-empty src attribute
        imgs = re.findall(r"<img\b[^>]*>", html)
        self.assertGreater(len(imgs), 0)
        for img in imgs:
            self.assertRegex(img, r'\bsrc=["\'][^"\']+["\']', f"img missing valid src: {img}")

    def test_static_shell_buttons_have_accessible_names(self):
        html = text("index.html")
        for btn_id in ("shellNewRoom", "shellMenu", "shellBack"):
            m = re.search(rf'<button\b[^>]*id=["\']{btn_id}["\'][^>]*>', html)
            self.assertIsNotNone(m, f"button #{btn_id} not found in index.html")
            tag = m.group(0)
            self.assertTrue(
                "aria-label=" in tag or "data-i18n-aria-label=" in tag,
                f"button #{btn_id} missing accessible label: {tag}",
            )

    def test_composer_selects_have_accessible_labels(self):
        html = text("index.html")
        for sel_id in ("provider", "model"):
            m = re.search(rf'<select\b[^>]*id=["\']{sel_id}["\'][^>]*>', html)
            self.assertIsNotNone(m, f"select #{sel_id} not found in index.html")
            tag = m.group(0)
            self.assertIn("aria-label=", tag, f"select #{sel_id} missing aria-label: {tag}")


class TestCraftFloorIntegrity(unittest.TestCase):
    def test_no_side_tab_on_service_findings(self):
        css = text("chat-features.css")
        b = block(css, ".svc-finding")
        self.assertNotIn("border-left:3px", b)
        self.assertNotIn("border-left: 3px", b)
        self.assertIn("border:1px solid var(--border)", b)
        self.assertIn("border-radius:6px", b)

    def test_composer_hover_uses_accent_contrast_token(self):
        css = text("chat-composer.css")
        for sel in (".session-nav-btn.highlight:hover", ".session-switch-btn:hover"):
            b = block(css, sel)
            self.assertNotIn("color:#000", b)
            self.assertIn("color:var(--accent-contrast)", b)


class TestTouchTargetHitboxes(unittest.TestCase):
    def test_shell_icon_buttons_have_expanded_hitbox(self):
        css = text("shell.css")
        self.assertIn(".shell-btn-icon::after,.shell-pane-bar button::after,html.shell2 #shellBack::after{content:\"\";position:absolute;inset:-5px}", css)
        self.assertIn(".shell-reply button::after{content:\"\";position:absolute;inset:-9px}", css)


if __name__ == "__main__":
    unittest.main()
