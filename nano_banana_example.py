"""
Пример использования Google Nano Banana Pro через Replicate API
для генерации изображений по референсу
"""

import replicate
import os
from pathlib import Path

# Установите ваш API ключ Replicate
# Способ 1: Через переменную окружения (рекомендуется)
# export REPLICATE_API_TOKEN=your_token_here

# Способ 2: Напрямую в коде (не рекомендуется для продакшена)
# os.environ["REPLICATE_API_TOKEN"] = "your_token_here"


def generate_image_from_reference(
    prompt: str,
    image_url: str = None,
    image_path: str = None,
    **kwargs
):
    """
    Генерирует изображение по референсу используя nano-banana-pro
    
    Args:
        prompt: Текстовое описание желаемого изображения
        image_url: URL референсного изображения (если есть)
        image_path: Путь к локальному файлу референсного изображения
        **kwargs: Дополнительные параметры модели
    
    Returns:
        URL сгенерированного изображения
    """
    
    # Инициализация клиента Replicate
    client = replicate.Client(api_token=os.getenv("REPLICATE_API_TOKEN"))
    
    # Если указан локальный путь, загружаем файл
    if image_path:
        with open(image_path, "rb") as image_file:
            image_input = image_file
    elif image_url:
        image_input = image_url
    else:
        raise ValueError("Необходимо указать либо image_url, либо image_path")
    
    # Параметры для модели nano-banana-pro
    input_params = {
        "prompt": prompt,
        "image": image_input,
        # Дополнительные параметры (если доступны в модели)
        # "num_outputs": 1,
        # "guidance_scale": 7.5,
        # "num_inference_steps": 50,
    }
    
    # Добавляем дополнительные параметры из kwargs
    input_params.update(kwargs)
    
    # Запуск генерации
    print(f"Генерация изображения с промптом: {prompt}")
    output = client.run(
        "google/nano-banana-pro",
        input=input_params
    )
    
    return output


def main():
    """
    Пример использования функции генерации
    """
    
    # Проверка наличия API ключа
    if not os.getenv("REPLICATE_API_TOKEN"):
        print("ОШИБКА: Не установлен REPLICATE_API_TOKEN")
        print("Установите его через переменную окружения:")
        print("  export REPLICATE_API_TOKEN=your_token_here")
        print("Или в PowerShell:")
        print("  $env:REPLICATE_API_TOKEN='your_token_here'")
        return
    
    # Пример 1: Генерация по URL референса
    print("\n=== Пример 1: Генерация по URL референса ===")
    try:
        result = generate_image_from_reference(
            prompt="Создай вариацию этого изображения в стиле импрессионизма",
            image_url="https://example.com/reference-image.jpg"
        )
        print(f"Результат: {result}")
    except Exception as e:
        print(f"Ошибка: {e}")
    
    # Пример 2: Генерация по локальному файлу
    print("\n=== Пример 2: Генерация по локальному файлу ===")
    try:
        # Укажите путь к вашему референсному изображению
        reference_image = "path/to/your/reference.jpg"
        
        if Path(reference_image).exists():
            result = generate_image_from_reference(
                prompt="Преврати это изображение в картину маслом",
                image_path=reference_image
            )
            print(f"Результат: {result}")
        else:
            print(f"Файл {reference_image} не найден")
    except Exception as e:
        print(f"Ошибка: {e}")


if __name__ == "__main__":
    main()

