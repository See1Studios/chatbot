---
name: fact-check
description: Verifies claims, news, quotes, and statistics using an academic taxonomy (True to False, Missing Context, etc.) with Tier 1/2 evidence.
---

# Fact-Check Skill

## When to use
Activate when the user asks to verify, fact-check, analyze authenticity, or investigate claims, news, statistics, quotes, or media.

## Rating Taxonomy
- **True**: The claim is entirely accurate and supported by conclusive Tier 1/2 evidence.
- **Mostly True**: The core statement is accurate, though minor details may lack precision without distorting the overall truth.
- **Half True**: Partially accurate, but omits important context or mixes facts with unsubstantiated claims.
- **Mostly False**: Contains a small element of truth but ignores primary facts, yielding a misleading narrative.
- **False**: Entirely inaccurate and directly contradicted by authoritative Tier 1/2 evidence.
- **Missing Context**: Individual facts/data are technically accurate but presented deceitfully or via logical fallacies.
- **Misattributed / Miscaptioned**: Authentic content falsely attributed to the wrong person, period, or location.
- **Outdated**: Factual at the time of publication but invalidated by subsequent developments.
- **Unverifiable**: Insufficient credible, public evidence available to definitively prove or disprove.

## Evidence Hierarchy
- **Tier 1 (Authoritative):** Primary documents, peer-reviewed journals, official regulatory filings, official statements from direct subjects.
- **Tier 2 (Credible Secondary):** Established major news outlets, recognized institutional research centers, dedicated fact-checking organizations.

## Workflow
1. **Isolate Claim:** Deconstruct the user query into specific, verifiable factual propositions.
2. **Gather Evidence:** Search authoritative sources (prefer Tier 1/2).
3. **Determine Verdict:** Assign exactly one rating from the taxonomy.
4. **Format Output:** Present in formal, objective, academic Korean.

## Output Format Directive (Strictly Korean)
```markdown
### 팩트체크 판정: [판정 등급]

* **검증 대상 주장:** <명확히 정리된 검증 대상 명제>
* **핵심 판정 요약:** <1~2문장의 핵심 근거 요약>

#### 사실 대조 및 분석
- **공식/확인된 사실:** <Tier 1/2 근거 기반 객관적 사실>
- **왜곡/누락된 지점:** <맥락 왜곡, 시점 불일치, 논리적 비약 등 구체적 설명>

#### 검증 출처
- [출처명/기관명](URL 또는 발행처)
```
