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
</style>
""", unsafe_allow_html=True)

# Инициализация сессии
if 'generated_images' not in st.session_state:
    st.session_state.generated_images = []
if 'api_key_set' not in st.session_state:
    st.session_state.api_key_set = False

def download_image(url, filename):
    """Скачивает изображение по URL"""
    try:
        response = requests.get(url)
        if response.status_code == 200:
            return response.content
    except Exception as e:
        st.error(f"Ошибка при скачивании: {e}")
    return None

def generate_image(prompt, image_input, api_token, **kwargs):
    """Генерирует изображение через Replicate API"""
    try:
        client = replicate.Client(api_token=api_token)
        
        # Подготовка параметров
        input_params = {
            "prompt": prompt,
            "image": image_input,
        }
        
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
    api_key_input = st.text_input(
        "Replicate API Token",
        type="password",
        help="Получите ключ на https://replicate.com/account/api-tokens",
        value=os.getenv("REPLICATE_API_TOKEN", "")
    )
    
    if api_key_input:
        os.environ["REPLICATE_API_TOKEN"] = api_key_input
        st.session_state.api_key_set = True
        st.success("✅ API ключ установлен")
    elif os.getenv("REPLICATE_API_TOKEN"):
        st.session_state.api_key_set = True
        st.info("✅ Используется ключ из переменной окружения")
    else:
        st.session_state.api_key_set = False
        st.warning("⚠️ Введите API ключ для продолжения")
    
    st.divider()
    
    # Дополнительные параметры
    st.subheader("🎛️ Параметры генерации")
    
    # Расширенные настройки (если доступны в модели)
    with st.expander("🔧 Расширенные настройки", expanded=False):
        num_outputs = st.slider("Количество вариантов", 1, 4, 1)
        guidance_scale = st.slider("Guidance Scale", 1.0, 20.0, 7.5, 0.5)
        num_inference_steps = st.slider("Шаги генерации", 10, 100, 50, 5)
        seed = st.number_input("Seed (для воспроизводимости)", value=None, min_value=0)
    
    st.divider()
    
    # Информация
    st.subheader("ℹ️ Информация")
    st.info("""
    **Как использовать:**
    1. Введите API ключ Replicate
    2. Загрузите референсное изображение
    3. Введите текстовый промпт
    4. Нажмите "Сгенерировать"
    
    **Поддерживаемые форматы:**
    - JPG, PNG, WebP
    - Максимальный размер: 10MB
    """)

# Основная область
col1, col2 = st.columns([1, 1])

with col1:
    st.header("📤 Входные данные")
    
    # Загрузка изображения
    upload_method = st.radio(
        "Способ загрузки изображения",
        ["📁 Загрузить файл", "🔗 URL изображения"],
        horizontal=True
    )
    
    image_input = None
    image_display = None
    
    if upload_method == "📁 Загрузить файл":
        uploaded_file = st.file_uploader(
            "Выберите референсное изображение",
            type=["jpg", "jpeg", "png", "webp"],
            help="Загрузите изображение, которое будет использовано как референс"
        )
        
        if uploaded_file is not None:
            image_display = Image.open(uploaded_file)
            st.image(image_display, caption="Референсное изображение", width='stretch')
            uploaded_file.seek(0)  # Сброс указателя файла
            image_input = uploaded_file
    
    else:  # URL
        image_url = st.text_input(
            "URL изображения",
            placeholder="https://example.com/image.jpg",
            help="Вставьте прямую ссылку на изображение"
        )
        
        if image_url:
            try:
                response = requests.get(image_url, timeout=10)
                if response.status_code == 200:
                    image_display = Image.open(io.BytesIO(response.content))
                    st.image(image_display, caption="Референсное изображение", width='stretch')
                    image_input = image_url
                else:
                    st.error("Не удалось загрузить изображение по URL")
            except Exception as e:
                st.error(f"Ошибка при загрузке изображения: {e}")
    
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
        elif not image_input:
            st.error("❌ Пожалуйста, загрузите или укажите URL изображения")
        elif not prompt:
            st.error("❌ Пожалуйста, введите текстовый промпт")
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
            
            # Генерация
            result = generate_image(
                prompt=prompt,
                image_input=image_input,
                api_token=api_key_input or os.getenv("REPLICATE_API_TOKEN"),
                **gen_params
            )
            
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

