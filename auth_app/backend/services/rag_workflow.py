"""
RAG-style conversational legal intake and case analysis workflow.

Implements a two-phase system:
  Phase 1 — Information Gathering: Conversational extraction of case facts
             with an internal completeness checklist. The agent asks targeted
             follow-up questions until sufficient information is collected.
  Phase 2 — Structured Analysis: Generates the final legal analysis output
             in the prescribed format once the completeness threshold is met
             or the user explicitly requests it.

The entire conversation history is the single source of truth.
"""

from __future__ import annotations

import json
import re
import sys
import time
import logging
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean
from threading import Lock
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Ensure root app directory is importable
root_dir = str(Path(__file__).resolve().parents[3])
if root_dir not in sys.path:
    sys.path.append(root_dir)

try:
    from app.llm_router import generate
except ImportError:
    generate = None

DATASET_PATH = Path(__file__).resolve().parents[3] / "data" / "case_dataset_en.json"


# ═══════════════════════════════════════════════════════════════
#  COMPLETENESS CHECKLIST — attributes tracked for Phase 1
# ═══════════════════════════════════════════════════════════════

CASE_ATTRIBUTES = {
    "relationship_type": {
        "description": "Relationship between victim and respondent",
        "priority": 1,
        "indicators": [
            r"husband", r"wife", r"partner", r"boyfriend", r"ex[\s-]",
            r"colleague", r"boss", r"in[\s-]?laws?", r"family",
            r"live[\s-]?in", r"marriage", r"married", r"spouse",
            r"relative", r"neighbou?r", r"stranger", r"landlord",
        ],
    },
    "parties_involved": {
        "description": "Who is involved (names, roles, relationships)",
        "priority": 3,
        "indicators": [
            r"mother[\s-]?in[\s-]?law", r"father[\s-]?in[\s-]?law",
            r"brother[\s-]?in[\s-]?law", r"sister[\s-]?in[\s-]?law",
            r"husband", r"wife", r"children", r"parents",
        ],
    },
    "issue_types": {
        "description": "Types of issues (physical, emotional, verbal, financial, coercion, threats)",
        "priority": 1,
        "indicators": [
            r"hit", r"beat", r"slap", r"punch", r"kick", r"physical",
            r"emotional", r"mental", r"verbal", r"abuse", r"insult",
            r"financial", r"money", r"salary", r"dowry", r"demand",
            r"threat", r"coerci", r"force", r"blackmail", r"harass",
            r"sexual", r"molest", r"torture", r"cruelty",
        ],
    },
    "timeline_duration": {
        "description": "Timeline and duration of events",
        "priority": 2,
        "indicators": [
            r"\d+\s*(?:year|month|week|day)", r"since\s+\d{4}",
            r"from\s+\d{4}", r"last\s+\d+", r"ago",
            r"recently", r"for\s+(?:a\s+)?long", r"ongoing",
        ],
    },
    "living_situation": {
        "description": "Current living arrangement",
        "priority": 2,
        "indicators": [
            r"living\s+with", r"staying\s+with", r"moved\s+out",
            r"thrown\s+out", r"parents'?\s+house", r"separate",
            r"same\s+house", r"marital\s+home", r"shelter",
        ],
    },
    "financial_dependency": {
        "description": "Financial dependency or denial",
        "priority": 3,
        "indicators": [
            r"financially?\s+depend", r"no\s+income", r"housewife",
            r"not\s+working", r"earning", r"salary\s+taken",
            r"bank\s+account", r"no\s+money", r"denied\s+money",
        ],
    },
    "children_involved": {
        "description": "Whether children are involved and their situation",
        "priority": 3,
        "indicators": [
            r"child", r"children", r"son", r"daughter",
            r"custody", r"minor", r"baby", r"kid",
        ],
    },
    "prior_complaints": {
        "description": "Prior complaints or legal actions taken",
        "priority": 2,
        "indicators": [
            r"fir", r"complaint", r"police", r"report",
            r"already\s+filed", r"court", r"petition",
            r"protection\s+order", r"lawyer", r"advocate",
        ],
    },
    "evidence_available": {
        "description": "Evidence availability (messages, recordings, medical, witnesses, documents)",
        "priority": 2,
        "indicators": [
            r"message", r"whatsapp", r"screenshot", r"recording",
            r"medical\s+report", r"photo", r"video", r"cctv",
            r"witness", r"proof", r"evidence", r"document",
        ],
    },
    "relief_sought": {
        "description": "Relief sought (maintenance, protection, residence, compensation, etc.)",
        "priority": 2,
        "indicators": [
            r"maintenance", r"alimony", r"protection", r"residence",
            r"compensation", r"divorce", r"custody", r"want\s+to\s+leave",
            r"need\s+help", r"what\s+(?:can|should)\s+i\s+do",
        ],
    },
}

