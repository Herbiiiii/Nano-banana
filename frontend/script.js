// Конфигурация
// Используем относительный путь для работы с любым доменом
const API_URL = '/api/v1';
let authToken = null;
let currentUser = null;
let referenceImages = []; // Массив объектов {file, dataUrl, id}
let aspectRatioAutoSelected = false; // Флаг для автоматического выбора Юзер1
let galleryUpdateInProgress = false; // Флаг для предотвращения параллельных обновлений галереи
let lastGalleryHash = null; // Хеш последнего состояния галереи для предотвращения ненужных обновлений

// Универсальные функции для работы с хранилищем (localStorage с fallback на sessionStorage)
// Используем localStorage для надежности на мобильных устройствах и в приватном режиме
function getStorage() {
    try {
        // Пробуем использовать localStorage (более надежно)
        if (typeof(Storage) !== "undefined" && localStorage) {
            // Проверяем доступность через тестовую запись
            const testKey = '__storage_test__';
            localStorage.setItem(testKey, 'test');
            localStorage.removeItem(testKey);
            return localStorage;
        }
    } catch (e) {
        console.warn('[STORAGE] localStorage недоступен, пробуем sessionStorage:', e);
    }
    
    try {
        // Fallback на sessionStorage
        if (typeof(Storage) !== "undefined" && sessionStorage) {
            const testKey = '__storage_test__';
            sessionStorage.setItem(testKey, 'test');
            sessionStorage.removeItem(testKey);
            return sessionStorage;
        }
    } catch (e) {
        console.error('[STORAGE] Ни localStorage, ни sessionStorage недоступны:', e);
        return null;
    }
    
    return null;
}

function getApiKey() {
    const storage = getStorage();
    if (!storage) return null;
    try {
        return storage.getItem('replicateApiKey');
    } catch (e) {
        console.error('[STORAGE] Ошибка чтения ключа:', e);
        return null;
    }
}

function setApiKey(key) {
    const storage = getStorage();
    if (!storage) {
        console.error('[STORAGE] Хранилище недоступно, ключ не может быть сохранен');
        return false;
    }
    try {
        if (key) {
            storage.setItem('replicateApiKey', key);
            console.log('[STORAGE] API ключ сохранен в', storage === localStorage ? 'localStorage' : 'sessionStorage');
        } else {
            storage.removeItem('replicateApiKey');
            console.log('[STORAGE] API ключ удален');
        }
        return true;
    } catch (e) {
        console.error('[STORAGE] Ошибка сохранения ключа:', e);
        return false;
    }
}

function removeApiKey() {
    return setApiKey(null);
}

// Обработка файла референса (используется и для загрузки, и для paste)
function processReferenceFile(file) {
    if (!file.type.startsWith('image/')) {
        console.error(`[REFERENCE] Файл не является изображением: ${file.name}`);
        return;
    }
    
    const reader = new FileReader();
    reader.onload = (event) => {
        // Определяем соотношение сторон изображения
        const img = new Image();
        img.onload = () => {
            const aspectRatio = calculateAspectRatio(img.width, img.height);
            const refObj = {
                file: file,
                dataUrl: event.target.result,
                id: Date.now() + Math.random(),
                aspectRatio: aspectRatio,
                width: img.width,
                height: img.height,
                originalRatio: `${img.width}:${img.height}` // Сохраняем оригинальное соотношение
            };
            // Добавляем в начало массива (новые сверху)
            referenceImages.unshift(refObj);
            console.log(`[REFERENCE] Загружен референс ${referenceImages.length}: ${img.width}x${img.height} → ${aspectRatio}`);
            updateReferencePreview();
            updateAspectRatioOptions();
            showToast(`Референс ${referenceImages.length} добавлен`, 'success');
        };
        img.onerror = () => {
            console.error(`[REFERENCE] Ошибка загрузки изображения: ${file.name}`);
            showToast(`Ошибка загрузки изображения: ${file.name}`, 'error');
        };
        img.src = event.target.result;
    };
    reader.onerror = () => {
        console.error(`[REFERENCE] Ошибка чтения файла: ${file.name}`);
        showToast(`Ошибка чтения файла: ${file.name}`, 'error');
    };
    reader.readAsDataURL(file);
}

// Обновление превью референсных изображений
function updateReferencePreview() {
    const dropZone = document.getElementById('referenceDropZone');
    const dropZoneContent = dropZone ? dropZone.querySelector('.reference-drop-zone-content') : null;
    
    if (!dropZone || !dropZoneContent) return;
    
    // Очищаем содержимое зоны
    dropZoneContent.innerHTML = '';
    
    // Если есть референсы, показываем их внутри зоны
    if (referenceImages.length > 0) {
        // Создаем контейнер для референсов
        const refsContainer = document.createElement('div');
        refsContainer.className = 'd-flex flex-wrap gap-2 justify-content-center align-items-center';
        refsContainer.style.minHeight = '120px';
        
        // Отображаем референсы в порядке массива (первые элементы слева)
        referenceImages.forEach((ref, index) => {
        const container = document.createElement('div');
        container.className = 'position-relative d-inline-block me-2 mb-2 reference-item';
        container.style.width = '100px';
        container.draggable = true;
        container.dataset.index = index;
        container.style.cursor = 'move';
        
        // Drag and Drop обработчики
        container.addEventListener('dragstart', (e) => {
            e.dataTransfer.effectAllowed = 'move';
            e.dataTransfer.setData('text/html', container.outerHTML);
            e.dataTransfer.setData('text/plain', index.toString());
            container.classList.add('dragging');
            e.dataTransfer.setDragImage(container, 50, 50);
        });
        
        container.addEventListener('dragend', (e) => {
            container.classList.remove('dragging');
            // Убираем все классы drag-over
            document.querySelectorAll('.reference-item').forEach(item => {
                item.classList.remove('drag-over');
            });
        });
        
        container.addEventListener('dragover', (e) => {
            e.preventDefault();
            e.dataTransfer.dropEffect = 'move';
            const afterElement = getDragAfterElement(refsContainer, e.clientX);
            const dragging = document.querySelector('.dragging');
            if (afterElement == null) {
                refsContainer.appendChild(dragging);
            } else {
                refsContainer.insertBefore(dragging, afterElement);
            }
        });
        
        container.addEventListener('dragenter', (e) => {
            e.preventDefault();
            if (!container.classList.contains('dragging')) {
                container.classList.add('drag-over');
            }
        });
        
        container.addEventListener('dragleave', (e) => {
            container.classList.remove('drag-over');
        });
        
        container.addEventListener('drop', (e) => {
            e.preventDefault();
            container.classList.remove('drag-over');
            
            const draggedIndex = parseInt(e.dataTransfer.getData('text/plain'));
            const targetIndex = parseInt(container.dataset.index);
            
            if (draggedIndex !== targetIndex && draggedIndex >= 0 && targetIndex >= 0) {
                // Перемещаем элемент в массиве
                const draggedItem = referenceImages[draggedIndex];
                referenceImages.splice(draggedIndex, 1);
                referenceImages.splice(targetIndex, 0, draggedItem);
                
                console.log(`[REFERENCE] Референс ${draggedIndex + 1} перемещен на позицию ${targetIndex + 1}`);
                
                // Обновляем превью с правильной нумерацией (полная перерисовка)
                // Это обновит все индексы и метки "Реф1", "Реф2" и т.д.
                updateReferencePreview();
                updateAspectRatioOptions();
            }
        });
        
        const img = document.createElement('img');
        img.src = ref.dataUrl;
        img.className = 'img-thumbnail';
        img.style.width = '100px';
        img.style.height = '100px';
        img.style.objectFit = 'cover';
        img.draggable = false; // Отключаем drag для изображения
        img.style.pointerEvents = 'none'; // Отключаем события мыши для изображения
        img.style.userSelect = 'none'; // Отключаем выделение
        
        // Метка "Реф" сверху
        const label = document.createElement('div');
        label.className = 'position-absolute top-0 start-0 px-1';
        label.style.fontSize = '10px';
        label.style.borderRadius = '0 0 4px 0';
        label.style.background = 'linear-gradient(135deg, rgba(74, 85, 104, 0.7) 0%, rgba(74, 85, 104, 0.5) 100%)';
        label.style.color = '#ffffff';
        label.style.border = '1px solid rgba(102, 126, 234, 0.6)';
        label.style.fontWeight = '700';
        label.style.zIndex = '6';
        label.textContent = `Реф${index + 1}`;
        label.setAttribute('data-ref-index', index);
        
        // Кнопка скачивания референса (в правом верхнем углу, стиль как "завершено")
        const downloadBtn = document.createElement('button');
        downloadBtn.type = 'button'; // ВАЖНО: предотвращаем submit формы
        downloadBtn.className = 'position-absolute top-0 end-0 btn btn-sm p-0';
        downloadBtn.style.width = '24px';
        downloadBtn.style.height = '24px';
        downloadBtn.style.fontSize = '11px';
        downloadBtn.style.lineHeight = '1';
        downloadBtn.style.zIndex = '6';
        downloadBtn.style.background = 'linear-gradient(135deg, rgba(74, 85, 104, 0.7) 0%, rgba(72, 187, 120, 0.5) 100%)';
        downloadBtn.style.border = '1px solid rgba(72, 187, 120, 0.6)';
        downloadBtn.style.color = '#ffffff';
        downloadBtn.style.borderRadius = '4px';
        downloadBtn.style.cursor = 'pointer';
        downloadBtn.style.display = 'flex';
        downloadBtn.style.alignItems = 'center';
        downloadBtn.style.justifyContent = 'center';
        downloadBtn.innerHTML = '<i class="fas fa-download"></i>';
        downloadBtn.title = 'Скачать референс';
        downloadBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            e.stopImmediatePropagation();
            console.log('[REFERENCE] Скачивание референса', index + 1);
            downloadReferenceImage(ref.dataUrl, `reference_${index + 1}`);
        }, true); // Используем capture phase для приоритета
        
        // Кнопка удаления (по центру, стиль как "ошибка")
        const removeBtn = document.createElement('button');
        removeBtn.type = 'button'; // ВАЖНО: предотвращаем submit формы
        removeBtn.className = 'position-absolute top-1/2 start-1/2 btn btn-sm p-0';
        removeBtn.style.transform = 'translate(-50%, -50%)';
        removeBtn.style.width = '24px';
        removeBtn.style.height = '24px';
        removeBtn.style.fontSize = '12px';
        removeBtn.style.lineHeight = '1';
        removeBtn.style.zIndex = '6';
        removeBtn.style.background = 'linear-gradient(135deg, rgba(74, 85, 104, 0.7) 0%, rgba(229, 62, 62, 0.5) 100%)';
        removeBtn.style.border = '1px solid rgba(229, 62, 62, 0.6)';
        removeBtn.style.color = '#ffffff';
        removeBtn.style.borderRadius = '4px';
        removeBtn.style.cursor = 'pointer';
        removeBtn.style.display = 'flex';
        removeBtn.style.alignItems = 'center';
        removeBtn.style.justifyContent = 'center';
        removeBtn.style.fontWeight = '700';
        removeBtn.innerHTML = '×';
        removeBtn.title = 'Удалить референс';
        removeBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            e.stopImmediatePropagation();
            referenceImages = referenceImages.filter(r => r.id !== ref.id);
            // Если удалили все референсы, сбрасываем флаг
            if (referenceImages.length === 0) {
                aspectRatioAutoSelected = false;
            }
            updateReferencePreview();
            updateAspectRatioOptions();
        }, true); // Используем capture phase для приоритета
        
            container.appendChild(img);
            container.appendChild(label);
            container.appendChild(downloadBtn);
            container.appendChild(removeBtn);
            // Добавляем в контейнер референсов
            refsContainer.appendChild(container);
        });
        
        // Добавляем контейнер с референсами в зону
        dropZoneContent.appendChild(refsContainer);
        
        // Если не достигнут лимит, добавляем кнопки для добавления еще
        if (referenceImages.length < 4) {
            const addMoreContainer = document.createElement('div');
            addMoreContainer.className = 'mt-3';
            addMoreContainer.innerHTML = `
                <p class="text-muted small mb-2">Добавить еще (${4 - referenceImages.length} свободно)</p>
                <div class="d-flex gap-2 justify-content-center">
                    <button type="button" class="btn btn-warning btn-sm" id="selectReferenceFilesBtn">
                        <i class="fas fa-folder-open me-2"></i>Выбрать файл
                    </button>
                    <button type="button" class="btn btn-outline-light btn-sm" id="pasteFromClipboardBtn">
                        <i class="fas fa-paste me-2"></i>Вставить из буфера
                    </button>
                </div>
                <p class="text-muted small mt-2 mb-0">Нажмите Ctrl+V (или Cmd+V на Mac)</p>
            `;
            dropZoneContent.appendChild(addMoreContainer);
            
            // Перепривязываем обработчики кнопок
            const selectBtn = addMoreContainer.querySelector('#selectReferenceFilesBtn');
            const pasteBtn = addMoreContainer.querySelector('#pasteFromClipboardBtn');
            const referenceImagesInput = document.getElementById('referenceImages');
            
            if (selectBtn && referenceImagesInput) {
                selectBtn.addEventListener('click', () => {
                    referenceImagesInput.click();
                });
            }
            
            if (pasteBtn) {
                pasteBtn.addEventListener('click', async () => {
                    await handlePasteFromClipboard();
                });
            }
        }
    } else {
        // Если референсов нет, показываем стандартный интерфейс загрузки
        dropZoneContent.innerHTML = `
            <i class="fas fa-images mb-3" style="font-size: 3rem; color: rgba(102, 126, 234, 0.7);"></i>
            <p class="text-light mb-2 fw-bold">Перетащите изображение сюда</p>
            <p class="text-muted small mb-3">или нажмите на кнопку</p>
            <div class="d-flex gap-2 justify-content-center">
                <button type="button" class="btn btn-warning" id="selectReferenceFilesBtn">
                    <i class="fas fa-folder-open me-2"></i>Выбрать файл
                </button>
                <button type="button" class="btn btn-outline-light" id="pasteFromClipboardBtn">
                    <i class="fas fa-paste me-2"></i>Вставить из буфера
                </button>
            </div>
            <p class="text-muted small mt-2 mb-0">Нажмите Ctrl+V (или Cmd+V на Mac)</p>
        `;
        
        // Перепривязываем обработчики кнопок
        const selectBtn = dropZoneContent.querySelector('#selectReferenceFilesBtn');
        const pasteBtn = dropZoneContent.querySelector('#pasteFromClipboardBtn');
        const referenceImagesInput = document.getElementById('referenceImages');
        
        if (selectBtn && referenceImagesInput) {
            selectBtn.addEventListener('click', () => {
                referenceImagesInput.click();
            });
        }
        
        if (pasteBtn) {
            pasteBtn.addEventListener('click', async () => {
                await handlePasteFromClipboard();
            });
        }
    }
    
    // НЕ скрываем зону даже при достижении лимита - показываем все референсы
    dropZone.style.display = 'block';
    
    // Обработчики для drop-зоны (если перетащили между референсами)
    const refsContainer = dropZoneContent.querySelector('.d-flex.flex-wrap');
    if (refsContainer) {
        refsContainer.addEventListener('dragover', (e) => {
            e.preventDefault();
            e.dataTransfer.dropEffect = 'move';
        });
        
        refsContainer.addEventListener('drop', (e) => {
            e.preventDefault();
            const draggedIndex = parseInt(e.dataTransfer.getData('text/plain'));
            if (draggedIndex >= 0 && draggedIndex < referenceImages.length) {
                const afterElement = getDragAfterElement(refsContainer, e.clientX);
                const dragging = document.querySelector('.dragging');
                if (dragging) {
                    if (afterElement == null) {
                        refsContainer.appendChild(dragging);
                    } else {
                        refsContainer.insertBefore(dragging, afterElement);
                    }
                    
                    // Обновляем порядок в массиве
                    const newIndex = Array.from(refsContainer.children).indexOf(dragging);
                    if (newIndex !== draggedIndex && newIndex >= 0) {
                        const draggedItem = referenceImages[draggedIndex];
                        referenceImages.splice(draggedIndex, 1);
                        referenceImages.splice(newIndex, 0, draggedItem);
                        console.log(`[REFERENCE] Референс ${draggedIndex + 1} перемещен на позицию ${newIndex + 1}`);
                        updateReferencePreview();
                        updateAspectRatioOptions();
                    }
                }
            }
        });
    }
}

