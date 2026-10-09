"""Summon wizard REST (cgs/F).

One card format, the one card_gen already weaves: chara_card_v2 plus visual.md.
Wizard choices overwrite the model on the fields the person actually picked.
The page reads step copy from engine_data/summon_steps.json; this module does not
own a second card shape and does not take a filesystem path from the request.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

import card_prompt
import characters
from tools import card_gen

STEPS_PATH = Path(__file__).resolve().parent / "engine_data" / "summon_steps.json"
IDEA_MAX = 500
NAME_MAX = 40
TITLE_MAX = 24
KEY_MAX = 8
LLM_TIMEOUT = 45
PROFILES = ("short", "detailed", "verbose")
ALIASES = {"first_mes": "first_message", "mes_example": "message_examples"}
LLM = None  # tests inject a callable; None means the live adapter, bounded


def public_spec() -> Dict[str, Any]:
    return json.loads(STEPS_PATH.read_text(encoding="utf-8"))


def _step(spec: Dict[str, Any], sid: str) -> Dict[str, Any]:
    for step in spec.get("steps") or []:
        if step.get("id") == sid:
            return step
    return {}


def _opt(step: Dict[str, Any], oid: str) -> Dict[str, Any]:
    for opt in step.get("options") or []:
        if opt.get("id") == oid:
            return opt
    return {}


def _one_line(val: Any, limit: int) -> str:
    return " ".join(str(val or "").split())[:limit]


def _fill(template: str, **parts: str) -> str:
    text = template or ""
    for key, val in parts.items():
        text = text.replace("{" + key + "}", val)
    return text


def bounded(call: Callable[[str, str], str], timeout: int = LLM_TIMEOUT) -> Callable[[str, str], str]:
    """Stop a stuck adapter from holding the request open. The call may still finish later."""

    def wrapped(system: str, user: str) -> str:
        box: Dict[str, Any] = {}

        def run() -> None:
            try:
                box["text"] = call(system, user)
            except Exception as exc:  # noqa: BLE001 — the caller decides fallback vs error
                box["err"] = exc

        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        worker.join(timeout)
        if worker.is_alive():
            raise TimeoutError("card weave timed out")
        if "err" in box:
            raise box["err"]
        return str(box.get("text") or "")

    return wrapped


def resolve_call(passed: Optional[Callable[[str, str], str]]) -> Callable[[str, str], str]:
    if passed is not None:
        return passed
    if LLM is not None:
        return LLM
    return bounded(card_gen._call_provider_adapter)


def normalize(body: Dict[str, Any], spec: Dict[str, Any]) -> Dict[str, Any]:
    raw = body.get("choices")
    raw = raw if isinstance(raw, dict) else {}
    idea = body.get("idea")
    if idea is None:
        idea = raw.get("idea")
    look_step = _step(spec, "look")
    look = str(raw.get("look") or body.get("look") or "")
    if not _opt(look_step, look):
        look = str(look_step.get("recommended") or "")
    pstep = _step(spec, "personality")
    picked = raw.get("personality")
    if picked is None:
        picked = body.get("personality")
    if isinstance(picked, str):
        picked = [picked]
    if not isinstance(picked, list):
        picked = []
    personality = [str(p) for p in picked if _opt(pstep, str(p))]
    if not personality:
        personality = [str(p) for p in (pstep.get("recommended") or [])]
    vstep = _step(spec, "voice")
    voice = str(raw.get("voice") or body.get("voice") or "")
    if not _opt(vstep, voice):
        voice = str(vstep.get("recommended") or "")
    bstep = _step(spec, "bond")
    bond = str(raw.get("bond") or body.get("bond") or "")
    if not _opt(bstep, bond):
        bond = str(bstep.get("recommended") or "")
    name = raw.get("name") if "name" in raw else body.get("name")
    if name is None or not str(name).strip():
        name = _step(spec, "name").get("recommended") or ""
    title = raw.get("user_title") if "user_title" in raw else body.get("user_title")
    if title is None or not str(title).strip():
        title = _opt(bstep, bond).get("title") or bstep.get("title_recommended") or ""
    profile = str(body.get("profile") or "short")
    return {
        "idea": _one_line(idea, IDEA_MAX),
        "look": look,
        "personality": personality,
        "voice": voice,
        "bond": bond,
        "name": _one_line(name, NAME_MAX),
        "user_title": _one_line(title, TITLE_MAX),
        "profile": profile if profile in PROFILES else "short",
    }


def compose_idea(choices: Dict[str, Any]) -> str:
    base = "Summon a friend named %s. look=%s personality=%s voice=%s bond=%s. The user is called %s." % (
        choices["name"], choices["look"], ",".join(choices["personality"]),
        choices["voice"], choices["bond"], choices["user_title"])
    extra = choices["idea"]
    return ((extra + "\n" + base) if extra else base)[:IDEA_MAX]


def apply_choices(fields: Dict[str, Any], spec: Dict[str, Any], choices: Dict[str, Any]) -> Dict[str, Any]:
    """The person's picks win. A model may fill only what they left open."""
    fields = dict(fields or {})
    look = _opt(_step(spec, "look"), choices["look"])
    look_card = str(look.get("card") or "")
    desc = str(fields.get("description") or "").strip()
    if look_card and look_card not in desc:
        fields["description"] = (look_card + ("\n\n" + desc if desc else "")).strip()
    if look.get("image") and card_gen.is_field_empty(fields.get("image_prompt")):
        fields["image_prompt"] = str(look["image"])
    labels, bits = [], []
    for pid in choices["personality"]:
        opt = _opt(_step(spec, "personality"), pid)
        if not opt:
            continue
        labels.append(str(opt.get("label") or pid))
        if opt.get("card"):
            bits.append(str(opt["card"]))
    if bits:
        fields["personality"] = " ".join(bits)
    if labels:
        fields["tags"] = labels
    voice = _opt(_step(spec, "voice"), choices["voice"])
    bond = _opt(_step(spec, "bond"), choices["bond"])
    # #899: the example follows both picks (bond x voice) and keeps {{user}}/{{char}} -- SillyTavern's macros, which
    # the engine resolves when a prompt is built; filling the names in here broke the card format
    example = str((bond.get("examples") or {}).get(choices["voice"]) or voice.get("example") or "")
    if example:
        fields["message_examples"] = example
    fields["voice"] = str(voice.get("card") or "")
    if bond.get("scenario"):
        fields["scenario"] = str(bond["scenario"])
    fields["name"] = choices["name"]
    if card_gen.is_field_empty(fields.get("first_message")) and card_gen.is_field_empty(fields.get("first_mes")):
        fields["first_message"] = _fill(
            str(spec.get("greeting") or "{name}"),
            name=choices["name"], user_title=choices["user_title"],
            hook=str((bond.get("hooks") or {}).get(choices["voice"]) or bond.get("hook") or ""))
    return fields


