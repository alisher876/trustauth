"""Registration and the login challenge loop (docs/interface.md §7).

POST /auth/register                    create an account
POST /auth/login/start                 build the context, select factors, return the first challenge
POST /auth/login/{login_id}/verify     check one factor answer; next / retry / authenticated / denied
GET  /auth/me                          who is logged in (Authorization: Bearer <session>)

Unknown usernames get a normal-looking login with decoy factors that always fail, so an
attacker cannot tell which usernames exist. Decoy attempts are not logged.
"""

from __future__ import annotations

import logging
import re
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.context import ClientInfo, build_login_context
from app.core.db import get_db
from app.core.flow import Decision, LoginProgress, decide
from app.core.login_store import LoginStore, get_store
from app.core.models import Attempt, User
from app.engine.selection import candidates, select_fixed
from app.factors.base import FactorResult, LoginContext, get_factor, registered_factors

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

USERNAME_PATTERN = re.compile(r"^[a-z0-9_.-]{3,32}$")
SELECTOR = "fixed"  # week 3; "adaptive" from week 6
RISK_LEVEL = "low"  # week 3; risk score v1 in week 5
DECOY_USER = "unknown"  # user_id passed to start() for unknown usernames


# --- request bodies ------------------------------------------------------------------


class RegisterRequest(BaseModel):
    username: str

    @field_validator("username")
    @classmethod
    def _valid_username(cls, value: str) -> str:
        value = value.strip().lower()
        if not USERNAME_PATTERN.fullmatch(value):
            raise ValueError("3-32 characters: lowercase letters, digits, '.', '_' or '-'")
        return value


class LoginStartRequest(BaseModel):
    username: str = Field(max_length=64)
    client: ClientInfo = ClientInfo()


class VerifyRequest(BaseModel):
    factor: str
    payload: dict = Field(default_factory=dict)


# --- registration ----------------------------------------------------------------------


@router.post("/register", status_code=201)
def register_user(body: RegisterRequest, db: Session = Depends(get_db)) -> dict:
    if db.scalar(select(User).where(User.username == body.username)) is not None:
        raise HTTPException(status_code=409, detail="username already taken")
    user = User(username=body.username)
    db.add(user)
    db.commit()
    return {"user_id": user.id}


# --- login -------------------------------------------------------------------------------


@router.post("/login/start")
async def login_start(body: LoginStartRequest, request: Request, db: Session = Depends(get_db),
                      store: LoginStore = Depends(get_store)) -> dict:
    user = db.scalar(select(User).where(User.username == body.username.strip().lower()))
    login_id = str(uuid.uuid4())
    ip = request.client.host if request.client else "0.0.0.0"
    ctx = build_login_context(login_id, request.headers.get("user-agent", ""), ip, body.client)

    # Usable = available in this context AND (for a real user) enrolled.
    usable = []
    for name, factor in registered_factors().items():
        if factor.is_available(ctx) and (user is None or await factor.is_enrolled(user.id)):
            usable.append(name)

    plan = select_fixed(usable)
    if not plan:
        raise HTTPException(status_code=422, detail="no authentication method is usable on this device")
    spare = [name for name in candidates(usable) if name not in plan]
    progress = LoginProgress(plan=plan, spare=spare)

    challenge = await get_factor(plan[0]).start(user.id if user else DECOY_USER, ctx)
    store.save_login(login_id, {
        "user_id": user.id if user else None,
        "context": ctx.model_dump(),
        "selected_factors": list(plan),
        "progress": progress.to_dict(),
    })
    return {"login_id": login_id, "factors": plan, "next": {"factor": plan[0], "challenge": challenge}}


@router.post("/login/{login_id}/verify")
async def login_verify(login_id: str, body: VerifyRequest, db: Session = Depends(get_db),
                       store: LoginStore = Depends(get_store)) -> dict:
    state = store.load_login(login_id)
    if state is None:
        raise HTTPException(status_code=404, detail="login not found or expired")
    progress = LoginProgress.from_dict(state["progress"])
    ctx = LoginContext(**state["context"])
    if body.factor != progress.current:
        raise HTTPException(status_code=409, detail=f"expected factor {progress.current!r}")

    user_id = state["user_id"]
    if user_id is None:
        # Decoy login for an unknown username: always rejected, never logged.
        result = FactorResult(factor=progress.current, accepted=False, score=0.0, duration_ms=0)
    else:
        result = await _run_verify(progress.current, user_id, body.payload, ctx)
        light = result.context.get("light")
        if light in ("normal", "dim"):
            ctx.light = light  # face measured the light: the condition is now known exactly
        _log_attempt(db, login_id, user_id, result, ctx, state["selected_factors"])

    decision = decide(progress, result)
    if decision.status in ("authenticated", "denied"):
        store.delete_login(login_id)
    else:
        state["progress"] = progress.to_dict()
        state["context"] = ctx.model_dump()
        store.save_login(login_id, state)
    return await _response(decision, user_id, ctx, store)


@router.get("/me")
def me(authorization: str = Header(default=""), db: Session = Depends(get_db),
       store: LoginStore = Depends(get_store)) -> dict:
    token = authorization.removeprefix("Bearer ").strip()
    user_id = store.session_user(token) if token else None
    user = db.get(User, user_id) if user_id else None
    if user is None:
        raise HTTPException(status_code=401, detail="not logged in")
    return {"user_id": user.id, "username": user.username}


# --- helpers -------------------------------------------------------------------------------


async def _run_verify(factor_name: str, user_id: str, payload: dict, ctx: LoginContext) -> FactorResult:
    """Call the factor's verify(). A crash or a result for the wrong factor becomes error "internal"."""
    try:
        result = await get_factor(factor_name).verify(user_id, payload, ctx)
        if result.factor != factor_name:
            raise ValueError(f"{factor_name} returned a result for {result.factor}")
        return result
    except Exception:
        logger.exception("factor %s failed during verify", factor_name)
        return FactorResult(factor=factor_name, accepted=False, score=0.0, duration_ms=0, error="internal")


def _log_attempt(db: Session, login_id: str, user_id: str, result: FactorResult, ctx: LoginContext,
                 selected: list[str]) -> None:
    """Write one row of the attempt log (interface §9). Study labels stay null in normal use."""
    db.add(Attempt(
        login_id=login_id, user_id=user_id, factor=result.factor, accepted=result.accepted,
        score=result.score, duration_ms=result.duration_ms, error=result.error,
        condition=ctx.condition, context={"login": ctx.model_dump(), "factor": result.context},
        risk_level=RISK_LEVEL, selected_factors=selected, selector=SELECTOR,
    ))
    db.commit()


async def _response(decision: Decision, user_id: str | None, ctx: LoginContext, store: LoginStore) -> dict:
    if decision.status == "authenticated":
        return {"status": "authenticated", "session": store.create_session(user_id)}
    if decision.status == "denied":
        return {"status": "denied"}
    challenge = await get_factor(decision.factor).start(user_id or DECOY_USER, ctx)
    response = {"status": decision.status, "next": {"factor": decision.factor, "challenge": challenge}}
    if decision.status == "retry":
        response["reason"] = decision.reason
    return response
