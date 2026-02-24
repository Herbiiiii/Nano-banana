-- Миграция: добавление колонки model_name в таблицу generations
-- Выполнить этот SQL в базе данных

-- Проверяем, существует ли колонка, и добавляем её если нет
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 
        FROM information_schema.columns 
        WHERE table_name = 'generations' 
        AND column_name = 'model_name'
    ) THEN
        ALTER TABLE generations ADD COLUMN model_name VARCHAR;
        -- Проставляем значение по умолчанию для существующих записей
        UPDATE generations SET model_name = 'nano-banana-pro' WHERE model_name IS NULL;
        RAISE NOTICE 'Колонка model_name успешно добавлена';
    ELSE
        RAISE NOTICE 'Колонка model_name уже существует';
    END IF;
END $$;

