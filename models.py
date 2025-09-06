# models.py
from pydantic import BaseModel
from typing import List, Optional

class ProjectCreate(BaseModel):
    name: str
    region: str = "US"
    regulations: List[str] = ["HIPAA", "21CFR"]

class IngestResponse(BaseModel):
    project_id: int
    ingested: int
    requirements: List[dict]

class TestCaseOut(BaseModel):
    test_id: int
    requirement_id: int
    title: str
    steps: List[str]
    compliance_justification: List[dict]
    risk_score: float
