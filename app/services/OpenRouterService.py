"""
Сервис генерации изображений через OpenRouter Image API.
"""
from __future__ import annotations

import base64
import logging
from typing import Any, Dict, List, Optional

import requests

from app.config import settings
from app.services.image_models import get_model_entry, openrouter_slug

logger = logging.getLogger(__name__)

OPENROUTER_IMAGES_URL = "https://openrouter.ai/api/v1/images"
OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_ALLOWED_ASPECTS = frozenset({"1:1", "3:2", "2:3", "auto"})

PROMPT_REWRITE_SYSTEM = (
    "Ты переписываешь промпты для генерации изображений так, чтобы они проходили фильтры "
    "безопасности Google/OpenAI. Сохраняй язык и общий смысл сцены, но обязательно: "
    "замени имён реальных знаменитостей на обобщённые описания "
    "(например «известный футболист в синей форме» вместо конкретного имени); "
    "убери насилие, унижение, NSFW и провокации. "
    "Верни ТОЛЬКО переписанный промпт, без кавычек и пояснений."
)


def _map_aspect_ratio(aspect_ratio: str) -> str:
    ratio = (aspect_ratio or "1:1").strip()
    if ratio in OPENROUTER_ALLOWED_ASPECTS:
        return ratio
    if ratio in {"16:9", "4:3", "21:9", "5:4"}:
        return "3:2"
    if ratio in {"9:16", "3:4", "2:3"}:
        return "2:3"
    return "auto"


def _build_input_references(reference_images: Optional[List[Any]]) -> List[dict]:
    refs: List[dict] = []
    for img in reference_images or []:
        if not img:
            continue
        if isinstance(img, str):
            url = img.strip()
            if not url:
                continue
            if url.startswith("data:image") or url.startswith("http://") or url.startswith("https://"):
                refs.append({"type": "image_url", "image_url": {"url": url}})
        elif isinstance(img, dict):
            refs.append(img)
    return refs[:16]


