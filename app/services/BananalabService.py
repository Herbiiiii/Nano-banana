"""
Клиент HTTP API Banana Lab (https://api.bananalab.pw) для Nano Banana.
Схема запроса — по документации Playground: POST /v1/generations.
"""
import base64
import json
import logging
import time
from typing import Any, Dict, List, Optional

import requests

from app.config import settings
from app.services.generation_prompt import enhance_prompt_for_image_generation
from app.services.bananalab_response import (
    absolute_job_status_url,
    detail_from_response_body,
    find_image_in_json,
)

logger = logging.getLogger(__name__)

_MAX_ERROR_BODY_LOG = 8000


def _safe_response_body_for_log(body: Any) -> str:
    """Полное тело ответа API в лог (для 422/4xx в проде). Ключи и тексты, не бинарь."""
    try:
        if isinstance(body, (dict, list)):
            s = json.dumps(body, ensure_ascii=False, default=str)
        else:
            s = str(body)
        if len(s) > _MAX_ERROR_BODY_LOG:
            return s[:_MAX_ERROR_BODY_LOG] + "…[truncated]"
        return s
    except Exception:
        return str(body)[:_MAX_ERROR_BODY_LOG]


# По актуальной документации Banana Lab выбор модели не передается в request body.
SUPPORTED_BANANALAB_FRONTEND_MODELS = frozenset(("nano-banana-pro", "nano-banana-2", "nano-banana"))


def _optimize_image_for_api(image_data: bytes, ref_index: int) -> bytes:
    # Ленивый импорт: модуль replicate не совместим с некоторыми версиями Python при тестах.
    from app.services.ReplicateService import ReplicateService

    class _RefOptimizeShim:
        MAX_REF_DIMENSION = ReplicateService.MAX_REF_DIMENSION
        MAX_REF_SIZE_MB = ReplicateService.MAX_REF_SIZE_MB

    return ReplicateService._optimize_image_for_api(_RefOptimizeShim(), image_data, ref_index)


