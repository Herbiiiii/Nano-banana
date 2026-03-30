"""
Определение провайдера генерации по API-ключу пользователя.
"""
from typing import Literal

ImageApiProvider = Literal["replicate", "bananalab"]


def infer_image_api_provider(api_key: str) -> ImageApiProvider:
    """Banana Lab выдаёт ключи с префиксом nb_, Replicate — обычно r8_."""
    k = (api_key or "").strip()
    if k.startswith("nb_"):
        return "bananalab"
    return "replicate"
