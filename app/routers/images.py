"""
Роутер для генерации изображений: Replicate, Banana Lab или OpenRouter (по ключу модели).
"""
from concurrent.futures import ThreadPoolExecutor
from collections import deque
import json
import threading
import time
from typing import Annotated, Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from starlette.requests import Request
from datetime import datetime, timedelta
import logging
import uuid
from app.services.CryptoService import CryptoService
from app.models.schemas import ImageGenerationRequest, ImageGenerationResponse, ImageResponse
from app.services.ReplicateService import ReplicateService
from app.services.BananalabService import BananalabService, SUPPORTED_BANANALAB_FRONTEND_MODELS
from app.services.OpenRouterService import OpenRouterService
from app.services.image_api_provider import infer_image_api_provider
from app.services.image_models import (
    DEFAULT_MODEL_ID,
    MODEL_REGISTRY,
    get_provider_for_model,
    provider_label,
    select_api_key_for_model,
)
from app.services.MinioService import MinioService
from app.services.DBService import db_service
from app.services.AuthService import auth_service
from app.models.base import Generation, User
from app.config import settings
from app.models.token import TokenPayload
from app.security_helpers import generate_storage_object_name, is_allowed_reference_url
from app.services.result_storage import persist_generation_result
from app.services.bananalab_response import (
    BANANALAB_UPSTREAM_NO_IMAGE_EXHAUSTED_MESSAGE,
    BANANALAB_UPSTREAM_NO_IMAGE_RETRY_MESSAGE,
    humanize_api_error,
    is_bananalab_paused_message,
    is_bananalab_unavailable_message,
    is_bananalab_upstream_no_image_message,
    is_policy_block_error,
    upstream_no_image_retry_delay_seconds,
)

logger = logging.getLogger(__name__)

# Глобальный пул воркеров для обработки генераций
executor = ThreadPoolExecutor(max_workers=settings.MAX_WORKERS)

# Максимальное количество повторных попыток генерации при временных ошибках (E003 / 429)
MAX_GENERATION_RETRIES = 5
PAUSED_RETRY_DELAY_SECONDS = 30

router = APIRouter(prefix="/images", tags=["images"])
minio = MinioService()

FALLBACK_MODEL_BY_MODEL = {}
paused_queue = deque()
paused_queue_ids = set()
paused_queue_lock = threading.Lock()
paused_worker_started = False
bananalab_runtime_state = {
    "last_paused_at": None,
    "last_paused_error": None,
    "last_success_at": None,
    "project_paused_since": None,
    "last_unavailable_at": None,
    "last_unavailable_error": None,
    "provider_unavailable_since": None,
    "health_probe_at": None,
    "health_probe_ok": None,
    "health_probe_error": None,
}

BANANALAB_HEALTH_PROBE_TTL_SECONDS = 45


def get_fallback_model(model_name: Optional[str]) -> Optional[str]:
    """Возвращает fallback-модель для кнопки быстрого перезапуска."""
    if not model_name:
        return None
    return FALLBACK_MODEL_BY_MODEL.get(model_name)


def _rewrite_metadata_fields(metadata: Optional[dict]) -> dict:
    meta = metadata or {}
    return {
        "provider": meta.get("provider"),
        "original_prompt": meta.get("original_prompt"),
        "sanitized_prompt": meta.get("sanitized_prompt"),
        "sanitize_replacements": meta.get("sanitize_replacements"),
        "rewritten_prompt": meta.get("rewritten_prompt"),
        "rewrite_model": meta.get("rewrite_model"),
        "rewrite_error": meta.get("rewrite_error"),
        "policy_gpt_attempts": meta.get("policy_gpt_attempts"),
    }


def _init_policy_rewrite_metadata(
    generation,
    session,
    prompt: str,
    rewrite_requested: bool,
) -> None:
    if not rewrite_requested:
        return
    if not generation.generation_metadata:
        generation.generation_metadata = {}
    from sqlalchemy.orm.attributes import flag_modified

    generation.generation_metadata["rewrite_requested"] = True
    generation.generation_metadata.setdefault("original_prompt", prompt)
    generation.generation_metadata.setdefault("policy_gpt_attempts", [])
    flag_modified(generation, "generation_metadata")
    session.commit()


def _record_policy_gpt_rewrite(
    generation,
    session,
    generation_id: int,
    attempt_num: int,
    block_reason: str,
    rewrite_result: dict,
) -> None:
    from sqlalchemy.orm.attributes import flag_modified

    if not generation.generation_metadata:
        generation.generation_metadata = {}

    attempts = list(generation.generation_metadata.get("policy_gpt_attempts") or [])
    attempts.append(
        {
            "attempt": attempt_num,
            "block_reason": (block_reason or "")[:500],
            "rewritten_prompt": rewrite_result.get("prompt"),
            "model": rewrite_result.get("model"),
        }
    )
    generation.generation_metadata["policy_gpt_attempts"] = attempts
    generation.generation_metadata["rewritten_prompt"] = rewrite_result.get("prompt")
    generation.generation_metadata["rewrite_model"] = rewrite_result.get("model")
    generation.generation_metadata.pop("rewrite_error", None)
    flag_modified(generation, "generation_metadata")
    session.commit()
    logger.info(
        "[GENERATION] policy GPT rewrite gen=%s attempt=%s model=%s | block: %s | new: %s",
        generation_id,
        attempt_num,
        rewrite_result.get("model"),
        (block_reason or "")[:160],
        str(rewrite_result.get("prompt") or "")[:160],
    )


def _try_policy_gpt_rewrite(
    generation,
    session,
    generation_id: int,
    prompt: str,
    block_reason: str,
    keys: dict,
) -> Optional[str]:
    openrouter_key = keys.get("openrouter")
    if not openrouter_key:
        return None

    rewrite_result = OpenRouterService(api_key=openrouter_key).rewrite_prompt_after_block(
        prompt,
        block_reason,
    )
    if rewrite_result.get("success") and rewrite_result.get("prompt"):
        attempt_num = len(generation.generation_metadata.get("policy_gpt_attempts") or []) + 1
        _record_policy_gpt_rewrite(
            generation,
            session,
            generation_id,
            attempt_num,
            block_reason,
            rewrite_result,
        )
        return rewrite_result["prompt"]

    err = humanize_api_error(rewrite_result.get("error") or "GPT не смог переписать промпт", provider="openrouter")
    if not generation.generation_metadata:
        generation.generation_metadata = {}
    generation.generation_metadata["rewrite_error"] = err
    from sqlalchemy.orm.attributes import flag_modified

    flag_modified(generation, "generation_metadata")
    session.commit()
    logger.warning("[GENERATION] policy GPT rewrite FAIL gen=%s: %s", generation_id, err)
    return None


def _is_paused_error(error_message: str) -> bool:
    if not error_message:
        return False
    return is_bananalab_paused_message(error_message)


def _is_unavailable_error(error_message: str) -> bool:
    if not error_message:
        return False
    return is_bananalab_unavailable_message(error_message)


def _mark_bananalab_paused(error_message: str) -> None:
    now = datetime.utcnow().isoformat()
    bananalab_runtime_state["last_paused_at"] = now
    bananalab_runtime_state["last_paused_error"] = error_message
    if not bananalab_runtime_state.get("project_paused_since"):
        bananalab_runtime_state["project_paused_since"] = now


def _clear_bananalab_paused() -> None:
    bananalab_runtime_state["project_paused_since"] = None
    bananalab_runtime_state["last_paused_error"] = None