# Minimum % of attributes that must be at least partially resolved
COMPLETENESS_THRESHOLD = 0.55  # 55% of attributes should be present


# ═══════════════════════════════════════════════════════════════
#  SESSION STATE
# ═══════════════════════════════════════════════════════════════

@dataclass
class SessionState:
    """Full conversation state for one user session."""
    session_id: str
    story: str = ""
    summary: str = ""
    summary_fields: dict[str, Any] = field(default_factory=dict)
    correction: str | None = None
    facts: dict[str, Any] = field(default_factory=dict)
    followup_questions: list[str] = field(default_factory=list)
    answers: dict[str, str] = field(default_factory=dict)
    # Conversation memory — the single source of truth
    messages: list[dict[str, str]] = field(default_factory=list)
    # Tracked attributes — which ones are resolved
    resolved_attributes: dict[str, bool] = field(default_factory=dict)
    # Current phase: "gathering" or "analysis"
    phase: str = "gathering"
    # How many exchanges have happened
    exchange_count: int = 0
    # User-requested analysis
    analysis_requested: bool = False
    # The final structured analysis (cached)
    final_analysis: dict[str, str] | None = None


class ConversationStore:
    """Thread-safe in-memory session store."""

    def __init__(self) -> None:
        self._data: dict[str, SessionState] = {}
        self._lock = Lock()

    def set(self, state: SessionState) -> None:
        with self._lock:
            self._data[state.session_id] = state

    def get(self, session_id: str) -> SessionState | None:
        with self._lock:
            return self._data.get(session_id)


store = ConversationStore()


# ═══════════════════════════════════════════════════════════════
#  COMPLETENESS ANALYSIS
# ═══════════════════════════════════════════════════════════════

def analyze_completeness(full_text: str) -> tuple[dict[str, bool], float, list[str]]:
    """
    Scan the full conversation text and determine which case attributes
    are present. Returns (resolved_map, completeness_ratio, missing_attributes).
    """
    text_lower = full_text.lower()
    resolved = {}
    missing = []

    for attr_name, attr_config in CASE_ATTRIBUTES.items():
        found = any(re.search(p, text_lower) for p in attr_config["indicators"])
        resolved[attr_name] = found
        if not found:
            missing.append(attr_name)

    total = len(CASE_ATTRIBUTES)
    found_count = sum(1 for v in resolved.values() if v)
    ratio = found_count / total if total > 0 else 0.0

    # Sort missing by priority (lower number = higher priority)
    missing.sort(key=lambda k: CASE_ATTRIBUTES[k]["priority"])

    return resolved, ratio, missing


def should_transition_to_analysis(state: SessionState, user_message: str) -> bool:
    """
    Determine if we should transition from Phase 1 to Phase 2.

    Conditions:
    (a) Completeness threshold is met, OR
    (b) User explicitly requests analysis/summary
    """
    # Check explicit user request
    analysis_triggers = [
        r"generat\w*\s+(?:my\s+)?(?:summary|analysis|report|recommendation)",
        r"give\s+me\s+(?:the\s+)?(?:summary|analysis|report|prediction|recommendation)",
        r"(?:what|show)\s+(?:is|are)\s+(?:my\s+)?(?:legal\s+)?(?:options|outcomes?|prediction)",
        r"analyze\s+my\s+case",
        r"proceed\s+(?:with\s+)?(?:the\s+)?analysis",
        r"(?:i\s+(?:want|need)\s+)?(?:the\s+)?(?:final\s+)?(?:summary|analysis|output|report)",
        r"that'?s?\s+(?:all|everything|it)\b",
        r"nothing\s+(?:else|more)",
        r"no\s+(?:more\s+)?(?:details?|info|information)",
        r"i'?ve?\s+(?:shared|told|said)\s+everything",
        r"can\s+you\s+(?:now\s+)?(?:analyze|summarize|predict|recommend)",
    ]
    msg_lower = user_message.lower().strip()
    for pattern in analysis_triggers:
        if re.search(pattern, msg_lower):
            return True

    # Check completeness threshold
    full_text = _build_full_text(state)
    _, ratio, _ = analyze_completeness(full_text)
    if ratio >= COMPLETENESS_THRESHOLD and state.exchange_count >= 3:
        return True

    return False


def _build_full_text(state: SessionState) -> str:
    """Concatenate all user messages into a single text block."""
    parts = []
    for msg in state.messages:
        if msg["role"] == "user":
            parts.append(msg["content"])
    return " ".join(parts)


# ═══════════════════════════════════════════════════════════════
#  LLM PROMPTS
# ═══════════════════════════════════════════════════════════════

