# evals/run_evals.py

import asyncio
import json
import sys

from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))


from dotenv import load_dotenv
from agent.traced_agent import run_traced_investigation
from evals.scorer import score_report

load_dotenv()



PASS_THRESHOLD = 0.70  # If overall score drops below 70%, fail the eval

async def run_evals():
    # Load all test cases
    with open("evals/test_cases.json") as f:
        test_cases = json.load(f)
    
    all_scores = []
    
    for case in test_cases:
        print(f"\nRunning eval: {case['id']}")
    
        # try:
        report = await run_traced_investigation(case["ticket"])
        scores = score_report(report, case["expected"])
        # except Exception as e:
        #     print(f"  ⚠️ Eval {case['id']} failed: {e} — scoring as 0.0")
        #     scores = {
        #         "diagnosis_accuracy":  0.0,
        #         "steps_completeness":  0.0,
        #         "evidence_grounding":  0.0,
        #         "past_incident_recall": 0.0,
        #         "report_actionability": 0.0,
        #         "overall":             0.0
        #     }
    
        print(f"  Overall:   {scores['overall']:.2f}")
        print(f"  Diagnosis: {scores['diagnosis_accuracy']:.2f} | Steps: {scores['steps_completeness']:.2f}")
        print(f"  Grounding: {scores['evidence_grounding']:.2f} | Recall: {scores['past_incident_recall']:.2f}")
    
        all_scores.append(scores["overall"])
    
    # Average across all test cases
    avg_score = sum(all_scores) / len(all_scores)
    print(f"\n{'='*40}")
    print(f"AVERAGE SCORE: {avg_score:.2f}")
    
    if avg_score < PASS_THRESHOLD:
        print(f"❌ FAILED — score below threshold ({PASS_THRESHOLD})")
        sys.exit(1)  # Exit code 1 = failure. GitHub Actions reads this.
    else:
        print(f"✅ PASSED")
        sys.exit(0)

if __name__ == "__main__":
    asyncio.run(run_evals()) 
