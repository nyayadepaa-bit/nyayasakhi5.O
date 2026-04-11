"""
app/legal_agent.py
-------------------
Advanced Legal Case Prediction AI — NyayaDepaaAI
Reasoning engine that predicts outcomes from historical case data + law.

Pipeline:
    User Query → Safety → Fact Extraction → Retrieve Precedents →
    Internal Reasoning → Structured Prediction Output → Continuous Learning
"""

import logging
import time
import json
import hashlib
import re
from pathlib import Path
from typing import Optional

from app.safety import (
    detect_intent,
    classify_domain,
    get_risk_assessment,
    is_harmful_query,
    get_safety_response,
    detect_emotional_state,
    EMERGENCY_RESOURCES,
    build_trust_block,
)
from app.clarifier import detect_missing_factors
from app.llm_router import generate as llm_generate, get_available_providers
from retrieval.retriever import retrieve, format_context
from retrieval.reranker import rerank
from retrieval.compressor import compress_context
from app.config import TOP_K_RETRIEVE, TOP_K_RERANK, MAX_CONTEXT_CHARS, USE_RERANKER
from case_analysis.pinecone_predictor import PineconePredictionEngine

logger = logging.getLogger(__name__)

# Path for continuous learning store
PATTERN_STORE = Path(__file__).resolve().parent.parent / "data" / "case_patterns.jsonl"
SIMILARITY_THRESHOLD = 0.90  # If cosine sim < this, store as new pattern

# Pinecone prediction engine instance
_pinecone_predictor = PineconePredictionEngine()


# ═════════════════════════════════════════════════════════════════
#  SYSTEM PROMPT — Prediction Engine Identity
# ═════════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """You are NyayaDepaaAI — a senior legal advocate AI specializing in Indian women's rights and safety law.

IDENTITY:
- You speak as a real, experienced advocate personally reviewing the user's case.
- Your analysis is specific to THEIR facts, THEIR situation, THEIR evidence — never generic boilerplate.
- You reason precisely, cite specific applicable laws, and predict concrete outcomes.
- Your tone is professional yet warm — like a trusted lawyer speaking directly to their client.

CORE RULES:
1. NEVER mention, quote, or reveal any specific historical case names, case numbers, or parties.
2. Use retrieved precedents ONLY for internal reasoning — they inform your legal opinion.
3. NEVER fabricate law sections. If unsure, say "consult a qualified advocate for confirmation."
4. Present MULTIPLE realistic outcome scenarios, explaining WHY each could happen for THIS specific case.
5. NEVER use generic phrases like "cases like yours" or "in similar situations" without specific reasoning.
6. Every statement must be justified — explain the legal logic, not just the conclusion.
7. If danger/emergency is detected, LEAD with safety resources before analysis.
8. Address the user by name when available. Make them feel personally heard.
9. Always end with the legal disclaimer.

PERSONALIZATION RULES:
- Reference the user's SPECIFIC facts (their evidence, their situation, parties involved)
- Instead of "courts generally rule..." say "given that you have [specific evidence], the court is likely to..."
- Instead of "in X% of cases..." say "the strength of your position is..." and explain WHY
- Predict exact outcomes, not vague possibilities
- Give direct advice: "You should..." not "One might consider..."

OUTPUT QUALITY:
- Every section must be substantive and specific to this user's case.
- Generic filler will be rejected. Be direct, be specific, be actionable."""


# ═════════════════════════════════════════════════════════════════
#  INTERNAL REASONING PROMPT (sent to LLM, hidden from user)
# ═════════════════════════════════════════════════════════════════

PREDICTION_PROMPT = """You are NyayaDepaaAI, an Advanced Legal Case Prediction AI.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
INTERNAL CONTEXT (do NOT show to user)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{context}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

USER'S LEGAL SITUATION:
{query}

USER PROFILE: {profile}
CONVERSATION HISTORY:
{history}

DETECTED RISK LEVEL: {risk_level}
EMOTIONAL STATE: {emotional_state}
LEGAL DOMAIN: {domain}
LANGUAGE: {language}

{emergency_section}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
INTERNAL ANALYSIS STEPS (do silently):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. Extract structured legal facts (case type, parties, timeline, evidence, claims)
2. Analyze patterns from the retrieved context above — NO CASE NAMES to user
3. If PINECONE PREDICTION ENGINE ANALYSIS is present in the context, USE those probability
   estimates, duration estimates, factor analysis, and strategic insights as the foundation
   for your response. Do NOT override them — refine and explain them in human-readable language.