GATHERING_SYSTEM_PROMPT = """You are **NyayaSakhi**, an intelligent, empathetic, and adaptive AI legal assistant focused on helping users in sensitive legal situations (especially domestic issues, abuse, and personal disputes).

Your primary goals:
1. Understand the user's situation progressively (do NOT assume missing details)
2. Respond conversationally, not in rigid templates
3. Ask relevant follow-up questions when information is incomplete
4. Provide legal awareness and guidance (NOT absolute legal advice)
5. Prioritize user safety at all times

---

### CORE BEHAVIOR RULES
* NEVER generate full legal analysis if the user's input is unclear, too short, or ambiguous.
* NEVER force structured outputs like "Victim Case Summary" unless sufficient data exists.
* DO NOT hallucinate facts or assume abuse types without evidence.
* ALWAYS adapt your response based on input quality.

---

### INPUT QUALITY HANDLING
If user input is:
* Greeting ("hello", "hi") → respond warmly and invite sharing
* Nonsense ("fwa", "hh") → politely ask for clarification
* Partial info → ask targeted follow-up questions
* Detailed situation → begin structured reasoning gradually

---

### CONVERSATION FLOW LOGIC
Follow this decision pipeline:

1. **Check urgency**
   If signs of immediate danger:
   → advise contacting local authorities first

2. **Check input completeness**
   If insufficient:
   → ask 1–2 specific, simple questions (NOT a list)

3. **Build understanding step-by-step**
   Extract gradually:
   * relationship type
   * type of issue (physical, emotional, financial, etc.)
   * duration/frequency
   * evidence (if any)
   * current risk level
   * user's goal (safety, separation, financial help, etc.)

4. **Only when enough info is available**
   → provide analysis

---

### RESPONSE STYLE
* Conversational, human-like, supportive
* Avoid legal jargon unless necessary
* Break responses into small readable parts
* Do NOT dump large structured blocks

---

### RETRIEVAL-AWARE BEHAVIOR (FOR RAG)
If case knowledge is available:
* Use similar past cases to guide reasoning
* Do NOT explicitly mention "retrieved cases"
* Integrate insights naturally

---

### SAFETY LAYER
If any indication of:
* violence
* threats
* coercion
Then:
* prioritize safety guidance
* suggest reaching out to trusted person / authority

---

### OUTPUT CONSTRAINTS
* DO NOT generate long reports unless explicitly asked
* DO NOT assume missing facts
* DO NOT repeat the same structure every time
* KEEP RESPONSES ADAPTIVE

ALREADY GATHERED INFORMATION:
{gathered_info}

MISSING INFORMATION (prioritized):
{missing_info}
"""

ANALYSIS_SYSTEM_PROMPT = """You are NyayaSakhi — a senior legal case analysis AI specializing in Indian women's safety and family law.

Based on the COMPLETE conversation history provided below, generate a structured legal analysis.
The conversation history IS the single source of truth. Do not add, assume, or fabricate any facts not present in the conversation.

YOU MUST produce output in EXACTLY this format with these exact section headers. No other sections, no meta-commentary, no introduction or closing remarks outside these sections:

### Victim Case Summary
[Write a clear, coherent narrative synthesized from the entire conversation. Include: relationship type, nature of abuse/issues, timeline, living situation, financial dependency, children, evidence status, and relief sought. Present it as a factual case summary.]

### Predicted Legal Outcomes
[Provide likelihood-based assessments for each applicable legal remedy:
- Protection Order under PWDVA: [High/Moderate/Low likelihood] — [reason]
- Maintenance/Alimony: [High/Moderate/Low/Uncertain] — [reason]
- Residence Order: [if applicable]
- Custody Order: [if applicable]
- Criminal prosecution under IPC/BNS: [if applicable]
- Compensation: [if applicable]
Base these on the strength of evidence described and general legal patterns. Explicitly state where evidence is weak or missing.]

### Expected Duration of the Case
[Provide realistic timelines:
- If settled/mediated: X-Y months
- If contested in court: X-Y months/years
- Factors that could speed up or slow down the case]

### Decision Recommendation
[ONE clear directive. Choose from:
- "Proceed with litigation"
- "Attempt mediation/settlement first"
- "Litigate after strengthening evidence"
- "Seek urgent protection immediately"
- "Explore counseling before legal action"
Only pick one. Be decisive.]

### Reason for Recommendation
[Logically justify the recommendation using:
- Specific facts from the conversation
- Strength of available evidence
- Severity and urgency of the situation
- Likelihood of cooperation from respondent
- User's stated priorities and relief sought]

### Recommended Next Actions
[Numbered, practical, prioritized steps. Include:
1. Immediate actions (safety, evidence preservation)
2. Legal steps (filing complaints, approaching courts)
3. Documentation needed
4. Support resources (helplines, legal aid, NGOs)
Each step must be actionable and specific to THIS case.]

RULES:
- Do NOT use emojis anywhere.
- Acknowledge uncertainty where evidence is weak.
- Remain legally neutral — no guarantees.
- Base all reasoning on patterns, not assumptions.
- Tone: professional, supportive, precise.
- NO meta explanations like "Based on the information gathered..." — go straight to the content.
"""