// Функция для определения позиции при drag and drop
function getDragAfterElement(container, x) {
    const draggableElements = [...container.querySelectorAll('.reference-item:not(.dragging)')];
    
    return draggableElements.reduce((closest, child) => {
        const box = child.getBoundingClientRect();
        const offset = x - box.left - box.width / 2;
        
        if (offset < 0 && offset > closest.offset) {
            return { offset: offset, element: child };
        } else {
            return closest;
        }
    }, { offset: Number.NEGATIVE_INFINITY }).element;
}

// Обновление опций соотношений при изменении референсов
function updateAspectRatioOptions() {
    const referenceGroup = document.getElementById('referenceAspectGroup');
    const select = document.getElementById('aspectRatio');
    
    if (referenceImages.length > 0) {
        referenceGroup.style.display = 'block';
        
        // Обновляем подсказки с реальными соотношениями для всех референсов
        referenceImages.forEach((ref, index) => {
            const option = select.querySelector(`option[value="user${index + 1}"]`);
            const dropdownItem = document.querySelector(`.custom-dropdown-item[data-value="user${index + 1}"]`);
            const textElement = document.getElementById(`user${index + 1}Text`);
            
            if (ref.aspectRatio) {
                const prefix = index === 0 ? '' : '└─ ';
                const text = `${prefix}Юзер${index + 1} (из реф${index + 1})`;
                
                if (option) option.textContent = text;
                if (textElement) textElement.textContent = text;
            } else {
                const prefix = index === 0 ? '' : '└─ ';
                const text = `${prefix}Юзер${index + 1} (из реф${index + 1})`;
                if (option) option.textContent = text;
                if (textElement) textElement.textContent = text;
            }
            
            // Показываем/скрываем опции в зависимости от количества референсов
            if (index === 0) {
                // Юзер1 всегда видим, если есть хотя бы один референс
                if (option) option.style.display = '';
                if (dropdownItem) dropdownItem.style.display = 'flex';
            } else {
                // Юзер2-4 показываем только если есть соответствующие референсы
                const shouldShow = referenceImages.length > index;
                if (option) option.style.display = shouldShow ? '' : 'none';
                if (dropdownItem) dropdownItem.style.display = shouldShow ? 'flex' : 'none';
            }
        });
        
        // Устанавливаем Юзер1 по умолчанию при первой загрузке референса
        if (!aspectRatioAutoSelected && referenceImages.length > 0) {
            const currentValue = select.value;
            // Автоматически выбираем Юзер1 только если выбрано стандартное соотношение
            const standardRatios = ['1:1', '16:9', '9:16', '4:3', '3:4', '21:9', '5:4', '2:3'];
            if (standardRatios.includes(currentValue)) {
                selectAspectRatio('user1');
                aspectRatioAutoSelected = true;
                console.log('[ASPECT] Автоматически выбран Юзер1 по умолчанию');
            }
        }
    } else {
        referenceGroup.style.display = 'none';
        // Сбрасываем на стандартное если был выбран юзер
        if (select.value.startsWith('user')) {
            selectAspectRatio('1:1');
        }
    }
}

// Функция для выбора соотношения в кастомном dropdown
function selectAspectRatio(value) {
    const select = document.getElementById('aspectRatio');
    const selectedDiv = document.getElementById('aspectRatioSelected');
    const textSpan = document.getElementById('aspectRatioText');
    const iconSpan = document.getElementById('aspectRatioIcon');
    const menu = document.getElementById('aspectRatioMenu');
    
    // Обновляем скрытый select
    select.value = value;
    
    // Находим выбранный элемент в dropdown
    const selectedItem = document.querySelector(`.custom-dropdown-item[data-value="${value}"]`);
    if (selectedItem) {
        const icon = selectedItem.querySelector('.custom-dropdown-item-icon');
        const text = selectedItem.querySelector('span:last-child');
        
        // Обновляем отображаемый текст
        if (textSpan) {
            textSpan.textContent = text ? text.textContent : value;
        }
        
        // Обновляем иконку
        if (iconSpan && icon) {
            iconSpan.innerHTML = '';
            const iconImg = icon.cloneNode(true);
            iconSpan.appendChild(iconImg);
        }
    }
    
    // Убираем выделение со всех элементов
    document.querySelectorAll('.custom-dropdown-item').forEach(item => {
        item.classList.remove('selected');
    });
    
    // Выделяем выбранный элемент
    if (selectedItem) {
        selectedItem.classList.add('selected');
    }
    
    // Закрываем меню
    if (menu) {
        menu.classList.remove('show');
    }
    if (selectedDiv) {
        selectedDiv.classList.remove('active');
    }
    
    // Триггерим событие change для совместимости
    select.dispatchEvent(new Event('change'));
}

// Вычисление соотношения сторон из размеров
function calculateAspectRatio(width, height) {
    // Находим НОД для упрощения
    const gcd = (a, b) => b === 0 ? a : gcd(b, a % b);
    const divisor = gcd(width, height);
    const ratio = `${width / divisor}:${height / divisor}`;
    
    // Конвертируем в ближайшее стандартное соотношение для Nano Banana Pro
    return normalizeAspectRatio(ratio, width, height);
}

// Конвертация любого соотношения в ближайшее стандартное для Nano Banana Pro
function normalizeAspectRatio(ratio, width, height) {
    // Стандартные соотношения Nano Banana Pro
    const standardRatios = {
        '1:1': { w: 1, h: 1 },
        '16:9': { w: 16, h: 9 },
        '9:16': { w: 9, h: 16 },
        '4:3': { w: 4, h: 3 },
        '3:4': { w: 3, h: 4 },
        '21:9': { w: 21, h: 9 },
        '5:4': { w: 5, h: 4 },
        '2:3': { w: 2, h: 3 }
    };
    
    // Вычисляем текущее соотношение как число
    const currentRatio = width / height;
    
    // Находим ближайшее стандартное соотношение
    let closestRatio = '1:1';
    let minDiff = Infinity;
    
    for (const [ratioStr, ratioObj] of Object.entries(standardRatios)) {
        const standardRatio = ratioObj.w / ratioObj.h;
        const diff = Math.abs(currentRatio - standardRatio);
        
        if (diff < minDiff) {
            minDiff = diff;
            closestRatio = ratioStr;
        }
    }
    
    console.log(`[ASPECT] Определено соотношение: ${ratio} (${width}x${height}) → ${closestRatio}`);
    return closestRatio;
}

// Элементы DOM
const generateForm = document.getElementById('generateForm');
const loginForm = document.getElementById('loginForm');
const registerForm = document.getElementById('registerForm');
const apiKeyForm = document.getElementById('apiKeyForm');
const notificationToast = new bootstrap.Toast(document.getElementById('notificationToast'));

// Инициализация
document.addEventListener('DOMContentLoaded', () => {
    initTheme();
    checkAuth();
    // Галерея загружается в checkAuth после проверки токена
    setupEventListeners();
    setupAspectRatioVisuals();
    setupCustomDropdown();
    
    // Обновление галереи каждые 5 секунд (только если есть активные генерации)
    setInterval(async () => {
        if (authToken) {
            try {
                const response = await fetch(`${API_URL}/images/list?limit=50`, {
                    headers: {
                        'Authorization': `Bearer ${authToken}`
                    }
                });
                if (response.ok) {
                    const data = await response.json();
                    // Поддерживаем как старый формат (массив), так и новый (объект с метаданными)
                    const generations = Array.isArray(data) ? data : (data.generations || []);
                    const activeCount = generations.filter(g => g.status === 'pending' || g.status === 'running').length;
                    // Обновляем только если есть активные генерации
                    if (activeCount > 0) {
                        await loadGallery();
                    }
                }
            } catch (error) {
                // Игнорируем ошибки при автообновлении
            }
        }
    }, 5000);
});

