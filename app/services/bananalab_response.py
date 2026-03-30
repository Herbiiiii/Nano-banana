"""Разбор тел ответов Banana Lab API (без зависимости от replicate/settings)."""
import base64
import io
import json
import re
from typing import Any, Dict, Optional, Tuple

from PIL import Image


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
            return su
        return f"{base}{su if su.startswith('/') else '/' + su}"
    jid = data.get("job_id")
    if jid:
        return f"{base}/v1/jobs/{jid}"
    return None


def detail_from_response_body(data: Any) -> str:
    if isinstance(data, dict):
        d = data.get("detail")
        if isinstance(d, str):
            return d
        if isinstance(d, list):
            parts = []
            for item in d:
                if isinstance(item, dict):
                    loc = item.get("loc", [])
                    msg = item.get("msg", "")
                    parts.append(f"{loc}: {msg}" if loc else str(msg))
                else:
                    parts.append(str(item))
            return "; ".join(parts) if parts else json.dumps(data)
        if d is not None:
            return str(d)
        if "message" in data:
            return str(data["message"])
    return str(data) if data else "Неизвестная ошибка API"


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