def _mark_bananalab_unavailable(error_message: str) -> None:
    now = datetime.utcnow().isoformat()
    bananalab_runtime_state["last_unavailable_at"] = now
    bananalab_runtime_state["last_unavailable_error"] = error_message
    if not bananalab_runtime_state.get("provider_unavailable_since"):
        bananalab_runtime_state["provider_unavailable_since"] = now


def _clear_bananalab_unavailable() -> None:
    bananalab_runtime_state["provider_unavailable_since"] = None
    bananalab_runtime_state["last_unavailable_error"] = None


def _bananalab_is_unavailable() -> bool:
    last_unavailable = bananalab_runtime_state.get("last_unavailable_at")
    last_success = bananalab_runtime_state.get("last_success_at")
    last_error = bananalab_runtime_state.get("last_unavailable_error") or ""
    if _is_unavailable_error(last_error):
        if last_unavailable and (not last_success or str(last_success) < str(last_unavailable)):
            return True
    return False


def _bananalab_health_status() -> tuple[bool, Optional[str]]:
    now_ts = time.time()
    probe_at = bananalab_runtime_state.get("health_probe_at")
    if probe_at is not None and (now_ts - float(probe_at)) < BANANALAB_HEALTH_PROBE_TTL_SECONDS:
        return bool(bananalab_runtime_state.get("health_probe_ok")), bananalab_runtime_state.get("health_probe_error")

    reachable, probe_error = BananalabService.probe_reachable()
    bananalab_runtime_state["health_probe_at"] = now_ts
    bananalab_runtime_state["health_probe_ok"] = reachable
    bananalab_runtime_state["health_probe_error"] = probe_error
    if not reachable:
        _mark_bananalab_unavailable(probe_error or "BananaHub API недоступен.")
    return reachable, probe_error


def _unavailable_duration_seconds() -> Optional[int]:
    since = (
        bananalab_runtime_state.get("provider_unavailable_since")
        or bananalab_runtime_state.get("last_unavailable_at")
    )
    if not since:
        return None
    try:
        started = datetime.fromisoformat(str(since))
        return max(0, int((datetime.utcnow() - started).total_seconds()))
    except ValueError:
        return None