def weave(idea: str, choices: Dict[str, Any], llm_call: Optional[Callable[[str, str], str]]) -> Tuple[Dict[str, Any], bool]:
    if llm_call is None:
        return {}, False
    try:
        data = card_gen.generate_card_data(idea, llm_call, profile=choices["profile"])
    except Exception:  # noqa: BLE001 — a failed weave still summons from the picks
        return {}, False
    return (data if isinstance(data, dict) else {}), bool(data)


def _has_card(cid: str, ws: Any) -> bool:
    try:
        return bool(cid) and characters.card_path(cid, ws).is_file()
    except ValueError:
        return False


def roster_add(cid: str, ws: Any) -> None:
    """Join the roster. Become the default only when the roster has none."""
    team = characters.load_team(ws)
    members = dict(team["members"])
    members.setdefault(cid, [])
    default = team["default"] if _has_card(team["default"], ws) else cid
    characters.save_team({"default": default, "members": members}, ws)


def summon(body: Any, llm_call: Optional[Callable[[str, str], str]] = None, ws: Any = None) -> Tuple[int, Dict[str, Any]]:
    if not isinstance(body, dict):
        return 400, {"ok": False, "error": "json object required"}
    spec = public_spec()
    choices = normalize(body, spec)
    if not choices["name"]:
        return 400, {"ok": False, "error": "name required"}
    fields, woven = weave(compose_idea(choices), choices, llm_call)
    fields = apply_choices(fields, spec, choices)
    if card_gen.is_field_empty(fields.get("negative_prompt")):
        fields["negative_prompt"] = card_prompt.DEFAULT_NEGATIVE_PROMPT
    voice = str(fields.pop("voice", "") or "")
    card = card_gen.build_chara_v2_card(fields, user_title=choices["user_title"], voice=voice)
    cid = characters.new_id()
    visual = card_gen.build_visual_md(choices["name"], cid, card=fields)
    card_gen.save_character_package(card, visual, ws=ws, cid=cid)
    roster_add(cid, ws)
    data = card["data"]
    return 200, {"ok": True, "id": cid, "name": data.get("name") or choices["name"],
                 "first_mes": data.get("first_mes") or "", "woven": woven}


def _keys(body: Dict[str, Any]) -> Tuple[Optional[list], Optional[str]]:
    keys = body.get("keys")
    if isinstance(keys, str):
        keys = [keys]
    if not isinstance(keys, list) or not keys:
        return None, "keys required"
    norm = []
    for key in keys:
        key = ALIASES.get(str(key), str(key))
        if key not in card_prompt.CARD_FIELDS:
            return None, "unknown key"
        if key not in norm:
            norm.append(key)
    if len(norm) > KEY_MAX:
        return None, "too many keys"
    return norm, None


def regenerate(cid: str, body: Any, llm_call: Optional[Callable[[str, str], str]], ws: Any = None) -> Tuple[int, Dict[str, Any]]:
    if not isinstance(body, dict):
        return 400, {"ok": False, "error": "json object required"}
    if not characters.ID_RE.match(cid or ""):
        return 400, {"ok": False, "error": "character required"}
    keys, err = _keys(body)
    if err:
        return 400, {"ok": False, "error": err}
    try:
        card = characters.load(cid, ws)
    except (OSError, ValueError):
        return 404, {"ok": False, "error": "no such character"}
    if llm_call is None:
        return 502, {"ok": False, "error": "weave failed"}
    idea = _one_line(body.get("idea") or "", IDEA_MAX) or "Regenerate the named fields."
    profile = str(body.get("profile") or "short")
    if profile not in PROFILES:
        profile = "short"
    try:
        patch = card_gen.regenerate_fields(idea, card, keys, llm_call, profile=profile)
    except Exception:  # noqa: BLE001
        return 502, {"ok": False, "error": "weave failed"}
    if not patch:
        return 502, {"ok": False, "error": "weave failed"}
    card_gen.apply_patch(card, patch)
    characters.save(cid, card, ws)
    return 200, {"ok": True, "id": cid, "changed": sorted(patch)}


def handle_summon(body: Any, llm_call: Optional[Callable[[str, str], str]] = None, ws: Any = None) -> Tuple[int, Dict[str, Any]]:
    return summon(body, resolve_call(llm_call), ws)


def handle_regenerate(cid: str, body: Any, llm_call: Optional[Callable[[str, str], str]] = None, ws: Any = None) -> Tuple[int, Dict[str, Any]]:
    return regenerate(cid, body, resolve_call(llm_call), ws)
