from app import app, init_db

# Инициализация SQLite при старте Gunicorn/production-сервера
init_db()

application = app

if __name__ == "__main__":
    app.run()