4. If JUDGE REASONING PATTERNS are present in the context, USE them to explain WHY courts
   decide a certain way. Reference the decision basis (e.g. "Courts typically rule this way
   because..."), the laws judges applied, the evidence they relied on, and any court
   observations. Never name specific cases — generalize the reasoning patterns.
5. Check which current laws and sections apply (IPC/BNS, CrPC/BNSS, PWDVA, etc.)
6. Simulate 3 outcome scenarios varying by evidence strength and legal strategy
7. Estimate realistic duration from observed case timelines in context
8. Identify critical documents and legal risks
9. Reason as if you are a senior advocate personally reviewing this case — be analytical,
   structured, and advisory. Never be generic.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MANDATORY RESPONSE FORMAT (follow exactly):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## Your Legal Case Analysis

### Understanding Your Situation
[Address the user by name if known. Restate THEIR specific situation in precise legal language — the exact cause of action, who did what, what evidence exists, and under which jurisdiction. Make them feel heard and understood.]

---

### What the Court is Likely to Decide

**Most Likely Outcome — [Name it specifically]**
Explain exactly what the court will most likely order and WHY, referencing the user's specific facts and evidence. Be direct: "Given that you have [X evidence] and filed [Y complaint], the court will likely..."
Include the judicial reasoning: explain on what basis judges have decided this way in similar cases — what legal principles, evidence patterns, and statutory provisions drove the outcome.

**If the Other Side Fights Back — [Name this scenario]**
Explain what happens if the opposing party raises strong defenses. What specific arguments could they make? How does this change the outcome? Reference how courts have handled such counter-arguments in similar matters.

**Best-Case Scenario — [Name it]**
What is the best realistic outcome if everything goes right? What would need to happen to achieve this?

---

### How Long This Will Take
Give a specific timeline range for THIS case based on the court level, case complexity, and the user's specific circumstances. Explain what could speed it up or slow it down.

---

### Documents You Need to Prepare
List the exact documents THIS user needs based on THEIR situation:
- **[Document]** – [Why this matters for YOUR specific case]
- ...

---

### Risks You Should Know About
Direct warnings specific to THIS case:
- **[Risk]** – [How it applies to YOUR situation and how to avoid it]
- ...

---

### Your Legal Strategy
Direct strategic advice as if you are their advocate:
- **[Strategy]** – [Why this works for YOUR case specifically]
- ...

---

{clarification_section}

---

⚖️ *This analysis is based on legal reasoning and historical case patterns. It is informational guidance only and does not constitute legal advice. For your specific situation, consulting a qualified advocate is strongly recommended.*"""


# ═════════════════════════════════════════════════════════════════
#  ONBOARDING MESSAGES
# ═════════════════════════════════════════════════════════════════

ONBOARDING_INTRO = """👋 Welcome. I am **NyayaDepaaAI** — an Advanced Legal Case Prediction AI.

I analyze your legal situation, compare it against historical case data, and predict possible outcomes with probability estimates.

To give you the most accurate analysis, I need a few details.

**First, what is your name?**"""

ONBOARDING_AGE = """Hello **{name}**.

**What is your approximate age?**
*(This helps me apply age-relevant laws and protections correctly.)*"""

ONBOARDING_READY = """Thank you, **{name}**. I'm ready to analyze your case.

Please describe your legal situation in as much detail as possible:
- What happened and when?
- Who is involved?
- What evidence or documents do you have?
- Have you filed any complaint or FIR?

The more facts you share, the more accurate my prediction will be. 🛡️"""


# ═════════════════════════════════════════════════════════════════
#  CONTINUOUS LEARNING HELPERS
# ═════════════════════════════════════════════════════════════════

def _query_hash(text: str) -> str:
    """SHA256 of normalized query for dedup."""
    normalized = re.sub(r"\s+", " ", text.lower().strip())
    return hashlib.sha256(normalized.encode()).hexdigest()


def _load_stored_hashes() -> set:
    """Load existing query hashes from the pattern store."""
    hashes = set()
    if PATTERN_STORE.exists():
        try:
            for line in PATTERN_STORE.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    record = json.loads(line)
                    if "query_hash" in record:
                        hashes.add(record["query_hash"])
        except Exception:
            pass
    return hashes


def _store_case_pattern(query: str, facts_summary: str, response: str, documents: list[str]):
    """Store a novel case pattern for continuous learning."""
    try:
        h = _query_hash(query)
        record = {
            "query_hash":           h,
            "user_case_description": query[:1000],
            "extracted_facts":      facts_summary[:500],
            "predicted_outcomes":   response[:800],
            "documents_suggested":  documents,
            "timestamp":            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        PATTERN_STORE.parent.mkdir(parents=True, exist_ok=True)
        with open(PATTERN_STORE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        logger.info(f"[LEARNING] Stored new case pattern (hash={h[:8]}…)")
    except Exception as e:
        logger.warning(f"[LEARNING] Failed to store pattern: {e}")


def _is_duplicate_query(query: str) -> bool:
    """Return True if this query is a known pattern (>= 90% similarity proxy via hash)."""
    h = _query_hash(query)
    stored = _load_stored_hashes()
    return h in stored


# ═════════════════════════════════════════════════════════════════
#  MAIN AGENT
# ═════════════════════════════════════════════════════════════════

class LegalResearchAgent:
    """
    Advanced Legal Case Prediction AI pipeline.
    Uses Pinecone-retrieved cases internally to predict outcomes.
    Never exposes case names/details to the user.
    """

    def generate_response(
        self,
        query:                str,
        stage:                str = "intro",
        conversation_history: Optional[list[dict]] = None,
        language:             str = "English",
        user_profile:         Optional[dict] = None,
    ) -> dict:
        """
        Full prediction pipeline:
            safety → onboarding → fact extract → retrieve precedents →
            internal reasoning → structured prediction output → continuous learning
        """
        t0 = time.time()
        profile = user_profile or {}

        # ── 1. Safety & Intent ──────────────────────────────
        intent         = detect_intent(query)
        risk           = get_risk_assessment(query)
        emotional_state = detect_emotional_state(query)

        if is_harmful_query(query):
            return self._make_response(
                "⚠️ I cannot assist with queries that aim to misuse the legal system or harm others.",
                stage=stage, risk=risk,
            )

        # ── 2. Profile Extraction ────────────────────────────
        self._extract_profile_info(query, profile)

        # ── 3. Onboarding State Machine ──────────────────────
        if query.strip() == "HELLO_INIT" or (intent == "greeting" and stage == "intro" and not profile.get("name")):
            return self._make_response(ONBOARDING_INTRO, stage="ask_age", risk=risk, is_greeting=True)

        if stage == "ask_age":
            if not profile.get("name"):
                profile["name"] = query.strip().title()[:20] if len(query.split()) <= 3 else "Friend"
            return self._make_response(
                ONBOARDING_AGE.format(name=profile.get("name", "Friend")),
                stage="ask_topic", risk=risk, is_greeting=True,
                options=["Under 18", "18–25", "26–40", "41–60", "Over 60"],
            )

        if stage == "ask_topic":
            if not profile.get("age"):
                profile["age"] = query.strip()
            return self._make_response(
                ONBOARDING_READY.format(name=profile.get("name", "Friend")),
                stage="followup", risk=risk, is_greeting=True,
                options=[
                    "I am facing domestic violence at home",
                    "My husband/in-laws are demanding dowry",
                    "I am facing harassment at my workplace",
                    "I need to file a complaint against my abuser",
                    "I need to understand maintenance / alimony rights",
                ],
            )

        # ── 4. Conversational / Off-topic ────────────────────
        if intent == "conversational":
            safety_resp = get_safety_response(intent, risk)
            if safety_resp:
                return self._make_response(safety_resp, stage=stage, risk=risk, is_greeting=True)

        if intent == "off_topic":
            safety_resp = get_safety_response(intent, risk)
            return self._make_response(
                safety_resp or "I can only analyze legal matters related to women's safety in India.",
                stage=stage, risk=risk, is_legal=False,
            )

        # ── 5. Emergency Fast-Path ───────────────────────────
        if risk["level"] in ("high", "emergency"):
            logger.warning(f"[RISK] High/emergency risk detected for query.")

        # ── 6. Clarification (skip for emergencies) ──────────
        if risk["level"] not in ("high", "emergency"):
            clarification = detect_missing_factors(query, conversation_history)
            if clarification["needs_clarification"]:
                logger.info(f"[CLARIFY] Missing: {clarification['missing_factors']}")
                return {
                    "response":           clarification["message"],
                    "sources":            [],
                    "stage":              stage,
                    "domain":             classify_domain(query),
                    "risk":               risk,
                    "provider":           None,
                    "retrieval_error":    None,
                    "emotional_state":    emotional_state,
                    "needs_clarification": True,
                    "suggestions":        clarification["suggestions"],
                    "missing_factors":    clarification["missing_factors"],
                }

        # ── 7. Domain Classification ─────────────────────────
        domains = classify_domain(query)
        logger.info(f"[PIPELINE] Intent={intent} | Emotion={emotional_state} | Domain={domains}")

        # ── 8. Precedent Retrieval ───────────────────────────
        t_retrieve = time.time()
        try:
            results = retrieve(
                query=query,
                namespaces=domains if domains != ["general"] else None,
                top_k=TOP_K_RETRIEVE,
                use_mmr=True,
            )
            retrieval_error = None
        except Exception as e:
            logger.error(f"[RETRIEVE] Failed: {e}")
            results        = []
            retrieval_error = str(e)

        retrieval_ms = int((time.time() - t_retrieve) * 1000)
        n_precedents = len(results)
        logger.info(f"[TELEMETRY] Retrieval latency: {retrieval_ms}ms | Precedents found: {n_precedents}")

        # ── 9. Reranking ─────────────────────────────────────
        if results and USE_RERANKER:
            try:
                results = rerank(query, results, top_k=TOP_K_RERANK)
            except Exception as e:
                logger.warning(f"[RERANK] Failed: {e}")
                results = results[:TOP_K_RERANK]
        elif results:
            results = results[:TOP_K_RERANK]

        # ── 10. Context Compression ──────────────────────────
        # Build rich internal context from case metadata — NOT shown to user
        context = format_context(results, max_chars=MAX_CONTEXT_CHARS) if results else \
                  "No matching precedents found. Use general legal knowledge."
        # ── 10b. Pinecone Prediction Engine ──────────────────────
        # Run the structured prediction engine on retrieved cases
        pinecone_prediction = None
        try:
            pinecone_prediction = _pinecone_predictor.predict(
                user_query=query,
                retrieved_cases=results,
                user_profile=profile,
            )
            enrichment = pinecone_prediction.get("enrichment_context", "")
            if enrichment:
                context = context + "\n\n" + enrichment
            logger.info(
                f"[PREDICTION] Factors={pinecone_prediction.get('user_factors', [])} | "
                f"Top={pinecone_prediction.get('outcome_predictions', {}).get('top_outcome', 'N/A')} | "
                f"Conf={pinecone_prediction.get('confidence_score', 0):.2f}"
            )
        except Exception as e:
            logger.warning(f"[PREDICTION] Pinecone prediction engine failed: {e}")
            pinecone_prediction = None
        # ── 11. Build Prediction Prompt ──────────────────────
        # Build personalised trust block using user's name + detected domain
        _trust_name = profile.get("name", "")
        _trust_sit  = " ".join(domains) if domains else ""
        emergency_section = build_trust_block(_trust_name, _trust_sit) if risk["level"] in ("high", "emergency") else ""
        profile_str       = self._format_profile(profile, conversation_history)
        history_text      = "\n".join(
            f"{m['role'].upper()}: {m['content'][:400]}"
            for m in (conversation_history or [])[-8:]
        )

        # Clarification section if info is still thin
        clarification_section = ""
        if not conversation_history or len(conversation_history) < 2:
            clarification_section = (
                "### ❓ INFORMATION THAT WOULD IMPROVE PREDICTION ACCURACY\n\n"
                "To sharpen these predictions, please confirm:\n\n"
                "• Was a written complaint or FIR already filed?\n"
                "• Do you have any photograph, medical, or digital evidence?\n"
                "• Which state/jurisdiction does this case fall under?\n"
                "• Are there any witnesses to the incidents?\n\n"
                "*You can answer any of these to receive a more accurate analysis.*"
            )

        t_llm = time.time()
        prompt = PREDICTION_PROMPT.format(
            context              = context,
            query                = query,
            profile              = profile_str,
            history              = history_text or "First message in this session.",
            risk_level           = risk["level"],
            emotional_state      = emotional_state,
            domain               = ", ".join(domains),
            language             = language,
            emergency_section    = emergency_section,
            clarification_section = clarification_section,
        )

        # ── 12. LLM Generation ───────────────────────────────
        llm_result    = llm_generate(prompt=prompt, system_prompt=SYSTEM_PROMPT)
        response_text = llm_result["text"]
        llm_ms        = int((time.time() - t_llm) * 1000)

        # ── 13. Confidence Proxy ─────────────────────────────
        # Simple heuristic: more precedents + longer response = higher confidence
        confidence_score = min(0.95, 0.40 + (n_precedents * 0.06) + (min(len(response_text), 2000) / 10000))
        logger.info(
            f"[TELEMETRY] LLM latency: {llm_ms}ms | "
            f"Precedents analyzed: {n_precedents} | "
            f"Confidence score: {confidence_score:.2f} | "
            f"Provider: {llm_result.get('provider', 'unknown')}"
        )

        # Trust block already embedded in PREDICTION_PROMPT via {emergency_section} — do not double-prepend

        # ── 14. Continuous Learning ──────────────────────────
        is_new_pattern = not _is_duplicate_query(query)
        if is_new_pattern:
            # Extract a rough facts summary from the query
            facts_summary = f"Domain: {', '.join(domains)} | Risk: {risk['level']} | Query length: {len(query)}"
            _store_case_pattern(
                query         = query,
                facts_summary = facts_summary,
                response      = response_text,
                documents     = [],   # could be parsed from response in future
            )
            logger.info(f"[LEARNING] New pattern stored (duplicate={not is_new_pattern})")
        else:
            logger.info(f"[LEARNING] Duplicate query — skipping storage")

        total_ms = int((time.time() - t0) * 1000)
        logger.info(f"[TELEMETRY] Total pipeline time: {total_ms}ms")

        # Sources omitted from user-facing response (cases never shown to user)
        return {
            "response":        response_text,
            "sources":         [],          # intentionally empty — cases are internal only
            "stage":           "followup",
            "domain":          domains,
            "risk":            {"level": risk["level"]},
            "provider":        llm_result.get("provider"),
            "retrieval_error": retrieval_error or llm_result.get("error"),
            "emotional_state": emotional_state,
            # Pinecone prediction data (used by main.py for structured output)
            "_pinecone_prediction": pinecone_prediction,
            # Telemetry (backend only, not shown in chat UI)
            "_telemetry": {
                "retrieval_ms":       retrieval_ms,
                "llm_ms":             llm_ms,
                "total_ms":           total_ms,
                "n_precedents":       n_precedents,
                "confidence_score":   round(confidence_score, 3),
                "is_new_pattern":     is_new_pattern,
            },
        }

    # ── Profile Helpers ──────────────────────────────────────────

    def _extract_profile_info(self, query: str, profile: dict):
        """Extract name and age from user message if mentioned."""
        name_patterns = [
            r"(?:my\s+name\s+(?:is|'s)\s+)([a-zA-Z]+)",
            r"(?:i\s+am\s+|i'm\s+)([a-zA-Z]+)(?:\s|$|,)",
            r"(?:call\s+me\s+)([a-zA-Z]+)",
        ]
        for p in name_patterns:
            m = re.search(p, query, re.IGNORECASE)
            if m and len(m.group(1)) > 1:
                profile["name"] = m.group(1).capitalize()
                break

        age_patterns = [
            r"(?:i\s+am|i'm|age\s+is|aged?)\s+(\d{1,2})\s*(?:years?|yrs?|y\.?o\.?)?",
            r"(\d{1,2})\s*(?:years?\s*old|yrs?\s*old)",
        ]
        for p in age_patterns:
            m = re.search(p, query, re.IGNORECASE)
            if m:
                age = int(m.group(1))
                if 10 <= age <= 99:
                    profile["age"] = str(age)
                    break

    def _format_profile(self, profile: dict, history: Optional[list[dict]]) -> str:
        """Format user profile for prompt injection."""
        parts = []
        if profile.get("name"):
            parts.append(f"Name: {profile['name']}")
        if profile.get("age"):
            parts.append(f"Age: {profile['age']}")
        if profile.get("situation_summary"):
            parts.append(f"Situation: {profile['situation_summary']}")
        parts.append(f"Messages exchanged: {len(history) if history else 0}")
        return " | ".join(parts) if parts else "No profile yet."

    def _make_response(self, text, stage="intro", risk=None, is_greeting=False,
                       is_legal=True, options=None, **kwargs):
        """Helper to build a response dict."""
        return {
            "response":        text,
            "sources":         [],
            "stage":           stage,
            "domain":          [],
            "risk":            risk or {"level": "low"},
            "provider":        None,
            "retrieval_error": None,
            "is_greeting":     is_greeting,
            "is_legal":        is_legal,
            "emotional_state": "neutral",
            "options":         options or [],
        }
