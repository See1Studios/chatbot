#!/usr/bin/env python3
"""
Custom Character Chat Engine (Chatbot-native provider integration)

SimCore State Machine + Character Roleplaying Engine.
Completely decoupled and independent from external character-chat service (port 3013).
Uses chatbot's native provider infrastructure (default: agy CLI, or configurable model).
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import yaml
from pathlib import Path

# Paths
DEFAULT_AGY = "/volume1/homes/me/.local/bin/agy"
AGY_BIN = os.environ.get("AGY_BIN", DEFAULT_AGY)
DEFAULT_MODEL = "gemini-3.8-flash-low"
AGY_TIMEOUT_SEC = 60
STATE_DIR = Path("/volume1/homes/me/services/chatbot/data/workspace/.agents/skills/character-chat/sessions")


def load_character(yaml_path: str) -> dict:
    p = Path(yaml_path)
    if not p.is_file():
        # Check standard data/characters directory
        alt = Path("/volume1/homes/me/data/characters") / f"{p.stem}.yaml"
        if alt.is_file():
            p = alt
        else:
            raise FileNotFoundError(f"Character YAML not found: {yaml_path}")
    with open(p, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    data["_id"] = p.stem
    return data


def resolve_model_tier(model_name: str) -> str:
    """Resolve model to prompt tier: high, balanced, or light_enforced."""
    name = (model_name or "").lower()
    if any(k in name for k in ["opus", "sonnet", "pro", "gpt-4"]):
        return "high"
    if any(k in name for k in ["openrouter", "deepseek", "qwen", "mistral", "llama", "mini", "flash"]):
        if "openrouter" in name or any(k in name for k in ["qwen", "mistral", "llama", "deepseek-r1-distill", "8b", "7b"]):
            return "light_enforced"
        return "balanced"
    return "balanced"


def build_system_instruction(spec: dict, model_name: str = DEFAULT_MODEL) -> str:
    persona = spec.get("persona", {})
    guidelines = spec.get("guidelines", [])
    guideline_text = "\n".join(f"- {g}" for g in guidelines)
    speech_styles = "\n".join(f"- {s}" for s in persona.get("speech_style", []))

    lore_entries = spec.get("lorebook", [])
    lore_text = ""
    if lore_entries:
        lines = []
        for entry in lore_entries:
            kw = ", ".join(entry.get("keywords", []))
            content = entry.get("content", "")
            lines.append(f"- [키워드: {kw}] {content}")
        lore_text = "\n# LOREBOOK & CONTEXT\n" + "\n".join(lines) + "\n"

    tier = resolve_model_tier(model_name)
    tier_instructions = ""
    if tier == "light_enforced":
        tier_instructions = """
# CRITICAL FORMAT & BEHAVIOR CONSTRAINTS (오픈라우터/경량 모델 엄격 준수)
1. [표정 태그 단일화]: `[expression: neutral]` 등 표정 태그는 오직 전체 응답의 '맨 첫 줄 맨 처음'에 단 1번만 붙입니다. 문장 중간이나 끝에 태그를 반복하지 마십시오.
2. [상대방 말 되받기(Echoing) 금지]: 실장님의 질문이나 마지막 단어를 그대로 되묻거나 흉내 내지 마십시오. (예: "옆에 앉아도 돼?"라는 말에 "옆에 앉아도 돼요?"라고 되묻기 금지)
3. [자문자답 및 1인 다역 금지]: 혼자 묻고 혼자 답하지 마십시오. 1턴에 하나의 명확한 감정 반응과 대사만 건네십시오.
4. [지문 간결화]: 괄호 안의 행동 묘사는 1~2문장으로 짧게 작성하고 곧바로 대사로 넘어가십시오.

[모범 응답 샘플 (One-Shot Example)]
[expression: shy] (가방을 살짝 끌어당겨 무릎 위에 올려놓으며 옆자리를 비워준다.)
"…네, 괜찮아요. 여기 앉으세요."
"""
    elif tier == "balanced":
        tier_instructions = """
# FORMAT CONSTRAINTS
- 표정 태그 `[expression: ...]`는 응답 맨 첫머리에 1회만 붙입니다. 문장마다 남발하지 마십시오.
- 실장님의 질문을 그대로 되받아치는(Echoing) 불필요한 반복을 삼가십시오.
"""

    return f"""# ROLE & IDENTITY