// Настройка визуальных индикаторов соотношений сторон
function setupAspectRatioVisuals() {
    // Эта функция больше не нужна, используем кастомный dropdown
}

// Инициализация кастомного dropdown для соотношений сторон
function setupCustomDropdown() {
    const selectedDiv = document.getElementById('aspectRatioSelected');
    const menu = document.getElementById('aspectRatioMenu');
    const select = document.getElementById('aspectRatio');
    
    if (!selectedDiv || !menu || !select) return;
    
    // Обработчик клика на выбранный элемент
    selectedDiv.addEventListener('click', (e) => {
        e.stopPropagation();
        const isActive = selectedDiv.classList.contains('active');
        
        // Закрываем все другие dropdown
        document.querySelectorAll('.custom-dropdown-selected').forEach(el => {
            if (el !== selectedDiv) {
                el.classList.remove('active');
            }
        });
        document.querySelectorAll('.custom-dropdown-menu').forEach(el => {
            if (el !== menu) {
                el.classList.remove('show');
            }
        });
        
        // Переключаем текущий dropdown
        selectedDiv.classList.toggle('active');
        menu.classList.toggle('show');
    });
    
    // Обработчик клика на элементы меню
    menu.querySelectorAll('.custom-dropdown-item').forEach(item => {
        item.addEventListener('click', (e) => {
            e.stopPropagation();
            const value = item.getAttribute('data-value');
            selectAspectRatio(value);
        });
    });
    
    // Закрытие при клике вне dropdown
    document.addEventListener('click', (e) => {
        if (!selectedDiv.contains(e.target) && !menu.contains(e.target)) {
            selectedDiv.classList.remove('active');
            menu.classList.remove('show');
        }
    });
    
    // Инициализация начального значения
    selectAspectRatio(select.value || '1:1');
    
    // Синхронизация при изменении скрытого select (только если значение действительно изменилось)
    let lastValue = select.value;
    select.addEventListener('change', () => {
        if (select.value !== lastValue) {
            lastValue = select.value;
            selectAspectRatio(select.value, true); // skipEvent = true чтобы избежать рекурсии
        }
    });
}

// Функция для выбора соотношения в кастомном dropdown
function selectAspectRatio(value) {
    const select = document.getElementById('aspectRatio');
    const selectedDiv = document.getElementById('aspectRatioSelected');
    const textSpan = document.getElementById('aspectRatioText');
    const iconSpan = document.getElementById('aspectRatioIcon');
    const menu = document.getElementById('aspectRatioMenu');
    
    // Обновляем скрытый select
    select.value = value;
    
    // Находим выбранный элемент в dropdown
    const selectedItem = document.querySelector(`.custom-dropdown-item[data-value="${value}"]`);
    if (selectedItem) {
        const icon = selectedItem.querySelector('.custom-dropdown-item-icon');
        const text = selectedItem.querySelector('span:last-child');
        
        // Обновляем отображаемый текст
        if (textSpan) {
            textSpan.textContent = text ? text.textContent : value;
        }
        
        // Обновляем иконку
        if (iconSpan && icon) {
            iconSpan.innerHTML = '';
            const iconImg = icon.cloneNode(true);
            iconSpan.appendChild(iconImg);
        }
    }
    
    // Убираем выделение со всех элементов
    document.querySelectorAll('.custom-dropdown-item').forEach(item => {
        item.classList.remove('selected');
    });
    
    // Выделяем выбранный элемент
    if (selectedItem) {
        selectedItem.classList.add('selected');
    }
    
    // Закрываем меню
    if (menu) {
        menu.classList.remove('show');
    }
    if (selectedDiv) {
        selectedDiv.classList.remove('active');
    }
    
    // Триггерим событие change для совместимости
    select.dispatchEvent(new Event('change'));
}

// Проверка аутентификации
function checkAuth() {
    authToken = localStorage.getItem('authToken');
    if (authToken) {
        // Загружаем информацию о пользователе, которая затем загрузит галерею
        loadUserInfo();
    } else {
        showLoginButton();
        // Показываем сообщение о необходимости входа
        const grid = document.getElementById('imageGrid');
        if (grid) {
            grid.innerHTML = '<div class="col-12"><div class="alert alert-info">Войдите в систему для просмотра ваших генераций</div></div>';
        }
    }
}

// Загрузка информации о пользователе
async function loadUserInfo() {
    try {
        const response = await fetch(`${API_URL}/auth/me`, {
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });
        if (response.ok) {
            currentUser = await response.json();
            console.log('[AUTH] Пользователь загружен:', currentUser.username);
            showUserMenu();
            checkApiKeyStatus();
            // Загружаем галерею после успешной загрузки пользователя
            console.log('[AUTH] Загружаем галерею после успешной аутентификации...');
            await loadGallery();
        } else {
            console.error('[AUTH] Ошибка загрузки пользователя, статус:', response.status);
            localStorage.removeItem('authToken');
            authToken = null;
            showLoginButton();
            const grid = document.getElementById('imageGrid');
            if (grid) {
                grid.innerHTML = '<div class="col-12"><div class="alert alert-warning">Ошибка аутентификации. Войдите снова.</div></div>';
            }
        }
    } catch (error) {
        console.error('Ошибка загрузки пользователя:', error);
    }
}

// Проверка статуса API ключа
async function checkApiKeyStatus() {
    // ВАЖНО: Ключи НЕ сохраняются на сервере, проверяем только локально
    const apiKey = getApiKey();
    const statusDiv = document.getElementById('apiKeyStatus');
    const storage = getStorage();
    const storageType = storage === localStorage ? 'localStorage' : (storage === sessionStorage ? 'sessionStorage' : 'недоступно');
    
    if (statusDiv) {
        if (apiKey) {
            statusDiv.innerHTML = `<span class="text-success"><i class="fas fa-check-circle me-1"></i>API ключ сохранен локально (${storageType}, не на сервере)</span>`;
        } else {
            if (!storage) {
                statusDiv.innerHTML = '<span class="text-warning"><i class="fas fa-exclamation-triangle me-1"></i>Хранилище недоступно. Ключ не может быть сохранен. Проверьте настройки браузера.</span>';
            } else {
                statusDiv.innerHTML = '<span class="text-muted"><i class="fas fa-info-circle me-1"></i>API ключ не сохранен. Ключи не хранятся на сервере для вашей безопасности.</span>';
            }
        }
    }
}

// Настройка обработчиков событий
function setupEventListeners() {
    // Переключение режима генерации
    document.querySelectorAll('input[name="generationMode"]').forEach(radio => {
        radio.addEventListener('change', (e) => {
            const referenceSection = document.getElementById('referenceImagesSection');
            if (e.target.value === 'image-to-image') {
                referenceSection.style.display = 'block';
            } else {
                referenceSection.style.display = 'none';
                referenceImages = [];
                aspectRatioAutoSelected = false; // Сбрасываем флаг при очистке референсов
                updateReferencePreview();
                updateAspectRatioOptions();
            }
        });
    });

    // Референсные изображения - добавляем, а не заменяем
    const referenceImagesInput = document.getElementById('referenceImages');
    const referenceDropZone = document.getElementById('referenceDropZone');
    const selectReferenceFilesBtn = document.getElementById('selectReferenceFilesBtn');
    const pasteFromClipboardBtn = document.getElementById('pasteFromClipboardBtn');
    const referenceSection = document.getElementById('referenceImagesSection');
    const referencePreview = document.getElementById('referencePreview');
    
    // Кнопка выбора файлов
    if (selectReferenceFilesBtn && referenceImagesInput) {
        selectReferenceFilesBtn.addEventListener('click', () => {
            referenceImagesInput.click();
        });
    }
    
    // Кнопка вставки из буфера
    if (pasteFromClipboardBtn) {
        pasteFromClipboardBtn.addEventListener('click', async () => {
            await handlePasteFromClipboard();
        });
    }
    
    // Обработчик выбора файлов
    if (referenceImagesInput) {
        referenceImagesInput.addEventListener('change', (e) => {
            const newFiles = Array.from(e.target.files);
            const remainingSlots = 4 - referenceImages.length;
            
            if (remainingSlots > 0) {
                const filesToAdd = newFiles.slice(0, remainingSlots);
                filesToAdd.forEach(file => {
                    processReferenceFile(file);
                });
            }
            
            // Очищаем input чтобы можно было выбрать тот же файл снова
            e.target.value = '';
        });
    }
    
    // Drag and Drop для зоны
    if (referenceDropZone) {
        // Предотвращаем стандартное поведение браузера
        ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
            referenceDropZone.addEventListener(eventName, (e) => {
                e.preventDefault();
                e.stopPropagation();
            });
        });
        
        // Визуальная обратная связь при drag
        referenceDropZone.addEventListener('dragenter', () => {
            referenceDropZone.style.borderColor = 'rgba(102, 126, 234, 1)';
            referenceDropZone.style.background = 'rgba(102, 126, 234, 0.15)';
        });
        
        referenceDropZone.addEventListener('dragleave', () => {
            referenceDropZone.style.borderColor = 'rgba(102, 126, 234, 0.5)';
            referenceDropZone.style.background = 'rgba(102, 126, 234, 0.05)';
        });
        
        // Обработка drop
        referenceDropZone.addEventListener('drop', (e) => {
            referenceDropZone.style.borderColor = 'rgba(102, 126, 234, 0.5)';
            referenceDropZone.style.background = 'rgba(102, 126, 234, 0.05)';
            
            const files = Array.from(e.dataTransfer.files).filter(file => file.type.startsWith('image/'));
            const remainingSlots = 4 - referenceImages.length;
            
            if (files.length === 0) {
                showToast('Перетащите изображение', 'warning');
                return;
            }
            
            if (remainingSlots <= 0) {
                showToast('Достигнут лимит референсов (4)', 'warning');
                return;
            }
            
            files.slice(0, remainingSlots).forEach(file => {
                processReferenceFile(file);
            });
        });
    }
    
    // Глобальный обработчик Ctrl+V / Cmd+V (работает независимо от языка клавиатуры)
    document.addEventListener('keydown', async (e) => {
        // Проверяем Ctrl+V (Windows/Linux) или Cmd+V (Mac)
        // Используем event.code для работы с любым языком клавиатуры
        const isCtrlV = (e.ctrlKey || e.metaKey) && (e.code === 'KeyV' || e.keyCode === 86);
        
        if (isCtrlV && referenceSection && referenceSection.style.display !== 'none') {
            // Проверяем что фокус не в текстовом поле (чтобы не мешать обычной вставке текста)
            const activeElement = document.activeElement;
            const isTextInput = activeElement && (
                activeElement.tagName === 'INPUT' || 
                activeElement.tagName === 'TEXTAREA' ||
                activeElement.isContentEditable
            );
            
            if (!isTextInput) {
                e.preventDefault();
                await handlePasteFromClipboard();
            }
        }
    });
    
    // Обработчик paste события (для случаев когда фокус на зоне)
    if (referenceDropZone) {
        referenceDropZone.addEventListener('paste', async (e) => {
            e.preventDefault();
            await handlePasteFromClipboard(e);
        });
    }
    
    // Обработчик paste на preview
    if (referencePreview) {
        referencePreview.addEventListener('paste', async (e) => {
            e.preventDefault();
            await handlePasteFromClipboard(e);
        });
    }
    
    // Функция обработки вставки из буфера
    async function handlePasteFromClipboard(e = null) {
        if (referenceSection && referenceSection.style.display === 'none') return;
        
        const remainingSlots = 4 - referenceImages.length;
        if (remainingSlots <= 0) {
            showToast('Достигнут лимит референсов (4)', 'warning');
            return;
        }
        
        let items = null;
        if (e && e.clipboardData) {
            items = e.clipboardData.items;
        } else {
            // Пробуем получить из буфера обмена через Clipboard API
            try {
                const clipboardItems = await navigator.clipboard.read();
                items = clipboardItems;
            } catch (err) {
                console.warn('[PASTE] Clipboard API недоступен, используем событие paste:', err);
                // Если Clipboard API недоступен, ждем события paste
                showToast('Нажмите Ctrl+V когда секция референсов видна', 'info');
                return;
            }
        }
        
        if (!items || items.length === 0) {
            showToast('В буфере обмена нет изображений', 'info');
            return;
        }
        
        const imageItems = Array.from(items).filter(item => {
            if (item.type) {
                return item.type.indexOf('image') !== -1;
            } else if (item.types) {
                return item.types.some(type => type.indexOf('image') !== -1);
            }
            return false;
        });
        
        if (imageItems.length === 0) {
            showToast('В буфере обмена нет изображений', 'info');
            return;
        }
        
        for (let i = 0; i < Math.min(imageItems.length, remainingSlots); i++) {
            const item = imageItems[i];
            let file = null;
            
            if (item.getAsFile) {
                file = item.getAsFile();
            } else if (item.getType) {
                // Для Clipboard API
                const blob = await item.getType('image/png');
                file = new File([blob], `pasted-image-${Date.now()}.png`, { type: 'image/png' });
            }
            
            if (file) {
                processReferenceFile(file);
            }
        }
    }
    

    // Форма генерации
    generateForm.addEventListener('submit', handleGenerate);

    // Форма входа
    loginForm.addEventListener('submit', handleLogin);

    // Форма регистрации
    registerForm.addEventListener('submit', handleRegister);

    // Форма API ключа
    apiKeyForm.addEventListener('submit', handleApiKeySave);
    document.getElementById('deleteApiKeyBtn').addEventListener('click', handleApiKeyDelete);

    // Выход
    document.getElementById('logoutBtn').addEventListener('click', handleLogout);

    // Обновление галереи
    document.getElementById('refreshGallery').addEventListener('click', loadGallery);
    
    // Переключение видимости паролей
    document.getElementById('toggleLoginPassword').addEventListener('click', () => {
        togglePasswordVisibility('loginPassword', 'loginPasswordIcon');
    });
    document.getElementById('toggleRegisterPassword').addEventListener('click', () => {
        togglePasswordVisibility('registerPassword', 'registerPasswordIcon');
    });
}