def _format_duration_hint(total_seconds: Optional[int], prefix: str) -> str:
    if total_seconds is None:
        return ""
    hours, rem = divmod(total_seconds, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours:
        return f" {prefix} {hours} ч {minutes} мин."
    if minutes:
        return f" {prefix} {minutes} мин {seconds} сек."
    return f" {prefix} {seconds} сек."


def _bananalab_is_paused() -> bool:
    last_paused = bananalab_runtime_state.get("last_paused_at")
    last_success = bananalab_runtime_state.get("last_success_at")
    last_error = bananalab_runtime_state.get("last_paused_error") or ""
    if _is_paused_error(last_error):
        if last_paused and (not last_success or str(last_success) < str(last_paused)):
            return True
    queue_size = _queue_size()
    if queue_size > 0 and last_paused:
        if not last_success or str(last_success) < str(last_paused):
            return True
    return False


def _paused_duration_seconds() -> Optional[int]:
    since = bananalab_runtime_state.get("project_paused_since") or bananalab_runtime_state.get("last_paused_at")
    if not since:
        return None
    try:
        started = datetime.fromisoformat(str(since))
        return max(0, int((datetime.utcnow() - started).total_seconds()))
    except ValueError:
        return None


def _queue_size() -> int:
    with paused_queue_lock:
        return len(paused_queue)


def _encrypt_api_key_for_resume(api_key: str) -> str:
    if not api_key:
        return ""
    return CryptoService.encrypt(api_key)


def _decrypt_api_key_for_resume(token: str) -> Optional[str]:
    if not token:
        return None
    return CryptoService.decrypt(token)


def enqueue_paused_generation(generation_id: int, user_id: int, request_data: dict, prioritize: bool = False):
    with paused_queue_lock:
        if generation_id in paused_queue_ids:
            return
        item = {
            "generation_id": generation_id,
            "user_id": user_id,
            "request_data": request_data,
            "retry_after": time.time() + PAUSED_RETRY_DELAY_SECONDS,
        }
        if prioritize:
            paused_queue.appendleft(item)
        else:
            paused_queue.append(item)
        paused_queue_ids.add(generation_id)


def _build_resume_payload(generation: Generation, request_data: dict) -> Dict[str, Any]:
    metadata = generation.generation_metadata or {}
    plain_api_key = request_data.get("api_key")
    return {
        # В БД храним только шифрованную форму ключа для автовозобновления.
        "api_key_encrypted": _encrypt_api_key_for_resume(plain_api_key) if plain_api_key else "",
        "prompt": request_data.get("prompt") or generation.prompt,
        "negative_prompt": request_data.get("negative_prompt") or generation.negative_prompt,
        "resolution": request_data.get("resolution") or generation.resolution,
        "aspect_ratio": request_data.get("aspect_ratio") or generation.aspect_ratio,
        "guidance_scale": request_data.get("guidance_scale") or generation.guidance_scale,
        "num_inference_steps": request_data.get("num_inference_steps") or generation.num_inference_steps,
        "seed": request_data.get("seed") if request_data.get("seed") is not None else generation.seed,
        "model_name": request_data.get("model_name") or generation.model_name or metadata.get("model_name"),
        "reference_images": request_data.get("reference_images") or metadata.get("reference_image_urls") or [],
    }


def restore_paused_queue_from_db():
    with db_service.get_session() as session:
        paused_generations = (
            session.query(Generation)
            .filter(Generation.status == "paused")
            .order_by(Generation.created_at.asc())
            .all()
        )
        for generation in paused_generations:
            metadata = generation.generation_metadata or {}
            request_data = metadata.get("paused_request_data")
            if request_data and (request_data.get("api_key_encrypted") or request_data.get("api_key")):
                enqueue_paused_generation(generation.id, generation.user_id, request_data, prioritize=False)


def _paused_queue_worker_loop():
    while True:
        item = None
        now_ts = time.time()
        with paused_queue_lock:
            if paused_queue:
                candidate = paused_queue[0]
                if candidate["retry_after"] <= now_ts:
                    item = paused_queue.popleft()
                    paused_queue_ids.discard(item["generation_id"])
        if not item:
            time.sleep(2)
            continue
        executor.submit(
            process_generation_async,
            item["generation_id"],
            item["user_id"],
            item["request_data"],
        )
        time.sleep(1)


def start_paused_queue_worker():
    global paused_worker_started
    if paused_worker_started:
        return
    with paused_queue_lock:
        if paused_worker_started:
            return
        thread = threading.Thread(target=_paused_queue_worker_loop, daemon=True)
        thread.start()
        paused_worker_started = True


def _extract_minio_path_from_url(url: str, bucket: str) -> Optional[str]:
    """
    Вспомогательная функция: из публичного URL MinIO достает путь объекта внутри бакета.
    Ожидаемый формат:
      {PUBLIC_URL}/{bucket}/{object_path}
    Возвращает object_path или None, если разобрать не удалось.
    """
    try:
        if not url:
            return None

        # Ищем подстроку "/{bucket}/"
        marker = f"/{bucket}/"
        idx = url.find(marker)
        if idx == -1:
            return None
        return url[idx + len(marker) :]
    except Exception:
        return None

def get_user_generation_api_key(user_id: int, api_key_from_request: Optional[str] = None) -> str:
    """
    API ключ из запроса (Replicate r8_… или Banana Lab nb_…).
    Ключи не сохраняются в БД.
    """
    if api_key_from_request and api_key_from_request.strip():
        return api_key_from_request.strip()

    # Fallback: безопасно достаем ключ пользователя из БД (зашифрованный)
    with db_service.get_session() as session:
        db_user = session.query(User).filter(User.id == user_id).first()
        encrypted_key = db_user.replicate_api_key if db_user else None
    decrypted_key = CryptoService.decrypt(encrypted_key) if encrypted_key else None
    if decrypted_key:
        return decrypted_key

    raise ValueError(
        "API ключ не указан. Введите ключ Replicate (r8_…), Banana Lab (nb_…) "
        "или OpenRouter (sk-or_…) в настройках."
    )


def _load_user_api_keys(user_id: int) -> Dict[str, str]:
    with db_service.get_session() as session:
        db_user = session.query(User).filter(User.id == user_id).first()
        encrypted_key = db_user.replicate_api_key if db_user else None
    decrypted = CryptoService.decrypt(encrypted_key) if encrypted_key else None
    if not decrypted:
        return {"replicate": "", "bananalab": "", "openrouter": ""}
    try:
        parsed = json.loads(decrypted)
        if isinstance(parsed, dict):
            return {
                "replicate": str(parsed.get("replicate") or "").strip(),
                "bananalab": str(parsed.get("bananalab") or "").strip(),
                "openrouter": str(parsed.get("openrouter") or "").strip(),
            }
    except Exception:
        pass
    key = str(decrypted).strip()
    if not key:
        return {"replicate": "", "bananalab": "", "openrouter": ""}
    provider = infer_image_api_provider(key)
    keys = {"replicate": "", "bananalab": "", "openrouter": ""}
    keys[provider] = key
    return keys


def _select_api_key_for_model(user_id: int, model_name: Optional[str], api_key_from_request: Optional[str] = None) -> str:
    keys = _load_user_api_keys(user_id)
    return select_api_key_for_model(model_name, keys, api_key_from_request)

def process_generation_async(generation_id: int, user_id: int, request_data: dict):
    """Асинхронная обработка генерации"""
    started_at = datetime.utcnow()
    try:
        with db_service.get_session() as session:
            generation = session.query(Generation).filter(Generation.id == generation_id).first()
            if not generation:
                logger.error(f"[GENERATION] Генерация {generation_id} не найдена")
                return
            
            # Обновляем статус на running
            generation.status = "running"
            session.commit()
            
            # Получаем API ключ из request_data (если передан вручную)
            api_key_from_request = request_data.get('api_key')
            if (not api_key_from_request or not str(api_key_from_request).strip()) and request_data.get("api_key_encrypted"):
                api_key_from_request = _decrypt_api_key_for_resume(request_data.get("api_key_encrypted"))
            logger.info(f"[GENERATION] В process_generation_async: ключ из запроса: {'передан' if api_key_from_request else 'не передан'}")
            api_key = _select_api_key_for_model(user_id, request_data.get("model_name"), api_key_from_request)
            keys = _load_user_api_keys(user_id)
            provider = get_provider_for_model(request_data.get("model_name"), keys) or infer_image_api_provider(api_key)
            provider_label_text = provider_label(provider)

            # Обрабатываем ошибки инициализации клиента
            try:
                if provider == "bananalab":
                    generation_service = BananalabService(api_key=api_key)
                elif provider == "openrouter":
                    generation_service = OpenRouterService(api_key=api_key)
                else:
                    generation_service = ReplicateService(api_token=api_key)
            except Exception as init_error:
                error_msg = f"Ошибка инициализации клиента ({provider_label_text}): {str(init_error)}"
                logger.error(f"[GENERATION] {error_msg}")
                generation.status = "failed"
                generation.completed_at = datetime.utcnow()
                if not generation.generation_metadata:
                    generation.generation_metadata = {}
                generation.generation_metadata['error'] = error_msg
                # ВАЖНО: Уведомляем SQLAlchemy об изменении JSON поля
                from sqlalchemy.orm.attributes import flag_modified
                flag_modified(generation, "generation_metadata")
                session.commit()
                logger.error(f"[GENERATION] Генерация {generation_id} завершена с ошибкой инициализации: {error_msg}")
                return
            
            try:
                # Получаем модель из запроса или из БД (для старых записей)
                model_name = request_data.get('model_name')
                if not model_name:
                    # Если модель не указана в запросе, берем из БД
                    with db_service.get_session() as session:
                        gen = session.query(Generation).filter(Generation.id == generation_id).first()
                        if gen and gen.model_name:
                            model_name = gen.model_name
                        else:
                            # Если в БД тоже нет, используем по умолчанию
                            model_name = "nano-banana-pro"
                
                if provider == "bananalab" and model_name not in SUPPORTED_BANANALAB_FRONTEND_MODELS:
                    logger.warning(
                        "[GENERATION] Для Banana Lab передана неподдерживаемая модель '%s'. "
                        "Banana Lab endpoint не принимает model в body, значение будет проигнорировано.",
                        model_name,
                    )

                logger.info(
                    f"[GENERATION] Провайдер {provider_label_text}, модель {model_name}, генерация {generation_id}"
                )

                prompt_for_generation = request_data.get("prompt") or ""
                rewrite_requested = bool(request_data.get("rewrite_prompt"))
                _init_policy_rewrite_metadata(
                    generation,
                    session,
                    prompt_for_generation,
                    rewrite_requested,
                )
                max_policy_gpt = settings.MAX_POLICY_GPT_RETRIES if rewrite_requested else 0
                policy_gpt_used = 0
                result = None
                last_raw_error = ""

                while True:
                    try:
                        result = generation_service.generate_image(
                            prompt=prompt_for_generation,
                            negative_prompt=request_data.get('negative_prompt'),
                            resolution=request_data.get('resolution', '1K'),
                            aspect_ratio=request_data.get('aspect_ratio', '1:1'),
                            guidance_scale=request_data.get('guidance_scale', 7.5),
                            num_inference_steps=request_data.get('num_inference_steps', 50),
                            seed=request_data.get('seed'),
                            reference_images=request_data.get('reference_images'),
                            model_name=model_name
                        )
                    except Exception as gen_error:
                        error_msg = str(gen_error)
                        if hasattr(gen_error, 'message'):
                            error_msg = str(gen_error.message)
                        elif hasattr(gen_error, 'args') and len(gen_error.args) > 0:
                            error_msg = str(gen_error.args[0])

                        full_error_msg = humanize_api_error(error_msg, provider=provider)
                        if not full_error_msg.startswith(
                            ("Banana Lab", "BananaHub", "OpenRouter", "Google", "Replicate", "Ошибка провайдера", "Сервис Banana", "Запрос не прошёл")
                        ):
                            full_error_msg = f"Ошибка генерации ({provider_label_text}): {full_error_msg}"

                        logger.error(f"[GENERATION] {full_error_msg}", exc_info=True)
                        generation.status = "failed"
                        generation.completed_at = datetime.utcnow()
                        if not generation.generation_metadata:
                            generation.generation_metadata = {}
                        generation.generation_metadata['error'] = full_error_msg
                        from sqlalchemy.orm.attributes import flag_modified
                        flag_modified(generation, "generation_metadata")
                        session.commit()
                        logger.error(f"[GENERATION] Генерация {generation_id} завершена с ошибкой генерации: {full_error_msg}")
                        return

                    if result.get('success'):
                        break

                    error_message = result.get('error')
                    if not error_message or (isinstance(error_message, str) and error_message.strip() == ''):
                        error_message = result.get('message') or result.get('detail') or result.get('error_message')
                    if not error_message or (isinstance(error_message, str) and error_message.strip() == ''):
                        error_message = 'Неизвестная ошибка генерации'
                    if not isinstance(error_message, str):
                        error_message = str(error_message)
                    raw_error_message = error_message
                    last_raw_error = raw_error_message
                    error_message = humanize_api_error(raw_error_message, provider=provider)

                    if result.get("unavailable") or _is_unavailable_error(error_message):
                        break
                    if result.get("paused") or _is_paused_error(error_message):
                        break

                    if (
                        rewrite_requested
                        and is_policy_block_error(raw_error_message)
                        and policy_gpt_used < max_policy_gpt
                    ):
                        if not keys.get("openrouter"):
                            if not generation.generation_metadata:
                                generation.generation_metadata = {}
                            generation.generation_metadata["rewrite_error"] = (
                                "GPT авто-переписывание недоступно — добавьте ключ sk-or_ в настройках."
                            )
                            from sqlalchemy.orm.attributes import flag_modified
                            flag_modified(generation, "generation_metadata")
                            session.commit()
                            break

                        new_prompt = _try_policy_gpt_rewrite(
                            generation,
                            session,
                            generation_id,
                            prompt_for_generation,
                            error_message,
                            keys,
                        )
                        if new_prompt and new_prompt.strip() != prompt_for_generation.strip():
                            prompt_for_generation = new_prompt
                            policy_gpt_used += 1
                            logger.warning(
                                "[GENERATION] policy block gen=%s — GPT retry %s/%s",
                                generation_id,
                                policy_gpt_used,
                                max_policy_gpt,
                            )
                            continue
                        break

                    break
            except Exception as gen_error:
                # Ошибка при генерации (например, неправильный API ключ, таймаут и т.д.)
                # Улучшенное извлечение деталей ошибки
                error_msg = str(gen_error)
                
                if hasattr(gen_error, 'message'):
                    error_msg = str(gen_error.message)
                elif hasattr(gen_error, 'args') and len(gen_error.args) > 0:
                    error_msg = str(gen_error.args[0])
                
                full_error_msg = humanize_api_error(error_msg, provider=provider)
                if not full_error_msg.startswith(
                    ("Banana Lab", "BananaHub", "OpenRouter", "Google", "Replicate", "Ошибка провайдера", "Сервис Banana", "Запрос не прошёл")
                ):
                    full_error_msg = f"Ошибка генерации ({provider_label_text}): {full_error_msg}"
                
                logger.error(f"[GENERATION] {full_error_msg}", exc_info=True)
                generation.status = "failed"
                generation.completed_at = datetime.utcnow()
                if not generation.generation_metadata:
                    generation.generation_metadata = {}
                generation.generation_metadata['error'] = full_error_msg
                # ВАЖНО: Уведомляем SQLAlchemy об изменении JSON поля
                from sqlalchemy.orm.attributes import flag_modified
                flag_modified(generation, "generation_metadata")
                session.commit()
                logger.error(f"[GENERATION] Генерация {generation_id} завершена с ошибкой генерации: {full_error_msg}")
                return
            
            if result['success']:
                if provider == "bananalab":
                    bananalab_runtime_state["last_success_at"] = datetime.utcnow().isoformat()
                    _clear_bananalab_paused()
                    _clear_bananalab_unavailable()
                if generation.generation_metadata and generation.generation_metadata.get("paused_request_data"):
                    generation.generation_metadata.pop("paused_request_data", None)
                logger.info(
                    "[GENERATION] Результат провайдера: image_url=%s, image_data=%s",
                    "есть" if result.get("image_url") else "отсутствует",
                    "есть" if result.get("image_data") else "отсутствует",
                )
                upload_result = persist_generation_result(minio, result)
                if not upload_result:
                    error_msg = (
                        "Не удалось сохранить изображение в хранилище. "
                        "Сеть или сервис провайдера могли быть недоступны — повторите генерацию."
                    )
                    logger.error("[GENERATION] %s", error_msg)
                    generation.status = "failed"
                    generation.completed_at = datetime.utcnow()
                    if not generation.generation_metadata:
                        generation.generation_metadata = {}
                    generation.generation_metadata["error"] = error_msg
                    from sqlalchemy.orm.attributes import flag_modified
                    flag_modified(generation, "generation_metadata")
                    session.commit()
                    return

                generation.result_url = upload_result["url"]
                generation.result_path = upload_result["path"]
                logger.info(
                    "[GENERATION] Результат сохранён в MinIO: %s...",
                    generation.result_url[:100],
                )
                generation.status = "completed"
                generation.completed_at = datetime.utcnow()
                total_elapsed = (generation.completed_at - started_at).total_seconds()
                logger.info(f"[GENERATION] Генерация {generation_id} заняла {total_elapsed:.1f} сек")
            else:
                # Генерация не удалась - сохраняем ошибку
                # Сначала пытаемся понять, можно ли повторить генерацию (временная ошибка типа E003/429)
                if not generation.generation_metadata:
                    generation.generation_metadata = {}

                error_message = result.get('error')
                if not error_message or (isinstance(error_message, str) and error_message.strip() == ''):
                    error_message = result.get('message') or result.get('detail') or result.get('error_message')
                if not error_message or (isinstance(error_message, str) and error_message.strip() == ''):
                    error_message = 'Неизвестная ошибка генерации'

                if not isinstance(error_message, str):
                    error_message = str(error_message)

                error_message = humanize_api_error(error_message, provider=provider)
                if result.get("unavailable") or _is_unavailable_error(error_message):
                    generation.status = "failed"
                    generation.completed_at = datetime.utcnow()
                    generation.generation_metadata["error"] = error_message
                    generation.generation_metadata.pop("paused_request_data", None)
                    if provider == "bananalab":
                        _mark_bananalab_unavailable(error_message)
                    from sqlalchemy.orm.attributes import flag_modified
                    flag_modified(generation, "generation_metadata")
                    session.commit()
                    return

                if result.get("paused") or _is_paused_error(error_message):
                    generation.status = "paused"
                    generation.completed_at = None
                    paused_payload = _build_resume_payload(generation, request_data)
                    generation.generation_metadata["error"] = error_message
                    generation.generation_metadata["paused_at"] = datetime.utcnow().isoformat()
                    generation.generation_metadata["paused_request_data"] = paused_payload
                    if provider == "bananalab":
                        _mark_bananalab_paused(error_message)
                    from sqlalchemy.orm.attributes import flag_modified
                    flag_modified(generation, "generation_metadata")
                    session.commit()
                    enqueue_paused_generation(
                        generation_id=generation_id,
                        user_id=user_id,
                        request_data=paused_payload,
                        prioritize=False,
                    )
                    return

                # Проверяем, является ли ошибка временной (rate limit / high demand)
                # Приоритет у явного флага из ReplicateService, чтобы ретраи не зависели от текста user-friendly сообщения.
                lower_err = error_message.lower()
                service_retryable = bool(result.get("retryable"))
                policy_block = is_policy_block_error(last_raw_error) or is_policy_block_error(error_message)
                upstream_no_image = (
                    not policy_block
                    and is_bananalab_upstream_no_image_message(last_raw_error or error_message)
                )
                is_retryable = service_retryable or upstream_no_image or (
                    "e003" in lower_err
                    or "high demand" in lower_err
                    or "429" in lower_err
                    or "ratelimit" in lower_err
                    or "временно недоступен" in lower_err
                    or "521" in lower_err
                    or "522" in lower_err
                    or "524" in lower_err
                )

                current_retries = generation.generation_metadata.get("retry_count", 0)
                max_retries_for_error = (
                    settings.BANANALAB_UPSTREAM_NO_IMAGE_MAX_RETRIES
                    if upstream_no_image
                    else MAX_GENERATION_RETRIES
                )

                if is_retryable and current_retries < max_retries_for_error:
                    # Увеличиваем счетчик попыток и ставим задачу обратно в очередь
                    generation.generation_metadata["retry_count"] = current_retries + 1
                    generation.generation_metadata["max_retries"] = max_retries_for_error
                    generation.status = "pending"
                    generation.completed_at = None
                    if upstream_no_image:
                        generation.generation_metadata["last_upstream_no_image_at"] = (
                            datetime.utcnow().isoformat()
                        )
                        generation.generation_metadata["error"] = (
                            BANANALAB_UPSTREAM_NO_IMAGE_RETRY_MESSAGE
                        )

                    from sqlalchemy.orm.attributes import flag_modified
                    flag_modified(generation, "generation_metadata")

                    session.commit()

                    retry_delay = (
                        upstream_no_image_retry_delay_seconds(
                            current_retries,
                            settings.BANANALAB_UPSTREAM_NO_IMAGE_RETRY_BASE_DELAY_SECONDS,
                        )
                        if upstream_no_image
                        else 0
                    )
                    logger.warning(
                        f"[GENERATION] Генерация {generation_id} получила временную ошибку "
                        f"и будет автоматически повторена ({current_retries + 1}/{max_retries_for_error})"
                        f"{f', пауза {retry_delay:.0f}s' if retry_delay else ''}: "
                        f"{error_message[:200]}"
                    )

                    def _retry_generation():
                        if retry_delay > 0:
                            time.sleep(retry_delay)
                        process_generation_async(generation_id, user_id, request_data)

                    executor.submit(_retry_generation)
                    return

                # Если ошибка не временная или исчерпаны попытки — помечаем как failed
                generation.status = "failed"
                generation.completed_at = datetime.utcnow()
                total_elapsed = (generation.completed_at - started_at).total_seconds()
                generation.generation_metadata.pop("paused_request_data", None)

                if upstream_no_image:
                    error_message = BANANALAB_UPSTREAM_NO_IMAGE_EXHAUSTED_MESSAGE
                    generation.generation_metadata["error_code"] = "upstream_no_image"

                # Обрезаем слишком длинные сообщения об ошибках (максимум 2000 символов)
                if len(error_message) > 2000:
                    error_message = error_message[:2000] + "... (сообщение обрезано)"

                generation.generation_metadata['error'] = error_message

                # ВАЖНО: Уведомляем SQLAlchemy об изменении JSON поля
                from sqlalchemy.orm.attributes import flag_modified
                flag_modified(generation, "generation_metadata")

                logger.error(
                    f"[GENERATION] Генерация {generation_id} завершена с ошибкой "
                    f"после {current_retries} попыток за {total_elapsed:.1f} сек. "
                    f"error_message: {error_message[:200]}..."
                )
                logger.info(f"[GENERATION] generation_metadata перед commit: {generation.generation_metadata}")

                # Сохраняем ошибку в файл
                from app.services.ErrorLogger import save_error_to_file
                error_data = {
                    "type": "generation_error",
                    "generation_id": generation_id,
                    "user_id": user_id,
                    "prompt": request_data.get('prompt'),
                    "error": error_message,
                    "status": "failed"
                }
                save_error_to_file(error_data)
            
            session.commit()
            logger.info(f"[GENERATION] Генерация {generation_id} завершена со статусом {generation.status}")
            
            # Проверяем что error_message сохранился
            if generation.status == 'failed':
                session.refresh(generation)
                saved_error = generation.generation_metadata.get('error') if generation.generation_metadata else None
                logger.info(f"[GENERATION] Проверка сохранения error_message для генерации {generation_id}: {saved_error[:200] if saved_error else 'НЕ СОХРАНЕНО!'}...")
            
    except Exception as e:
        logger.error(f"[GENERATION] Ошибка обработки генерации {generation_id}: {e}", exc_info=True)
        
        # Сохраняем ошибку в файл
        from app.services.ErrorLogger import save_error_to_file
        error_data = {
            "type": "generation_exception",
            "generation_id": generation_id,
            "user_id": user_id,
            "error": str(e),
            "error_type": type(e).__name__,
        }
        save_error_to_file(error_data)
        
        with db_service.get_session() as session:
            generation = session.query(Generation).filter(Generation.id == generation_id).first()
            if generation:
                generation.status = "failed"
                generation.completed_at = datetime.utcnow()
                if not generation.generation_metadata:
                    generation.generation_metadata = {}
                generation.generation_metadata.pop("paused_request_data", None)
                meta = generation.generation_metadata or {}
                prov = meta.get("provider")
                generation.generation_metadata['error'] = humanize_api_error(str(e), provider=prov)
                # ВАЖНО: Уведомляем SQLAlchemy об изменении JSON поля
                from sqlalchemy.orm.attributes import flag_modified
                flag_modified(generation, "generation_metadata")
                session.commit()

@router.post("/generate", response_model=ImageGenerationResponse)
async def generate_image(
    request: ImageGenerationRequest,
    user: Annotated[TokenPayload, Depends(auth_service.get_current_user)]
):
    """
    Генерация изображения через Nano Banana Pro
    
    Требует API ключ: Replicate (r8_…), Banana Lab (nb_…) или OpenRouter (sk-or_…).
    """
    try:
        logger.info(f"[GENERATION] API ключ из запроса: {'передан' if request.api_key else 'не передан'}")
        selected_model = request.model_name if request.model_name else DEFAULT_MODEL_ID
        keys = _load_user_api_keys(user.user_id)
        model_provider = get_provider_for_model(selected_model, keys)
        if not model_provider:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Для модели «{selected_model}» нет подходящего API ключа. "
                    "Добавьте ключ в настройках."
                ),
            )
        api_key = _select_api_key_for_model(user.user_id, request.model_name, request.api_key)
        
        # Проверяем лимиты активных генераций по API ключу
        # Создаем хеш API ключа для группировки (первые 8 символов для идентификации)
        api_key_hash = api_key[:8] if len(api_key) >= 8 else api_key
        with db_service.get_session() as session:
            # Подсчитываем активные генерации для этого API ключа
            # Используем generation_metadata для хранения хеша ключа (безопасно, не храним сам ключ)
            active_generations = session.query(Generation).filter(
                Generation.user_id == user.user_id,
                Generation.status.in_(["pending", "running", "paused"])
            ).all()
            
            # Фильтруем по API ключу через metadata (если храним хеш)
            # Или просто считаем все активные генерации пользователя
            # Для простоты считаем все активные генерации пользователя
            active_count = len(active_generations)
            max_concurrent = settings.MAX_CONCURRENT_GENERATIONS
            
            if active_count >= max_concurrent:
                raise HTTPException(
                    status_code=429,
                    detail=f"Достигнут лимит одновременных генераций ({max_concurrent}). Дождитесь завершения текущих генераций."
                )
            
            logger.info(f"[GENERATION] Активных генераций для пользователя {user.user_id}: {active_count}/{max_concurrent}")
        
        reference_image_urls: List[str] = []
        # Создаем запись в БД
        with db_service.get_session() as session:
            # Определяем модель для сохранения (по умолчанию "nano-banana-pro")
            selected_model = request.model_name if request.model_name else DEFAULT_MODEL_ID
            logger.info(f"[GENERATION] Выбрана модель: {selected_model}")
            
            # Сохраняем выбранную модель в метаданных (для обратной совместимости)
            generation_metadata = {}
            generation_metadata['model_name'] = selected_model
            generation_metadata['provider'] = model_provider
            generation_metadata['retry_count'] = 0
            generation_metadata['max_retries'] = MAX_GENERATION_RETRIES
            
            generation = Generation(
                user_id=user.user_id,
                prompt=request.prompt,
                negative_prompt=request.negative_prompt,
                generation_mode=request.generation_mode,
                model_name=selected_model,  # Сохраняем в отдельное поле
                resolution=request.resolution,
                aspect_ratio=request.aspect_ratio,
                guidance_scale=request.guidance_scale,
                num_inference_steps=request.num_inference_steps,
                seed=request.seed,
                status="pending",
                generation_metadata=generation_metadata
            )
            session.add(generation)
            session.commit()
            session.refresh(generation)
            
            generation_id = generation.id
            logger.info(f"[GENERATION] Генерация {generation_id} создана в БД для пользователя {user.user_id}")
            
            # Теперь сохраняем референсные изображения в MinIO и получаем их URL
            if request.reference_images:
                import base64
                for idx, ref_img_data in enumerate(request.reference_images):
                    try:
                        # Если это base64 data URL, извлекаем данные
                        if ref_img_data.startswith('data:image'):
                            # Парсим data URL: data:image/jpeg;base64,/9j/4AAQ...
                            header, base64_data = ref_img_data.split(',', 1)
                            mime_type = header.split(';')[0].split(':')[1] if ':' in header else 'image/jpeg'
                            image_bytes = base64.b64decode(base64_data)
                            
                            # Определяем расширение файла
                            ext = 'jpg'
                            if 'png' in mime_type:
                                ext = 'png'
                            elif 'webp' in mime_type:
                                ext = 'webp'
                            
                            # Валидация формата изображения через PIL (только проверка, без изменения)
                            try:
                                from PIL import Image as PILImage
                                import io as image_io
                                img = PILImage.open(image_io.BytesIO(image_bytes))
                                img.verify()  # Проверяем что это валидное изображение
                                img = PILImage.open(image_io.BytesIO(image_bytes))  # Пересоздаем после verify
                                
                                # Проверяем что изображение не слишком большое (максимум 8192x8192 для валидации)
                                MAX_DIMENSION_VALIDATION = 8192
                                if img.width > MAX_DIMENSION_VALIDATION or img.height > MAX_DIMENSION_VALIDATION:
                                    error_msg = f"Референс {idx + 1} слишком большой ({img.width}x{img.height}). Максимальный размер: {MAX_DIMENSION_VALIDATION}x{MAX_DIMENSION_VALIDATION}"
                                    logger.error(f"[GENERATION] {error_msg}")
                                    raise ValueError(error_msg)
                                
                                # Проверяем размер файла (максимум 20MB для сохранения в MinIO)
                                MAX_REF_SIZE = 20 * 1024 * 1024  # 20MB
                                if len(image_bytes) > MAX_REF_SIZE:
                                    error_msg = f"Референс {idx + 1} слишком большой ({len(image_bytes) / 1024 / 1024:.1f}MB). Максимальный размер: {MAX_REF_SIZE / 1024 / 1024}MB"
                                    logger.error(f"[GENERATION] {error_msg}")
                                    raise ValueError(error_msg)
                                
                            except ValueError:
                                raise  # Пробрасываем ValueError дальше
                            except Exception as img_error:
                                error_msg = f"Референс {idx + 1} не является валидным изображением: {str(img_error)}"
                                logger.error(f"[GENERATION] {error_msg}")
                                raise ValueError(error_msg)
                            
                            ref_filename = generate_storage_object_name("references", ext)
                            
                            # ВАЖНО: Сохраняем ОРИГИНАЛЬНОЕ качество в MinIO (без обработки)
                            # Оптимизация будет происходить только при отправке в Replicate API
                            upload_result = minio.upload_image(
                                image_bytes,
                                ref_filename,
                                mime_type
                            )
                            reference_image_urls.append(upload_result['url'])
                            logger.info(f"[GENERATION] Референс {idx + 1} сохранен в MinIO: {upload_result['url'][:100]}...")
                        elif ref_img_data.startswith(("http://", "https://")):
                            if not is_allowed_reference_url(ref_img_data, settings):
                                raise ValueError(
                                    f"Референс {idx + 1}: разрешены только ссылки на файлы вашего хранилища "
                                    f"({settings.MINIO_PUBLIC_URL})"
                                )
                            reference_image_urls.append(ref_img_data)
                        else:
                            raise ValueError(f"Референс {idx + 1}: неподдерживаемый формат (нужен data:image или URL MinIO)")
                    except ValueError:
                        raise
                    except Exception as e:
                        logger.error(f"[GENERATION] Ошибка сохранения референса {idx + 1}: {e}", exc_info=True)
                        raise ValueError(f"Ошибка сохранения референса {idx + 1}: {e}") from e
                
                # Обновляем generation_metadata с URL референсов
                if not generation.generation_metadata:
                    generation.generation_metadata = {}
                generation.generation_metadata['reference_images_count'] = len(request.reference_images)
                generation.generation_metadata['reference_image_urls'] = reference_image_urls
                # Модель уже сохранена в отдельное поле model_name, но для совместимости сохраняем и в metadata
                if not generation.generation_metadata.get('model_name'):
                    generation.generation_metadata['model_name'] = generation.model_name or "nano-banana-pro"
                from sqlalchemy.orm.attributes import flag_modified
                flag_modified(generation, "generation_metadata")
                session.commit()
                logger.info(f"[GENERATION] Референсы сохранены для генерации {generation_id}: {len(reference_image_urls)} URL")
        
        # Запускаем асинхронную обработку
        request_data = request.dict()
        # Для Banana Lab быстрее передавать уже сохраненные URL референсов
        # (используется /v1/nb2/url-generations), чтобы не грузить base64 повторно.
        if reference_image_urls:
            request_data["reference_images"] = reference_image_urls
        executor.submit(process_generation_async, generation_id, user.user_id, request_data)
        
        logger.info(f"[GENERATION] Задача {generation_id} добавлена в очередь пользователем {user.user_id}")
        
        return ImageGenerationResponse(
            status="pending",
            image_id=generation_id,
            message="Генерация добавлена в очередь"
        )
        
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[GENERATION] Ошибка создания задачи: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Ошибка создания задачи генерации: {str(e)}")

