"""
Веб-интерфейс для Nano Banana Pro с поддержкой MinIO и PostgreSQL
Версия для Docker
"""
import streamlit as st
import replicate
import os
import requests
from PIL import Image
import io
from datetime import datetime
import json
import uuid

# Импорт модулей для работы с БД и хранилищем
try:
    from database import init_database, save_generation, get_generations
    from storage import upload_image, download_image
    DB_AVAILABLE = True
except ImportError:
    DB_AVAILABLE = False
    st.warning("⚠️ Модули database и storage не найдены. Работаем без сохранения данных.")

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
if 'session_id' not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())
if 'api_key_set' not in st.session_state:
    st.session_state.api_key_set = False

# Инициализация БД при первом запуске
if DB_AVAILABLE:
    if 'db_initialized' not in st.session_state:
        # Пробуем инициализировать БД с повторными попытками
        import time
        from config import POSTGRES_CONFIG
        
        # Отладка: показываем настройки подключения
        debug_info = f"Подключение к БД: host={POSTGRES_CONFIG['host']}, port={POSTGRES_CONFIG['port']}, db={POSTGRES_CONFIG['database']}"
        
        max_retries = 5
        for attempt in range(max_retries):
            try:
                if init_database():
                    st.session_state.db_initialized = True
                    st.success(f"✅ База данных подключена! {debug_info}")
                    break
                else:
                    if attempt < max_retries - 1:
                        time.sleep(2)  # Ждем 2 секунды перед следующей попыткой
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(2)
                else:
                    st.warning(f"⚠️ Не удалось подключиться к БД: {e}. {debug_info}. Приложение работает без сохранения истории.")

def generate_image(prompt, image_input, api_token, **kwargs):
    """Генерирует изображение через Replicate API"""
    try:
        client = replicate.Client(api_token=api_token)
        
        input_params = {
            "prompt": prompt,
            "image": image_input,
        }
        input_params.update(kwargs)
        
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

if DB_AVAILABLE:
    st.info("💾 Данные сохраняются в PostgreSQL и MinIO")

# Боковая панель
with st.sidebar:
    st.header("⚙️ Настройки")
    
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
    
    st.subheader("🎛️ Параметры генерации")
    with st.expander("🔧 Расширенные настройки", expanded=False):
        num_outputs = st.slider("Количество вариантов", 1, 4, 1)
        guidance_scale = st.slider("Guidance Scale", 1.0, 20.0, 7.5, 0.5)
        num_inference_steps = st.slider("Шаги генерации", 10, 100, 50, 5)
        seed = st.number_input("Seed", value=None, min_value=0)
    
    st.divider()
    
    if DB_AVAILABLE:
        st.subheader("💾 Хранилище")
        st.info("""
        **MinIO**: Изображения  
        **PostgreSQL**: История генераций
        """)

# Основная область
col1, col2 = st.columns([1, 1])

