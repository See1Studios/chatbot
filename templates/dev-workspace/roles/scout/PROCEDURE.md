# Scout procedure

Read before research and scouting work. The every-turn part is `ROLE.md`.

## Where to look
- Communities: Reddit (`r/SillyTavern`, `r/LocalLLaMA`, `r/Chub_AI`), GitHub Trending, HuggingFace RP/reasoning models.
- Prior art and concepts: `VISION.md`, `~/wiki/concepts/`, `~/wiki/trends/`. Check existing knowledge before scouting to avoid duplicate work.

## Research workflow
1. **Scope and isolate**: Take the brief from {{default}} or {{user}}. Clarify the core question, target tools, or communities before crawling.
2. **Verify facts**: Use the `web` tool to read primary documentation, releases, or issue discussions. Use skill `fact-check` on community rumors or benchmark claims.
3. **Filter noise**: Discard marketing fluff, vanity forks, and low-signal drama. Focus on actual user friction (pain points), architectural breakthroughs, and UX patterns.
4. **Synthesize**: Every finding ends with:
   - **Verdict**: 1-sentence bottom line.
   - **Core analysis**: 3 concise bullet points explaining what it is and why users care.
   - **PE angle**: Concrete integration points, opportunities, or risks for our engine.
5. **Knowledge documentation**: Write lasting findings to `~/wiki/trends/` or `~/wiki/concepts/` using standard markdown wiki format.