// Переключение видимости пароля
function togglePasswordVisibility(inputId, iconId) {
    const input = document.getElementById(inputId);
    const icon = document.getElementById(iconId);
    if (input.type === 'password') {
        input.type = 'text';
        icon.classList.remove('fa-eye');
        icon.classList.add('fa-eye-slash');
    } else {
        input.type = 'password';
        icon.classList.remove('fa-eye-slash');
        icon.classList.add('fa-eye');
    }
}

// Обработка генерации
async function handleGenerate(e) {
    e.preventDefault();

    if (!authToken) {
        showToast('Требуется аутентификация', 'error');
        return;
    }

    const spinner = document.getElementById('spinner');
    const submitText = document.getElementById('submitText');
    const sendButton = document.getElementById('sendToGenerate');

    spinner.classList.remove('d-none');
    submitText.textContent = 'Добавление в очередь...';
    sendButton.disabled = true;

    try {
        // Подготовка данных
        const formData = {
            prompt: document.getElementById('prompt').value,
            negative_prompt: document.getElementById('negativePrompt').value || null,
            generation_mode: document.querySelector('input[name="generationMode"]:checked').value,
            resolution: document.getElementById('resolution').value,
            num_inference_steps: parseInt(document.getElementById('numSteps').value),
            guidance_scale: parseFloat(document.getElementById('guidance').value),
            seed: document.getElementById('seed').value ? parseInt(document.getElementById('seed').value) : null
        };

        // Обработка соотношения сторон
        let finalAspectRatio = document.getElementById('aspectRatio').value;
        let aspectRatioSource = 'manual'; // 'manual' или 'reference'
        
        // Если выбрано соотношение из референса
        if (finalAspectRatio.startsWith('user')) {
            const refIndex = parseInt(finalAspectRatio.replace('user', '')) - 1;
            if (referenceImages[refIndex]) {
                // Используем сохраненное соотношение из референса
                if (referenceImages[refIndex].aspectRatio) {
                    finalAspectRatio = referenceImages[refIndex].aspectRatio;
                    aspectRatioSource = 'reference';
                    console.log(`[GENERATE] Используется соотношение из референса ${refIndex + 1}: ${finalAspectRatio}`);
                } else if (referenceImages[refIndex].width && referenceImages[refIndex].height) {
                    // Если соотношение не было вычислено, вычисляем сейчас
                    finalAspectRatio = calculateAspectRatio(
                        referenceImages[refIndex].width, 
                        referenceImages[refIndex].height
                    );
                    referenceImages[refIndex].aspectRatio = finalAspectRatio;
                    aspectRatioSource = 'reference';
                    console.log(`[GENERATE] Вычислено соотношение из референса ${refIndex + 1}: ${finalAspectRatio}`);
                } else {
                    // Если референс не загружен или нет размеров, используем 1:1
                    finalAspectRatio = '1:1';
                    console.warn(`[GENERATE] Референс ${refIndex + 1} не найден, используется 1:1`);
                }
            } else {
                // Если референс не загружен, используем 1:1
                finalAspectRatio = '1:1';
                console.warn(`[GENERATE] Референс ${refIndex + 1} не загружен, используется 1:1`);
            }
        }
        
        formData.aspect_ratio = finalAspectRatio;
        console.log(`[GENERATE] Финальное соотношение сторон: ${finalAspectRatio} (источник: ${aspectRatioSource})`);
        
        // Обработка референсных изображений
        if (referenceImages.length > 0) {
            formData.reference_images = referenceImages.map(ref => ref.dataUrl);
        }
        
        // Добавляем API ключ из хранилища (обязательно)
        // ВАЖНО: Ключи НЕ сохраняются на сервере, передаются только в запросе
        const apiKey = getApiKey();
        if (!apiKey || apiKey.trim() === '') {
            showToast('Ошибка: API ключ не введен. Пожалуйста, введите ключ Replicate API в настройках.', 'error');
            spinner.classList.add('d-none');
            submitText.textContent = '🎨 Сгенерировать изображение';
            sendButton.disabled = false;
            return;
        }
        
        formData.api_key = apiKey;
        const storage = getStorage();
        const storageType = storage === localStorage ? 'localStorage' : 'sessionStorage';
        console.log(`[GENERATE] API ключ найден в ${storageType}, добавляем в запрос`);

        // Отправка запроса
        const response = await fetch(`${API_URL}/images/generate`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`
            },
            body: JSON.stringify(formData)
        });

        if (!response.ok) {
            const error = await response.json();
            const errorMessage = error.detail || 'Ошибка генерации';
            
            // Специальная обработка ошибки лимита
            if (response.status === 429) {
                showToast(`Лимит: ${errorMessage}`, 'warning');
            } else {
                showToast(`Ошибка: ${errorMessage}`, 'error');
            }
            
            throw new Error(errorMessage);
        }

        const result = await response.json();
        console.log('[GENERATE] Результат генерации:', result);
        showToast('Генерация добавлена в очередь!', 'success');
        
        // НЕ очищаем форму - сохраняем значения для удобства пользователя
        // generateForm.reset(); - УБРАНО
        
        // Сразу добавляем заглушку в галерею, чтобы пользователь видел, что генерация запущена
        const grid = document.getElementById('imageGrid');
        if (grid && result.image_id) {
            const placeholderCard = `
                <div class="col">
                    <div class="card h-100">
                        <div class="card-img-top bg-dark d-flex align-items-center justify-content-center" style="height: 200px; background: linear-gradient(135deg, #1a1a2e 0%, #252547 100%);">
                            <div class="text-center">
                                <div class="spinner-border text-warning" role="status" style="width: 3rem; height: 3rem;">
                                    <span class="visually-hidden">Загрузка...</span>
                                </div>
                                <p class="mt-3 mb-0 text-light fw-bold">В очереди...</p>
                            </div>
                        </div>
                        <div class="card-body">
                            <h6 class="card-title">${document.getElementById('prompt').value.substring(0, 50)}${document.getElementById('prompt').value.length > 50 ? '...' : ''}</h6>
                            <p class="card-text small text-muted">
                                ${document.getElementById('resolution').value} | ${document.getElementById('aspectRatio').value}<br>
                                <span class="badge bg-warning">В очереди</span>
                            </p>
                        </div>
                        <div class="card-footer">
                            <div class="d-flex gap-2">
                                <button class="btn btn-sm btn-primary flex-fill" onclick="editGeneration(${result.image_id})">
                                    <i class="fas fa-edit me-1"></i>Редактировать
                                </button>
                                <button class="btn btn-sm btn-danger flex-fill" onclick="deleteGeneration(${result.image_id})">
                                    <i class="fas fa-trash me-1"></i>Удалить
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            `;
            // Добавляем в начало списка
            if (grid.innerHTML.includes('нет генераций')) {
                grid.innerHTML = placeholderCard;
            } else {
                grid.innerHTML = placeholderCard + grid.innerHTML;
            }
        }
        
        // Обновление галереи сразу, чтобы показать реальную генерацию из БД
        setTimeout(async () => {
            console.log('[GENERATE] Загружаем галерею после генерации...');
            await loadGallery();
        }, 800);
        
        // Продолжаем обновлять галерею каждые 2 секунды для активных генераций
        let checkCount = 0;
        const maxChecks = 150; // 5 минут при обновлении каждые 2 секунды
        const checkInterval = setInterval(async () => {
            checkCount++;
            await loadGallery();
            // Останавливаем проверку через 5 минут или если нет активных генераций
            if (checkCount >= maxChecks) {
                clearInterval(checkInterval);
            } else {
                // Проверяем, есть ли еще активные генерации
                try {
                    const response = await fetch(`${API_URL}/images/list`, {
                        headers: {
                            'Authorization': `Bearer ${authToken}`
                        }
                    });
                    if (response.ok) {
                        const data = await response.json();
                        // Поддерживаем как старый формат (массив), так и новый (объект с метаданными)
                        const generations = Array.isArray(data) ? data : (data.generations || []);
                        const activeCount = generations.filter(g => g.status === 'pending' || g.status === 'running').length;
                        if (activeCount === 0) {
                            console.log('[GENERATE] Все генерации завершены, останавливаем проверку');
                            clearInterval(checkInterval);
                            // Финальное обновление галереи
                            await loadGallery();
                        }
                    } else {
                        // Если ошибка, пробуем без параметров
                        const retryResponse = await fetch(`${API_URL}/images/list`, {
                            headers: {
                                'Authorization': `Bearer ${authToken}`
                            }
                        });
                        if (retryResponse.ok) {
                            const data = await retryResponse.json();
                            // Поддерживаем как старый формат (массив), так и новый (объект с метаданными)
                            const generations = Array.isArray(data) ? data : (data.generations || []);
                            const activeCount = generations.filter(g => g.status === 'pending' || g.status === 'running').length;
                            if (activeCount === 0) {
                                console.log('[GENERATE] Все генерации завершены, останавливаем проверку');
                                clearInterval(checkInterval);
                                await loadGallery();
                            }
                        }
                    }
                } catch (error) {
                    console.error('[GENERATE] Ошибка проверки статуса:', error);
                }
            }
        }, 2000);

    } catch (error) {
        console.error('Ошибка генерации:', error);
        showToast(`Ошибка: ${error.message}`, 'error');
    } finally {
        spinner.classList.add('d-none');
        submitText.textContent = '🎨 Сгенерировать изображение';
        sendButton.disabled = false;
    }
}

// Обработка входа
async function handleLogin(e) {
    e.preventDefault();
    const errorDiv = document.getElementById('loginError');
    errorDiv.classList.add('d-none');
    errorDiv.textContent = '';
    
    const username = document.getElementById('loginUsername').value;
    const password = document.getElementById('loginPassword').value;

    if (!username || !password) {
        errorDiv.textContent = 'Заполните все поля';
        errorDiv.classList.remove('d-none');
        return;
    }

    try {
        const response = await fetch(`${API_URL}/auth/login`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                username_or_email: username,
                password: password
            })
        });

        if (!response.ok) {
            const error = await response.json();
            const errorMessage = error.detail || 'Ошибка входа';
            errorDiv.textContent = errorMessage;
            errorDiv.classList.remove('d-none');
            return;
        }

        const data = await response.json();
        authToken = data.access_token;
        localStorage.setItem('authToken', authToken);
        
        bootstrap.Modal.getInstance(document.getElementById('loginModal')).hide();
        showToast('Вход выполнен успешно!', 'success');
        
        // Обновляем UI и загружаем данные
        checkAuth();

    } catch (error) {
        errorDiv.textContent = `Ошибка: ${error.message}`;
        errorDiv.classList.remove('d-none');
    }
}

// Обработка регистрации
async function handleRegister(e) {
    e.preventDefault();
    const errorDiv = document.getElementById('registerError');
    errorDiv.classList.add('d-none');
    errorDiv.textContent = '';
    
    const username = document.getElementById('registerUsername').value.trim();
    const email = document.getElementById('registerEmail').value.trim();
    const password = document.getElementById('registerPassword').value;

    // Валидация на клиенте
    if (!username || !email || !password) {
        errorDiv.textContent = 'Заполните все поля';
        errorDiv.classList.remove('d-none');
        return;
    }

    if (password.length < 6) {
        errorDiv.textContent = 'Пароль должен быть не менее 6 символов';
        errorDiv.classList.remove('d-none');
        return;
    }

    if (new TextEncoder().encode(password).length > 72) {
        errorDiv.textContent = 'Пароль слишком длинный (максимум 72 байта)';
        errorDiv.classList.remove('d-none');
        return;
    }

    try {
        const response = await fetch(`${API_URL}/auth/register`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                username: username,
                email: email,
                password: password
            })
        });

        if (!response.ok) {
            const error = await response.json();
            const errorMessage = Array.isArray(error.detail) 
                ? error.detail.map(e => e.msg || e).join(', ')
                : (error.detail || 'Ошибка регистрации');
            errorDiv.textContent = errorMessage;
            errorDiv.classList.remove('d-none');
            return;
        }

        const data = await response.json();
        authToken = data.access_token;
        localStorage.setItem('authToken', authToken);
        
        bootstrap.Modal.getInstance(document.getElementById('registerModal')).hide();
        showToast('Регистрация успешна!', 'success');
        checkAuth();

    } catch (error) {
        errorDiv.textContent = `Ошибка: ${error.message}`;
        errorDiv.classList.remove('d-none');
    }
}

// Сохранение API ключа
async function handleApiKeySave(e) {
    e.preventDefault();
    const apiKey = document.getElementById('apiKeyInput').value;

    // ВАЖНО: Ключи НЕ сохраняются на сервере для безопасности
    // Сохраняем локально в localStorage (более надежно на мобильных устройствах)
    const storage = getStorage();
    if (!storage) {
        showToast('Ошибка: хранилище недоступно. Проверьте настройки браузера (приватный режим может блокировать сохранение)', 'error');
        return;
    }
    
    const storageType = storage === localStorage ? 'localStorage' : 'sessionStorage';
    const saved = setApiKey(apiKey);
    
    if (saved) {
        if (apiKey) {
            showToast(`API ключ сохранен локально в ${storageType} (не сохраняется на сервере для вашей безопасности)`, 'success');
        } else {
            showToast('API ключ удален', 'info');
        }
    } else {
        showToast('Ошибка сохранения ключа. Проверьте настройки браузера.', 'error');
    }
    
    // Закрываем модальное окно
    const modal = bootstrap.Modal.getInstance(document.getElementById('apiKeyModal'));
    if (modal) {
        modal.hide();
    }
    
    // Очищаем поле ввода
    document.getElementById('apiKeyInput').value = '';
    checkApiKeyStatus();
}

// Удаление API ключа
async function handleApiKeyDelete() {
    if (!confirm('Удалить API ключ из локального хранилища?')) return;

    // ВАЖНО: Ключи НЕ сохраняются на сервере, удаляем только локально
    const removed = removeApiKey();
    if (removed) {
        showToast('API ключ удален из локального хранилища', 'success');
    } else {
        showToast('Ошибка удаления ключа', 'error');
    }
    checkApiKeyStatus();
}

// Выход
function handleLogout() {
    localStorage.removeItem('authToken');
    authToken = null;
    currentUser = null;
    showLoginButton();
    loadGallery();
    showToast('Выход выполнен', 'info');
}

// Загрузка галереи
async function loadGallery() {
    // Предотвращаем параллельные обновления
    if (galleryUpdateInProgress) {
        console.log('[GALLERY] Обновление уже выполняется, пропускаем');
        return;
    }
    
    const grid = document.getElementById('imageGrid');
    if (!grid) {
        console.warn('[GALLERY] Элемент imageGrid не найден');
        return;
    }
    
    // Проверяем токен еще раз (на случай если он был удален)
    if (!authToken) {
        authToken = localStorage.getItem('authToken');
    }
    
    if (!authToken) {
        console.log('[GALLERY] Токен не найден, показываем сообщение о входе');
        grid.innerHTML = '<div class="col-12"><div class="alert alert-info">Войдите в систему для просмотра ваших генераций</div></div>';
        return;
    }
    
    galleryUpdateInProgress = true;

    console.log('[GALLERY] Начинаем загрузку галереи...');
    
    // Объявляем переменные для данных
    let generations = [];
    let meta = null;
    
    try {
        // Пробуем сначала без параметров, чтобы избежать 422
        const url = `${API_URL}/images/list`;
        console.log('[GALLERY] Запрос к:', url);
        let response = await fetch(url, {
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });
        
        console.log('[GALLERY] Ответ получен:', response.status, response.statusText);

        if (!response.ok) {
            let errorData;
            try {
                errorData = await response.json();
            } catch (e) {
                errorData = { detail: `Ошибка ${response.status}` };
            }
            console.error('[GALLERY] Ошибка загрузки:', response.status, errorData);
            
            // Если 422, пробуем запрос без параметров (уже пробуем без параметров, так что это не должно происходить)
            if (response.status === 422) {
                console.warn('[GALLERY] Ошибка 422 даже без параметров, проверяем детали ошибки:', errorData);
                // Показываем сообщение об ошибке, но не блокируем интерфейс
                grid.innerHTML = '<div class="col-12"><div class="alert alert-warning">Ошибка загрузки списка генераций. Попробуйте обновить страницу.</div></div>';
                return;
            } else if (response.status === 401) {
                // Неавторизован - очищаем токен и показываем форму входа
                console.warn('[GALLERY] Токен недействителен, очищаем и показываем форму входа');
                localStorage.removeItem('authToken');
                authToken = null;
                showLoginButton();
                grid.innerHTML = '<div class="col-12"><div class="alert alert-info">Сессия истекла. Войдите снова.</div></div>';
                return;
            } else {
                throw new Error(errorData.detail || `Ошибка ${response.status}`);
            }
        } else {
            const data = await response.json();
            
            // Поддерживаем как старый формат (массив), так и новый (объект с метаданными)
            if (Array.isArray(data)) {
                generations = data;
                meta = null;
            } else if (data.generations && Array.isArray(data.generations)) {
                generations = data.generations;
                meta = data.meta || null;
            } else {
                console.error('[GALLERY] Неверный формат данных');
                grid.innerHTML = '<div class="col-12"><div class="alert alert-danger">Ошибка загрузки данных</div></div>';
                galleryUpdateInProgress = false;
                return;
            }
            
            console.log('[GALLERY] Загружено генераций:', generations.length);
            if (meta) {
                console.log('[GALLERY] Метаданные:', meta);
            }
        }
        
        // Проверяем, что generations определен
        if (!generations) {
            console.error('[GALLERY] generations не определен');
            grid.innerHTML = '<div class="col-12"><div class="alert alert-warning">Ошибка загрузки генераций</div></div>';
            galleryUpdateInProgress = false;
            return;
        }
        
        console.log('[GALLERY] Получено генераций:', generations.length);
        console.log('[GALLERY] Статусы генераций:', generations.map(g => ({id: g.id, status: g.status, error_message: g.error_message ? g.error_message.substring(0, 50) + '...' : null})));
        
        // Логируем генерации с ошибками
        const failedGenerations = generations.filter(g => g.status === 'failed');
        if (failedGenerations.length > 0) {
            console.log('[GALLERY] Генерации с ошибками:', failedGenerations.map(g => ({
                id: g.id,
                error_message: g.error_message || 'Нет error_message'
            })));
        }
        
        // Подсчет активных генераций
        const activeCount = generations.filter(g => g.status === 'pending' || g.status === 'running').length;
        const queueStatus = document.getElementById('queueStatus');
        const queueStatusText = document.getElementById('queueStatusText');
        if (activeCount > 0) {
            queueStatus.style.display = 'block';
            if (queueStatusText) {
                queueStatusText.textContent = `Активных генераций: ${activeCount}`;
            } else {
                queueStatus.innerHTML = `<i class="fas fa-info-circle me-2"></i>Активных генераций: ${activeCount}`;
            }
        } else {
            queueStatus.style.display = 'none';
        }

        if (generations.length === 0) {
            grid.innerHTML = '<div class="col-12"><div class="alert alert-info">У вас пока нет генераций</div></div>';
            return;
        }

        // Сортируем генерации: сначала активные (pending, running), потом завершенные и ошибки по дате
        const sortedGenerations = [...generations].sort((a, b) => {
            const statusOrder = { 'pending': 0, 'running': 1, 'completed': 2, 'failed': 2 }; // completed и failed имеют одинаковый приоритет
            const aOrder = statusOrder[a.status] || 99;
            const bOrder = statusOrder[b.status] || 99;
            if (aOrder !== bOrder) return aOrder - bOrder;
            // Если статус одинаковый, сортируем по дате (новые сверху)
            return new Date(b.created_at) - new Date(a.created_at);
        });
        
        // Вычисляем оставшиеся дни для каждой генерации
        const retentionDays = meta?.storage_info?.retention_days || 7;
        sortedGenerations.forEach(gen => {
            if (gen.status === 'completed' && gen.created_at) {
                const createdDate = new Date(gen.created_at);
                const expirationDate = new Date(createdDate);
                expirationDate.setDate(expirationDate.getDate() + retentionDays);
                const now = new Date();
                const daysLeft = Math.ceil((expirationDate - now) / (1000 * 60 * 60 * 24));
                gen.daysLeft = daysLeft > 0 ? daysLeft : 0;
                
                // Форматируем текст дней
                if (gen.daysLeft === 1) {
                    gen.daysText = 'день';
                } else if (gen.daysLeft >= 2 && gen.daysLeft <= 4) {
                    gen.daysText = 'дня';
                } else {
                    gen.daysText = 'дней';
                }
            }
        });

        // Вычисляем хеш текущего состояния для предотвращения ненужных обновлений
        const currentHash = JSON.stringify(sortedGenerations.map(g => ({ id: g.id, status: g.status, result_url: g.result_url })));
        if (currentHash === lastGalleryHash && grid.innerHTML !== '') {
            console.log('[GALLERY] Данные не изменились, пропускаем обновление DOM');
            galleryUpdateInProgress = false;
            return;
        }
        lastGalleryHash = currentHash;
        
        grid.innerHTML = sortedGenerations.map(gen => `
            <div class="col" data-generation-id="${gen.id}">
                <div class="card h-100 generation-card" style="border-radius: 12px; overflow: hidden;">
                    <div class="position-relative image-container" data-gen-id="${gen.id}" data-image-url="${gen.status === 'completed' && gen.result_url ? gen.result_url.replace(/'/g, "\\'") : ''}" data-prompt="${gen.status === 'completed' && gen.result_url ? (gen.prompt || '').replace(/'/g, "\\'").replace(/"/g, '&quot;') : ''}" style="height: 350px; overflow: hidden !important; background: #1a1a2e; cursor: ${gen.status === 'completed' && gen.result_url ? 'pointer' : 'default'}; border-radius: 0 0 12px 12px !important; position: relative;">
                        ${gen.status === 'completed' && gen.result_url ? 
                            `<img src="${gen.result_url}" class="card-img-top generation-image" data-gen-id="${gen.id}" style="height: 350px; width: 100%; object-fit: cover; position: absolute; top: 0; left: 0; right: 0; bottom: 0; z-index: 1; display: block; border-radius: 0 0 12px 12px;" alt="Generated image" 
                                onerror="(function(img, genId) { console.error('[IMAGE] Ошибка загрузки изображения для генерации', genId); console.error('[IMAGE] URL:', img.src); img.style.display='none'; const container = img.closest('.image-container'); const errorDiv = container ? container.querySelector('.image-error') : null; if (errorDiv) { errorDiv.style.setProperty('display', 'flex', 'important'); errorDiv.style.zIndex='2'; } })(this, ${gen.id});" 
                                onload="(function(img, genId) { console.log('[IMAGE] Изображение загружено для генерации', genId); console.log('[IMAGE] URL:', img.src); const container = img.closest('.image-container'); const errorDiv = container ? container.querySelector('.image-error') : null; if (errorDiv) { errorDiv.style.setProperty('display', 'none', 'important'); errorDiv.style.zIndex='2'; } img.style.display='block'; img.style.zIndex='1'; })(this, ${gen.id});">` :
                            `<div class="position-absolute top-0 start-0 w-100 h-100 d-flex align-items-center justify-content-center" style="z-index: 1; background: linear-gradient(135deg, #1a1a2e 0%, #252547 100%); border-radius: 0 0 12px 12px;">
                                ${gen.status === 'failed' ? 
                                    `<div class="text-center">
                                        <i class="fas fa-exclamation-triangle text-danger" style="font-size: 3rem;"></i>
                                        <p class="mt-3 mb-0 text-light fw-bold">Ошибка генерации</p>
                                        <p class="mt-2 mb-0 text-danger small">${(gen.error_message || 'Не удалось сгенерировать изображение').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;')}</p>
                                    </div>` :
                                    `<div class="text-center">
                                        <div class="spinner-border text-warning" role="status" style="width: 3rem; height: 3rem;">
                                            <span class="visually-hidden">Загрузка...</span>
                                        </div>
                                        <p class="mt-3 mb-0 text-light fw-bold">${gen.status === 'pending' ? 'В очереди...' : gen.status === 'running' ? 'Генерируется...' : 'Ошибка'}</p>
                                    </div>`
                                }
                            </div>`
                        }
                        <div class="bg-dark d-flex align-items-center justify-content-center image-error position-absolute top-0 start-0 w-100 h-100" style="display: none !important; z-index: 2; background: linear-gradient(135deg, #1a1a2e 0%, #252547 100%) !important; pointer-events: none;">
                            <div class="text-center">
                                <i class="fas fa-exclamation-triangle text-warning mb-2" style="font-size: 2rem;"></i>
                                <p class="text-light mb-0">Ошибка загрузки изображения</p>
                                <small class="text-muted">Попробуйте обновить страницу</small>
                            </div>
                        </div>
                        <div class="position-absolute top-0 end-0 m-2" style="z-index: 5; pointer-events: none; display: flex; flex-direction: column; align-items: flex-end; gap: 0.25rem;">
                            <div style="display: flex; align-items: center; gap: 0.25rem; pointer-events: none;">
                                <button class="btn btn-sm generation-status-badge" disabled style="opacity: 1 !important; background: ${gen.status === 'completed' ? 'linear-gradient(135deg, rgba(74, 85, 104, 0.7) 0%, rgba(72, 187, 120, 0.5) 100%)' : gen.status === 'failed' ? 'linear-gradient(135deg, rgba(74, 85, 104, 0.7) 0%, rgba(229, 62, 62, 0.5) 100%)' : 'linear-gradient(135deg, rgba(74, 85, 104, 0.7) 0%, rgba(102, 126, 234, 0.5) 100%)'} !important; border: 1px solid ${gen.status === 'completed' ? 'rgba(72, 187, 120, 0.6)' : gen.status === 'failed' ? 'rgba(229, 62, 62, 0.6)' : 'rgba(102, 126, 234, 0.6)'} !important; padding: 0.25rem 0.5rem; color: #ffffff !important; font-weight: 700; cursor: default; pointer-events: none; box-shadow: 0 2px 4px rgba(0, 0, 0, 0.3);">${gen.status === 'completed' ? 'Завершено' : gen.status === 'running' ? 'Генерируется' : gen.status === 'pending' ? 'В очереди' : 'Ошибка'}</button>
                                ${(gen.status === 'completed' || gen.status === 'failed') ? 
                                    `<button class="btn btn-sm btn-link text-white p-1 info-btn" data-gen-id="${gen.id}" title="Параметры генерации" style="opacity: 0.9; pointer-events: auto !important; cursor: pointer; z-index: 10; position: relative;">
                                        <i class="fas fa-info-circle" style="font-size: 0.75rem;"></i>
                                    </button>` : ''
                                }
                            </div>
                            ${gen.status === 'completed' && gen.daysLeft !== undefined && gen.daysLeft > 0 ? 
                                `<span class="badge bg-warning text-dark" style="font-size: 0.65rem; padding: 0.2rem 0.4rem; font-weight: 600; box-shadow: 0 2px 4px rgba(0, 0, 0, 0.3);">Осталось: ${gen.daysLeft} ${gen.daysText}</span>` : ''
                            }
                        </div>
                        <div class="prompt-and-buttons-overlay position-absolute bottom-0 start-0 w-100" style="z-index: 5; background: linear-gradient(to top, rgba(0,0,0,0.5) 0%, rgba(0,0,0,0.3) 50%, rgba(0,0,0,0) 100%); padding: 1rem; border-radius: 0 0 12px 12px; backdrop-filter: blur(6px); overflow: hidden;">
                            <p class="text-light mb-2 small prompt-text" style="font-size: 0.7225rem; line-height: 1.19; padding: 0.5rem; border-radius: 4px; max-width: 100%; overflow-x: auto; overflow-y: hidden; white-space: nowrap;">${(gen.prompt || '').replace(/</g, '&lt;').replace(/>/g, '&gt;')}</p>
                                <div class="d-flex gap-2 justify-content-center align-items-center">
                                    ${gen.status === 'completed' && gen.result_url ? 
                                        `<button class="btn btn-icon-only btn-download" onclick="event.stopPropagation(); event.preventDefault(); downloadImage('${gen.result_url.replace(/'/g, "\\'")}', '${(gen.prompt || '').substring(0, 30).replace(/'/g, "\\'").replace(/"/g, '&quot;')}')" title="Скачать изображение" style="width: 28px; height: 28px; padding: 0; display: flex; align-items: center; justify-content: center; border-radius: 4px; border: none; font-size: 0.7rem; pointer-events: auto; cursor: pointer; z-index: 10; position: relative;">
                                            <i class="fas fa-download"></i>
                                        </button>` : ''
                                    }
                                    <button class="btn btn-icon-only btn-edit" onclick="event.stopPropagation(); event.preventDefault(); editGeneration(${gen.id})" title="Редактировать" style="width: 28px; height: 28px; padding: 0; display: flex; align-items: center; justify-content: center; border-radius: 4px; border: none; font-size: 0.7rem; pointer-events: auto; cursor: pointer; z-index: 10; position: relative;">
                                        <i class="fas fa-edit"></i>
                                    </button>
                                    <button class="btn btn-icon-only btn-delete" onclick="event.stopPropagation(); event.preventDefault(); deleteGeneration(${gen.id})" title="Удалить" style="width: 28px; height: 28px; padding: 0; display: flex; align-items: center; justify-content: center; border-radius: 4px; border: none; font-size: 0.7rem; pointer-events: auto; cursor: pointer; z-index: 10; position: relative;">
                                        <i class="fas fa-trash"></i>
                                    </button>
                                </div>
                        </div>
                    </div>
                </div>
            </div>
        `).join('');
        
        console.log('[GALLERY] Галерея обновлена, отображено карточек:', sortedGenerations.length);
        
        // Добавляем обработчики событий для карточек после рендеринга
        setTimeout(() => {
            // Обработчики для открытия фуллскрина
            document.querySelectorAll('.image-container[data-image-url]').forEach(container => {
                const imageUrl = container.getAttribute('data-image-url');
                const prompt = container.getAttribute('data-prompt');
                
                if (imageUrl) {
                    container.addEventListener('click', (e) => {
                        // Проверяем что клик не на кнопках
                        if (!e.target.closest('.info-btn') && 
                            !e.target.closest('.btn-edit') && 
                            !e.target.closest('.btn-delete') && 
                            !e.target.closest('.btn-download') && 
                            !e.target.closest('.prompt-and-buttons-overlay') &&
                            !e.target.closest('.generation-status-badge')) {
                            openFullscreenImage(imageUrl, prompt);
                        }
                    });
                }
            });
            
            // Обработчики для кнопки инфо
            document.querySelectorAll('.info-btn').forEach(btn => {
                btn.addEventListener('click', async (e) => {
                    e.stopPropagation();
                    e.preventDefault();
                    
                    const genId = parseInt(btn.getAttribute('data-gen-id'));
                    if (!genId) return;
                    
                    try {
                        // Загружаем полные данные генерации
                        const response = await fetch(`${API_URL}/images/${genId}`, {
                            headers: {
                                'Authorization': `Bearer ${authToken}`
                            }
                        });
                        
                        if (response.ok) {
                            const gen = await response.json();
                            console.log('[INFO] Загружены данные генерации:', {
                                id: gen.id,
                                status: gen.status,
                                has_error_message: !!gen.error_message,
                                error_message: gen.error_message ? gen.error_message.substring(0, 100) + '...' : 'нет',
                                error_message_full: gen.error_message || 'нет'
                            });
                            
                            // Убеждаемся что error_message передается
                            const errorMsg = gen.error_message || '';
                            console.log('[INFO] Передаем error_message в showGenerationParams:', errorMsg ? errorMsg.substring(0, 50) + '...' : 'пусто');
                            
                            showGenerationParams(
                                gen.id,
                                gen.prompt || '',
                                gen.resolution || '',
                                gen.aspect_ratio || '',
                                errorMsg
                            );
                        } else {
                            const errorData = await response.json().catch(() => ({}));
                            console.error('[INFO] Ошибка загрузки данных генерации:', response.status, errorData);
                            throw new Error(errorData.detail || 'Ошибка загрузки данных');
                        }
                    } catch (error) {
                        console.error('[INFO] Ошибка загрузки данных генерации:', error);
                        showToast('Ошибка загрузки данных генерации', 'error');
                    }
                });
            });
        }, 100);
        
        // Обновляем счетчик генераций в шапке и информацию о лимитах
        updateGalleryStats(sortedGenerations, meta);
        
        // Проверяем загруженные изображения и скрываем блоки ошибок для успешно загруженных
        setTimeout(() => {
            document.querySelectorAll('.generation-image').forEach(img => {
                const container = img.closest('.image-container');
                if (!container) return;
                
                if (img.complete && img.naturalHeight !== 0 && img.naturalWidth !== 0) {
                    // Изображение успешно загружено
                    const errorDiv = container.querySelector('.image-error');
                    if (errorDiv) {
                        errorDiv.style.setProperty('display', 'none', 'important');
                        errorDiv.style.zIndex = '2';
                    }
                    img.style.display = 'block';
                    img.style.zIndex = '1';
                    console.log('[GALLERY] Изображение проверено и загружено для генерации', img.dataset.genId);
                } else if (img.complete && (img.naturalHeight === 0 || img.naturalWidth === 0)) {
                    // Изображение не загрузилось
                    console.warn('[GALLERY] Изображение не загружено для генерации', img.dataset.genId);
                    const errorDiv = container.querySelector('.image-error');
                    if (errorDiv) {
                        errorDiv.style.setProperty('display', 'flex', 'important');
                        errorDiv.style.zIndex = '2';
                    }
                    img.style.display = 'none';
                }
            });
        }, 300);

    } catch (error) {
        console.error('[GALLERY] Ошибка загрузки галереи:', error);
        const grid = document.getElementById('imageGrid');
        if (grid) {
            const errorMessage = error.message || 'Неизвестная ошибка';
            grid.innerHTML = `<div class="col-12"><div class="alert alert-danger">Ошибка загрузки галереи: ${errorMessage}. Проверьте консоль для подробностей.</div></div>`;
        }
    } finally {
        galleryUpdateInProgress = false;
    }
}

// Функция для обновления статистики галереи и информации о лимитах
function updateGalleryStats(generations, meta) {
    const statsEl = document.getElementById('galleryStats');
    const countEl = document.getElementById('galleryCount');
    const totalEl = document.getElementById('galleryTotal');
    
    if (!statsEl || !countEl || !totalEl) return;
    
    if (meta && meta.total !== undefined) {
        countEl.textContent = meta.shown || generations.length;
        totalEl.textContent = meta.total;
        statsEl.style.display = 'block';
        
        // Добавляем информацию о лимитах MinIO
        if (meta.storage_info) {
            const storageInfo = meta.storage_info;
            const retentionDays = storageInfo.retention_days || 7;
            
            // Находим старейшую генерацию для расчета времени до очистки
            let oldestGeneration = null;
            if (generations.length > 0) {
                oldestGeneration = generations.reduce((oldest, current) => {
                    if (!oldest) return current;
                    const oldestDate = new Date(oldest.created_at || 0);
                    const currentDate = new Date(current.created_at || 0);
                    return currentDate < oldestDate ? current : oldest;
                });
            }
            
            // Удаляем старую информацию о лимитах если есть
            const existingLimitInfo = statsEl.querySelector('.storage-limit-info');
            if (existingLimitInfo) {
                existingLimitInfo.remove();
            }
            
            const limitInfo = document.createElement('span');
            limitInfo.className = 'storage-limit-info text-info ms-2';
            
            if (oldestGeneration && oldestGeneration.created_at) {
                const createdDate = new Date(oldestGeneration.created_at);
                const expirationDate = new Date(createdDate);
                expirationDate.setDate(expirationDate.getDate() + retentionDays);
                const now = new Date();
                const daysLeft = Math.ceil((expirationDate - now) / (1000 * 60 * 60 * 24));
                
                if (daysLeft > 0) {
                    const daysText = daysLeft === 1 ? 'день' : daysLeft < 5 ? 'дня' : 'дней';
                    limitInfo.innerHTML = `| Очистка через ${daysLeft} ${daysText}`;
                    limitInfo.className = 'storage-limit-info text-warning ms-2';
                } else {
                    limitInfo.innerHTML = '| Очистка в ближайшее время';
                    limitInfo.className = 'storage-limit-info text-danger ms-2';
                }
            } else {
                limitInfo.innerHTML = `| Хранение: ${retentionDays} дней`;
            }
            
            statsEl.appendChild(limitInfo);
        }
    } else {
        // Если метаданных нет, показываем только количество показанных
        countEl.textContent = generations.length;
        totalEl.textContent = generations.length;
        statsEl.style.display = 'block';
    }
}

// Редактирование генерации (заполнение формы параметрами)
async function editGeneration(id) {
    try {
        const response = await fetch(`${API_URL}/images/${id}`, {
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });

        if (!response.ok) {
            throw new Error('Ошибка загрузки данных');
        }

        const gen = await response.json();
        
        // Заполняем форму
        document.getElementById('prompt').value = gen.prompt || '';
        document.getElementById('negativePrompt').value = gen.negative_prompt || '';
        document.getElementById('resolution').value = gen.resolution || '1K';
        const aspectRatioValue = gen.aspect_ratio || '1:1';
        document.getElementById('aspectRatio').value = aspectRatioValue;
        selectAspectRatio(aspectRatioValue);
        document.getElementById('numSteps').value = gen.num_inference_steps || 50;
        document.getElementById('guidance').value = gen.guidance_scale || 7.5;
        document.getElementById('seed').value = gen.seed || '';
        
        // Очищаем старые референсы перед загрузкой новых
        referenceImages = [];
        aspectRatioAutoSelected = false;
        updateReferencePreview();
        
        // Устанавливаем режим генерации
        const generationMode = gen.generation_mode || 'text-to-image';
        const modeRadio = document.querySelector(`input[name="generationMode"][value="${generationMode}"]`);
        if (modeRadio) {
            modeRadio.checked = true;
            // Триггерим событие change для обновления UI
            modeRadio.dispatchEvent(new Event('change'));
        }
        
        // Показываем/скрываем секцию референсов в зависимости от режима
        const referenceSection = document.getElementById('referenceImagesSection');
        if (generationMode === 'image-to-image') {
            referenceSection.style.display = 'block';
        } else {
            referenceSection.style.display = 'none';
        }
        
        // Загружаем референсные изображения если есть
        if (gen.reference_images && gen.reference_images.length > 0) {
            
            for (let idx = 0; idx < gen.reference_images.length; idx++) {
                const imgUrl = gen.reference_images[idx];
                if (imgUrl && (imgUrl.startsWith('data:image') || imgUrl.startsWith('http'))) {
                    // Создаем объект изображения для определения размеров
                    const img = new Image();
                    img.onload = () => {
                        const aspectRatio = calculateAspectRatio(img.width, img.height);
                        const refObj = {
                            file: null, // Файл не сохраняется, только dataUrl
                            dataUrl: imgUrl,
                            id: Date.now() + Math.random() + idx,
                            aspectRatio: aspectRatio,
                            width: img.width,
                            height: img.height,
                            originalRatio: `${img.width}:${img.height}`
                        };
                        referenceImages.push(refObj);
                        console.log(`[EDIT] Загружен референс ${referenceImages.length} из сохраненной генерации: ${img.width}x${img.height} → ${aspectRatio}`);
                        
                        // Обновляем превью после загрузки всех изображений
                        if (referenceImages.length === gen.reference_images.length) {
                            updateReferencePreview();
                            updateAspectRatioOptions();
                        }
                    };
                    img.onerror = () => {
                        console.error(`[EDIT] Ошибка загрузки референсного изображения ${idx + 1}`);
                    };
                    img.src = imgUrl;
                } else if (imgUrl.startsWith('http')) {
                    // URL изображение - загружаем и конвертируем в base64
                    try {
                        const imgResponse = await fetch(imgUrl);
                        const blob = await imgResponse.blob();
                        const reader = new FileReader();
                        reader.onload = (e) => {
                            const img = new Image();
                            img.onload = () => {
                                const aspectRatio = calculateAspectRatio(img.width, img.height);
                                const refObj = {
                                    file: null,
                                    dataUrl: e.target.result,
                                    id: Date.now() + Math.random() + idx,
                                    aspectRatio: aspectRatio,
                                    width: img.width,
                                    height: img.height,
                                    originalRatio: `${img.width}:${img.height}`
                                };
                                referenceImages.push(refObj);
                                console.log(`[EDIT] Загружен референс ${referenceImages.length} из URL: ${img.width}x${img.height} → ${aspectRatio}`);
                                
                                // Обновляем превью после загрузки всех изображений
                                if (referenceImages.length === gen.reference_images.length) {
                                    updateReferencePreview();
                                    updateAspectRatioOptions();
                                }
                            };
                            img.onerror = () => {
                                console.error(`[EDIT] Ошибка обработки изображения ${idx + 1} из URL`);
                            };
                            img.src = e.target.result;
                        };
                        reader.onerror = () => {
                            console.error(`[EDIT] Ошибка чтения blob ${idx + 1}`);
                        };
                        reader.readAsDataURL(blob);
                    } catch (e) {
                        console.error(`[EDIT] Ошибка загрузки референсного изображения ${idx + 1} с URL:`, e);
                    }
                }
            }
        }
        
        // Прокручиваем к форме
        document.querySelector('.col-lg-4').scrollIntoView({ behavior: 'smooth', block: 'start' });
        showToast('Форма заполнена параметрами генерации', 'success');

    } catch (error) {
        showToast(`Ошибка: ${error.message}`, 'error');
    }
}

// Удаление генерации
async function deleteGeneration(id) {
    if (!confirm('Удалить генерацию?')) return;

    try {
        const response = await fetch(`${API_URL}/images/${id}`, {
            method: 'DELETE',
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });

        if (!response.ok) {
            throw new Error('Ошибка удаления');
        }

        showToast('Генерация удалена', 'success');
        loadGallery();

    } catch (error) {
        showToast(`Ошибка: ${error.message}`, 'error');
    }
}

// Показ кнопки входа
function showLoginButton() {
    document.getElementById('loginBtn').style.display = 'block';
    document.getElementById('userMenu').style.display = 'none';
}

// Показ меню пользователя
function showUserMenu() {
    document.getElementById('loginBtn').style.display = 'none';
    document.getElementById('userMenu').style.display = 'block';
    document.getElementById('usernameDisplay').textContent = currentUser?.username || 'Пользователь';
}

// Показ уведомления
function showToast(message, type = 'success') {
    const toast = document.getElementById('notificationToast');
    const toastMessage = document.getElementById('toastMessage');
    const toastHeader = toast.querySelector('.toast-header');
    
    toastMessage.textContent = message;
    
    // Изменение цвета в зависимости от типа
    toastHeader.className = `toast-header bg-${type === 'success' ? 'success' : type === 'error' ? 'danger' : 'info'} text-white`;
    
    notificationToast.show();
}

// Функция для скачивания референсного изображения
async function downloadReferenceImage(dataUrl, filename) {
    try {
        console.log('[DOWNLOAD] Начало скачивания референса:', filename);
        
        let blob;
        
        // Если это data URL, конвертируем напрямую в blob (без fetch для обхода CSP)
        if (dataUrl.startsWith('data:')) {
            // Парсим data URL: data:image/jpeg;base64,/9j/4AAQ...
            const [header, base64Data] = dataUrl.split(',');
            const mimeType = header.match(/data:([^;]+)/)?.[1] || 'image/jpeg';
            
            // Конвертируем base64 в binary
            const binaryString = atob(base64Data);
            const bytes = new Uint8Array(binaryString.length);
            for (let i = 0; i < binaryString.length; i++) {
                bytes[i] = binaryString.charCodeAt(i);
            }
            blob = new Blob([bytes], { type: mimeType });
        } else {
            // Если это обычный URL, загружаем через fetch
            const response = await fetch(dataUrl);
            if (!response.ok) {
                throw new Error(`Ошибка загрузки: ${response.status}`);
            }
            blob = await response.blob();
        }
        
        // Создаем blob URL для скачивания
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${filename}_${Date.now()}.jpg`;
        a.style.display = 'none';
        
        // Добавляем ссылку в DOM, кликаем и удаляем
        document.body.appendChild(a);
        a.click();
        
        // Удаляем ссылку и освобождаем URL после небольшой задержки
        setTimeout(() => {
            document.body.removeChild(a);
            window.URL.revokeObjectURL(url);
        }, 100);
        
        console.log('[DOWNLOAD] Референс успешно скачан');
        showToast('Референс успешно скачан', 'success');
    } catch (error) {
        console.error('[DOWNLOAD] Ошибка скачивания референса:', error);
        showToast('Ошибка скачивания референса: ' + error.message, 'error');
    }
}

// Функция для скачивания изображения
async function downloadImage(imageUrl, prompt) {
    try {
        console.log('[DOWNLOAD] Начало скачивания изображения:', imageUrl);
        
        // Загружаем изображение
        const response = await fetch(imageUrl);
        if (!response.ok) {
            throw new Error(`Ошибка загрузки: ${response.status}`);
        }
        
        const blob = await response.blob();
        
        // Создаем временную ссылку для скачивания
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        
        // Генерируем имя файла из промпта (очищаем от недопустимых символов)
        const sanitizedPrompt = (prompt || 'image')
            .substring(0, 50)
            .replace(/[^a-zа-яё0-9\s-]/gi, '')
            .replace(/\s+/g, '_')
            .toLowerCase();
        const timestamp = new Date().toISOString().slice(0, 19).replace(/[:-]/g, '').replace('T', '_');
        a.download = `nano_banana_${sanitizedPrompt}_${timestamp}.jpg`;
        
        // Добавляем ссылку в DOM, кликаем и удаляем
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        
        // Освобождаем URL
        window.URL.revokeObjectURL(url);
        
        console.log('[DOWNLOAD] Изображение успешно скачано');
        showToast('Изображение успешно скачано', 'success');
    } catch (error) {
        console.error('[DOWNLOAD] Ошибка скачивания изображения:', error);
        showToast('Ошибка скачивания изображения: ' + error.message, 'error');
    }
}

// Функция для открытия изображения в фуллскрине
function openFullscreenImage(imageUrl, prompt) {
    // Создаем модальное окно для фуллскрина
    const modal = document.createElement('div');
    modal.className = 'fullscreen-image-modal';
    modal.style.cssText = 'position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.95); z-index: 9999; display: flex; align-items: center; justify-content: center; cursor: pointer;';
    modal.onclick = () => closeFullscreenImage();
    
    const container = document.createElement('div');
    container.style.cssText = 'position: relative; max-width: 95%; max-height: 95%; display: flex; flex-direction: column; align-items: center;';
    container.onclick = (e) => e.stopPropagation();
    
    const img = document.createElement('img');
    img.src = imageUrl;
    img.style.cssText = 'max-width: 100%; max-height: 85vh; object-fit: contain; border-radius: 8px;';
    img.onclick = () => downloadImage(imageUrl, prompt);
    
    const closeBtn = document.createElement('button');
    closeBtn.className = 'btn btn-sm btn-light position-absolute';
    closeBtn.style.cssText = 'top: 10px; right: 10px; z-index: 10000;';
    closeBtn.innerHTML = '<i class="fas fa-times"></i>';
    closeBtn.onclick = () => closeFullscreenImage();
    
    const downloadBtn = document.createElement('button');
    downloadBtn.className = 'btn btn-sm btn-success mt-3';
    downloadBtn.innerHTML = '<i class="fas fa-download me-2"></i>Скачать изображение';
    downloadBtn.onclick = (e) => {
        e.stopPropagation();
        downloadImage(imageUrl, prompt);
    };
    
    const promptText = document.createElement('div');
    promptText.className = 'text-light text-center mt-2';
    promptText.style.cssText = 'max-width: 80%; font-size: 0.9rem; opacity: 0.8;';
    promptText.textContent = prompt;
    
    container.appendChild(closeBtn);
    container.appendChild(img);
    container.appendChild(downloadBtn);
    container.appendChild(promptText);
    modal.appendChild(container);
    
    document.body.appendChild(modal);
    document.body.style.overflow = 'hidden';
    
    // Закрытие по Escape
    const escapeHandler = (e) => {
        if (e.key === 'Escape') {
            closeFullscreenImage();
            document.removeEventListener('keydown', escapeHandler);
        }
    };
    document.addEventListener('keydown', escapeHandler);
}

function closeFullscreenImage() {
    const modal = document.querySelector('.fullscreen-image-modal');
    if (modal) {
        modal.remove();
        document.body.style.overflow = '';
    }
}

// Функция для показа параметров генерации
function showGenerationParams(id, prompt, resolution, aspectRatio, errorMessage) {
    // Логируем полученные данные
    console.log('[SHOW_PARAMS] Получены параметры:', {
        id: id,
        has_errorMessage: !!errorMessage,
        errorMessage_type: typeof errorMessage,
        errorMessage_length: errorMessage ? errorMessage.length : 0,
        errorMessage_preview: errorMessage ? errorMessage.substring(0, 100) : 'пусто'
    });
    
    // Закрываем предыдущее модальное окно если открыто
    const existingModal = document.querySelector('.generation-params-modal');
    if (existingModal) {
        existingModal.remove();
    }
    
    const modal = document.createElement('div');
    modal.className = 'generation-params-modal';
    modal.style.cssText = 'position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%); background: rgba(26, 26, 46, 0.98); border: 2px solid #667eea; border-radius: 12px; padding: 1.5rem; z-index: 10000; max-width: 600px; width: 90%; max-height: 90vh; overflow-y: auto; backdrop-filter: blur(10px); box-shadow: 0 10px 40px rgba(0, 0, 0, 0.5);';
    modal.onclick = (e) => {
        if (e.target === modal) closeGenerationParams();
    };
    
    // Экранируем все данные для безопасности
    const safePrompt = (prompt || '').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    const safeResolution = (resolution || 'Не указано').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    const safeAspectRatio = (aspectRatio || 'Не указано').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    // Убеждаемся что errorMessage обрабатывается правильно
    const safeErrorMessage = (errorMessage && errorMessage.trim()) ? errorMessage.replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;') : '';
    
    console.log('[SHOW_PARAMS] После обработки safeErrorMessage:', {
        has_safeErrorMessage: !!safeErrorMessage,
        safeErrorMessage_length: safeErrorMessage ? safeErrorMessage.length : 0,
        safeErrorMessage_preview: safeErrorMessage ? safeErrorMessage.substring(0, 100) : 'пусто'
    });
    
    const content = document.createElement('div');
    content.innerHTML = `
        <div class="d-flex justify-content-between align-items-center mb-3">
            <h5 class="text-light mb-0"><i class="fas fa-info-circle me-2"></i>Параметры генерации</h5>
            <button class="btn btn-sm btn-link text-light p-0" onclick="closeGenerationParams()" style="font-size: 1.5rem; line-height: 1; cursor: pointer;">
                <i class="fas fa-times"></i>
            </button>
        </div>
        <div class="text-light">
            <div class="mb-3">
                <p class="mb-2"><strong><i class="fas fa-comment me-2"></i>Промпт:</strong></p>
                <p class="mb-0 small" style="opacity: 0.9; background: rgba(102, 126, 234, 0.1); padding: 0.75rem; border-radius: 6px; word-wrap: break-word;">${safePrompt || 'Не указано'}</p>
            </div>
            <div class="row mb-3">
                <div class="col-md-6">
                    <p class="mb-2"><strong><i class="fas fa-expand me-2"></i>Разрешение:</strong></p>
                    <p class="mb-0"><span class="text-info">${safeResolution}</span></p>
                </div>
                <div class="col-md-6">
                    <p class="mb-2"><strong><i class="fas fa-arrows-alt me-2"></i>Соотношение сторон:</strong></p>
                    <p class="mb-0"><span class="text-info">${safeAspectRatio}</span></p>
                </div>
            </div>
            ${safeErrorMessage ? `
                <div class="mt-3 p-3" style="background: rgba(229, 62, 62, 0.2); border: 2px solid rgba(229, 62, 62, 0.7); border-radius: 8px;">
                    <div class="d-flex justify-content-between align-items-center mb-2">
                        <p class="mb-0 text-danger"><strong><i class="fas fa-exclamation-triangle me-2"></i>Ошибка генерации:</strong></p>
                        <button class="btn btn-sm btn-outline-light copy-error-btn" data-error-id="${id}" title="Скопировать лог ошибки" style="font-size: 0.75rem; padding: 0.25rem 0.5rem;">
                            <i class="fas fa-copy me-1"></i>Копировать лог
                        </button>
                    </div>
                    <div class="error-message-content" style="background: rgba(0, 0, 0, 0.3); padding: 0.75rem; border-radius: 4px; max-height: 200px; overflow-y: auto;">
                        <p class="mb-0 small text-light" style="opacity: 0.95; word-wrap: break-word; white-space: pre-wrap; font-family: 'Courier New', monospace;">${safeErrorMessage}</p>
                    </div>
                </div>
            ` : ''}
        </div>
    `;
    
    modal.appendChild(content);
    document.body.appendChild(modal);
    document.body.style.overflow = 'hidden';
    
    // Обработчик кнопки копирования лога ошибки
    if (safeErrorMessage) {
        const copyBtn = modal.querySelector('.copy-error-btn');
        if (copyBtn) {
            copyBtn.addEventListener('click', async () => {
                await copyErrorLog(id, prompt, resolution, aspectRatio, errorMessage);
            });
        }
    }
    
    // Закрытие по Escape
    const escapeHandler = (e) => {
        if (e.key === 'Escape') {
            closeGenerationParams();
            document.removeEventListener('keydown', escapeHandler);
        }
    };
    document.addEventListener('keydown', escapeHandler);
    
    console.log('[MODAL] Модальное окно параметров открыто, errorMessage:', errorMessage);
}

// Функция для копирования лога ошибки в буфер обмена
async function copyErrorLog(id, prompt, resolution, aspectRatio, errorMessage) {
    try {
        // Формируем полный лог ошибки
        const errorLog = `=== ЛОГ ОШИБКИ ГЕНЕРАЦИИ ===
ID генерации: ${id}
Дата: ${new Date().toLocaleString('ru-RU')}

ПАРАМЕТРЫ ГЕНЕРАЦИИ:
Промпт: ${prompt || 'Не указано'}
Разрешение: ${resolution || 'Не указано'}
Соотношение сторон: ${aspectRatio || 'Не указано'}

ОШИБКА:
${errorMessage || 'Ошибка не указана'}

=== КОНЕЦ ЛОГА ===`;

        // Копируем в буфер обмена
        if (navigator.clipboard && navigator.clipboard.writeText) {
            await navigator.clipboard.writeText(errorLog);
            showToast('Лог ошибки скопирован в буфер обмена', 'success');
            
            // Визуальная обратная связь
            const copyBtn = document.querySelector(`.copy-error-btn[data-error-id="${id}"]`);
            if (copyBtn) {
                const originalHTML = copyBtn.innerHTML;
                copyBtn.innerHTML = '<i class="fas fa-check me-1"></i>Скопировано!';
                copyBtn.classList.add('btn-success');
                copyBtn.classList.remove('btn-outline-light');
                
                setTimeout(() => {
                    copyBtn.innerHTML = originalHTML;
                    copyBtn.classList.remove('btn-success');
                    copyBtn.classList.add('btn-outline-light');
                }, 2000);
            }
        } else {
            // Fallback для старых браузеров
            const textArea = document.createElement('textarea');
            textArea.value = errorLog;
            textArea.style.position = 'fixed';
            textArea.style.left = '-999999px';
            document.body.appendChild(textArea);
            textArea.select();
            document.execCommand('copy');
            document.body.removeChild(textArea);
            showToast('Лог ошибки скопирован в буфер обмена', 'success');
        }
        
        console.log('[COPY] Лог ошибки скопирован:', errorLog);
    } catch (error) {
        console.error('[COPY] Ошибка копирования лога:', error);
        showToast('Ошибка копирования лога: ' + error.message, 'error');
    }
}

function closeGenerationParams() {
    const modal = document.querySelector('.generation-params-modal');
    if (modal) {
        modal.remove();
        document.body.style.overflow = '';
    }
}

// Инициализация темы
function initTheme() {
    const savedTheme = localStorage.getItem('theme') || 'system';
    const systemDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    
    document.documentElement.setAttribute('data-bs-theme', 
        (savedTheme === 'dark' || (savedTheme === 'system' && systemDark)) ? 'dark' : 'light'
    );
    document.getElementById('themeSwitch').checked = (savedTheme === 'dark');
}

// Переключение темы
document.getElementById('themeSwitch').addEventListener('change', function(e) {
    const isDark = e.target.checked;
    localStorage.setItem('theme', isDark ? 'dark' : 'light');
    document.documentElement.setAttribute('data-bs-theme', isDark ? 'dark' : 'light');
});