@router.get("/list", response_model=list[ImageResponse])
async def list_generations(
    request: Request,
    user: Annotated[TokenPayload, Depends(auth_service.get_current_user)]
):
    """Список генераций пользователя"""
    try:
        # Получаем параметры из query string напрямую, чтобы избежать проблем с валидацией FastAPI
        query_params = request.query_params
        limit_str = query_params.get("limit")
        offset_str = query_params.get("offset")
        
        # Валидация и нормализация параметров
        try:
            if limit_str is None or limit_str == "":
                limit_val = 50
            else:
                limit_val = int(limit_str)
                if limit_val < 1 or limit_val > 100:
                    limit_val = 50
        except (ValueError, TypeError):
            limit_val = 50
        
        try:
            if offset_str is None or offset_str == "":
                offset_val = 0
            else:
                offset_val = int(offset_str)
                if offset_val < 0:
                    offset_val = 0
        except (ValueError, TypeError):
            offset_val = 0
        
        logger.info(f"[LIST] Запрос списка генераций для пользователя {user.user_id}, limit={limit_val}, offset={offset_val}")
        with db_service.get_session() as session:
            # Проверяем, что пользователь существует
            db_user = session.query(User).filter(User.id == user.user_id).first()
            if not db_user:
                logger.error(f"[LIST] Пользователь {user.user_id} не найден в БД")
                raise HTTPException(status_code=404, detail="Пользователь не найден")
            
            # Получаем общее количество генераций пользователя
            total_count = session.query(Generation).filter(Generation.user_id == user.user_id).count()
            
            # Получаем все генерации пользователя
            all_generations = session.query(Generation).filter(
                Generation.user_id == user.user_id
            ).order_by(Generation.created_at.desc()).all()
            
            # Применяем limit и offset
            generations = all_generations[offset_val:offset_val+limit_val]
            
            result = []
            for gen in generations:
                # Извлекаем error_message из generation_metadata
                # Для старых генераций (до добавления error_message) будет None
                error_msg = None
                if gen.generation_metadata:
                    error_msg = gen.generation_metadata.get('error')
                    # Логируем только для failed генераций без error_message (проблема!)
                    if gen.status == 'failed' and not error_msg:
                        logger.warning(f"[LIST] Генерация {gen.id} имеет статус 'failed', но error_message отсутствует в generation_metadata: {gen.generation_metadata}")
                elif gen.status == 'failed':
                    logger.warning(f"[LIST] Генерация {gen.id} имеет статус 'failed', но generation_metadata отсутствует")
                
                # Извлекаем model_name из поля или метаданных (для обратной совместимости)
                model_name = gen.model_name
                if not model_name and gen.generation_metadata:
                    model_name = gen.generation_metadata.get('model_name')
                # Если модель все еще не найдена, используем по умолчанию
                if not model_name:
                    model_name = "nano-banana-pro"

                retry_count = 0
                max_retries = MAX_GENERATION_RETRIES
                if gen.generation_metadata:
                    retry_count = int(gen.generation_metadata.get("retry_count", 0) or 0)
                    max_retries = int(gen.generation_metadata.get("max_retries", MAX_GENERATION_RETRIES) or MAX_GENERATION_RETRIES)
                
                result.append(ImageResponse(
                    id=gen.id,
                    user_id=gen.user_id,
                    prompt=gen.prompt,
                    negative_prompt=gen.negative_prompt,
                    generation_mode=gen.generation_mode,
                    resolution=gen.resolution,
                    aspect_ratio=gen.aspect_ratio,
                    result_url=gen.result_url,
                    status=gen.status,
                    created_at=gen.created_at,
                    error_message=error_msg,  # None для старых генераций без ошибок
                    model_name=model_name,
                    retry_count=retry_count,
                    max_retries=max_retries,
                    fallback_model=get_fallback_model(model_name),
                    **_rewrite_metadata_fields(gen.generation_metadata),
                ))
            
            # Логируем только активные процессы (running/pending), чтобы не засорять логи
            running_count = sum(1 for resp in result if resp.status == 'running')
            pending_count = sum(1 for resp in result if resp.status == 'pending')
            if running_count or pending_count:
                logger.info(
                    f"[LIST] Активные генерации пользователя {user.user_id}: "
                    f"выполняется={running_count}, в очереди={pending_count}"
                )
            
            # Возвращаем результат с метаданными
            from fastapi.responses import JSONResponse
            import json
            
            # Сериализуем генерации с правильной обработкой datetime
            generations_data = []
            for gen in result:
                gen_dict = gen.dict()
                # Преобразуем datetime в строки для JSON сериализации
                if 'created_at' in gen_dict and gen_dict['created_at']:
                    gen_dict['created_at'] = gen_dict['created_at'].isoformat() if hasattr(gen_dict['created_at'], 'isoformat') else str(gen_dict['created_at'])
                if 'updated_at' in gen_dict and gen_dict.get('updated_at'):
                    gen_dict['updated_at'] = gen_dict['updated_at'].isoformat() if hasattr(gen_dict['updated_at'], 'isoformat') else str(gen_dict['updated_at'])
                if 'completed_at' in gen_dict and gen_dict.get('completed_at'):
                    gen_dict['completed_at'] = gen_dict['completed_at'].isoformat() if hasattr(gen_dict['completed_at'], 'isoformat') else str(gen_dict['completed_at'])
                # Убрали избыточное логирование error_message
                generations_data.append(gen_dict)
            
            return JSONResponse(content={
                "generations": generations_data,
                "meta": {
                    "total": total_count,
                    "shown": len(result),
                    "limit": limit_val,
                    "offset": offset_val,
                    "storage_info": {
                        "retention_days": 7,
                        "message": "Изображения хранятся 7 дней, затем автоматически удаляются"
                    }
                }
            })
    except Exception as e:
        logger.error(f"[LIST] Ошибка получения списка генераций: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Ошибка получения списка генераций: {str(e)}")

