# compliance.py
import os
import random
from typing import List, Dict, Tuple

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

# ---------------------------
# AI Test Case Generator
# ---------------------------
def generate_tests_via_llm(requirement_text: str, openai_key: str = None) -> List[Dict]:
    """
    Generates test cases for a requirement.
    - If OPENAI_API_KEY is set, uses OpenAI's GPT model
    - Otherwise, returns synthetic fallback tests
    """
    if openai_key and OpenAI:
        client = OpenAI(api_key=openai_key)

        prompt = f"""
You are an expert software QA engineer specializing in regulated domains 
(HIPAA, GDPR, 21 CFR Part 11). 
Given the requirement below, generate 2-3 test cases.

Requirement: {requirement_text}

For each test case, return JSON with fields:
- title (string)
- steps (list of steps, each a short string)
"""
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )
            content = response.choices[0].message.content
            import json
            parsed = json.loads(content)
            # Expecting {"tests":[{...},{...}]}
            return parsed.get("tests", [])
        except Exception as e:
            print("⚠️ LLM call failed, fallback mode:", e)

    # -------- Fallback demo tests --------
    base = [
        {
            "title": "Positive - happy path",
            "steps": [
                "Set up valid user with required roles",
                "Perform action per requirement",
                "Check success response and audit log"
            ]
        },
        {
            "title": "Negative - invalid input",
            "steps": [
                "Use malformed input",
                "Verify rejection with proper error code",
                "Ensure no data leakage"
            ]
        }
    ]
    return base

# ---------------------------
# Compliance Engine
# ---------------------------
class ComplianceEngine:
    RULES = {
        "PHI": [{"reg":"HIPAA", "clause":"164.308", "msg":"Access control for PHI required."}],
        "audit": [{"reg":"21CFR", "clause":"11.10", "msg":"Audit trails required."}],
        "encrypt": [{"reg":"GDPR", "clause":"32", "msg":"Encryption required for personal data."}]
    }

    def assess_test_and_justify(self, requirement_text: str, test_case: dict) -> Tuple[List[dict], float]:
        justification = []
        score = 0.2
        rt = requirement_text.lower()

        if "phi" in rt:
            justification += self.RULES["PHI"]; score += 0.4
        if "audit" in rt:
            justification += self.RULES["audit"]; score += 0.3
        if "encrypt" in rt:
            justification += self.RULES["encrypt"]; score += 0.25

        steps_text = " ".join(test_case.get("steps", [])).lower()
        if "audit" in steps_text and not any(j["reg"]=="21CFR" for j in justification):
            justification.append({"reg":"21CFR", "clause":"11.10", "msg":"Audit trail mentioned in steps."})
            score += 0.1

        for j in justification:
            j["explanation"] = f"Requirement relates to {j['reg']} {j['clause']} — {j['msg']}"

        return justification, min(1.0, round(score, 3))
