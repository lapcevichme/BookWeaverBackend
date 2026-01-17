# BookWeaver Utilities

Набор утилит для автоматизации сбора контента, очистки данных и подготовки ассетов (аудио/текст) для проекта.

## Начало работы

### 1. Установка зависимостей
```
pip install requests pydub pygame
```
> **Важно:** Для работы с аудио (`import_audio.py`) в системе должен быть установлен **FFmpeg**.

### 2. Настройка .env
Добавьте в `.env` в корне проекта ключи:
```
RANOBELIB_USER_TOKEN=твой_bearer
ELEVENLABS_API_KEY=твой_api_key
```
> **Важно**: Токен Ranobelib можно достать из большинства запросов с их сайта. Посмотреть код страницы -> Network -> Перезагрузить станицу. Ориентируйтесь на xhr запросы -> Тык -> Снизу Request Headers где будет Bearer (очень длинная строка)
---

## Утилиты

### 1. Загрузчик Ранобэ (ranobelib_loader.py)
Парсит книги, сохраняя структуру, главы, обложку и метаданные.

**Запуск:**
```
# Интерактивно
python ranobelib_loader.py

# По прямой ссылке
python ranobelib_loader.py https://ranobelib.me/ru/book/12345--title
```
**Результат:** Папка в `input/` с файлами `chapter_X.txt` и `metadata.json`.

---

### 2. Очистка Текста (text_cleaner.py)
Нормализует текст: удаляет NBSP, zero-width spaces, чистит абзацы.

**Запуск:**
```
# Очистить папку input/raw_text (по умолчанию)
python text_cleaner.py

# Указать папку и искать рекурсивно
python text_cleaner.py "путь/к/книгам" -r
```
---

### 3. Импорт Аудио (import_audio.py)
Подготавливает аудио (эмбиент, SFX): нормализует громкость, обрезает тишину, делает Fade-In/Out.

**Запуск:**
```
# Обработать input/raw_audio -> assets/ambient
python import_audio.py

# Задать громкость (например, -14dB для голоса)
python import_audio.py --db -14.0
```
---

### 4. Подбор Голосов (voice_picker.py)
Кастинг голосов через ElevenLabs по тегам.

**Запуск:**
```
python voice_picker.py
```
Следуйте инструкциям в консоли для прослушивания и сохранения вариантов.