@router.get("/models")
async def get_available_models(
    user: Annotated[TokenPayload, Depends(auth_service.get_current_user)],
):
    """Получение списка доступных моделей для генерации"""
    _ = user
    models = {}
    for key, entry in MODEL_REGISTRY.items():
        models[key] = {
            "display_name": entry["display_name"],
            "description": entry["description"],
            "name": entry.get("replicate_slug") or entry.get("openrouter_slug") or key,
            "providers": entry.get("providers", []),
            "color": entry.get("color", "replicate"),
            "params_profile": entry.get("params_profile", "nano"),
            "group": entry.get("group") or entry.get("color", "replicate"),
        }
    return {
        "models": models,
        "default_model": DEFAULT_MODEL_ID,
        "bananalab_key_prefix": "nb_",
        "replicate_key_prefix_hint": "r8_",
        "openrouter_key_prefix_hint": "sk-or",
        "provider_colors": {
            "bananalab": "#f59e0b",
            "replicate": "#3b82f6",
            "openrouter": "#10b981",
        },
    }


@router.get("/bananahub-health")
async def get_bananahub_health():
    """Публичный статус BananaHub API — для баннера на главной без авторизации."""
    reachable, probe_error = _bananalab_health_status()
    is_unavailable = not reachable or _bananalab_is_unavailable()
    is_paused = (not is_unavailable) and _bananalab_is_paused()

    if is_unavailable:
        duration_hint = _format_duration_hint(_unavailable_duration_seconds(), "Недоступен уже")
        base_message = probe_error or bananalab_runtime_state.get("last_unavailable_error") or (
            "BananaHub API недоступен: сервер провайдера не отвечает. "
            "Это не проблема вашего аккаунта — напишите в @bananahub в Telegram."
        )
        return {
            "provider": "bananalab",
            "state": "unavailable",
            "can_generate": False,
            "message": base_message + duration_hint,
        }

    if is_paused:
        duration_hint = _format_duration_hint(_paused_duration_seconds(), "На паузе уже")
        return {
            "provider": "bananalab",
            "state": "paused",
            "can_generate": False,
            "message": (
                f"BananaHub: проект на паузе у провайдера.{duration_hint} "
                f"Задач в очереди: {_queue_size()}. Автоповтор включён."
            ),
        }

    return {
        "provider": "bananalab",
        "state": "ok",
        "can_generate": True,
        "message": "BananaHub: генерация доступна.",
    }