# ═══════════════════════════════════════════════════════════════
#  KEYWORD-BASED CASE ANALYSIS (fallback + enrichment)
# ═══════════════════════════════════════════════════════════════

KEYWORDS = {
    "physical_abuse": ["hit", "beat", "injury", "slap", "physical", "violence"],
    "verbal_abuse": ["abuse", "insult", "threat", "shout", "humiliate"],
    "emotional_abuse": ["mental", "emotional", "depress", "trauma", "harass"],
    "economic_abuse": ["money", "financial", "salary", "dependent", "maintenance"],
    "sexual_abuse": ["sexual", "molest", "rape", "assault"],
    "forced_eviction": ["evict", "thrown out", "house", "home", "residence"],
    "children": ["child", "children", "custody", "son", "daughter"],
    "evidence": ["message", "whatsapp", "email", "photo", "video", "medical", "witness", "proof"],
    "safety": ["unsafe", "danger", "kill", "threaten", "risk", "fear"],
    "mediation": ["mediate", "discussion", "talk", "settle", "settlement"],
}

RELIEF_HINTS = {
    "maintenance": ["maintenance", "financial support", "money", "alimony"],
    "residence": ["residence", "house", "home", "stay in house"],
    "protection": ["protection", "safety", "restraining"],
    "compensation": ["compensation", "damages", "loss"],
    "custody": ["custody", "child"],
}

RECOMMENDATIONS = {
    "MEDIATE": "Attempt mediation/settlement first",
    "LITIGATE": "Proceed with litigation",
    "SETTLE": "Attempt settlement",
    "LITIGATE_EVIDENCE": "Litigate after strengthening evidence",
    "URGENT": "Seek urgent protection immediately",
}


def _contains_any(text: str, terms: list[str]) -> bool:
    low = text.lower()
    return any(t in low for t in terms)


def _extract_relationship(text: str) -> str | None:
    low = text.lower()
    if "husband" in low or "wife" in low or "marriage" in low:
        return "Marital relationship"
    if "live-in" in low or "partner" in low:
        return "Live-in relationship"
    if "in-law" in low or "in law" in low:
        return "Matrimonial family relationship"
    return None


def _extract_duration(text: str) -> str | None:
    m = re.search(r"(\d+\s*(?:year|years|month|months))", text.lower())
    return m.group(1) if m else None


def extract_facts(text: str) -> dict[str, Any]:
    """Extract structured facts from conversation text using keyword matching."""
    facts: dict[str, Any] = {}
    low = text.lower()

    facts["relationship_type"] = _extract_relationship(text) or "Not specified"
    facts["duration"] = _extract_duration(text) or "Not specified"

    # Abuse types
    facts["physical_abuse"] = _contains_any(low, KEYWORDS["physical_abuse"])
    facts["verbal_abuse"] = _contains_any(low, KEYWORDS["verbal_abuse"])
    facts["emotional_abuse"] = _contains_any(low, KEYWORDS["emotional_abuse"])
    facts["economic_abuse"] = _contains_any(low, KEYWORDS["economic_abuse"])
    facts["sexual_abuse"] = _contains_any(low, KEYWORDS["sexual_abuse"])
    facts["forced_eviction"] = _contains_any(low, KEYWORDS["forced_eviction"])
    facts["threat_to_safety"] = _contains_any(low, KEYWORDS["safety"])
    facts["children_involved"] = _contains_any(low, KEYWORDS["children"])
    facts["has_evidence"] = _contains_any(low, KEYWORDS["evidence"])
    facts["open_to_mediation"] = _contains_any(low, KEYWORDS["mediation"])

    # Evidence details
    evidence = []
    if _contains_any(low, ["message", "whatsapp", "email", "screenshot"]):
        evidence.append("Digital messages")
    if _contains_any(low, ["medical", "hospital", "doctor"]):
        evidence.append("Medical records")
    if _contains_any(low, ["witness"]):
        evidence.append("Witnesses")
    if _contains_any(low, ["photo", "video", "recording", "cctv"]):
        evidence.append("Photo/video evidence")
    if _contains_any(low, ["fir", "complaint", "police"]):
        evidence.append("Police complaint/FIR")
    facts["evidence_list"] = evidence

    # Relief sought
    reliefs = []
    for relief_name, terms in RELIEF_HINTS.items():
        if _contains_any(low, terms):
            reliefs.append(relief_name)
    facts["reliefs_sought"] = reliefs

    # Living situation
    if "with my parents" in low or "parents house" in low or "parents' house" in low:
        facts["living_situation"] = "With parents"
    elif "living with" in low and ("husband" in low or "respondent" in low):
        facts["living_situation"] = "With respondent"
    elif "moved out" in low or "left" in low or "staying elsewhere" in low:
        facts["living_situation"] = "Separated/moved out"
    else:
        facts["living_situation"] = "Not specified"

    # Financial dependency
    facts["financially_dependent"] = _contains_any(
        low, ["financially dependent", "no income", "housewife", "not working", "no job"]
    )

    return facts


