# evals/scorer.py

import os
import json
from groq import Groq

client = Groq()

def score_report(report, expected: dict) -> dict:
    """
    Scores an agent-generated report against the expected outcomes.
    Returns a dict of scores, each 0.0 to 1.0.

    Report schema (from generate_report):
    {
        "ticket_id":    str,
        "generated_at": str,
        "triage": {
            "priority":         str,
            "category":         str,
            "affected_service": str
        },
        "diagnosis": {
            "most_likely_root_cause": str,
            "confidence":             str,
            "supporting_evidence":    str   ← evidence_summary plain text
        },
        "resolution": str,                  ← resolution_summary plain text
        "generated_by": str
    }
    """

    # ── Parse report: unwrap JSON string(s) until we have a dict ─────────────
    # LLaMA / MCP can double or triple encode the JSON — loop until it's a dict
    if isinstance(report, str):
        try:
            while isinstance(report, str):
                report = json.loads(report)
        except (json.JSONDecodeError, TypeError):
            print(f"  ⚠️  Could not parse report as JSON — scoring as empty")
            report = {}

    # Safety net: if after all parsing we still don't have a dict, score as empty
    if not isinstance(report, dict):
        print(f"  ⚠️  Report is not a dict (got {type(report).__name__}) — scoring as empty")
        report = {}

    scores = {}   # always defined here, never inside a branch

    # ── Score 1: Diagnosis Accuracy ───────────────────────────────────────────
    # Checks report["diagnosis"]["most_likely_root_cause"] for expected keywords.
    root_cause = report.get("diagnosis", {}).get("most_likely_root_cause", "").lower()

    keyword_hits = sum(
        1 for kw in expected["root_cause_keywords"]
        if kw.lower() in root_cause
    )
    scores["diagnosis_accuracy"] = 1.0 if keyword_hits > 0 else 0.0

    # ── Score 2: Steps Completeness ───────────────────────────────────────────
    # resolution is now a plain text string (resolution_summary), not a list.
    # We search for required keywords directly in that string.
    resolution_text = report.get("resolution", "").lower()

    step_hits = sum(
        1 for kw in expected["required_steps_keywords"]
        if kw.lower() in resolution_text
    )
    # Partial credit: 2 out of 3 keywords → 0.67
    scores["steps_completeness"] = step_hits / len(expected["required_steps_keywords"])

    # ── Score 3: Evidence Grounding (LLM-based) ───────────────────────────────
    # Checks report["diagnosis"]["supporting_evidence"] — plain text string.
    # Ask the LLM: are the claims backed by actual log/metric evidence?
    supporting_evidence = report.get("diagnosis", {}).get("supporting_evidence", "")

    prompt = f"""
    You are an evaluator. Given this supporting evidence from an investigation report,
    score how well every claim is backed by actual log or metric evidence.
    Score 0.0 to 1.0. Respond with ONLY a number, nothing else.

    Supporting evidence: {supporting_evidence}
    Full report: {json.dumps(report)}
    """
    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}]
        )
        scores["evidence_grounding"] = float(response.choices[0].message.content.strip())
    except Exception as e:
        print(f"  ⚠️  Evidence grounding scoring failed: {e}")
        scores["evidence_grounding"] = 0.0

    # ── Score 4: Past Incident Recall ─────────────────────────────────────────
    # Past incident references live in diagnosis["supporting_evidence"] (plain text)
    # and/or resolution (plain text). We search both for the expected incident ID.
    if expected["should_find_past_incident"]:
        search_text = (
            report.get("diagnosis", {}).get("supporting_evidence", "") + " " +
            report.get("resolution", "")
        ).lower()

        expected_id = expected["past_incident_id"].lower()
        scores["past_incident_recall"] = 1.0 if expected_id in search_text else 0.0
    else:
        scores["past_incident_recall"] = 1.0

    # ── Score 5: Report Actionability (LLM-based) ─────────────────────────────
    # resolution is plain text — ask LLM if an engineer can immediately act on it.
    prompt2 = f"""
    You are an evaluator. Given this resolution from an investigation report,
    score how actionable it is for a human engineer — can they immediately start
    working from this? Score 0.0 to 1.0. Respond with ONLY a number.

    Resolution: {report.get("resolution", "")}
    """
    try:
        response2 = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt2}]
        )
        scores["report_actionability"] = float(response2.choices[0].message.content.strip())
    except Exception as e:
        print(f"  ⚠️  Actionability scoring failed: {e}")
        scores["report_actionability"] = 0.0

    # ── Overall: simple average across all 5 dimensions ──────────────────────
    scores["overall"] = sum(scores.values()) / len(scores)

    return scores
