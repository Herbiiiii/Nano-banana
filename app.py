"""
Полнофункциональный веб-интерфейс для Nano Banana Pro
Запуск: streamlit run app.py
"""

import streamlit as st
import replicate
import os
import requests
from PIL import Image
import io
from datetime import datetime
import json

# Настройка страницы
st.set_page_config(
    page_title="Nano Banana Pro - Генератор изображений",
    page_icon="🍌",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Стили
st.markdown("""
<style>
    .main-header {
        font-size: 3rem;
        font-weight: bold;
        text-align: center;
        background: linear-gradient(90deg, #FFD700, #FFA500);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 1rem;
    }
    .stButton>button {
        width: 100%;
        background: linear-gradient(90deg, #FFD700, #FFA500);
        color: white;
        font-weight: bold;
        border-radius: 10px;
        padding: 0.5rem 1rem;
    }
    .stButton>button:hover {
        background: linear-gradient(90deg, #FFA500, #FF8C00);
    }
    
    /* Исправление дрожания экрана */
    .stApp {
        overflow-x: hidden;
    }
    [data-testid="stAppViewContainer"] {
        overflow-x: hidden;
    }
    /* Отключаем автоматические обновления, которые могут вызывать дрожание */
    .element-container {
        will-change: auto;
    }
    
    /* Мобильная оптимизация */
    @media (max-width: 768px) {
        .main-header {
            font-size: 2rem;
        }
        /* Улучшаем отображение слайдеров на мобильных */
        .stSlider {
            padding: 0.5rem 0;
        }
        /* Улучшаем боковую панель на мобильных */
        [data-testid="stSidebar"] {
            width: 100% !important;
        }
        /* Улучшаем колонки на мобильных */
        [data-testid="column"] {
            width: 100% !important;
        }
    }
    
    /* Улучшаем видимость параметров */
    .stSlider label {
        font-size: 0.9rem;
        font-weight: 500;
    }
</style>
""", unsafe_allow_html=True)

# Инициализация сессии
if 'generated_images' not in st.session_state:
    st.session_state.generated_images = []
if 'api_key_set' not in st.session_state:
    st.session_state.api_key_set = False
if 'active_generations' not in st.session_state:
    st.session_state.active_generations = 0  # Количество активных генераций
if 'max_concurrent_generations' not in st.session_state:
    st.session_state.max_concurrent_generations = 3  # Максимум одновременных генераций

def download_image(url, filename):
    """Скачивает изображение по URL"""
    try:
        response = requests.get(url)
        if response.status_code == 200:
            return response.content
    except Exception as e:
        st.error(f"Ошибка при скачивании: {e}")
    return None

def generate_image(prompt, image_input=None, images_list=None, api_token=None, **kwargs):
    """Генерирует изображение через Replicate API
    
    Args:
        prompt: Текстовый промпт
        image_input: Одно референсное изображение (для обратной совместимости)
        images_list: Список референсных изображений (до 4)
        api_token: API ключ Replicate
        **kwargs: Дополнительные параметры
    """
    try:
        client = replicate.Client(api_token=api_token)
        
        # Подготовка параметров
        input_params = {
            "prompt": prompt,
        }
        
        # Поддержка множественных изображений (до 4)
        # Для nano-banana-pro можно передать несколько изображений через параметр image (список)
        if images_list and len(images_list) > 0:
            # Если одно изображение
            if len(images_list) == 1:
                input_params["image"] = images_list[0]
            else:
                # Для нескольких изображений передаем список (модель поддерживает до 4)
                input_params["image"] = images_list[:4]  # Ограничиваем до 4
        elif image_input:
            input_params["image"] = image_input
        # Если изображение не передано (text-to-image режим), не добавляем параметр image
        # Некоторые версии модели могут работать без изображения
        
        # Добавляем дополнительные параметры
        input_params.update(kwargs)
        
        # Запуск генерации
        with st.spinner("🎨 Генерирую изображение... Это может занять некоторое время"):
            output = client.run(
                "google/nano-banana-pro",
                input=input_params
            )
        
        return output
    except Exception as e:
        st.error(f"Ошибка генерации: {str(e)}")
        return None

# Заголовок
st.markdown('<h1 class="main-header">🍌 Nano Banana Pro</h1>', unsafe_allow_html=True)
st.markdown('<p style="text-align: center; font-size: 1.2rem; color: #666;">Генерация изображений по референсу с помощью ИИ</p>', unsafe_allow_html=True)

# Боковая панель - настройки
with st.sidebar:
    st.header("⚙️ Настройки")
    
    # API ключ
    st.subheader("🔑 API Ключ")
    
    # Проверяем, есть ли ключ в сессии (пользователь ввел его ранее в этой сессии)
    if 'user_api_key' not in st.session_state:
        st.session_state.user_api_key = ""
    
    api_key_input = st.text_input(
        "Replicate API Token",
        type="password",
        help="Получите ключ на https://replicate.com/account/api-tokens",
        value=st.session_state.user_api_key,
        key="api_key_input"
    )
    
    # Сохраняем ключ в сессии (только для текущего пользователя)
    if api_key_input:
        st.session_state.user_api_key = api_key_input
        st.session_state.api_key_set = True
        st.success("✅ API ключ установлен")
    elif os.getenv("REPLICATE_API_TOKEN"):
        # Fallback: если ключ установлен в Secrets Space (для администратора)
        st.session_state.api_key_set = True
        st.info("ℹ️ Используется системный ключ (если установлен)")
    else:
        st.session_state.api_key_set = False
        st.warning("⚠️ Введите API ключ для продолжения")
    
    st.divider()
    
    # Дополнительные параметры
    st.subheader("🎛️ Параметры генерации")
    
    # Параметры всегда видны (не в expander) для лучшей мобильной поддержки
    num_outputs = st.slider("Количество вариантов", 1, 4, 1, help="Сколько вариантов изображения сгенерировать")
    guidance_scale = st.slider("Guidance Scale", 1.0, 20.0, 7.5, 0.5, help="Влияние промпта на результат (выше = сильнее)")
    num_inference_steps = st.slider("Шаги генерации", 10, 100, 50, 5, help="Количество шагов обработки (больше = качественнее, но дольше)")
    
    # Seed в отдельном expander, так как он реже используется
    with st.expander("🔧 Дополнительные настройки", expanded=False):
        seed = st.number_input("Seed (для воспроизводимости)", value=None, min_value=0, help="Фиксированное значение для воспроизводимости результатов")
    
    # Показываем статус активных генераций
    if st.session_state.active_generations > 0:
        st.info(f"🔄 Активных генераций: {st.session_state.active_generations}/{st.session_state.max_concurrent_generations}")
    else:
        st.success(f"✅ Можно запустить до {st.session_state.max_concurrent_generations} генераций одновременно")
    
    st.divider()
    
    # Информация
    st.subheader("ℹ️ Информация")
    st.info("""
    **Режимы работы:**
    - 🖼️ **С референсом**: до 4 референсных изображений
    - ✨ **Text-to-Image**: генерация только по промпту
    
    **Как использовать:**
    1. Введите API ключ Replicate
    2. Выберите режим генерации
    3. Загрузите изображения (если режим с референсом)
    4. Введите текстовый промпт
    5. Нажмите "Сгенерировать"
    
    **Поддерживаемые форматы:**
    - JPG, PNG, WebP
    - Максимальный размер: 10MB на файл
    """)

# Основная область
col1, col2 = st.columns([1, 1])

with col1:
    st.header("📤 Входные данные")
    
    # Режим работы: с референсом или text-to-image
    generation_mode = st.radio(
        "Режим генерации",
        ["🖼️ С референсным изображением", "✨ Text-to-Image (без референса)"],
        horizontal=True,
        help="Выберите режим: с референсом или только по текстовому промпту"
    )
    
    images_list = []
    image_displays = []
    
    if generation_mode == "🖼️ С референсным изображением":
        # Количество референсных изображений (до 4)
        num_reference_images = st.slider(
            "Количество референсных изображений", 
            1, 4, 1,
            help="Можно загрузить до 4 референсных изображений"
        )
        
        # Загрузка изображений
        upload_method = st.radio(
            "Способ загрузки",
            ["📁 Загрузить файлы", "🔗 URL изображений"],
            horizontal=True
        )
        
        if upload_method == "📁 Загрузить файлы":
            uploaded_files = st.file_uploader(
                f"Выберите референсные изображения (до {num_reference_images})",
                type=["jpg", "jpeg", "png", "webp"],
                accept_multiple_files=True,
                help=f"Можно загрузить до {num_reference_images} изображений"
            )
            
            if uploaded_files:
                # Ограничиваем количество загруженных файлов
                uploaded_files = uploaded_files[:num_reference_images]
                
                for idx, uploaded_file in enumerate(uploaded_files):
                    image_display = Image.open(uploaded_file)
                    image_displays.append(image_display)
                    st.image(image_display, caption=f"Референсное изображение {idx + 1}", width='stretch')
                    uploaded_file.seek(0)  # Сброс указателя файла
                    images_list.append(uploaded_file)
        
        else:  # URL
            for i in range(num_reference_images):
                image_url = st.text_input(
                    f"URL изображения {i + 1}",
                    placeholder="https://example.com/image.jpg",
                    help="Вставьте прямую ссылку на изображение",
                    key=f"image_url_{i}"
                )
                
                if image_url:
                    try:
                        response = requests.get(image_url, timeout=10)
                        if response.status_code == 200:
                            image_display = Image.open(io.BytesIO(response.content))
                            image_displays.append(image_display)
                            st.image(image_display, caption=f"Референсное изображение {i + 1}", width='stretch')
                            images_list.append(image_url)
                        else:
                            st.error(f"Не удалось загрузить изображение {i + 1} по URL")
                    except Exception as e:
                        st.error(f"Ошибка при загрузке изображения {i + 1}: {e}")
    
    else:  # Text-to-Image режим
        st.info("✨ Режим Text-to-Image: генерация только по текстовому промпту без референсного изображения")
    
    # Текстовый промпт
    st.subheader("✍️ Текстовый промпт")
    prompt = st.text_area(
        "Опишите желаемое изображение",
        placeholder="Например: Преврати это изображение в картину маслом в стиле Ван Гога",
        height=100,
        help="Опишите, как вы хотите изменить или дополнить изображение"
    )
    
    # Негативный промпт
    negative_prompt = st.text_area(
        "🚫 Негативный промпт (что исключить)",
        placeholder="Например: blurry, low quality, distorted, watermark, text",
        height=60,
        help="Опишите, чего НЕ должно быть на изображении"
    )
    
    # Примеры промптов
    with st.expander("💡 Примеры промптов"):
        example_prompts = [
            "Создай вариацию в стиле импрессионизма",
            "Преврати в цифровое искусство с неоновыми эффектами",
            "Добавь фантастический фон с космосом",
            "Сделай в стиле аниме",
            "Преврати в картину маслом",
            "Создай версию в стиле поп-арт"
        ]
        for example in example_prompts:
            if st.button(example, key=f"example_{example}", width='stretch'):
                prompt = example
                st.rerun()

with col2:
    st.header("📥 Результат")
    
    # Кнопка генерации
    if st.button("🎨 Сгенерировать изображение", type="primary", width='stretch'):
        if not st.session_state.api_key_set:
            st.error("❌ Пожалуйста, введите API ключ в боковой панели")
        elif generation_mode == "🖼️ С референсным изображением" and len(images_list) == 0:
            st.error("❌ Пожалуйста, загрузите или укажите URL референсного изображения")
        elif not prompt:
            st.error("❌ Пожалуйста, введите текстовый промпт")
        elif st.session_state.active_generations >= st.session_state.max_concurrent_generations:
            st.warning(f"⏳ Достигнут лимит одновременных генераций ({st.session_state.max_concurrent_generations}). Дождитесь завершения текущих генераций.")
        else:
            # Параметры для генерации
            gen_params = {}
            if num_outputs > 1:
                gen_params["num_outputs"] = num_outputs
            if guidance_scale != 7.5:
                gen_params["guidance_scale"] = guidance_scale
            if num_inference_steps != 50:
                gen_params["num_inference_steps"] = num_inference_steps
            if seed is not None:
                gen_params["seed"] = int(seed)
            # Добавляем негативный промпт, если указан
            if negative_prompt and negative_prompt.strip():
                gen_params["negative_prompt"] = negative_prompt.strip()
            
            # Увеличиваем счетчик активных генераций
            st.session_state.active_generations += 1
            
            # Генерация
            # Используем ключ из сессии пользователя или системный (если установлен)
            user_token = st.session_state.get('user_api_key', '') or os.getenv("REPLICATE_API_TOKEN", "")
            
            try:
                # Для text-to-image не передаем изображения
                if generation_mode == "✨ Text-to-Image (без референса)":
                    result = generate_image(
                        prompt=prompt,
                        image_input=None,
                        images_list=None,
                        api_token=user_token,
                        **gen_params
                    )
                else:
                    # Для режима с референсом передаем список изображений
                    result = generate_image(
                        prompt=prompt,
                        image_input=None,
                        images_list=images_list if images_list else None,
                        api_token=user_token,
                        **gen_params
                    )
            finally:
                # Уменьшаем счетчик после завершения (успешного или с ошибкой)
                st.session_state.active_generations = max(0, st.session_state.active_generations - 1)
            
            if result:
                # Сохранение в историю
                result_data = {
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "prompt": prompt,
                    "result": result,
                    "params": gen_params
                }
                st.session_state.generated_images.append(result_data)
                
                # Отображение результата
                if isinstance(result, list):
                    for idx, img_url in enumerate(result):
                        st.subheader(f"Вариант {idx + 1}")
                        try:
                            img_response = requests.get(img_url)
                            if img_response.status_code == 200:
                                result_img = Image.open(io.BytesIO(img_response.content))
                                st.image(result_img, width='stretch')
                                
                                # Кнопка скачивания
                                st.download_button(
                                    label=f"💾 Скачать вариант {idx + 1}",
                                    data=img_response.content,
                                    file_name=f"nano_banana_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{idx+1}.png",
                                    mime="image/png",
                                    key=f"download_{idx}"
                                )
                        except Exception as e:
                            st.error(f"Ошибка при загрузке изображения: {e}")
                            st.text(f"URL: {img_url}")
                else:
                    # Один результат
                    try:
                        img_response = requests.get(result)
                        if img_response.status_code == 200:
                            result_img = Image.open(io.BytesIO(img_response.content))
                            st.image(result_img, width='stretch')
                            
                            # Кнопка скачивания
                            st.download_button(
                                label="💾 Скачать изображение",
                                data=img_response.content,
                                file_name=f"nano_banana_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png",
                                mime="image/png"
                            )
                    except Exception as e:
                        st.error(f"Ошибка при загрузке изображения: {e}")
                        st.text(f"URL: {result}")
                
                st.success("✅ Изображение успешно сгенерировано!")
    
    # История генераций
    if st.session_state.generated_images:
        st.divider()
        st.subheader("📜 История генераций")
        
        for idx, gen_data in enumerate(reversed(st.session_state.generated_images[-5:])):  # Последние 5
            with st.expander(f"🖼️ {gen_data['timestamp']} - {gen_data['prompt'][:50]}..."):
                if isinstance(gen_data['result'], list):
                    for img_idx, img_url in enumerate(gen_data['result']):
                        try:
                            img_response = requests.get(img_url, timeout=5)
                            if img_response.status_code == 200:
                                st.image(Image.open(io.BytesIO(img_response.content)), width='stretch')
                        except:
                            st.text(f"URL: {img_url}")
                else:
                    try:
                        img_response = requests.get(gen_data['result'], timeout=5)
                        if img_response.status_code == 200:
                            st.image(Image.open(io.BytesIO(img_response.content)), width='stretch')
                    except:
                        st.text(f"URL: {gen_data['result']}")
                
                st.text(f"Промпт: {gen_data['prompt']}")
                if gen_data['params']:
                    st.json(gen_data['params'])

# Футер
st.divider()
st.markdown("""
<div style="text-align: center; color: #666; padding: 1rem;">
    <p>🍌 Nano Banana Pro UI | Powered by <a href="https://replicate.com">Replicate</a></p>
    <p>Создано для локального использования с вашим API ключом</p>
</div>
""", unsafe_allow_html=True)