@router.get("/provider-status")
async def get_provider_status(
    request: Request,
    user: Annotated[TokenPayload, Depends(auth_service.get_current_user)],
    model_name: Optional[str] = None,
):
    """
    Статус доступности генерации для текущего провайдера (по ключу пользователя).
    Нужен для UI-индикатора "можно генерировать / пауза".
    """
    _ = request
    keys = _load_user_api_keys(user.user_id)
    has_replicate_key = bool(keys.get("replicate"))
    has_bananalab_key = bool(keys.get("bananalab"))
    has_openrouter_key = bool(keys.get("openrouter"))
    model = (model_name or DEFAULT_MODEL_ID).strip().lower()
    provider = get_provider_for_model(model, keys)
    api_key = keys.get(provider) if provider else None

    queue_size = _queue_size()
    last_paused_at = bananalab_runtime_state.get("last_paused_at")
    last_success_at = bananalab_runtime_state.get("last_success_at")
    last_paused_error = bananalab_runtime_state.get("last_paused_error")

    base_meta = {
        "paused_queue_size": queue_size,
        "last_paused_at": last_paused_at,
        "last_success_at": last_success_at,
        "has_replicate_key": has_replicate_key,
        "has_bananalab_key": has_bananalab_key,
        "has_openrouter_key": has_openrouter_key,
        "model_name": model,
    }

    if not provider:
        return {
            "provider": "unknown",
            "state": "unknown",
            "can_generate": False,
            "message": "Для выбранной модели нет подходящего API ключа. Добавьте ключ в настройках.",
            **base_meta,
        }

    if provider == "replicate":
        return {
            "provider": "replicate",
            "state": "ok",
            "can_generate": True,
            "message": "Replicate: генерация доступна.",
            **base_meta,
        }

    if provider == "openrouter":
        return {
            "provider": "openrouter",
            "state": "ok",
            "can_generate": True,
            "message": "OpenRouter (GPT): генерация доступна.",
            **base_meta,
        }

    _ = api_key

    # Banana Lab: сначала проверяем доступность хоста, затем паузу проекта
    reachable, probe_error = _bananalab_health_status()
    is_unavailable = not reachable or _bananalab_is_unavailable()
    is_paused = (not is_unavailable) and _bananalab_is_paused()
    paused_since = bananalab_runtime_state.get("project_paused_since") or (
        bananalab_runtime_state.get("last_paused_at") if is_paused else None
    )
    unavailable_since = bananalab_runtime_state.get("provider_unavailable_since") or (
        bananalab_runtime_state.get("last_unavailable_at") if is_unavailable else None
    )
    paused_duration_seconds = _paused_duration_seconds() if is_paused else None
    unavailable_duration_seconds = _unavailable_duration_seconds() if is_unavailable else None
    queue_size = _queue_size()
    last_unavailable_at = bananalab_runtime_state.get("last_unavailable_at")
    last_unavailable_error = bananalab_runtime_state.get("last_unavailable_error")

    if is_unavailable:
        duration_hint = _format_duration_hint(unavailable_duration_seconds, "Недоступен уже")
        base_message = probe_error or last_unavailable_error or (
            "BananaHub API недоступен: сервер провайдера не отвечает. "
            "Это не проблема вашего аккаунта — напишите в @bananahub в Telegram."
        )
        message = base_message + duration_hint
        state = "unavailable"
    elif is_paused:
        duration_hint = _format_duration_hint(paused_duration_seconds, "На паузе уже")
        message = (
            f"BananaHub: проект на паузе у провайдера.{duration_hint} "
            f"Задач в очереди: {queue_size}. Автоповтор включён."
        )
        state = "paused"
    else:
        message = "BananaHub: генерация доступна."
        state = "ok"

    return {
        "provider": "bananalab",
        "state": state,
        "can_generate": state == "ok",
        "message": message,
        "paused_queue_size": queue_size,
        "last_paused_at": last_paused_at,
        "last_success_at": last_success_at,
        "last_paused_error": last_paused_error,
        "last_unavailable_at": last_unavailable_at,
        "last_unavailable_error": last_unavailable_error,
        "paused_since": paused_since,
        "paused_duration_seconds": paused_duration_seconds,
        "unavailable_since": unavailable_since,
        "unavailable_duration_seconds": unavailable_duration_seconds,
        **base_meta,
    }


