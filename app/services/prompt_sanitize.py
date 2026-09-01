"""
Локальная очистка промпта от типичных триггеров фильтров (имена, бренды, NSFW).
Работает без внешнего API — до отправки в BananaHub / Replicate / OpenRouter.
"""
from __future__ import annotations

import re
from typing import List, Tuple

# (pattern, replacement) — порядок важен: более специфичные правила выше
_SANITIZE_RULES: List[Tuple[str, str]] = [
    # Реальные спортсмены / знаменитости
    (r"\b(?:lionel\s+)?messi\b", "a famous football player in Argentina-style kit"),
    (r"\b(?:cristiano\s+)?ronaldo\b", "a famous football player in Portugal-style kit"),
    (r"\bмесси\b", "известный футболист в полосатой форме"),
    (r"\bроналду\b", "известный футболист в яркой форме"),
    (r"\bкриштиан[уо]\s+роналду\b", "известный футболист в яркой форме"),
    (r"\bneymar\b", "a famous Brazilian football player"),
    (r"\bнеймар\b", "известный бразильский футболист"),
    (r"\belon\s+musk\b", "a tech entrepreneur in casual clothes"),
    (r"\bилон\s+маск\b", "технологический предприниматель"),
    (r"\bputin\b", "a middle-aged man in formal suit"),
    (r"\bпутin\b", "мужчина в деловом костюме"),
    (r"\bпутин\b", "мужчина в деловом костюме"),
    (r"\btrump\b", "a politician in a suit"),
    (r"\bтрамп\b", "политик в костюме"),
    # Персонажи / бренды
    (r"\bbatman\b", "a masked hero in a dark cape and tactical suit"),
    (r"\bб[еэ]т[мм]ен\w*", "герой в чёрном плаще и маске"),
    (r"\bбэтмэн\w*", "герой в чёрном плаще и маске"),
    (r"\bsuperman\b", "a heroic figure in blue and red costume with a cape"),
    (r"\bсупермен\b", "герой в синем и красном костюме с плащом"),
    (r"\bspider[\s-]?man\b", "a masked hero in red and blue suit"),
    (r"\bчеловек[\s-]?паук\b", "герой в красно-синем костюме"),
    (r"\bharry\s+potter\b", "a young wizard in round glasses and robe"),
    (r"\bгарри\s+поттер\b", "молодой волшебник в очках и мантии"),
    (r"\bpokemon\b", "a cute fantasy creature"),
    (r"\bпокемон\b", "милое фантастическое существо"),
    (r"\bdisney\b", "classic animation style"),
    (r"\bдисней\b", "классический анимационный стиль"),
    (r"\bmarvel\b", "comic book superhero style"),
    (r"\bмarvel\b", "стиль комиксов о супергероях"),
    (r"\bstar\s+wars\b", "sci-fi space adventure style"),
    (r"\bзв[её]здные\s+войны\b", "фантастический космический стиль"),
    # Грубые / провокационные формулировки
    (r"\bпинает\s+под\s+зад\b", "игривая комичная сцена на поле"),
    (r"\bkicks?\s+(?:him\s+)?in\s+the\s+butt\b", "playful comedic scene"),
    (r"\bnsfw\b", ""),
    (r"\bголый\b", "в одежде"),
    (r"\bголая\b", "в одежде"),
    (r"\bnude\b", "clothed"),
    (r"\bnaked\b", "clothed"),
]

_COMPILED_RULES: List[Tuple[re.Pattern[str], str]] = [
    (re.compile(pattern, re.IGNORECASE | re.UNICODE), replacement)
    for pattern, replacement in _SANITIZE_RULES
]


def sanitize_prompt(prompt: str) -> dict:
    """
    Заменяет известные триггер-слова на нейтральные описания.

    Returns:
        {
            "prompt": str,           # текст для генерации
            "original": str,
            "changed": bool,
            "replacements": list[str] # какие правила сработали (для лога/UI)
        }
    """
    original = (prompt or "").strip()
    if not original:
        return {
            "prompt": "",
            "original": "",
            "changed": False,
            "replacements": [],
        }

    text = original
    applied: List[str] = []
    for pattern, replacement in _COMPILED_RULES:
        new_text, count = pattern.subn(replacement, text)
        if count:
            applied.append(f"{pattern.pattern} → {replacement!r} ({count})")
            text = new_text

    text = re.sub(r"\s{2,}", " ", text).strip()
    text = re.sub(r"\s+([,.!?])", r"\1", text)

    return {
        "prompt": text or original,
        "original": original,
        "changed": text != original,
        "replacements": applied,
    }