# ═══════════════════════════════════════════════════════════════
#  DATASET-BASED CASE RETRIEVAL (for duration estimates)
# ═══════════════════════════════════════════════════════════════

from functools import lru_cache

@lru_cache(maxsize=1)
def load_dataset() -> dict[str, Any]:
    if not DATASET_PATH.exists():
        return {"records": []}
    with DATASET_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def _duration_from_record(record: dict[str, Any]) -> float | None:
    duration = (((record.get("dates") or {}).get("duration")) or {})
    years = duration.get("years")
    months = duration.get("months")
    days = duration.get("days")
    if years is None and months is None and days is None:
        return None
    return float(years or 0) + (float(months or 0) / 12.0) + (float(days or 0) / 365.0)


def retrieve_similar_cases(facts: dict[str, Any], top_k: int = 5) -> list[dict[str, Any]]:
    dataset = load_dataset()
    records = dataset.get("records", [])
    if not records:
        return []

    abuse_terms = []
    for key in ["physical_abuse", "emotional_abuse", "economic_abuse", "sexual_abuse"]:
        if facts.get(key):
            abuse_terms.append(key.replace("_abuse", ""))

    relief_terms = set(facts.get("reliefs_sought") or [])

    scored: list[tuple[int, dict]] = []
    for rec in records:
        score = 0
        case_type = str(rec.get("case_type") or "").lower()
        if "domestic violence" in case_type:
            score += 2

        summary_text = str((rec.get("case_summary") or {}).get("summary_short") or "").lower()
        for term in abuse_terms:
            if term in summary_text:
                score += 2
        for term in relief_terms:
            if term in summary_text:
                score += 1

        if score > 0:
            scored.append((score, rec))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in scored[:top_k]]


# ═══════════════════════════════════════════════════════════════
#  CORE CONVERSATION ENGINE
# ═══════════════════════════════════════════════════════════════

def process_message(session_id: str, user_message: str) -> dict[str, Any]:
    """
    Main entry point. Process a user message and return the agent response.

    Returns:
        {
            "response": str,           # The assistant's reply
            "phase": str,              # "gathering" or "analysis"
            "completeness": float,     # 0.0 to 1.0
            "resolved": dict,          # which attributes are resolved
            "missing": list[str],      # which attributes are missing
            "is_final": bool,          # whether this is the final structured output
            "final_response": dict | None,  # structured output (Phase 2)
        }
    """
    state = store.get(session_id)
    if not state:
        state = SessionState(session_id=session_id)

    # Record the user message
    state.messages.append({"role": "user", "content": user_message})
    state.exchange_count += 1

    # Append to story for keyword-based fallback
    if state.story:
        state.story += " " + user_message
    else:
        state.story = user_message

    # Analyze completeness
    full_text = _build_full_text(state)
    resolved, ratio, missing = analyze_completeness(full_text)
    state.resolved_attributes = resolved

    # Determine if we should transition to analysis
    transition = should_transition_to_analysis(state, user_message)

    if transition or state.phase == "analysis":
        # PHASE 2: Generate structured analysis
        state.phase = "analysis"
        result = _generate_analysis(state)
        store.set(state)
        return result

    # PHASE 1: Continue gathering information
    result = _generate_gathering_response(state, resolved, ratio, missing)
    store.set(state)
    return result