@router.get("/{generation_id}", response_model=dict)
async def get_generation_full(
    generation_id: int,
    user: Annotated[TokenPayload, Depends(auth_service.get_current_user)]
):
    """Получение полных данных генерации для редактирования"""
    with db_service.get_session() as session:
        generation = session.query(Generation).filter(
            Generation.id == generation_id,
            Generation.user_id == user.user_id
        ).first()

        if not generation:
            raise HTTPException(status_code=404, detail="Генерация не найдена")

        metadata = generation.generation_metadata or {}
        model_name = generation.model_name
        if not model_name:
            model_name = metadata.get("model_name", "nano-banana-pro")

        return {
            "id": generation.id,
            "prompt": generation.prompt,
            "negative_prompt": generation.negative_prompt,
            "generation_mode": generation.generation_mode,
            "resolution": generation.resolution,
            "aspect_ratio": generation.aspect_ratio,
            "guidance_scale": generation.guidance_scale,
            "num_inference_steps": generation.num_inference_steps,
            "seed": generation.seed,
            "model_name": model_name,
            "reference_images": metadata.get("reference_image_urls", []),
            "result_url": generation.result_url,
            "status": generation.status,
            "error_message": metadata.get('error'),
            **_rewrite_metadata_fields(metadata),
        }


@router.delete("/{generation_id}")
async def delete_generation(
    generation_id: int,
    user: Annotated[TokenPayload, Depends(auth_service.get_current_user)]
):
    """Удаление генерации"""
    with db_service.get_session() as session:
        generation = session.query(Generation).filter(
            Generation.id == generation_id,
            Generation.user_id == user.user_id
        ).first()
        
        if not generation:
            raise HTTPException(status_code=404, detail="Генерация не найдена")
        
        # Удаляем из MinIO результат, если есть
        if generation.result_path:
            minio.delete_image(generation.result_path)

        session.delete(generation)
        session.commit()

        return {"message": "Генерация удалена"}


