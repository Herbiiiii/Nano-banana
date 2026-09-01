"""
Админ-роутер: управление пользователями, обзор генераций и метрики.
"""

from datetime import datetime, timedelta
from typing import Annotated, Optional
import threading
import time

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, func

from app.models.base import Generation, User, AdminAuditLog
from app.models.token import TokenPayload
from app.services.AuthService import auth_service
from app.services.DBService import db_service
from app.config import settings

router = APIRouter(prefix="/admin", tags=["admin"])
_admin_read_attempts = {}
_admin_read_lock = threading.Lock()


def _require_admin(user: TokenPayload):
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Доступ только для админов")


def _rate_limit_admin_read(user_id: int, scope: str):
    now = time.time()
    window = settings.SECURITY_ADMIN_READ_WINDOW_SECONDS
    max_requests = settings.SECURITY_ADMIN_READ_MAX_REQUESTS
    key = f"{user_id}:{scope}"
    with _admin_read_lock:
        attempts = _admin_read_attempts.get(key, [])
        attempts = [ts for ts in attempts if now - ts <= window]
        if len(attempts) >= max_requests:
            raise HTTPException(
                status_code=429,
                detail="Слишком много админ-запросов. Повторите позже.",
            )
        attempts.append(now)
        _admin_read_attempts[key] = attempts


def _audit_admin_action(session, actor_admin_id: int, action: str, target_user_id: Optional[int], details: Optional[dict] = None):
    log_row = AdminAuditLog(
        actor_admin_id=actor_admin_id,
        target_user_id=target_user_id,
        action=action,
        details=details or {},
    )
    session.add(log_row)


def _infer_provider(gen: Generation) -> str:
    metadata = gen.generation_metadata or {}
    provider = (metadata.get("provider") or "").strip().lower()
    if provider in ("replicate", "bananalab", "openrouter"):
        return provider
    model_name = (gen.model_name or "").lower()
    if model_name.startswith("gpt-"):
        return "openrouter"
    if model_name.startswith("imagen") or "gemini" in model_name:
        return "replicate"
    if "nano-banana" in model_name:
        return "hybrid"
    return "unknown"


def _generation_full_payload(gen: Generation, username: Optional[str] = None) -> dict:
    metadata = gen.generation_metadata or {}
    model_name = gen.model_name or metadata.get("model_name") or "nano-banana-pro"
    return {
        "id": gen.id,
        "user_id": gen.user_id,
        "username": username,
        "prompt": gen.prompt,
        "negative_prompt": gen.negative_prompt,
        "generation_mode": gen.generation_mode,
        "resolution": gen.resolution,
        "aspect_ratio": gen.aspect_ratio,
        "guidance_scale": gen.guidance_scale,
        "num_inference_steps": gen.num_inference_steps,
        "seed": gen.seed,
        "model_name": model_name,
        "reference_images": metadata.get("reference_image_urls") or [],
        "result_url": gen.result_url,
        "status": gen.status,
        "error_message": metadata.get("error"),
        "provider": _infer_provider(gen),
        "created_at": gen.created_at.isoformat() if gen.created_at else None,
    }


def _estimate_cost_usd(gen: Generation) -> float:
    model = (gen.model_name or "nano-banana-pro").lower()
    resolution = (gen.resolution or "1K").upper()
    metadata = gen.generation_metadata or {}

    model_price = {
        "nano-banana": 0.015,
        "nano-banana-2": 0.02,
        "nano-banana-pro": 0.03,
        "gemini-2.5-flash-image": 0.02,
        "imagen-4": 0.04,
        "imagen-4-fast": 0.02,
        "imagen-4-ultra": 0.06,
        "gpt-5-image": 0.05,
        "gpt-5-image-mini": 0.02,
    }.get(model, 0.02)
    resolution_multiplier = {"1K": 1.0, "2K": 1.6, "4K": 2.5}.get(resolution, 1.0)
    refs_count = int(metadata.get("reference_images_count") or 0)
    refs_fee = min(refs_count, 14) * 0.002
    return round(model_price * resolution_multiplier + refs_fee, 6)


