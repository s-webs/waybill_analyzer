# Waybill Analyzer API

HTTP-сервис на FastAPI для анализа накладных по фото через OpenAI vision-модели.

## Возможности

- HTTP endpoint для анализа накладной (`POST /analyze`)
- Health endpoint (`GET /health`)
- Структурированный JSON-ответ для интеграции с `alfoods`
- Валидация и обогащение результата (`validators.py`)

---

## Установка

```bash
# 1. Создайте виртуальное окружение
python -m venv .venv

# 2. Активируйте его
# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate

# 3. Установите зависимости
pip install -r requirements.txt
```

---

## Запуск

```bash
uvicorn api_server:app --host 0.0.0.0 --port 8001
```

API будет доступен на `http://localhost:8001`:
- `GET /health`
- `POST /analyze` (multipart `file`)
- `GET /ui` (небольшой web-интерфейс для ручной загрузки скриншотов/накладных)

---

## Использование с OpenAI

1. Скопируйте файл окружения:
   ```bash
   cp .env.example .env
   ```
2. Откройте `.env` и добавьте ваш ключ:
   ```
   OPENAI_API_KEY=sk-...
   ```
3. Запускайте сервис как обычно, модель можно передавать параметром `model` в `POST /analyze`.

---

## Структура проекта

```
alfoods_waybill_analyzer/
├── api_server.py        # FastAPI transport
├── ai_clients.py        # Клиент OpenAI
├── schemas.py           # Pydantic-схемы
├── prompts.py           # Системный промпт
├── validators.py        # Валидация результата AI
├── API_CONTRACT.md      # Контракт HTTP API
├── requirements.txt
├── .env.example
```

---

## Требования

- Python 3.11+
- OpenAI API Key
- ~200 MB RAM (зависит от нагрузки и модели)
- GPU не обязателен

---

## Docker (для VPS)

### 1) Подготовка

1. Установите Docker и Docker Compose на VPS.
2. Скопируйте проект на сервер.
3. Создайте `.env` рядом с `docker-compose.yml`:

```bash
cp .env.example .env
```

И добавьте ключ:

```env
OPENAI_API_KEY=sk-...
```

### 2) Сборка и запуск

```bash
docker compose up -d --build
```

API будет доступен на `http://<YOUR_VPS_IP>:8001`.

### 3) Полезные команды

```bash
# Логи
docker compose logs -f

# Перезапуск
docker compose restart

# Остановка
docker compose down
```

## Примечания

- Если модель возвращает JSON в markdown-блоках, сервис очищает ответ автоматически.
- Для интеграции и примеров payload/response см. `API_CONTRACT.md`.
- UI на `/ui` использует тот же `POST /analyze`, поэтому API-контракт для приложений не меняется.
