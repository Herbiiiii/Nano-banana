"""Разбор тел ответов Banana Lab API (без зависимости от replicate/settings)."""
import base64
import io
import json
import re
from typing import Any, Dict, Optional, Tuple

from PIL import Image


def _join_base_and_path(base_url: str, path: str) -> str:
    """Склеивает base_url и относительный path без дублирования /api."""
    base = (base_url or "").rstrip("/")
    if not path.startswith("/"):
        path = "/" + path
    if base.endswith("/api") and path.startswith("/api/"):
        path = path[len("/api") :]
    return f"{base}{path}"


def absolute_job_status_url(base_url: str, data: Dict[str, Any]) -> Optional[str]:
    """
    POST /v1/generations отдаёт job_id и/или относительный status_url.
    Возвращает полный URL для GET опроса статуса.
    """
    base = (base_url or "").rstrip("/")
    su = data.get("status_url")
    if isinstance(su, str) and su.strip():
        su = su.strip()
        if su.startswith("http://") or su.startswith("https://"):
            return _normalize_bananalab_job_url(su, base)
        return _normalize_bananalab_job_url(_join_base_and_path(base, su), base)
    jid = data.get("job_id")
    if jid:
        return f"{base}/v1/jobs/{jid}"
    return None


def _normalize_bananalab_job_url(url: str, base_url: str) -> str:
    """Job URL иногда приходит без префикса /api (legacy hosts + Moonez)."""
    if "/api/api/" in url:
        return url.replace("/api/api/", "/api/", 1)
    for host in (
        "api.moonez.ai",
        "moonez.ai",
        "bananahub.app",
        "www.bananahub.app",
        "bananahub.io",
        "www.bananahub.io",
    ):
        legacy = f"https://{host}/v1/jobs/"
        fixed = f"https://{host}/api/v1/jobs/"
        if url.startswith(legacy):
            return url.replace(legacy, fixed, 1)
    # Старые absolute job URL на BananaHub → Moonez
    for old_host in ("bananahub.app", "www.bananahub.app", "bananahub.io", "www.bananahub.io"):
        old_prefix = f"https://{old_host}/api/v1/jobs/"
        if url.startswith(old_prefix):
            return "https://api.moonez.ai/api/v1/jobs/" + url[len(old_prefix) :]
    return url


_CLOUDFLARE_GATEWAY_MESSAGES = {
    "502": "Banana Lab временно недоступен (502): ошибка шлюза. Попробуйте через несколько минут.",
    "503": "Banana Lab временно недоступен (503): сервис перегружен. Попробуйте позже.",
    "521": "Banana Lab временно недоступен (521): сервер провайдера не отвечает. Попробуйте через несколько минут.",
    "522": "Banana Lab временно недоступен (522): не удалось подключиться к серверу провайдера.",
    "523": "Banana Lab временно недоступен (523): сервер провайдера недостижим.",
    "524": "Banana Lab временно недоступен (524): провайдер не ответил вовремя.",
}

_MAX_USER_ERROR_LEN = 500

BANANALAB_PROJECT_PAUSED_MESSAGE = (
    "Проект Moonez на паузе. Генерация временно недоступна — "
    "дождитесь возобновления или проверьте панель https://moonez.ai"
)

BANANALAB_PROVIDER_UNAVAILABLE_MESSAGE = (
    "Moonez API недоступен: сервер провайдера не отвечает. "
    "Это проблема на стороне Moonez, не вашего аккаунта. "
    "Документация: https://docs.moonez.ai/"
)

BANANALAB_UPSTREAM_NO_IMAGE_RETRY_MESSAGE = (
    "Moonez не получил изображение от Google (временный сбой). "
    "Повторяем автоматически — тот же запрос, без изменений."
)

BANANALAB_UPSTREAM_NO_IMAGE_EXHAUSTED_MESSAGE = (
    "Google Gemini не вернул изображение после нескольких попыток с тем же запросом. "
    "Это ограничение модели (иногда срабатывает на фото знаменитостей или нестабильный upstream), "
    "а не ошибка вашего сайта. Попробуйте запустить генерацию ещё раз позже или измените формулировку вручную."
)


def upstream_no_image_retry_delay_seconds(retry_count: int, base_delay: float = 3.0) -> float:
    """Экспоненциальная пауза: 3s, 5s, 8s, 12s, 15s (cap)."""
    attempt = max(0, int(retry_count))
    return min(float(base_delay) + attempt * 2.0, 15.0)

_UNAVAILABLE_MARKERS = (
    "connection refused",
    "failed to establish a new connection",
    "failed to connect",
    "could not connect",
    "couldn't connect",
    "name or service not known",
    "failed to resolve",
    "name resolution",
    "nodename nor servname",
    "getaddrinfo failed",
    "max retries exceeded",
    "connectionerror",
    "newconnectionerror",
    "connection aborted",
    "connection reset",
    "bananahub api недоступен",
    "moonez api недоступен",
    "errno 111",
    "errno -2",
    "errno -3",
)


def is_bananalab_unavailable_message(text: Any) -> bool:
    lower = str(text or "").lower()
    return any(marker in lower for marker in _UNAVAILABLE_MARKERS)