def _generate_gathering_response(
    state: SessionState,
    resolved: dict[str, bool],
    ratio: float,
    missing: list[str],
) -> dict[str, Any]:
    """Generate a conversational follow-up response during Phase 1."""

    # Build context about what we know and what we need
    gathered_lines = []
    for attr_name, is_resolved in resolved.items():
        desc = CASE_ATTRIBUTES[attr_name]["description"]
        status = "✓ Provided" if is_resolved else "✗ Not yet gathered"
        gathered_lines.append(f"- {desc}: {status}")

    missing_lines = []
    for attr_name in missing[:3]:  # Focus on top 3 missing
        desc = CASE_ATTRIBUTES[attr_name]["description"]
        missing_lines.append(f"- {desc} (priority: {CASE_ATTRIBUTES[attr_name]['priority']})")

    gathered_info = "\n".join(gathered_lines)
    missing_info = "\n".join(missing_lines) if missing_lines else "All critical attributes gathered."

    system_prompt = GATHERING_SYSTEM_PROMPT.format(
        gathered_info=gathered_info,
        missing_info=missing_info,
    )

    # Build conversation history for LLM
    history_messages = []
    for msg in state.messages[-16:]:  # Keep last 16 messages for context window
        history_messages.append(f"{msg['role'].upper()}: {msg['content']}")
    history_text = "\n".join(history_messages)

    user_prompt = (
        f"CONVERSATION HISTORY:\n{history_text}\n\n"
        f"COMPLETENESS: {ratio*100:.0f}% ({sum(1 for v in resolved.values() if v)}/{len(resolved)} attributes)\n\n"
        f"Generate your next conversational response. Remember: acknowledge what was shared, "
        f"then ask 1-2 targeted follow-up questions about the most critical missing information."
    )

    # Try LLM generation
    response_text = None
    if generate:
        try:
            llm_result = generate(
                prompt=user_prompt,
                system_prompt=system_prompt,
                temperature=0.6,
                max_tokens=800,
            )
            response_text = llm_result.get("text", "").strip()
        except Exception as e:
            logger.warning(f"LLM gathering response failed: {e}")

    # Fallback if LLM fails
    if not response_text:
        response_text = _fallback_gathering_response(state, missing)

    # Record assistant response
    state.messages.append({"role": "assistant", "content": response_text})

    return {
        "response": response_text,
        "phase": "gathering",
        "completeness": round(ratio, 2),
        "resolved": resolved,
        "missing": missing,
        "is_final": False,
        "final_response": None,
    }


def _fallback_gathering_response(state: SessionState, missing: list[str]) -> str:
    """Keyword-based fallback when LLM is unavailable."""
    if state.exchange_count == 1:
        return (
            "Thank you for reaching out. I'm here to help you understand your legal options.\n\n"
            "Could you tell me a bit more about your situation? For instance:\n"
            "- What is your relationship with the person involved?\n"
            "- What kind of issues are you facing?"
        )

    question_map = {
        "relationship_type": "Could you tell me about your relationship with the person involved — are they your spouse, partner, family member, or someone else?",
        "issue_types": "What kind of issues are you experiencing — physical violence, emotional abuse, financial control, threats, or something else?",
        "timeline_duration": "How long has this been going on? When did it start?",
        "living_situation": "Are you currently living with the person, or have you separated?",
        "evidence_available": "Do you have any evidence such as messages, photos, medical reports, or witnesses?",
        "prior_complaints": "Have you filed any complaints with the police or taken any legal action so far?",
        "relief_sought": "What kind of help are you seeking — protection, financial support, divorce, custody, or something else?",
        "financial_dependency": "Are you financially dependent on the other person, or do you have your own income?",
        "children_involved": "Are there any children involved in this situation?",
        "parties_involved": "Who else is involved in this situation besides the main person?",
    }

    # Pick the top missing attribute and ask about it
    for attr in missing:
        if attr in question_map:
            return (
                "Thank you for sharing that information. I understand this is difficult.\n\n"
                + question_map[attr]
            )

    return (
        "Thank you for the details you've shared so far. "
        "Is there anything else about your situation that you'd like to tell me? "
        "When you're ready, I can generate a complete legal analysis for you."
    )


