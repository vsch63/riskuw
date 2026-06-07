"""
backend/services/ai_score.py
─────────────────────────────
AI Risk Scoring engines for underwriting assist.
Supports three engines:
  1. xgboost  — local ML model (trained on synthetic data at first call)
  2. claude   — Anthropic Claude API (requires ANTHROPIC_API_KEY in system_config)
  3. ollama   — local Ollama LLM (llava-llama3 at 172.17.0.1:11434)

Called by POST /underwriting/ai-score
"""
from __future__ import annotations
import json
import logging
import os
from typing import Any

logger = logging.getLogger("uw_platform")

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://dnb_ollama:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llava-llama3:latest")

# ── Shared prompt builder ─────────────────────────────────────────────────────
def _build_prompt(payload: dict) -> str:
    age         = payload.get("age", "?")
    gender      = payload.get("gender", "?")
    face        = float(payload.get("face_amount") or 0)
    tobacco     = payload.get("tobacco_status", "NON_TOBACCO")
    bmi         = payload.get("bmi") or _calc_bmi(payload)
    diabetes    = payload.get("diabetes_type", "NONE")
    heart       = payload.get("heart_condition", "NONE")
    bp_sys      = payload.get("systolic_bp", 120)
    bp_dia      = payload.get("diastolic_bp", 80)
    hiv         = payload.get("hiv_positive", False)
    stroke      = payload.get("stroke_history", False)
    kidney      = payload.get("kidney_disease", False)
    copd        = payload.get("copd", False)
    alcohol     = payload.get("alcohol_drinks_week", 0)
    hazardous   = payload.get("hazardous_activity", False)
    occ_class   = payload.get("occupation_class", 1)
    income      = float(payload.get("annual_income") or 0)
    net_debits  = payload.get("net_debit_points", 0)
    uw_outcome  = payload.get("uw_outcome", "")

    # Build risk flags list
    flags = []
    if str(tobacco).upper() in ("SMOKER","TOBACCO"): flags.append("tobacco user")
    if bmi and float(bmi) > 30: flags.append(f"overweight BMI {bmi}")
    if str(diabetes).upper() not in ("NONE",""): flags.append(f"diabetes {diabetes}")
    if str(heart).upper() not in ("NONE",""): flags.append("cardiac history")
    if bp_sys and int(bp_sys) > 140: flags.append(f"hypertension {bp_sys}/{bp_dia}")
    if hiv: flags.append("HIV positive")
    if stroke: flags.append("stroke history")
    if kidney: flags.append("kidney disease")
    if copd: flags.append("COPD")
    if alcohol and int(alcohol) > 14: flags.append(f"heavy alcohol use {alcohol}/week")
    if hazardous: flags.append("hazardous activity")

    positives = []
    if age and int(age) < 40: positives.append(f"young age {age}")
    if bmi and 18 < float(bmi) < 27: positives.append(f"healthy BMI {bmi}")
    if not flags: positives.append("no major risk factors")

    flags_str    = ", ".join(flags)    if flags    else "none identified"
    positives_str = ", ".join(positives) if positives else "none"

    return f"""You are a life insurance underwriting AI. Assess this applicant and return ONLY a JSON object.

APPLICANT: Age {age}, {gender}, Face Amount ₹{face:,.0f}
RISK FLAGS: {flags_str}
POSITIVE FACTORS: {positives_str}
RULES ENGINE DECISION: {uw_outcome or "not run"} (debit points: {net_debits})

Return ONLY this JSON with real values filled in (no placeholders):
{{
  "risk_tier": "STANDARD",
  "confidence": 0.85,
  "risk_score": 25,
  "primary_concerns": {json.dumps(flags[:3]) if flags else '[]'},
  "positive_factors": {json.dumps(positives[:3]) if positives else '[]'},
  "recommendation": "APPROVE",
  "narrative": "Brief 2 sentence assessment based on the risk flags above.",
  "loading_suggestion": "Standard rates"
}}

Rules: risk_tier must be STANDARD/SUBSTANDARD/RATED/DECLINED. risk_score 0-100 (higher=riskier). Return ONLY the JSON, no other text."""


