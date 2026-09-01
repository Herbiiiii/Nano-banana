"""
Определение провайдера генерации по API-ключу пользователя.
"""
from typing import Literal

ImageApiProvider = Literal["replicate", "bananalab", "openrouter"]


def infer_image_api_provider(api_key: str) -> ImageApiProvider:
    """BananaHub — nb_, OpenRouter — sk-or…, Replicate — обычно r8_."""
    k = (api_key or "").strip()
    if k.startswith("nb_"):
        return "bananalab"
    if k.startswith("sk-or"):
        return "openrouter"
    return "replicate"
