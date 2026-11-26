"""Registration, enrollment and the login challenge loop (docs/interface.md §7).

POST /auth/register                    create an account; returns a session for enrolling factors
POST /auth/enroll/{factor}/start       enrollment screen data (logged in)
POST /auth/enroll/{factor}/finish      submit enrollment data; may be called several times (logged in)
POST /auth/login/start                 build the context, select factors, return the first challenge
POST /auth/login/{login_id}/verify     check one factor answer; next / retry / authenticated / denied
GET  /auth/me                          who is logged in (Authorization: Bearer <session>)

Unknown usernames get a normal-looking login with decoy factors that always fail, so an
attacker cannot tell which usernames exist. Decoy attempts are not logged.
"""

from __future__ import annotations

import logging
import os
import re
import time
import uuid

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.context import ClientInfo, build_login_context
from app.core.db import get_db
from app.core.flow import Decision, LoginProgress, decide
from app.core.known import DEVICE_COOKIE, DEVICE_COOKIE_MAX_AGE_S, is_known_device, is_known_network, remember_login
from app.core.login_store import LoginStore, get_store
from app.core.models import Attempt, User
from app.engine.selection import candidates, select_fixed
from app.factors.base import FACTOR_NAMES, FactorResult, LoginContext, get_factor, registered_factors

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

USERNAME_PATTERN = re.compile(r"^[a-z0-9_.-]{3,32}$")
SELECTOR = "fixed"  # until the adaptive engine (week 6)
RISK_LEVEL = "low"  # until risk score v1 (week 5)
DECOY_USER = "unknown"  # user_id passed to start() for unknown usernames
# The device cookie is only sent over HTTPS when this is on (set COOKIE_SECURE=true behind HTTPS/ngrok).
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"


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


class EnrollStartRequest(BaseModel):
    client: ClientInfo = ClientInfo()


class EnrollFinishRequest(BaseModel):
    payload: dict = Field(default_factory=dict)


# --- sessions ----------------------------------------------------------------------------


def current_user_id(authorization: str = Header(default=""), store: LoginStore = Depends(get_store)) -> str:
    """Dependency: the logged-in user's id from "Authorization: Bearer <session>", else 401."""
    token = authorization.removeprefix("Bearer ").strip()
    user_id = store.session_user(token) if token else None
    if user_id is None:
        raise HTTPException(status_code=401, detail="not logged in")
    return user_id


# --- registration and enrollment ---------------------------------------------------------


@router.post("/register", status_code=201)
def register_user(body: RegisterRequest, db: Session = Depends(get_db),
                  store: LoginStore = Depends(get_store)) -> dict:
    """Create the account and log the user in, so they can enroll their first factors."""
    if db.scalar(select(User).where(User.username == body.username)) is not None:
        raise HTTPException(status_code=409, detail="username already taken")
    user = User(username=body.username)
    db.add(user)
    db.commit()
    return {"user_id": user.id, "session": store.create_session(user.id)}


def _enroll_context(request: Request, client: ClientInfo) -> LoginContext:
    ip = request.client.host if request.client else "0.0.0.0"
    return build_login_context(f"enroll-{uuid.uuid4()}", request.headers.get("user-agent", ""), ip, client)


def _factor_or_404(name: str):
    if name not in FACTOR_NAMES or name not in registered_factors():
        raise HTTPException(status_code=404, detail=f"factor {name!r} is not available")
    return get_factor(name)


@router.post("/enroll/{factor_name}/start")
async def enroll_start(factor_name: str, body: EnrollStartRequest, request: Request,
                       user_id: str = Depends(current_user_id)) -> dict:
    factor = _factor_or_404(factor_name)
    return await factor.enroll_start(user_id, _enroll_context(request, body.client))


@router.post("/enroll/{factor_name}/finish")
async def enroll_finish(factor_name: str, body: EnrollFinishRequest, request: Request,
                        user_id: str = Depends(current_user_id)) -> dict:
    factor = _factor_or_404(factor_name)
    result = await factor.enroll_finish(user_id, body.payload, _enroll_context(request, ClientInfo()))
    return result.model_dump()


# --- login -------------------------------------------------------------------------------


@router.post("/login/start")
async def login_start(body: LoginStartRequest, request: Request, db: Session = Depends(get_db),
                      store: LoginStore = Depends(get_store),
                      device_cookie: str | None = Cookie(default=None, alias=DEVICE_COOKIE)) -> dict:
    user = db.scalar(select(User).where(User.username == body.username.strip().lower()))
    login_id = str(uuid.uuid4())
    ip = request.client.host if request.client else "0.0.0.0"
    history = {}
    if user is not None:
        history = {
            "known_network": is_known_network(db, user.id, ip),
            "known_device": is_known_device(db, user.id, device_cookie),
            "recent_failures": store.recent_failures(user.id),
        }
    ctx = build_login_context(login_id, request.headers.get("user-agent", ""), ip, body.client, **history)

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
        "challenge_sent_at": time.time(),
    })
    return {"login_id": login_id, "factors": plan, "next": {"factor": plan[0], "challenge": challenge}}


@router.post("/login/{login_id}/verify")
async def login_verify(login_id: str, body: VerifyRequest, response: Response, db: Session = Depends(get_db),
                       store: LoginStore = Depends(get_store),
                       device_cookie: str | None = Cookie(default=None, alias=DEVICE_COOKIE)) -> dict:
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
        if result.duration_ms == 0:
            # Real factors cannot see how long the user took; the core measured challenge -> answer.
            measured = int((time.time() - state.get("challenge_sent_at", time.time())) * 1000)
            result = result.model_copy(update={"duration_ms": max(measured, 0)})
        light = result.context.get("light")
        if light in ("normal", "dim"):
            ctx.light = light  # face measured the light: the condition is now known exactly
        if result.factor == "password" and not result.accepted and result.error is None:
            ctx.recent_failures = store.add_password_failure(user_id)
        _log_attempt(db, store, login_id, user_id, result, ctx, state["selected_factors"])

    decision = decide(progress, result)
    if decision.status in ("authenticated", "denied"):
        store.delete_login(login_id)
    else:
        state["progress"] = progress.to_dict()
        state["context"] = ctx.model_dump()
        state["challenge_sent_at"] = time.time()
        store.save_login(login_id, state)

    if decision.status == "authenticated":
        store.clear_failures(user_id)
        token = remember_login(db, user_id, ctx.ip, device_cookie)
        response.set_cookie(DEVICE_COOKIE, token, max_age=DEVICE_COOKIE_MAX_AGE_S, httponly=True,
                            samesite="lax", secure=COOKIE_SECURE)
    return await _response(decision, user_id, ctx, store)


@router.get("/me")
def me(user_id: str = Depends(current_user_id), db: Session = Depends(get_db)) -> dict:
    user = db.get(User, user_id)
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


def _log_attempt(db: Session, store: LoginStore, login_id: str, user_id: str, result: FactorResult,
                 ctx: LoginContext, selected: list[str]) -> None:
    """Write one row of the attempt log (interface §9), with the current study label if one is set."""
    label = store.study_label() or {}
    db.add(Attempt(
        login_id=login_id, user_id=user_id, factor=result.factor, accepted=result.accepted,
        score=result.score, duration_ms=result.duration_ms, error=result.error,
        is_genuine=label.get("is_genuine"), attack_type=label.get("attack_type"),
        study_session_id=label.get("study_session_id"),
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