def _build_narrative(payload: dict, result: dict) -> str:
    """Generate a readable narrative from structured result — used when LLM leaves it blank."""
    age       = payload.get("age", "?")
    gender    = payload.get("gender", "?").lower()
    tier      = result.get("risk_tier", "STANDARD")
    score     = result.get("risk_score", 0)
    concerns  = result.get("primary_concerns", [])
    positives = result.get("positive_factors", [])
    rec       = result.get("recommendation", "APPROVE")

    concern_txt  = f"Key risk factors: {', '.join(concerns[:3])}." if concerns else "No major risk factors identified."
    positive_txt = f"Favourable factors: {', '.join(positives[:2])}." if positives else ""

    tier_map = {
        "STANDARD":    "presents a standard risk profile",
        "SUBSTANDARD": "presents a substandard risk profile with some concerns",
        "RATED":       "presents an elevated risk requiring rated terms",
        "DECLINED":    "presents risks that exceed insurable limits",
    }
    tier_desc = tier_map.get(tier, "has been assessed")

    return (
        f"This {age}-year-old {gender} {tier_desc} (AI risk score: {score}/100). "
        f"{concern_txt} {positive_txt} "
        f"Recommended action: {rec}."
    ).strip()


def _calc_bmi(payload: dict):
    h = payload.get("height_inches")
    w = payload.get("weight_lbs")
    try:
        h = float(h) if h is not None else None
        w = float(w) if w is not None else None
    except (ValueError, TypeError):
        return None
    if h and w and h > 0:
        return round((w / (h ** 2)) * 703, 1)
    return None


def _safe_parse(text: str) -> dict:
    """Extract JSON from LLM response."""
    text = text.strip()
    # Try direct parse
    try:
        return json.loads(text)
    except Exception:
        pass
    # Extract JSON block
    import re
    m = re.search(r'\{[\s\S]*\}', text)
    if m:
        try:
            return json.loads(m.group())
        except Exception:
            pass
    return {}


# ── ENGINE 1: XGBoost ─────────────────────────────────────────────────────────
_xgb_model = None  # lazy-loaded singleton

def _get_xgb_model():
    global _xgb_model
    if _xgb_model is not None:
        return _xgb_model
    try:
        import xgboost as xgb
        import numpy as np
        from sklearn.datasets import make_classification
        from sklearn.model_selection import train_test_split

        logger.info("Training XGBoost model on synthetic data...")
        np.random.seed(42)
        n = 10000

        # Generate synthetic underwriting data
        age         = np.random.randint(18, 75, n)
        bmi         = np.random.normal(26, 5, n).clip(15, 50)
        tobacco     = np.random.choice([0, 1], n, p=[0.75, 0.25])
        diabetes    = np.random.choice([0, 1, 2], n, p=[0.80, 0.10, 0.10])
        heart       = np.random.choice([0, 1], n, p=[0.90, 0.10])
        bp_sys      = np.random.normal(125, 20, n).clip(90, 200)
        hiv         = np.random.choice([0, 1], n, p=[0.99, 0.01])
        stroke      = np.random.choice([0, 1], n, p=[0.97, 0.03])
        kidney      = np.random.choice([0, 1], n, p=[0.97, 0.03])
        alcohol     = np.random.randint(0, 21, n)
        hazardous   = np.random.choice([0, 1], n, p=[0.90, 0.10])
        occ_class   = np.random.randint(1, 5, n)
        face_ratio  = np.random.uniform(1, 20, n)  # face/income ratio

        X = np.column_stack([
            age, bmi, tobacco, diabetes, heart, bp_sys,
            hiv, stroke, kidney, alcohol, hazardous, occ_class, face_ratio,
        ])

        # Risk score (0=low risk, 1=high risk)
        risk = (
            (age > 55).astype(float) * 0.2 +
            (bmi > 35).astype(float) * 0.15 +
            tobacco * 0.15 +
            (diabetes > 0).astype(float) * 0.15 +
            heart * 0.15 +
            (bp_sys > 140).astype(float) * 0.10 +
            hiv * 0.40 +
            stroke * 0.20 +
            kidney * 0.15 +
            (alcohol > 14).astype(float) * 0.10 +
            hazardous * 0.10 +
            (occ_class > 2).astype(float) * 0.05 +
            (face_ratio > 15).astype(float) * 0.05
        )
        y = (risk + np.random.normal(0, 0.05, n) > 0.35).astype(int)

        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
        model = xgb.XGBClassifier(
            n_estimators=200, max_depth=5, learning_rate=0.1,
            use_label_encoder=False, eval_metric='logloss',
            random_state=42,
        )
        model.fit(X_train, y_train)
        _xgb_model = model
        auc = model.score(X_test, y_test)
        logger.info(f"XGBoost model trained. Accuracy: {auc:.3f}")
        return _xgb_model
    except Exception as e:
        logger.error(f"XGBoost training failed: {e}")
        return None


