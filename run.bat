@echo off
echo Запуск Nano Banana Pro UI...
echo.
echo Убедитесь, что установлены зависимости:
echo   pip install -r requirements.txt
echo.
echo Установите API ключ (опционально):
echo   set REPLICATE_API_TOKEN=ваш_ключ
echo.
pause
streamlit run app.py