def _generate_analysis(state: SessionState) -> dict[str, Any]:
    """Generate the structured Phase 2 analysis."""

    full_text = _build_full_text(state)
    resolved, ratio, missing = analyze_completeness(full_text)

    # Build conversation transcript for the LLM
    transcript_lines = []
    for msg in state.messages:
        role_label = "User" if msg["role"] == "user" else "Legal Assistant"
        transcript_lines.append(f"{role_label}: {msg['content']}")
    transcript = "\n\n".join(transcript_lines)

    # Extract keyword-based facts for enrichment
    facts = extract_facts(full_text)
    state.facts = facts

    # Retrieve similar cases for duration estimate
    similar_cases = retrieve_similar_cases(facts, top_k=5)

    # Duration context
    duration_vals = [d for d in (_duration_from_record(c) for c in similar_cases) if d is not None]
    if duration_vals:
        avg_y = mean(duration_vals)
        if avg_y < 1:
            duration_context = "Similar cases resolved in 6-12 months on average."
        elif avg_y < 2:
            duration_context = "Similar cases took 1-2 years on average."
        else:
            duration_context = "Similar cases took 2+ years on average if fully contested."
    else:
        duration_context = "No similar case duration data available. Use standard estimates."

    # Generate via LLM
    response_text = None
    if generate:
        user_prompt = (
            f"COMPLETE CONVERSATION TRANSCRIPT:\n\n{transcript}\n\n"
            f"---\n\n"
            f"KEYWORD-EXTRACTED FACTS (for reference):\n"
            f"- Relationship: {facts.get('relationship_type', 'Unknown')}\n"
            f"- Duration: {facts.get('duration', 'Unknown')}\n"
            f"- Abuse types: Physical={facts.get('physical_abuse')}, "
            f"Emotional={facts.get('emotional_abuse')}, "
            f"Verbal={facts.get('verbal_abuse')}, "
            f"Financial={facts.get('economic_abuse')}, "
            f"Sexual={facts.get('sexual_abuse')}\n"
            f"- Living situation: {facts.get('living_situation', 'Unknown')}\n"
            f"- Evidence: {', '.join(facts.get('evidence_list', [])) or 'None mentioned'}\n"
            f"- Children involved: {facts.get('children_involved', False)}\n"
            f"- Relief sought: {', '.join(facts.get('reliefs_sought', [])) or 'Not specified'}\n"
            f"- Financial dependency: {facts.get('financially_dependent', False)}\n"
            f"\nDURATION REFERENCE: {duration_context}\n"
            f"\nGenerate the structured legal analysis now. Follow the format EXACTLY."
        )
        try:
            llm_result = generate(
                prompt=user_prompt,
                system_prompt=ANALYSIS_SYSTEM_PROMPT,
                temperature=0.4,
                max_tokens=3000,
            )
            response_text = llm_result.get("text", "").strip()
        except Exception as e:
            logger.warning(f"LLM analysis generation failed: {e}")

    # Build structured output
    final_response = None
    if response_text:
        # Parse the LLM response into sections
        final_response = _parse_analysis_sections(response_text)

    # Fallback to keyword-based analysis
    if not final_response:
        final_response = _fallback_analysis(facts, similar_cases)
        response_text = _format_analysis_as_text(final_response)

    state.final_analysis = final_response

    # Record the analysis in conversation
    state.messages.append({"role": "assistant", "content": response_text or _format_analysis_as_text(final_response)})

    return {
        "response": response_text or _format_analysis_as_text(final_response),
        "phase": "analysis",
        "completeness": round(ratio, 2),
        "resolved": resolved,
        "missing": missing,
        "is_final": True,
        "final_response": final_response,
    }


def _parse_analysis_sections(text: str) -> dict[str, str] | None:
    """Parse the LLM's structured output into a dict of sections."""
    sections = {
        "Victim Case Summary": "",
        "Predicted Legal Outcomes": "",
        "Expected Duration of the Case": "",
        "Decision Recommendation": "",
        "Reason for Recommendation": "",
        "Recommended Next Actions": "",
    }

    # Try to extract each section using ### headers
    for section_name in sections:
        pattern = rf"###\s*{re.escape(section_name)}\s*\n(.*?)(?=###|\Z)"
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if match:
            sections[section_name] = match.group(1).strip()

    # Check if we got meaningful content
    filled = sum(1 for v in sections.values() if len(v) > 20)
    if filled < 3:
        return None  # Not enough sections parsed successfully

    return sections