def score_xgboost(payload: dict) -> dict:
    try:
        import numpy as np

        def _f(key, default=0):
            try: return float(payload.get(key) or default)
            except: return float(default)

        def _b(key):
            v = payload.get(key)
            if isinstance(v, bool): return 1.0 if v else 0.0
            return 1.0 if str(v).lower() in ("true","1","yes") else 0.0

        model     = _get_xgb_model()
        if model is None:
            return {"error": "XGBoost model not available — install xgboost package"}

        age       = _f("age", 35)
        bmi       = float(_calc_bmi(payload) or payload.get("bmi") or 26)
        tobacco   = 1.0 if str(payload.get("tobacco_status","")).upper() in ("SMOKER","TOBACCO") else 0.0
        diabetes  = {"NONE":0,"TYPE1":2,"TYPE2":1}.get(str(payload.get("diabetes_type","NONE")).upper(), 0)
        heart     = 0.0 if str(payload.get("heart_condition","NONE")).upper() in ("NONE","") else 1.0
        bp_sys    = _f("systolic_bp", 120)
        hiv       = _b("hiv_positive")
        stroke    = _b("stroke_history")
        kidney    = _b("kidney_disease")
        alcohol   = _f("alcohol_drinks_week", 0)
        hazardous = _b("hazardous_activity")
        occ_class = _f("occupation_class", 1)
        income    = _f("annual_income", 1) or 1
        face      = _f("face_amount", 0)
        face_ratio = min(face / income, 20) if income > 0 else 10

        X = np.array([[age, bmi, tobacco, diabetes, heart, bp_sys,
                        hiv, stroke, kidney, alcohol, hazardous, occ_class, face_ratio]])

        prob_high_risk = float(model.predict_proba(X)[0][1])
        risk_score     = round(prob_high_risk * 100, 1)

        if prob_high_risk < 0.25:
            risk_tier = "STANDARD"; recommendation = "APPROVE"
        elif prob_high_risk < 0.50:
            risk_tier = "SUBSTANDARD"; recommendation = "RATE"
        elif prob_high_risk < 0.75:
            risk_tier = "RATED"; recommendation = "REFER"
        else:
            risk_tier = "DECLINED"; recommendation = "DECLINE"

        concerns = []
        positives = []
        if tobacco:    concerns.append("Tobacco use")
        if bmi > 35:   concerns.append(f"Elevated BMI ({bmi:.1f})")
        if diabetes:   concerns.append("Diabetes history")
        if heart:      concerns.append("Cardiac history")
        if bp_sys > 140: concerns.append(f"Hypertension (BP {bp_sys:.0f})")
        if hiv:        concerns.append("HIV positive")
        if stroke:     concerns.append("Stroke history")
        if age < 45 and not tobacco: positives.append("Young age")
        if bmi < 28:   positives.append("Healthy BMI")
        if not diabetes and not heart: positives.append("No major medical history")

        loading = {
            "STANDARD":    "Standard rates",
            "SUBSTANDARD": "+25% to +50% loading",
            "RATED":       "+75% to +150% loading or Table rating",
            "DECLINED":    "Not insurable at standard or rated terms",
        }[risk_tier]

        xgb_result = {
            "engine":          "xgboost",
            "risk_tier":       risk_tier,
            "confidence":      round(1 - abs(prob_high_risk - 0.5) * 0.5, 2),
            "risk_score":      risk_score,
            "primary_concerns": concerns[:4],
            "positive_factors": positives[:3],
            "recommendation":  recommendation,
            "loading_suggestion": loading,
        }
        xgb_result["narrative"] = _build_narrative(payload, xgb_result)
        return xgb_result
    except Exception as e:
        logger.error(f"XGBoost scoring failed: {e}")
        return {"error": str(e)}