class OpenRouterService:
    TIMEOUT = 900
    MAX_RETRIES = 3
    RETRY_DELAY_SECONDS = 5

    def __init__(self, api_key: str):
        key = (api_key or "").strip()
        if not key:
            raise ValueError("OpenRouter API ключ не указан")
        if not key.startswith("sk-or"):
            raise ValueError("OpenRouter API ключ должен начинаться с sk-or")
        self.api_key = key

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        referer = (settings.OPENROUTER_HTTP_REFERER or "").strip()
        title = (settings.OPENROUTER_X_TITLE or "").strip()
        if referer:
            headers["HTTP-Referer"] = referer
        if title:
            headers["X-Title"] = title
        return headers

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
        _ = (negative_prompt, resolution, guidance_scale, num_inference_steps, seed)
        entry = get_model_entry(model_name)
        slug = openrouter_slug(model_name)
        if not slug:
            return {
                "success": False,
                "error": f"Модель '{model_name}' недоступна через OpenRouter",
            }

        payload: Dict[str, Any] = {
            "model": slug,
            "prompt": prompt,
            "aspect_ratio": _map_aspect_ratio(aspect_ratio),
            "n": 1,
        }
        refs = _build_input_references(reference_images)
        if refs:
            payload["input_references"] = refs

        logger.info(
            "[OPENROUTER] Генерация model=%s (%s), prompt=%s...",
            model_name,
            slug,
            prompt[:100],
        )

        last_error = "Неизвестная ошибка OpenRouter"
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                response = requests.post(
                    OPENROUTER_IMAGES_URL,
                    headers=self._headers(),
                    json=payload,
                    timeout=self.TIMEOUT,
                )
                if response.status_code >= 400:
                    last_error = self._extract_error(response)
                    retryable = response.status_code in (408, 429, 500, 502, 503, 504)
                    logger.warning(
                        "[OPENROUTER] HTTP %s attempt=%s: %s",
                        response.status_code,
                        attempt,
                        last_error,
                    )
                    if retryable and attempt < self.MAX_RETRIES:
                        continue
                    return {"success": False, "error": last_error, "retryable": retryable}

                body = response.json()
                image_data = self._extract_image_bytes(body)
                if not image_data:
                    last_error = "OpenRouter не вернул изображение"
                    logger.warning("[OPENROUTER] Пустой ответ attempt=%s", attempt)
                    if attempt < self.MAX_RETRIES:
                        continue
                    return {"success": False, "error": last_error, "retryable": True}

                display = entry.get("display_name") if entry else model_name
                logger.info("[OPENROUTER] Успех model=%s (%s)", model_name, display)
                return {"success": True, "image_data": image_data, "image_url": None}
            except requests.RequestException as exc:
                last_error = f"OpenRouter: ошибка сети — {exc}"
                logger.warning("[OPENROUTER] RequestException attempt=%s: %s", attempt, exc)
                if attempt < self.MAX_RETRIES:
                    continue
                return {"success": False, "error": last_error, "retryable": True}

        return {"success": False, "error": last_error, "retryable": True}

    def rewrite_prompt(self, prompt: str) -> Dict[str, Any]:
        """Переформулирует промпт через текстовую модель OpenRouter."""
        text = (prompt or "").strip()
        if not text:
            return {"success": False, "error": "Пустой промпт"}

        rewrite_model = (settings.OPENROUTER_PROMPT_REWRITE_MODEL or "openai/gpt-4o-mini").strip()
        payload = {
            "model": rewrite_model,
            "messages": [
                {"role": "system", "content": PROMPT_REWRITE_SYSTEM},
                {"role": "user", "content": f"Rewrite this image prompt:\n\n{text}"},
            ],
            "max_tokens": 600,
            "temperature": 0.3,
        }

        try:
            response = requests.post(
                OPENROUTER_CHAT_URL,
                headers=self._headers(),
                json=payload,
                timeout=60,
            )
            if response.status_code >= 400:
                return {"success": False, "error": self._extract_error(response)}

            body = response.json()
            choices = body.get("choices") if isinstance(body, dict) else None
            if not isinstance(choices, list) or not choices:
                return {"success": False, "error": "OpenRouter не вернул переформулированный промпт"}

            message = choices[0].get("message") if isinstance(choices[0], dict) else None
            rewritten = (message or {}).get("content") if isinstance(message, dict) else None
            rewritten = str(rewritten or "").strip().strip('"').strip("'")
            if not rewritten:
                return {"success": False, "error": "OpenRouter вернул пустой промпт"}

            logger.info(
                "[OPENROUTER] rewrite model=%s | original=%s | rewritten=%s",
                rewrite_model,
                text[:200],
                rewritten[:200],
            )
            return {"success": True, "prompt": rewritten, "model": rewrite_model, "original": text}
        except requests.RequestException as exc:
            return {"success": False, "error": f"OpenRouter: ошибка сети — {exc}"}

    @staticmethod
    def _extract_error(response: requests.Response) -> str:
        try:
            body = response.json()
        except Exception:
            text = (response.text or "").strip()
            return text or f"OpenRouter HTTP {response.status_code}"

        if isinstance(body, dict):
            err = body.get("error")
            if isinstance(err, dict):
                msg = err.get("message") or err.get("code")
                if msg:
                    return f"OpenRouter: {msg}"
            if isinstance(err, str) and err.strip():
                return f"OpenRouter: {err.strip()}"
            detail = body.get("detail") or body.get("message")
            if detail:
                return f"OpenRouter: {detail}"
        return f"OpenRouter HTTP {response.status_code}"

    @staticmethod
    def _extract_image_bytes(body: Any) -> Optional[bytes]:
        if not isinstance(body, dict):
            return None
        data = body.get("data")
        if not isinstance(data, list) or not data:
            return None
        first = data[0]
        if not isinstance(first, dict):
            return None
        b64 = first.get("b64_json")
        if not b64:
            return None
        try:
            return base64.b64decode(b64)
        except Exception:
            return None
