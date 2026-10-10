"""Touch adaptation for the chat UI (impeccable adapt).

Visible text fields stay at 16px so a phone does not zoom the page. The
typing stop chip is a 24px control. Session-nav and shell icon buttons keep
their drawn size and grow the hit area with an outset. The touch composer
row, including a short screen and an open keyboard, is 38px.

Run: engine/run-tests.sh test_a11y_adapt
"""
import re
import unittest
from pathlib import Path

from tests._paths import REPO  # noqa: E402

STATIC = REPO / "static"


def text(name):
    return (STATIC / name).read_text(encoding="utf-8")


def block(css, selector):
    m = re.search(r"(?m)^[ \t]*" + re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert m, selector
    return m.group(1)


def prop(body, name):
    m = re.search(r"(?:^|[;\s])" + re.escape(name) + r"\s*:\s*([^;!]+)", body)
    return m.group(1).strip() if m else None


def px(value):
    m = re.fullmatch(r"(-?\d+)px", value or "")
    assert m, value
    return int(m.group(1))


class VisibleFieldsStay16(unittest.TestCase):
    def test_the_named_fields_are_16px(self):
        panes = text("chat-panes.css")
        for sel in (
            ".status-edit-area",
            ".card-input,.card-textarea",
            ".obs-form select,.obs-form input",
            ".status-mcp-add input",
            ".card-input,.card-textarea,.status-edit-area",
        ):
            self.assertEqual(prop(block(panes, sel), "font-size"), "16px", sel)
        shell = text("shell.css")
        self.assertEqual(prop(block(shell, ".shell-field-input,.shell-field-textarea"), "font-size"), "16px")

    def test_the_composer_input_never_drops_below_16px(self):
        panes = text("chat-panes.css")
        phone = panes[panes.index("@media (max-width: 640px)"):]
        self.assertEqual(prop(block(phone, "#input"), "font-size"), "16px")
        resp = text("chat-responsive.css")
        short = resp[resp.index("@media (max-height: 500px)"):]
        self.assertEqual(prop(block(short, "#input"), "font-size"), "16px")
        self.assertEqual(prop(block(resp, "body.keyboard-open #input"), "font-size"), "16px")
        self.assertNotIn("font-size:14px", resp)
        self.assertNotIn("font-size:15px", panes)


class HitAreaAtLeast24(unittest.TestCase):
    def test_the_stop_chip_box_is_24(self):
        panes = text("chat-panes.css")
        chip = block(panes, ".md-typing > #stopBtn.turn-stop-btn")
        for name in ("width", "height", "min-width", "min-height"):
            self.assertGreaterEqual(px(prop(chip, name)), 24, name)
        shell = text("shell.css")
        twin = block(shell, "html.shell2 .md-typing > .turn-stop-btn,html.shell2 .md-typing > #stopBtn")
        for name in ("width", "height", "min-width", "min-height"):
            self.assertGreaterEqual(px(prop(twin, name)), 24, name)

    def test_dense_controls_keep_their_drawing_and_outset_the_hit(self):
        cases = (
            ("chat-composer.css", ".session-nav-btn", ".session-nav-btn::after", "height"),
            ("shell.css", ".shell-icon-btn", ".shell-icon-btn::after,.shell-hero-focal-btn::after", "width"),
            ("shell.css", ".shell-hero-focal-btn", ".shell-icon-btn::after,.shell-hero-focal-btn::after", "width"),
        )
        for filename, box_sel, hit_sel, axis in cases:
            css = text(filename)
            drawn = px(prop(block(css, box_sel), axis))
            outset = -px(prop(block(css, hit_sel), "inset"))
            self.assertGreaterEqual(drawn + outset * 2, 24, box_sel)


class TouchComposerIs38(unittest.TestCase):
    def test_phone_short_and_keyboard_rows_are_38(self):
        panes = text("chat-panes.css")
        phone = panes[panes.index("@media (max-width: 640px)"):]
        for sel in ("#slashBtn", "#modelBtn", "#geoBtn, #privateBtn", "#send", "#input"):
            self.assertEqual(prop(block(phone, sel), "height"), "38px", sel)
        resp = text("chat-responsive.css")
        phone = resp[resp.index("@media (max-width: 640px) {"):]
        self.assertEqual(prop(block(phone, "#micBtn"), "height"), "38px")
        short = resp[resp.index("@media (max-height: 500px)"):]
        for sel in ("#slashBtn", "#modelBtn, #geoBtn, #privateBtn, #micBtn", "#send", "#input"):
            self.assertEqual(prop(block(short, sel), "height"), "38px", sel)
        for sel in (
            "body.keyboard-open #slashBtn",
            "body.keyboard-open #modelBtn,\nbody.keyboard-open #geoBtn,\nbody.keyboard-open #privateBtn,\nbody.keyboard-open #micBtn",
            "body.keyboard-open #send",
            "body.keyboard-open #input",
        ):
            self.assertEqual(prop(block(resp, sel), "height"), "38px", sel)
        fine = resp[resp.index("@media (max-width: 640px) and (pointer: fine)"):]
        self.assertEqual(prop(block(fine, "#input"), "height"), "42px")
        shell = text("shell.css")
        self.assertIn(
            "@media (max-width: 640px) { html.shell2 #shellPlus{width:38px;min-width:38px;height:38px;",
            shell,
        )
        self.assertIn(
            "@media (max-height: 500px) { html.shell2 #shellPlus{width:38px;min-width:38px;height:38px;",
            shell,
        )
        self.assertEqual(prop(block(shell, "html.shell2 body.keyboard-open #shellPlus"), "height"), "38px")
        self.assertNotIn("height:32px", resp)


if __name__ == "__main__":
    unittest.main()