@router.post("/cleanup")
async def cleanup_old_generations(
    user: Annotated[TokenPayload, Depends(auth_service.get_current_user)]
):
    """
    Очистка генераций и связанных изображений старше 7 дней.

    Эндпоинт защищен: выполнять может только админ (is_admin=True).
    Предполагается, что его будет дергать крон или ручной вызов админа.
    """
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Доступ запрещен")

    retention_days = 7
    cutoff = datetime.utcnow() - timedelta(days=retention_days)

    deleted_count = 0
    deleted_files: List[str] = []

    from app.config import settings as app_settings

    with db_service.get_session() as session:
        old_generations: List[Generation] = (
            session.query(Generation)
            .filter(Generation.created_at < cutoff)
            .all()
        )

        logger.info(
            f"[CLEANUP] Найдено {len(old_generations)} генераций старше {retention_days} дней для удаления"
        )

        for gen in old_generations:
            # Удаляем результат из MinIO
            if gen.result_path:
                if minio.delete_image(gen.result_path):
                    deleted_files.append(gen.result_path)
            # Удаляем референсы из MinIO (по сохраненным публичным URL),
            # только если этот URL не используется ни в одной другой генерации.
            if gen.generation_metadata:
                ref_urls: List[str] = gen.generation_metadata.get("reference_image_urls") or []
                for url in ref_urls:
                    if not url:
                        continue
                    # Проверяем, есть ли другие генерации (кроме текущей),
                    # у которых в metadata присутствует этот же URL
                    other_gens: List[Generation] = (
                        session.query(Generation)
                        .filter(Generation.id != gen.id)
                        .filter(Generation.generation_metadata.isnot(None))
                        .all()
                    )
                    url_used_elsewhere = False
                    for other in other_gens:
                        other_urls = []
                        if other.generation_metadata:
                            other_urls = other.generation_metadata.get("reference_image_urls") or []
                        if url in other_urls:
                            url_used_elsewhere = True
                            break

                    if url_used_elsewhere:
                        continue

                    path = _extract_minio_path_from_url(url, app_settings.MINIO_BUCKET)
                    if path and minio.delete_image(path):
                        deleted_files.append(path)

            session.delete(gen)
            deleted_count += 1

        session.commit()

    logger.info(
        f"[CLEANUP] Удалено генераций: {deleted_count}, файлов в MinIO: {len(deleted_files)}"
    )

    return {
        "deleted_generations": deleted_count,
        "deleted_files": deleted_files,
        "retention_days": retention_days,
    }