이름: {spec.get('name')}
역할: {persona.get('role')}
말투 및 톤: {persona.get('tone')}
말투 특징:
{speech_styles}
배경 및 성격: {persona.get('background')}
{lore_text}
# CORE BEHAVIOR & GUIDELINES (SimCore 규격)
{guideline_text}
- 대사 시작 시 표정/모션 연동 태그: 응답 맨 첫머리에 반드시 `[expression: neutral|joy|shy|serious|sorrow|tired]` 중 하나를 붙여 시작하십시오. (예: `[expression: joy] 오늘 일정 말씀이신가요?`)
- Gemini 특유의 상투적 무드 라벨링('서늘한', '기괴한', '어두운 미소' 등)을 일절 금지합니다.
- 3rd Deep POV: 서술자는 캐릭터의 1인칭 감각과 내면 독백(thought)에 깊게 밀착하되 지문은 3인칭으로 간결하게 작성합니다.
{tier_instructions}
# SIMCORE STATE TRACKING PROTOCOL
당신은 대화를 나눌 때마다 내면의 심리 상태를 갱신합니다.
매 턴의 응답 맨 마지막에 반드시 아래 형식의 JSON 블록을 단 하나만 포함해야 합니다:
```state
{{
  "affinity_delta": -10 ~ +10 사이의 호감도 변화량 (정수),
  "stress_delta": -10 ~ +10 사이의 스트레스 변화량 (정수),
  "mood": "현재 턴 직후의 감정 요약 (예: 차분함, 조금 기쁨, 당황, 의아함, 피곤함 등)",
  "thought": "겉으로 드러내지 않는 1줄 속마음 독백 (3rd Deep POV 관점)"
}}
```"""


class NativeCharacterSession:
    def __init__(self, character_path: str, session_id: str = None, model: str = DEFAULT_MODEL):
        self.spec = load_character(character_path)
        self.char_id = self.spec.get("_id", "character")
        self.model = model
        self.session_id = session_id or f"{self.char_id}-{int(time.time())}"
        self.session_file = STATE_DIR / f"{self.session_id}.json"
        
        # Initial SimCore state
        default_state = {
            "affinity": 10,
            "stress": 15,
            "mood": "보통",
            "act": 1,
            "turn_count": 0,
            "current_location": "기본 장소",
        }
        spec_state = self.spec.get("state") or {}
        default_state.update(spec_state)
        self.state = default_state
        self.conversation_id = None
        self.history = []
        self._load_session()

    def _load_session(self):
        if self.session_file.exists():
            try:
                data = json.loads(self.session_file.read_text(encoding="utf-8"))
                self.state = data.get("state", self.state)
                self.conversation_id = data.get("conversation_id")
                self.history = data.get("history", [])
            except Exception:
                pass

    def save_session(self):
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        data = {
            "session_id": self.session_id,
            "char_id": self.char_id,
            "model": self.model,
            "conversation_id": self.conversation_id,
            "state": self.state,
            "history": self.history[-100:],
            "updated_at": time.time(),
        }
        self.session_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _call_provider(self, prompt: str) -> str:
        cmd = [
            AGY_BIN,
            "-p", prompt,
            "--model", self.model,
            "--effort", "low",
        ]
        if self.conversation_id:
            cmd.extend(["--conversation", self.conversation_id])

        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=AGY_TIMEOUT_SEC)
        if res.returncode != 0:
            raise RuntimeError(f"Provider call failed: {res.stderr.strip() or res.stdout.strip()}")

        # Look for conversation id in stderr or output
        for line in res.stderr.splitlines():
            if "Conversation:" in line or "conversation_id:" in line:
                m = re.search(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", line, re.I)
                if m:
                    self.conversation_id = m.group(1)

        return res.stdout.strip()

    def _parse_state_block(self, raw_text: str):
        state_match = re.search(r"```(?:state|json)?\s*(\{.*?\})\s*```", raw_text, re.DOTALL)
        if state_match:
            try:
                data = json.loads(state_match.group(1))
                dialogue = raw_text[:state_match.start()].strip()
                return dialogue, data
            except json.JSONDecodeError:
                pass

        # Fallback regex for state fields
        return raw_text.strip(), None

    def send_message(self, user_msg: str) -> dict:
        self.state["turn_count"] = self.state.get("turn_count", 0) + 1

        # Act progression
        if self.state.get("affinity", 0) >= 50 and self.state.get("act", 1) < 3:
            self.state["act"] = 3
        elif self.state.get("affinity", 0) >= 25 and self.state.get("act", 1) < 2:
            self.state["act"] = 2

        current_state_prompt = (
            f"[현재 시스템 상태] Act: {self.state['act']} | "
            f"호감도: {self.state['affinity']} | 스트레스: {self.state['stress']} | "
            f"현재 기분: {self.state['mood']} | 장소: {self.state.get('current_location', '연구실')}"
        )

        if not self.conversation_id:
            sys_inst = build_system_instruction(self.spec, model_name=self.model)
            prompt = f"{sys_inst}\n\n{current_state_prompt}\n\n[실장님의 메시지]\n{user_msg}"
        else:
            prompt = f"{current_state_prompt}\n\n[실장님의 메시지]\n{user_msg}"

        raw_output = self._call_provider(prompt)
        dialogue, state_delta = self._parse_state_block(raw_output)

        thought = ""
        if state_delta:
            aff_delta = int(state_delta.get("affinity_delta", 0))
            str_delta = int(state_delta.get("stress_delta", 0))
            self.state["affinity"] = max(-100, min(100, self.state["affinity"] + aff_delta))
            self.state["stress"] = max(0, min(100, self.state["stress"] + str_delta))
            self.state["mood"] = state_delta.get("mood", self.state["mood"])
            thought = state_delta.get("thought", "")

        self.history.append({"role": "user", "content": user_msg, "ts": time.time()})
        self.history.append({
            "role": "assistant",
            "content": dialogue,
            "thought": thought,
            "state_delta": state_delta,
            "ts": time.time(),
        })
        self.save_session()

        return {
            "dialogue": dialogue,
            "thought": thought,
            "state_delta": state_delta,
            "state": self.state,
            "session_id": self.session_id,
        }


def main():
    parser = argparse.ArgumentParser(description="Chatbot Native Character Chat Engine")
    parser.add_argument("character", help="Character YAML file or name (e.g. yerin)")
    parser.add_argument("message", nargs="?", default="", help="Message to send")
    parser.add_argument("--session", default=None, help="Session ID to resume")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Model name")
    parser.add_argument("--status", action="store_true", help="Print current status only")
    args = parser.parse_args()

    session = NativeCharacterSession(args.character, session_id=args.session, model=args.model)
    if args.status:
        print(json.dumps({
            "session_id": session.session_id,
            "character": session.spec.get("name"),
            "state": session.state,
            "turns": len(session.history) // 2,
        }, ensure_ascii=False, indent=2))
        return

    if not args.message:
        print("Error: No message provided.", file=sys.stderr)
        sys.exit(1)

    result = session.send_message(args.message)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
