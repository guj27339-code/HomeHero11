# Development notes

## Локальный запуск

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 -u app.py
```

## Сброс локальной базы

```bash
rm -f instance/homehero.db
python3 -u app.py
```

## Безопасность

Не коммитьте:

- `.env`
- `instance/homehero.db`
- реальные документы
- реальные фото пользователей
- секретные ключи