def is_bananalab_paused_message(text: Any) -> bool:
    lower = str(text or "").lower()
    return (
        "project is paused" in lower
        or "model is paused" in lower
        or "проект banana lab на паузе" in lower
        or ("project or nanobanana" in lower and "try again later" in lower)
    )


def is_bananalab_upstream_no_image_message(text: Any) -> bool:
    """BananaHub иногда возвращает failed job без картинки — обычно лечится повтором."""
    lower = str(text or "").lower()
    return (
        "upstream returned no image" in lower
        or "исходный поток не вернул изображение" in lower
        or "upstream did not return an image" in lower
    )


def _looks_like_html(text: str) -> bool:
    lower = text.lower()
    return any(
        marker in lower
        for marker in ("<!doctype html", "<html", "cf-error-details", "<body", "cloudflare")
    )


def _extract_cloudflare_error_code(text: str) -> Optional[str]:
    lower = text.lower()
    match = re.search(r"error code (\d{3})", lower)
    if match:
        return match.group(1)
    for code in _CLOUDFLARE_GATEWAY_MESSAGES:
        if f" {code}" in lower or f"({code}" in lower or f"|{code}" in lower:
            return code
    return None


CONTENT_POLICY_MARKERS = (
    "safety",
    "moderation",
    "content policy",
    "content filter",
    "blocked",
    "reject",
    "nsfw",
    "responsible ai",
    "policy violation",
    "inappropriate",
    "harmful content",
    "prohibited",
    "not allowed",
    "cannot generate",
    "can't generate",
    "unable to generate",
    "couldn't process",
    "refused to",
    "violat",
    "sensitive content",
    "rai filter",
    "image_generation_user_error",
    "no image was generated",
    "security policy",
    "access denied",
)

CONTENT_POLICY_USER_MESSAGE = (
    "Запрос не прошёл фильтр безопасности. "
    "Переформулируйте описание мягче или попробуйте другой провайдер (bh_ / r8_ / sk-or_)."
)

OPENROUTER_ACCOUNT_GUARD_MESSAGE = (
    "OpenRouter заблокировал API-ключ (security policy на шлюзе OpenRouter). "
    "Это не фильтр вашего промпта — проверьте баланс, guardrails и статус ключа на openrouter.ai/keys "
    "или создайте новый sk-or_ ключ."
)

# Устаревший alias — оставлен для совместимости тестов/логов
OPENROUTER_SECURITY_MESSAGE = OPENROUTER_ACCOUNT_GUARD_MESSAGE

PROVIDER_POLICY_MESSAGES = {
    "bananalab": (
        "Google через Moonez не принял запрос (фильтр контента). "
        "Переформулируйте описание мягче или попробуйте r8_ / sk-or_."
    ),
    "openrouter": (
        "OpenRouter/OpenAI не сгенерировали изображение (фильтр контента модели). "
        "Переформулируйте описание или попробуйте bh_ / r8_."
    ),
    "replicate": (
        "Replicate/Google отклонили запрос (фильтр контента). "
        "Переформулируйте описание или попробуйте bh_ / sk-or_."
    ),
}


def is_openrouter_security_policy(message: str) -> bool:
    lower = (message or "").lower()
    return (
        "security policy" in lower
        or "access denied by security policy" in lower
        or "политика безопасности шлюза" in lower
        or lower.strip() == OPENROUTER_ACCOUNT_GUARD_MESSAGE.lower()
    )


def is_policy_block_error(message: str) -> bool:
    """Блокировка контент-фильтром (OpenRouter шлюз, Google, OpenAI и т.д.)."""
    if is_openrouter_security_policy(message):
        return True
    if is_content_policy_error(message):
        return True
    lower = (message or "").lower()
    return any(
        marker in lower
        for marker in (
            "фильтр контента",
            "контент-фильтр",
            "фильтр безопасности",
            "фильтр безопасности google",
            "не прошёл фильтр",
            "не прошел фильтр",
            "content filter",
            "content policy",
            "image_content_policy",
            "content_policy_violation",
            "policy violation",
            "responsible ai",
        )
    )


def is_content_policy_error(message: str) -> bool:
    lower = (message or "").lower()
    return any(marker in lower for marker in CONTENT_POLICY_MARKERS)