class BananalabService:
    TIMEOUT = 900
    JOB_TIMEOUT_SECONDS = 240
    MAX_RETRIES = 3
    RETRY_DELAY_SECONDS = 5
    JOB_POLL_INTERVAL_SECONDS = 1.5

    def __init__(self, api_key: str, base_url: Optional[str] = None):
        if not api_key or not api_key.strip():
            raise ValueError("Banana Lab API key is required")
        self.api_key = api_key.strip()
        self.base_url = (base_url or settings.BANANALAB_BASE_URL).rstrip("/")

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _job_status_normalized(data: Dict[str, Any]) -> str:
        return str(data.get("status") or "").strip().lower()

    def _poll_job_until_done(self, initial: Dict[str, Any]) -> Dict[str, Any]:
        """Опрос GET status_url пока задача не завершится или не истечёт TIMEOUT."""
        status_url = absolute_job_status_url(self.base_url, initial)
        if not status_url:
            return initial

        deadline = time.time() + self.JOB_TIMEOUT_SECONDS
        current: Any = initial
        last_logged: Optional[str] = None

        while time.time() < deadline:
            if not isinstance(current, dict):
                break

            st = self._job_status_normalized(current)
            # Banana Lab иногда сообщает о паузе модели текстом, не меняя status на failed.
            diag = (
                f"{current.get('error') or ''} "
                f"{current.get('message') or ''} "
                f"{current.get('detail') or ''}"
            ).lower()
            if "paused" in diag:
                return {
                    "__bananalab_job_failed__": True,
                    "error": str(
                        current.get("error")
                        or current.get("message")
                        or current.get("detail")
                        or "Модель Banana Lab временно на паузе"
                    ),
                    "_raw": current,
                }
            if st != last_logged:
                logger.info("[BANANALAB] Задача: status=%s", current.get("status"))
                last_logged = st

            if st in ("completed", "succeeded", "success", "done", "finished"):
                return current
            if st in ("failed", "error", "cancelled", "canceled"):
                err = (
                    current.get("error")
                    or current.get("message")
                    or detail_from_response_body(current)
                )
                return {"__bananalab_job_failed__": True, "error": str(err), "_raw": current}

            img_b, img_u = find_image_in_json(current)
            if img_b or img_u:
                return current

            if st not in (
                "",
                "queued",
                "pending",
                "processing",
                "running",
                "in_progress",
                "started",
                "working",
            ):
                logger.warning(
                    "[BANANALAB] Неизвестный status=%r — проверьте документацию API",
                    current.get("status"),
                )

            time.sleep(self.JOB_POLL_INTERVAL_SECONDS)

            try:
                pr = requests.get(status_url, headers=self._headers(), timeout=120)
            except requests.RequestException as e:
                logger.warning("[BANANALAB] Ошибка GET job: %s", e)
                continue

            if pr.status_code >= 400:
                try:
                    body = pr.json()
                except Exception:
                    body = pr.text
                logger.error(
                    "[BANANALAB] GET job HTTP %s: %s",
                    pr.status_code,
                    _safe_response_body_for_log(body),
                )
                return {
                    "__bananalab_job_failed__": True,
                    "error": detail_from_response_body(body),
                    "_raw": body,
                }

            try:
                current = pr.json()
            except Exception as e:
                return {
                    "__bananalab_job_failed__": True,
                    "error": f"Ответ job не JSON: {e}",
                    "_raw": None,
                }

        return {
            "__bananalab_job_failed__": True,
            "error": "Превышено время ожидания готовности изображения (Banana Lab)",
            "_raw": current,
        }

    def generate_image(
        self,
        prompt: str,
        negative_prompt: Optional[str] = None,
        resolution: str = "1K",
        aspect_ratio: str = "1:1",
        guidance_scale: float = 7.5,
        num_inference_steps: int = 50,
        seed: Optional[int] = None,
        reference_images: Optional[List] = None,
        model_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        if negative_prompt:
            logger.debug("[BANANALAB] negative_prompt игнорируется API Banana Lab")
        if guidance_scale != 7.5 or num_inference_steps != 50 or seed is not None:
            logger.debug(
                "[BANANALAB] guidance/steps/seed не поддерживаются провайдером, значения отброшены"
            )

        if model_name and model_name not in SUPPORTED_BANANALAB_FRONTEND_MODELS:
            logger.warning("[BANANALAB] Модель %s не поддерживается клиентом, игнорируем", model_name)
        input_b64_list: List[str] = []
        reference_images = reference_images or []

        for idx, img in enumerate(reference_images[:14], 1):
            try:
                if isinstance(img, str):
                    if img.startswith("data:image"):
                        _, encoded = img.split(",", 1)
                        img_data = base64.b64decode(encoded)
                        img_data = _optimize_image_for_api(img_data, idx)
                        input_b64_list.append(base64.b64encode(img_data).decode("ascii"))
                    elif img.startswith(("http://", "https://")):
                        r = requests.get(img, timeout=30)
                        if r.status_code == 200:
                            img_data = _optimize_image_for_api(r.content, idx)
                            input_b64_list.append(base64.b64encode(img_data).decode("ascii"))
                        else:
                            logger.warning(
                                "[BANANALAB] Референс %s: HTTP %s", idx, r.status_code
                            )
                    else:
                        logger.warning("[BANANALAB] Референс %s: неподдерживаемая строка", idx)
                elif hasattr(img, "read"):
                    img.seek(0)
                    img_data = _optimize_image_for_api(img.read(), idx)
                    input_b64_list.append(base64.b64encode(img_data).decode("ascii"))
            except Exception as e:
                logger.error("[BANANALAB] Ошибка референса %s: %s", idx, e)

        num_refs_effective = len(input_b64_list)
        if reference_images and num_refs_effective == 0:
            num_refs_effective = len(reference_images)

        final_prompt = enhance_prompt_for_image_generation(
            prompt, reference_images if reference_images else None, num_refs_effective
        )

        has_refs = len(input_b64_list) > 0
        if has_refs:
            payload: Dict[str, Any] = {
                "prompt": final_prompt,
                "aspect_ratio": aspect_ratio,
                "resolution": resolution,
                "input_images_base64": input_b64_list,
            }
            url = f"{self.base_url}/v1/nb2/generations"
        else:
            payload = {
                "prompt": final_prompt,
                "aspect_ratio": aspect_ratio,
                "resolution": resolution,
            }
            url = f"{self.base_url}/v1/nb2/text-generations"
        last_exc: Optional[Exception] = None

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                logger.info(
                    "[BANANALAB] POST %s (попытка %s/%s), референсов=%s",
                    url,
                    attempt,
                    self.MAX_RETRIES,
                    len(input_b64_list),
                )
                resp = requests.post(
                    url,
                    headers=self._headers(),
                    json=payload,
                    timeout=self.TIMEOUT,
                )

                if resp.status_code == 429 or resp.status_code == 503:
                    text = detail_from_response_body(
                        resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text
                    )
                    last_exc = RuntimeError(text)
                    if attempt < self.MAX_RETRIES:
                        logger.warning("[BANANALAB] %s, повтор через %ss", text, self.RETRY_DELAY_SECONDS)
                        time.sleep(self.RETRY_DELAY_SECONDS)
                        continue

                if resp.status_code >= 400:
                    try:
                        body = resp.json()
                    except Exception:
                        body = resp.text
                    msg = detail_from_response_body(body)
                    lower = msg.lower()
                    retryable = resp.status_code == 429 or any(
                        x in lower for x in ("429", "rate limit", "too many", "temporarily", "unavailable")
                    )
                    logger.error(
                        "[BANANALAB] POST generations HTTP %s. Кратко: %s | Полное тело: %s",
                        resp.status_code,
                        msg[:500],
                        _safe_response_body_for_log(body),
                    )
                    uf = msg
                    if retryable:
                        uf = (
                            "Сервис Banana Lab временно перегружен или лимит запросов. "
                            "Подождите и повторите. Детали: " + msg[:300]
                        )
                    return {
                        "success": False,
                        "image_url": None,
                        "image_data": None,
                        "error": uf,
                        "retryable": retryable,
                    }

                try:
                    data = resp.json()
                except Exception as e:
                    return {
                        "success": False,
                        "image_url": None,
                        "image_data": None,
                        "error": f"Ответ Banana Lab не JSON: {e}",
                        "retryable": False,
                    }

                if isinstance(data, dict) and (data.get("job_id") or data.get("status_url")):
                    data = self._poll_job_until_done(data)
                    if isinstance(data, dict) and data.get("__bananalab_job_failed__"):
                        err_msg = str(data.get("error") or "Ошибка задачи Banana Lab")
                        low = err_msg.lower()
                        return {
                            "success": False,
                            "image_url": None,
                            "image_data": None,
                            "error": err_msg,
                            "retryable": any(
                                x in low for x in ("timeout", "таймаут", "429", "503", "unavailable")
                            ),
                        }

                raw_bytes, image_url = find_image_in_json(data)
                if raw_bytes:
                    logger.info("[BANANALAB] Получены бинарные данные изображения, %s байт", len(raw_bytes))
                    return {
                        "success": True,
                        "image_url": image_url,
                        "image_data": raw_bytes,
                        "error": None,
                    }
                if image_url:
                    try:
                        img_r = requests.get(image_url, timeout=60)
                        if img_r.status_code != 200:
                            logger.warning(
                                "[BANANALAB] Скачивание результата HTTP %s: %s",
                                img_r.status_code,
                                _safe_response_body_for_log(img_r.text[:2000] if img_r.text else ""),
                            )
                        if img_r.status_code == 200:
                            return {
                                "success": True,
                                "image_url": image_url,
                                "image_data": img_r.content,
                                "error": None,
                            }
                        return {
                            "success": True,
                            "image_url": image_url,
                            "image_data": None,
                            "error": None,
                        }
                    except Exception as dl_e:
                        logger.warning("[BANANALAB] Не удалось скачать изображение: %s", dl_e)
                        return {
                            "success": True,
                            "image_url": image_url,
                            "image_data": None,
                            "error": None,
                        }

                logger.error(
                    "[BANANALAB] Не удалось извлечь изображение из ответа. Ключи верхнего уровня: %s",
                    list(data.keys()) if isinstance(data, dict) else type(data),
                )
                return {
                    "success": False,
                    "image_url": None,
                    "image_data": None,
                    "error": "Неожиданный формат ответа Banana Lab: нет URL и base64 изображения. "
                    "Проверьте логи сервера (ключи JSON).",
                    "retryable": False,
                }

            except requests.Timeout as e:
                last_exc = e
                if attempt < self.MAX_RETRIES:
                    time.sleep(self.RETRY_DELAY_SECONDS)
                    continue
                return {
                    "success": False,
                    "image_url": None,
                    "image_data": None,
                    "error": "Таймаут запроса к Banana Lab. Попробуйте проще промпт или позже.",
                    "retryable": True,
                }
            except Exception as e:
                logger.exception("[BANANALAB] Сбой запроса: %s", e)
                lower = str(e).lower()
                return {
                    "success": False,
                    "image_url": None,
                    "image_data": None,
                    "error": str(e) or "Ошибка сети при обращении к Banana Lab",
                    "retryable": any(x in lower for x in ("timeout", "connection", "429")),
                }

        return {
            "success": False,
            "image_url": None,
            "image_data": None,
            "error": str(last_exc) if last_exc else "Неизвестная ошибка",
            "retryable": True,
        }
