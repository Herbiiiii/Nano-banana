"""
Общая подготовка промпта для генерации изображений (Replicate и Banana Lab).
"""
import logging
import re
from typing import Any, List, Optional

logger = logging.getLogger(__name__)


def enhance_prompt_for_image_generation(
    prompt: str,
    reference_images: Optional[List[Any]],
    num_refs_effective: int,
) -> str:
    """
    Та же логика улучшения промпта, что раньше была в ReplicateService:
    text-to-image и image-to-image с референсами.
    """
    if not reference_images or len(reference_images) == 0:
        prompt_lower = prompt.lower().strip()

        image_generation_keywords = [
            "generate",
            "создать",
            "сделать",
            "сгенерируй",
            "сгенерировать",
            "изображение",
            "image",
            "картинка",
            "picture",
            "фото",
            "photo",
            "draw",
            "рисовать",
            "нарисовать",
            "нарисуй",
            "create",
            "создай",
            "создавать",
            "design",
            "дизайн",
            "спроектировать",
            "icon",
            "иконка",
            "favicon",
            "фавикон",
            "logo",
            "логотип",
            "лого",
        ]

        has_generation_keyword = any(keyword in prompt_lower for keyword in image_generation_keywords)
        starts_with_generation = any(
            prompt_lower.startswith(keyword)
            for keyword in ["generate", "создать", "сделать", "сгенерируй", "create", "draw", "нарисуй"]
        )

        if not has_generation_keyword or not starts_with_generation:
            if not prompt_lower.startswith(
                ("generate", "create", "draw", "make", "создать", "сделать", "нарисовать")
            ):
                enhanced = f"Generate an image of {prompt}"
                logger.info("[PROMPT] Улучшен для text-to-image: %s...", enhanced[:100])
                return enhanced
            if "image" not in prompt_lower and "изображение" not in prompt_lower and "картинка" not in prompt_lower:
                enhanced = f"{prompt}, high quality image"
                logger.info("[PROMPT] Уточнение для text-to-image: %s...", enhanced[:100])
                return enhanced
            return prompt
        return prompt

    prompt_lower = prompt.lower()
    enhanced_prompt = prompt

    ref_patterns = [
        (r"реф\s*(\d+)", r"reference image \1"),
        (r"референс\s*(\d+)", r"reference image \1"),
        (r"референса\s*(\d+)", r"reference image \1"),
        (r"референсом\s*(\d+)", r"reference image \1"),
        (r"ref\s*(\d+)", r"reference image \1"),
    ]

    for pattern, replacement in ref_patterns:
        enhanced_prompt = re.sub(pattern, replacement, enhanced_prompt, flags=re.IGNORECASE)

    num_refs = max(num_refs_effective, 0)
    if num_refs > 1:
        ref_instructions = (
            f"IMPORTANT: You have {num_refs} reference images. "
            f"When the prompt mentions 'reference image 1' or 'ref 1', use the FIRST reference image. "
            f"When it mentions 'reference image 2' or 'ref 2', use the SECOND reference image. "
            f"And so on for reference images 3 and 4. "
            f"Follow the prompt instructions carefully for which reference to use for which element. "
        )
        enhanced_prompt = ref_instructions + enhanced_prompt
    else:
        if not any(
            phrase in prompt_lower
            for phrase in ["based on", "using the reference", "preserve", "reference image"]
        ):
            enhanced_prompt = (
                f"STRICT INSTRUCTIONS: Use the reference image as the EXACT base. "
                f"Preserve EVERYTHING: exact same person, identical facial features, same age, "
                f"same gender, same body type, same pose, same clothing, same background. "
                f"ONLY modify according to: {enhanced_prompt}."
            )

    logger.info("[PROMPT] Улучшен для %s референсных изображений", num_refs)
    return enhanced_prompt