@router.get("/users")
async def admin_list_users(
    user: Annotated[TokenPayload, Depends(auth_service.get_current_user)],
    search: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    _require_admin(user)
    _rate_limit_admin_read(user.user_id, "users")
    with db_service.get_session() as session:
        query = session.query(User)
        if search:
            needle = f"%{search.strip()}%"
            query = query.filter(or_(User.username.ilike(needle), User.email.ilike(needle)))
        total = query.count()
        rows = query.order_by(User.created_at.desc()).offset(offset).limit(limit).all()

        return {
            "users": [
                {
                    "id": u.id,
                    "username": u.username,
                    "email": u.email,
                    "is_admin": bool(u.is_admin),
                    "is_active": bool(u.is_active),
                    "created_at": u.created_at.isoformat() if u.created_at else None,
                    "last_login": u.last_login.isoformat() if u.last_login else None,
                }
                for u in rows
            ],
            "meta": {"total": total, "limit": limit, "offset": offset},
        }


@router.get("/filters")
async def admin_filters(
    user: Annotated[TokenPayload, Depends(auth_service.get_current_user)],
):
    _require_admin(user)
    _rate_limit_admin_read(user.user_id, "filters")
    with db_service.get_session() as session:
        users = session.query(User).order_by(User.username.asc()).all()
        models = (
            session.query(func.distinct(Generation.model_name))
            .filter(Generation.model_name.isnot(None))
            .all()
        )
        provider_rows = session.query(Generation).order_by(Generation.created_at.desc()).limit(3000).all()
        providers = sorted({p for p in (_infer_provider(g) for g in provider_rows) if p and p != "unknown"})
        return {
            "users": [{"id": u.id, "username": u.username} for u in users],
            "models": sorted([m[0] for m in models if m and m[0]]),
            "providers": providers,
            "statuses": ["pending", "running", "paused", "completed", "failed"],
        }


@router.post("/users/{target_user_id}/grant-admin")
async def admin_grant_role(
    target_user_id: int,
    user: Annotated[TokenPayload, Depends(auth_service.get_current_user)],
):
    _require_admin(user)
    with db_service.get_session() as session:
        target = session.query(User).filter(User.id == target_user_id).first()
        if not target:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        target.is_admin = True
        _audit_admin_action(
            session=session,
            actor_admin_id=user.user_id,
            action="grant_admin",
            target_user_id=target.id,
            details={"target_username": target.username},
        )
        session.commit()
        return {"message": f"Пользователь {target.username} назначен админом"}


@router.post("/users/{target_user_id}/revoke-admin")
async def admin_revoke_role(
    target_user_id: int,
    user: Annotated[TokenPayload, Depends(auth_service.get_current_user)],
):
    _require_admin(user)
    with db_service.get_session() as session:
        target = session.query(User).filter(User.id == target_user_id).first()
        if not target:
            raise HTTPException(status_code=404, detail="Пользователь не найден")

        if target.id == user.user_id:
            raise HTTPException(status_code=400, detail="Нельзя снять права у самого себя")

        admins_count = session.query(User).filter(User.is_admin.is_(True)).count()
        if admins_count <= 1 and target.is_admin:
            raise HTTPException(status_code=400, detail="Нельзя снять права у последнего админа")

        target.is_admin = False
        _audit_admin_action(
            session=session,
            actor_admin_id=user.user_id,
            action="revoke_admin",
            target_user_id=target.id,
            details={"target_username": target.username},
        )
        session.commit()
        return {"message": f"Права админа сняты у пользователя {target.username}"}


@router.get("/generations")
async def admin_list_generations(
    user: Annotated[TokenPayload, Depends(auth_service.get_current_user)],
    user_id: Optional[int] = None,
    status: Optional[str] = None,
    model: Optional[str] = None,
    provider: Optional[str] = None,
    search: Optional[str] = None,
    error_only: bool = False,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = Query(60, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    _require_admin(user)
    _rate_limit_admin_read(user.user_id, "generations")
    with db_service.get_session() as session:
        query = session.query(Generation)
        if user_id is not None:
            query = query.filter(Generation.user_id == user_id)
        if status:
            query = query.filter(Generation.status == status)
        if model:
            query = query.filter(Generation.model_name == model)
        if search:
            needle = f"%{search.strip()}%"
            query = query.filter(Generation.prompt.ilike(needle))
        if error_only:
            query = query.filter(Generation.status == "failed")
        if date_from:
            dt_from = datetime.fromisoformat(date_from)
            query = query.filter(Generation.created_at >= dt_from)
        if date_to:
            dt_to = datetime.fromisoformat(date_to)
            query = query.filter(Generation.created_at <= dt_to)

        rows = query.order_by(Generation.created_at.desc()).offset(offset).limit(limit).all()
        total = query.count()

        user_ids = {g.user_id for g in rows}
        users_map = {}
        if user_ids:
            for u in session.query(User).filter(User.id.in_(user_ids)).all():
                users_map[u.id] = u.username

        payload = []
        for gen in rows:
            inferred_provider = _infer_provider(gen)
            if provider and inferred_provider != provider:
                continue
            metadata = gen.generation_metadata or {}
            payload.append(
                {
                    "id": gen.id,
                    "user_id": gen.user_id,
                    "username": users_map.get(gen.user_id),
                    "prompt": gen.prompt,
                    "status": gen.status,
                    "model_name": gen.model_name,
                    "resolution": gen.resolution,
                    "aspect_ratio": gen.aspect_ratio,
                    "result_url": gen.result_url,
                    "error": metadata.get("error"),
                    "error_message": metadata.get("error"),
                    "created_at": gen.created_at.isoformat() if gen.created_at else None,
                    "provider": inferred_provider,
                }
            )

        return {"generations": payload, "meta": {"total": total, "limit": limit, "offset": offset}}


@router.get("/generations/{generation_id}")
async def admin_get_generation(
    generation_id: int,
    user: Annotated[TokenPayload, Depends(auth_service.get_current_user)],
):
    """Полные параметры генерации любого пользователя — для вставки в форму админом."""
    _require_admin(user)
    _rate_limit_admin_read(user.user_id, "generation_detail")
    with db_service.get_session() as session:
        gen = session.query(Generation).filter(Generation.id == generation_id).first()
        if not gen:
            raise HTTPException(status_code=404, detail="Генерация не найдена")
        owner = session.query(User).filter(User.id == gen.user_id).first()
        username = owner.username if owner else None
        return _generation_full_payload(gen, username=username)


@router.get("/overview")
async def admin_overview(
    user: Annotated[TokenPayload, Depends(auth_service.get_current_user)],
    period_days: int = Query(30, ge=1, le=365),
    user_id: Optional[int] = None,
):
    _require_admin(user)
    _rate_limit_admin_read(user.user_id, "overview")
    cutoff = datetime.utcnow() - timedelta(days=period_days)

    with db_service.get_session() as session:
        users_total = session.query(User).count()
        active_users = (
            session.query(User)
            .filter(User.last_login.isnot(None))
            .filter(User.last_login >= cutoff)
            .count()
        )

        gens_query = session.query(Generation).filter(Generation.created_at >= cutoff)
        if user_id is not None:
            gens_query = gens_query.filter(Generation.user_id == user_id)
        gens = gens_query.all()
        generations_total = len(gens)
        failed_total = sum(1 for g in gens if g.status == "failed")
        completed_total = sum(1 for g in gens if g.status == "completed")
        running_total = sum(1 for g in gens if g.status in ("pending", "running", "paused"))
        model_breakdown = {}

        spend_by_user = {}
        for g in gens:
            amount = 0.0
            source = "estimated"
            metadata = g.generation_metadata or {}
            if metadata.get("provider_cost_usd") is not None:
                amount = float(metadata.get("provider_cost_usd") or 0)
                source = "fact"
            elif g.status in ("completed", "failed"):
                amount = _estimate_cost_usd(g)
            if g.user_id not in spend_by_user:
                spend_by_user[g.user_id] = {"amount": 0.0, "fact": 0, "estimated": 0}
            spend_by_user[g.user_id]["amount"] += amount
            spend_by_user[g.user_id][source] += 1
            model_key = g.model_name or "unknown"
            if model_key not in model_breakdown:
                model_breakdown[model_key] = {"count": 0, "amount_usd": 0.0}
            model_breakdown[model_key]["count"] += 1
            model_breakdown[model_key]["amount_usd"] += amount

        top_users = []
        if spend_by_user:
            users = session.query(User).filter(User.id.in_(list(spend_by_user.keys()))).all()
            users_map = {u.id: u for u in users}
            for uid, spend in spend_by_user.items():
                u = users_map.get(uid)
                top_users.append(
                    {
                        "user_id": uid,
                        "username": u.username if u else f"user-{uid}",
                        "email": u.email if u else None,
                        "amount_usd": round(spend["amount"], 4),
                        "fact_points": spend["fact"],
                        "estimated_points": spend["estimated"],
                    }
                )
            top_users.sort(key=lambda x: x["amount_usd"], reverse=True)
            top_users = top_users[:20]

        total_spend = round(sum(v["amount"] for v in spend_by_user.values()), 4)

        return {
            "period_days": period_days,
            "user_id": user_id,
            "users_total": users_total,
            "active_users": active_users,
            "generations_total": generations_total,
            "completed_total": completed_total,
            "failed_total": failed_total,
            "running_total": running_total,
            "spend_total_usd": total_spend,
            "spend_source": "hybrid",
            "top_users": top_users,
            "model_breakdown": [
                {
                    "model_name": k,
                    "count": v["count"],
                    "amount_usd": round(v["amount_usd"], 4),
                }
                for k, v in sorted(model_breakdown.items(), key=lambda item: item[1]["amount_usd"], reverse=True)
            ],
        }