def _fallback_analysis(facts: dict[str, Any], similar_cases: list[dict]) -> dict[str, str]:
    """Generate analysis using keyword extraction when LLM is unavailable."""

    abuse_types = []
    if facts.get("physical_abuse"):
        abuse_types.append("physical abuse")
    if facts.get("emotional_abuse"):
        abuse_types.append("emotional abuse")
    if facts.get("verbal_abuse"):
        abuse_types.append("verbal abuse")
    if facts.get("economic_abuse"):
        abuse_types.append("economic/financial abuse")
    if facts.get("sexual_abuse"):
        abuse_types.append("sexual abuse")

    summary = (
        f"Relationship type: {facts.get('relationship_type', 'Not specified')}. "
        f"Duration: {facts.get('duration', 'Not specified')}. "
        f"Abuse types reported: {', '.join(abuse_types) if abuse_types else 'Issues reported, type needs clarification'}. "
        f"Living situation: {facts.get('living_situation', 'Not specified')}. "
        f"Evidence available: {', '.join(facts.get('evidence_list', [])) or 'Not specified'}. "
        f"Children involved: {'Yes' if facts.get('children_involved') else 'No/Not mentioned'}. "
        f"Relief sought: {', '.join(facts.get('reliefs_sought', [])) or 'Not specified'}."
    )

    outcomes = []
    outcomes.append("Protection Order: Moderate likelihood if threats or violence are documented.")
    if facts.get("economic_abuse") or facts.get("financially_dependent"):
        outcomes.append("Maintenance: High likelihood where financial dependency is established.")
    if facts.get("forced_eviction"):
        outcomes.append("Residence Order: High likelihood where displacement from shared household is shown.")
    if facts.get("children_involved"):
        outcomes.append("Custody: Interim custody may be considered based on child welfare assessment.")
    if facts.get("physical_abuse") or facts.get("sexual_abuse"):
        outcomes.append("Criminal Prosecution: Possible under IPC/BNS sections if FIR is filed with supporting evidence.")
    if not facts.get("has_evidence"):
        outcomes.append("Note: Evidence appears limited which may reduce outcome certainty.")

    # Duration
    duration_vals = [d for d in (_duration_from_record(c) for c in similar_cases) if d is not None]
    if duration_vals:
        avg = mean(duration_vals)
        if avg < 1:
            duration = "If settled: 3-6 months. If contested: 6-12 months. Interim relief possible within weeks."
        elif avg < 2:
            duration = "If settled: 6-12 months. If contested: 1-2 years. Interim orders possible within 1-3 months."
        else:
            duration = "If settled: 6-12 months. If contested: 2-3+ years. Interim relief available earlier."
    else:
        duration = "If settled/mediated: 3-6 months. If contested in court: 1-2 years. Interim relief possible within weeks of filing."

    # Strategy
    severity = sum(1 for f in ["physical_abuse", "sexual_abuse", "threat_to_safety", "forced_eviction"] if facts.get(f))
    evidence_count = len(facts.get("evidence_list", []))
    cooperative = facts.get("open_to_mediation", False)

    if facts.get("threat_to_safety"):
        recommendation = RECOMMENDATIONS["URGENT"]
        reason = "Immediate safety risk is indicated. Urgent protective action must precede all other steps."
    elif severity >= 2 and not cooperative:
        recommendation = RECOMMENDATIONS["LITIGATE"]
        reason = "Abuse severity is high and cooperation likelihood appears low, warranting formal legal proceedings."
    elif severity >= 1 and evidence_count == 0:
        recommendation = RECOMMENDATIONS["LITIGATE_EVIDENCE"]
        reason = "The situation is legally actionable but evidence needs strengthening for a stronger case."
    elif cooperative:
        recommendation = RECOMMENDATIONS["MEDIATE"]
        reason = "There appears to be scope for negotiation. Mediation can provide faster resolution if both parties cooperate."
    else:
        recommendation = RECOMMENDATIONS["LITIGATE"]
        reason = "Based on the facts described, formal legal proceedings are recommended for effective resolution."

    actions = [
        "1. Preserve all evidence immediately — screenshot messages, keep medical reports, note witness contacts.",
        "2. Prepare a chronological timeline of all incidents with dates, descriptions, and any witnesses.",
        "3. Consult a qualified family law advocate in your area for personalized legal counsel.",
        "4. If safety is at risk, call 112 (Emergency) or 181 (Women Helpline) immediately.",
        "5. Consider approaching the local Protection Officer or Magistrate for interim protection orders.",
        "6. Keep certified copies of all important documents (marriage certificate, property papers, FIRs) in a safe place.",
    ]

    return {
        "Victim Case Summary": summary,
        "Predicted Legal Outcomes": "\n".join(outcomes),
        "Expected Duration of the Case": duration,
        "Decision Recommendation": recommendation,
        "Reason for Recommendation": reason,
        "Recommended Next Actions": "\n".join(actions),
    }


def _format_analysis_as_text(final_response: dict[str, str]) -> str:
    """Convert the structured dict into a readable markdown text."""
    parts = []
    for title, content in final_response.items():
        parts.append(f"### {title}\n{content}")
    return "\n\n".join(parts)


# ═══════════════════════════════════════════════════════════════
#  LEGACY COMPATIBILITY — keep old function signatures working
# ═══════════════════════════════════════════════════════════════

def summarize_story(story: str) -> tuple[str, dict[str, Any], bool]:
    """Legacy compatibility wrapper."""
    result = process_message(f"legacy-{hash(story)}", story)
    fields = result.get("resolved", {})
    return result["response"], fields, not result["is_final"]


def build_followup(state: SessionState) -> list[str]:
    """Legacy: build follow-up questions from state."""
    full_text = _build_full_text(state)
    _, _, missing = analyze_completeness(full_text)

    question_map = {
        "relationship_type": "What is your relationship with the person involved?",
        "issue_types": "What kind of issues are you experiencing?",
        "timeline_duration": "How long has this been going on?",
        "living_situation": "Are you currently living with the person?",
        "evidence_available": "Do you have any evidence or proof?",
        "prior_complaints": "Have you filed any complaints or taken legal action?",
        "relief_sought": "What kind of help or relief are you seeking?",
        "financial_dependency": "Are you financially dependent on the other person?",
        "children_involved": "Are children involved in this situation?",
        "parties_involved": "Who else is involved besides the main person?",
    }

    questions = [question_map[attr] for attr in missing if attr in question_map]
    return questions[:5]


def finalize_analysis(state: SessionState) -> dict[str, str]:
    """Legacy: generate final analysis from state."""
    full_text = _build_full_text(state)
    if state.correction:
        full_text += f" {state.correction}"
    for v in state.answers.values():
        full_text += f" {v}"

    facts = extract_facts(full_text)
    similar_cases = retrieve_similar_cases(facts, top_k=5)
    return _fallback_analysis(facts, similar_cases)
