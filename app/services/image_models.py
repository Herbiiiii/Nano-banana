"""
Реестр моделей генерации и привязка к провайдерам API-ключей.
"""
from __future__ import annotations

from typing import Dict, List, Literal, Optional

ImageApiProvider = Literal["replicate", "bananalab", "openrouter"]

ProviderColor = Literal["bananalab", "replicate", "openrouter", "mixed"]

MODEL_REGISTRY: Dict[str, dict] = {
    "nano-banana-2": {
        "display_name": "Nano Banana 2",
        "description": "Новая модель: качество Pro и скорость Flash",
        "providers": ["bananalab", "replicate"],
        "provider_priority": ["bananalab", "replicate"],
        "color": "mixed",
        "params_profile": "nano",
        "replicate_slug": "google/nano-banana-2",
    },
    "nano-banana": {
        "display_name": "Nano Banana",
        "description": "Google image editing model in Gemini 2.5",
        "providers": ["bananalab", "replicate"],
        "provider_priority": ["bananalab", "replicate"],
        "color": "mixed",
        "params_profile": "nano",
        "replicate_slug": "google/nano-banana",
    },
    "nano-banana-pro": {
        "display_name": "Nano Banana Pro",
        "description": "State of the art image generation and editing (Pro)",
        "providers": ["bananalab", "replicate"],
        "provider_priority": ["bananalab", "replicate"],
        "color": "mixed",
        "params_profile": "nano",
        "replicate_slug": "google/nano-banana-pro",
    },
    "gemini-2.5-flash-image": {
        "display_name": "Gemini 2.5 Flash Image",
        "description": "Google image generation in Gemini 2.5",
        "providers": ["replicate"],
        "provider_priority": ["replicate"],
        "color": "replicate",
        "params_profile": "imagen",
        "replicate_slug": "google/gemini-2.5-flash-image",
    },
    "imagen-4": {
        "display_name": "Imagen 4",
        "description": "Google Imagen 4 flagship image generation",
        "providers": ["replicate"],
        "provider_priority": ["replicate"],
        "color": "replicate",
        "params_profile": "imagen",
        "replicate_slug": "google/imagen-4",
    },
    "imagen-4-fast": {
        "display_name": "Imagen 4 Fast",
        "description": "Imagen 4 — быстрая генерация",
        "providers": ["replicate"],
        "provider_priority": ["replicate"],
        "color": "replicate",
        "params_profile": "imagen",
        "replicate_slug": "google/imagen-4-fast",
    },
    "imagen-4-ultra": {
        "display_name": "Imagen 4 Ultra",
        "description": "Imagen 4 — максимальное качество",
        "providers": ["replicate"],
        "provider_priority": ["replicate"],
        "color": "replicate",
        "params_profile": "imagen",
        "replicate_slug": "google/imagen-4-ultra",
    },
    "gpt-5-image": {
        "display_name": "GPT-5 Image",
        "description": "OpenAI GPT-5 Image через OpenRouter",
        "providers": ["openrouter"],
        "provider_priority": ["openrouter"],
        "color": "openrouter",
        "params_profile": "gpt_openrouter",
        "openrouter_slug": "openai/gpt-5-image",
    },
    "gpt-5-image-mini": {
        "display_name": "GPT-5 Image Mini",
        "description": "OpenAI GPT-5 Image Mini через OpenRouter",
        "providers": ["openrouter"],
        "provider_priority": ["openrouter"],
        "color": "openrouter",
        "params_profile": "gpt_openrouter",
        "openrouter_slug": "openai/gpt-5-image-mini",
    },
}

DEFAULT_MODEL_ID = "nano-banana-pro"

PROVIDER_LABELS = {
    "bananalab": "BananaHub",
    "replicate": "Replicate",
    "openrouter": "OpenRouter",
}

PROVIDER_GROUP_LABELS = {
    "bananalab": "BananaHub (nb_)",
    "replicate": "Replicate (r8_)",
    "openrouter": "OpenRouter GPT (sk-or_)",
    "mixed": "Nano Banana (nb_ или r8_)",
}


def get_model_entry(model_id: Optional[str]) -> Optional[dict]:
    if not model_id:
        return None
    return MODEL_REGISTRY.get(model_id.strip().lower())


def list_model_ids() -> List[str]:
    return list(MODEL_REGISTRY.keys())


def get_model_providers(model_id: Optional[str]) -> List[ImageApiProvider]:
    entry = get_model_entry(model_id)
    if not entry:
        return ["replicate"]
    return list(entry.get("provider_priority") or entry.get("providers") or ["replicate"])


def get_provider_for_model(model_id: Optional[str], keys: Dict[str, str]) -> Optional[ImageApiProvider]:
    for provider in get_model_providers(model_id):
        if keys.get(provider):
            return provider
    return None


def select_api_key_for_model(
    model_id: Optional[str],
    keys: Dict[str, str],
    api_key_from_request: Optional[str] = None,
) -> str:
    if api_key_from_request and str(api_key_from_request).strip():
        return str(api_key_from_request).strip()

    provider = get_provider_for_model(model_id, keys)
    if provider:
        return keys[provider]

    raise ValueError(
        "API ключи не найдены. Сохраните ключ BananaHub (nb_), Replicate (r8_) "
        "и/или OpenRouter (sk-or_) в настройках."
    )


def provider_label(provider: ImageApiProvider) -> str:
    return PROVIDER_LABELS.get(provider, provider)


def model_display_name(model_id: Optional[str]) -> str:
    entry = get_model_entry(model_id)
    if entry:
        return str(entry.get("display_name") or model_id)
    return model_id or DEFAULT_MODEL_ID


def openrouter_slug(model_id: Optional[str]) -> Optional[str]:
    entry = get_model_entry(model_id)
    if not entry:
        return None
    return entry.get("openrouter_slug")


def replicate_slug(model_id: Optional[str]) -> Optional[str]:
    entry = get_model_entry(model_id)
    if not entry:
        return model_id
    return entry.get("replicate_slug") or model_id


def is_bananalab_frontend_model(model_id: Optional[str]) -> bool:
    entry = get_model_entry(model_id)
    if not entry:
        return False
    return "bananalab" in (entry.get("providers") or [])