def humanize_api_error(
    message: Any,
    http_status: Optional[int] = None,
    provider: Optional[str] = None,
) -> str:
    """Короткое сообщение для UI вместо HTML-страниц Cloudflare и прочего шума."""
    if message is None:
        text = ""
    elif isinstance(message, dict):
        text = detail_from_response_body(message)
    else:
        text = str(message).strip()

    if not text:
        if http_status and str(http_status) in _CLOUDFLARE_GATEWAY_MESSAGES:
            return _CLOUDFLARE_GATEWAY_MESSAGES[str(http_status)]
        return "Неизвестная ошибка API"

    if _looks_like_html(text):
        cf_code = _extract_cloudflare_error_code(text)
        if cf_code and cf_code in _CLOUDFLARE_GATEWAY_MESSAGES:
            return _CLOUDFLARE_GATEWAY_MESSAGES[cf_code]
        title_match = re.search(r"<title>([^<]+)</title>", text, re.I)
        if title_match:
            title = title_match.group(1).strip()
            if "|" in title:
                title = title.split("|", 1)[1].strip()
            return f"Ошибка провайдера: {title}"
        if http_status and str(http_status) in _CLOUDFLARE_GATEWAY_MESSAGES:
            return _CLOUDFLARE_GATEWAY_MESSAGES[str(http_status)]
        return "Сервис Banana Lab вернул страницу ошибки вместо JSON. Попробуйте позже."

    if is_bananalab_paused_message(text):
        return BANANALAB_PROJECT_PAUSED_MESSAGE

    if is_bananalab_unavailable_message(text):
        return BANANALAB_PROVIDER_UNAVAILABLE_MESSAGE

    if is_bananalab_upstream_no_image_message(text):
        return BANANALAB_UPSTREAM_NO_IMAGE_RETRY_MESSAGE

    if is_openrouter_security_policy(text):
        if provider == "openrouter":
            return OPENROUTER_ACCOUNT_GUARD_MESSAGE
        if provider and provider in PROVIDER_POLICY_MESSAGES:
            return PROVIDER_POLICY_MESSAGES[provider]
        return CONTENT_POLICY_USER_MESSAGE

    if is_content_policy_error(text):
        policy_msg = PROVIDER_POLICY_MESSAGES.get(provider or "", CONTENT_POLICY_USER_MESSAGE)
        if provider and provider in PROVIDER_POLICY_MESSAGES:
            return policy_msg
        detail = text if len(text) < 180 else text[:180] + "…"
        return f"{CONTENT_POLICY_USER_MESSAGE} ({detail})"

    status_key = str(http_status) if http_status else None
    if status_key in _CLOUDFLARE_GATEWAY_MESSAGES and http_status and http_status >= 500:
        if len(text) < 120 and not _looks_like_html(text):
            return text
        return _CLOUDFLARE_GATEWAY_MESSAGES[status_key]

    if len(text) > _MAX_USER_ERROR_LEN:
        return text[:_MAX_USER_ERROR_LEN] + "…"
    return text


def detail_from_response_body(data: Any) -> str:
    if isinstance(data, dict):
        d = data.get("detail")
        if isinstance(d, dict):
            msg = d.get("message") or d.get("detail")
            if msg is not None:
                return humanize_api_error(str(msg))
            return humanize_api_error(json.dumps(d, ensure_ascii=False))
        if isinstance(d, str):
            return humanize_api_error(d)
        if isinstance(d, list):
            parts = []
            for item in d:
                if isinstance(item, dict):
                    loc = item.get("loc", [])
                    msg = item.get("msg", "")
                    parts.append(f"{loc}: {msg}" if loc else str(msg))
                else:
                    parts.append(str(item))
            return humanize_api_error("; ".join(parts) if parts else json.dumps(data))
        if d is not None:
            return humanize_api_error(str(d))
        if "message" in data:
            return humanize_api_error(str(data["message"]))
    return humanize_api_error(str(data) if data else "Неизвестная ошибка API")


def find_image_in_json(obj: Any, depth: int = 0) -> Tuple[Optional[bytes], Optional[str]]:
    if depth > 8:
        return None, None

    if isinstance(obj, str):
        s = obj.strip()
        if s.startswith("http://") or s.startswith("https://"):
            return None, s
        if len(s) > 80 and re.match(r"^[A-Za-z0-9+/=\s]+$", s[: min(500, len(s))]):
            try:
                raw = base64.b64decode(s, validate=False)
                if raw and len(raw) > 32:
                    try:
                        Image.open(io.BytesIO(raw)).verify()
                        return raw, None
                    except Exception:
                        pass
            except Exception:
                pass
        return None, None

    if isinstance(obj, dict):
        # Формат GET /v1/jobs/{id} при status=done: { "result": { "image_url": "https://..." } }
        res = obj.get("result")
        if isinstance(res, dict):
            for key in ("image_url", "url", "output_url", "result_url"):
                v = res.get(key)
                if isinstance(v, str) and (v.startswith("http://") or v.startswith("https://")):
                    return None, v
            for key in ("image_base64", "output_base64", "base64", "b64"):
                v = res.get(key)
                if isinstance(v, str):
                    b, u = find_image_in_json(v, depth + 1)
                    if b or u:
                        return b, u

        url_keys = ("image_url", "url", "output_url", "result_url")
        b64_keys = ("image_base64", "output_base64", "base64", "b64", "image", "result_base64")
        for k, v in obj.items():
            lk = k.lower()
            if lk in url_keys and isinstance(v, str) and v.startswith("http"):
                return None, v
            if lk in b64_keys and isinstance(v, str):
                b, u = find_image_in_json(v, depth + 1)
                if b or u:
                    return b, u
        for v in obj.values():
            b, u = find_image_in_json(v, depth + 1)
            if b or u:
                return b, u

    if isinstance(obj, list):
        for item in obj:
            b, u = find_image_in_json(item, depth + 1)
            if b or u:
                return b, u

    return None, None
