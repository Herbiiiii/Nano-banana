#!/bin/bash
echo "Запуск Nano Banana Pro UI..."
echo ""
echo "Убедитесь, что установлены зависимости:"
echo "  pip install -r requirements.txt"
echo ""
echo "Установите API ключ (опционально):"
echo "  export REPLICATE_API_TOKEN=ваш_ключ"
echo ""
streamlit run app.py