with col1:
    st.header("📤 Входные данные")
    
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
        )
        
        if uploaded_file is not None:
            image_display = Image.open(uploaded_file)
            st.image(image_display, caption="Референсное изображение", width='stretch')
            uploaded_file.seek(0)
            image_input = uploaded_file
    
    else:
        image_url = st.text_input(
            "URL изображения",
            placeholder="https://example.com/image.jpg",
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
    
    st.subheader("✍️ Текстовый промпт")
    prompt = st.text_area(
        "Опишите желаемое изображение",
        placeholder="Например: Преврати это изображение в картину маслом в стиле Ван Гога",
        height=100,
    )
    
    # Негативный промпт
    negative_prompt = st.text_area(
        "🚫 Негативный промпт (что исключить)",
        placeholder="Например: blurry, low quality, distorted, watermark, text",
        height=60,
        help="Опишите, чего НЕ должно быть на изображении"
    )

with col2:
    st.header("📥 Результат")
    
    if st.button("🎨 Сгенерировать изображение", type="primary", use_container_width=True):
        if not st.session_state.api_key_set:
            st.error("❌ Пожалуйста, введите API ключ")
        elif not image_input:
            st.error("❌ Пожалуйста, загрузите изображение")
        elif not prompt:
            st.error("❌ Пожалуйста, введите промпт")
        else:
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
            
            result = generate_image(
                prompt=prompt,
                image_input=image_input,
                api_token=api_key_input or os.getenv("REPLICATE_API_TOKEN"),
                **gen_params
            )
            
            if result:
                # Обработка результата
                results_list = result if isinstance(result, list) else [result]
                
                for idx, img_url in enumerate(results_list):
                    if idx > 0:
                        st.divider()
                    
                    st.subheader(f"Вариант {idx + 1}")
                    
                    try:
                        # Скачиваем изображение с Replicate
                        img_response = requests.get(img_url, timeout=30)
                        if img_response.status_code == 200:
                            img_data = img_response.content
                            result_img = Image.open(io.BytesIO(img_data))
                            st.image(result_img, width='stretch')
                            
                            # Сохраняем в MinIO (если доступно)
                            image_storage_info = None
                            if DB_AVAILABLE:
                                try:
                                    storage_result = upload_image(img_data)
                                    if storage_result:
                                        image_storage_info = storage_result
                                        st.success(f"💾 Изображение сохранено в MinIO")
                                except Exception as e:
                                    st.warning(f"⚠️ Не удалось сохранить в MinIO: {e}")
                            
                            # Сохраняем в БД (если доступно)
                            if DB_AVAILABLE:
                                try:
                                    save_generation(
                                        prompt=prompt,
                                        image_url=img_url,
                                        image_path=image_storage_info['path'] if image_storage_info else None,
                                        params=gen_params if gen_params else None,
                                        session_id=st.session_state.session_id,
                                        negative_prompt=negative_prompt.strip() if negative_prompt and negative_prompt.strip() else None
                                    )
                                except Exception as e:
                                    st.warning(f"⚠️ Не удалось сохранить в БД: {e}")
                            
                            # Кнопка скачивания
                            st.download_button(
                                label=f"💾 Скачать вариант {idx + 1}",
                                data=img_data,
                                file_name=f"nano_banana_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{idx+1}.png",
                                mime="image/png",
                                key=f"download_{idx}"
                            )
                    except Exception as e:
                        st.error(f"Ошибка при обработке изображения: {e}")
                        st.text(f"URL: {img_url}")
                
                st.success("✅ Изображение успешно сгенерировано!")
    
    # История из БД
    if DB_AVAILABLE:
        st.divider()
        st.subheader("📜 История генераций")
        
        try:
            history = get_generations(session_id=st.session_state.session_id, limit=10)
            
            if history:
                for gen in history:
                    with st.expander(f"🖼️ {gen['timestamp'].strftime('%Y-%m-%d %H:%M:%S')} - {gen['prompt'][:50]}..."):
                        # Показываем изображение
                        if gen['image_path']:
                            # Из MinIO
                            try:
                                img_data = download_image(gen['image_path'])
                                if img_data:
                                    st.image(Image.open(io.BytesIO(img_data)), width='stretch')
                            except:
                                if gen['image_url']:
                                    try:
                                        img_response = requests.get(gen['image_url'], timeout=5)
                                        if img_response.status_code == 200:
                                            st.image(Image.open(io.BytesIO(img_response.content)), width='stretch')
                                    except:
                                        st.text(f"URL: {gen['image_url']}")
                        elif gen['image_url']:
                            # Из Replicate
                            try:
                                img_response = requests.get(gen['image_url'], timeout=5)
                                if img_response.status_code == 200:
                                    st.image(Image.open(io.BytesIO(img_response.content)), width='stretch')
                            except:
                                st.text(f"URL: {gen['image_url']}")
                        
                        st.text(f"Промпт: {gen['prompt']}")
                        if gen['params']:
                            st.json(gen['params'])
            else:
                st.info("История пуста. Сгенерируйте первое изображение!")
        except Exception as e:
            st.warning(f"⚠️ Не удалось загрузить историю: {e}")

# Футер
st.divider()
st.markdown("""
<div style="text-align: center; color: #666; padding: 1rem;">
    <p>🍌 Nano Banana Pro UI | Powered by <a href="https://replicate.com">Replicate</a></p>
    <p>💾 MinIO + PostgreSQL | Docker Ready</p>
</div>
""", unsafe_allow_html=True)