# ── ENGINE 2: Claude (Anthropic) ──────────────────────────────────────────────
def score_claude(payload: dict, api_key: str) -> dict:
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        prompt = _build_prompt(payload)
        msg = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        text   = msg.content[0].text
        result = _safe_parse(text)
        if not result:
            return {"error": "Claude returned unparseable response", "raw": text[:200]}
        result["engine"] = "claude"
        return result
    except Exception as e:
        logger.error(f"Claude scoring failed: {e}")
        return {"error": str(e)}


# ── ENGINE 3: Ollama ──────────────────────────────────────────────────────────
def score_ollama(payload: dict, model: str = OLLAMA_MODEL) -> dict:
    try:
        import httpx
        prompt = _build_prompt(payload)

        # llava and vision models use /api/chat with messages format
        resp = httpx.post(
            f"{OLLAMA_HOST}/api/chat",
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.1, "num_predict": 1024},
            },
            timeout=180,
        )
        if resp.status_code != 200:
            return {"error": f"Ollama returned {resp.status_code}: {resp.text[:200]}"}

        data = resp.json()
        text = (data.get("message") or {}).get("content", "")
        if not text:
            return {"error": "Ollama returned empty response", "raw": str(data)[:200]}

        result = _safe_parse(text)
        if not result:
            return {"error": "Ollama returned unparseable response", "raw": text[:300]}
        # Fill narrative if LLM left it blank or returned the placeholder
        if (not result.get("narrative") or
                "brief 2 sentence" in str(result.get("narrative", "")).lower() or
                "based on the risk flags" in str(result.get("narrative", "")).lower()):
            result["narrative"] = _build_narrative(payload, result)
        result["engine"] = "ollama"
        result["model"]  = model
        return result
    except Exception as e:
        logger.error(f"Ollama scoring failed: {e}")
        return {"error": str(e)}


# ── Main dispatcher ───────────────────────────────────────────────────────────
def get_ai_score(payload: dict, engine: str = "xgboost", conn=None) -> dict:
    """
    Main entry point. engine = 'xgboost' | 'claude' | 'ollama'
    conn is a DB connection (for reading system_config API key).
    """
    engine = engine.lower().strip()

    if engine == "xgboost":
        return score_xgboost(payload)

    elif engine == "claude":
        api_key = ""
        # Try DB system_config first
        if conn:
            try:
                cur = conn.cursor()
                cur.execute(
                    "SELECT config_value FROM system_config WHERE config_key = 'anthropic_api_key' LIMIT 1"
                )
                row = cur.fetchone()
                cur.close()
                if row:
                    api_key = dict(row).get("config_value", "") if hasattr(row, "keys") else row[0]
            except Exception:
                pass
        # Fall back to env var
        if not api_key:
            api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            return {"error": "Anthropic API key not configured. Add it in System Config → General → anthropic_api_key"}
        return score_claude(payload, api_key)

    elif engine == "ollama":
        model = payload.pop("ollama_model", None) or OLLAMA_MODEL
        return score_ollama(payload, model)

    else:
        return {"error": f"Unknown engine: {engine}. Use xgboost, claude, or ollama"}
