"""Researcher endpoints for the user study (M1's requests in trust-lab/docs/attempt-log.md).

GET    /admin/study-label     the label currently copied into every attempt row
PUT    /admin/study-label     set it before a block of attempts
DELETE /admin/study-label     clear it (back to normal use: labels null)
GET    /admin/attempts.csv    export the attempt log for the Trust Lab

Protected by the header "X-Admin-Token: <ADMIN_TOKEN from .env>". Without ADMIN_TOKEN set,
the admin endpoints are switched off. The admin dashboard (weeks 8-11) will call these.
"""

from __future__ import annotations

import csv
import io
import json
import os
import secrets
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.login_store import LoginStore, get_store
from app.core.models import Attempt

router = APIRouter(prefix="/admin", tags=["admin"])

# attack_type codes from trust-lab/docs/threat-model.md
AttackType = Literal["printed_photo", "screen_replay", "qr_relay", "mfa_fatigue",
                     "credential_stuffing", "imposter_typing", "passkey_phishing"]

CSV_COLUMNS = ["attempt_id", "login_id", "user_id", "timestamp", "factor", "accepted", "score", "duration_ms",
               "error", "is_genuine", "attack_type", "study_session_id", "condition", "context", "risk_level",
               "selected_factors", "selector"]


def require_admin(x_admin_token: str = Header(default="")) -> None:
    expected = os.getenv("ADMIN_TOKEN", "")
    if not expected:
        raise HTTPException(status_code=503, detail="admin endpoints are off (ADMIN_TOKEN not set)")
    # compare_digest takes the same time whatever the input, so the token cannot be guessed by timing.
    if not secrets.compare_digest(x_admin_token.encode(), expected.encode()):
        raise HTTPException(status_code=403, detail="wrong admin token")


class StudyLabel(BaseModel):
    is_genuine: bool
    attack_type: AttackType | None = None
    study_session_id: str = Field(min_length=1, max_length=40)

    @model_validator(mode="after")
    def _genuine_has_no_attack(self) -> "StudyLabel":
        if self.is_genuine and self.attack_type is not None:
            raise ValueError("a genuine attempt cannot have an attack_type")
        return self


@router.get("/study-label", dependencies=[Depends(require_admin)])
def get_label(store: LoginStore = Depends(get_store)) -> dict:
    return {"label": store.study_label()}


@router.put("/study-label", dependencies=[Depends(require_admin)])
def set_label(label: StudyLabel, store: LoginStore = Depends(get_store)) -> dict:
    store.set_study_label(label.model_dump())
    return {"label": label.model_dump()}


@router.delete("/study-label", dependencies=[Depends(require_admin)])
def clear_label(store: LoginStore = Depends(get_store)) -> dict:
    store.clear_study_label()
    return {"label": None}


@router.get("/attempts.csv", dependencies=[Depends(require_admin)])
def export_attempts(db: Session = Depends(get_db)) -> StreamingResponse:
    """All attempt rows as CSV; `context` and `selected_factors` as JSON strings (attempt-log.md §3)."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(CSV_COLUMNS)
    for row in db.scalars(select(Attempt).order_by(Attempt.timestamp)):
        values = []
        for column in CSV_COLUMNS:
            value = getattr(row, column)
            if column in ("context", "selected_factors"):
                value = json.dumps(value)
            values.append("" if value is None else value)
        writer.writerow(values)
    buffer.seek(0)
    return StreamingResponse(iter([buffer.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=attempts.csv"})
