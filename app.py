
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path

from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "instance" / "homehero.db"

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "homehero-secret-change-me")
app.config["DATABASE"] = str(DB_PATH)
app.config["UPLOAD_FOLDER"] = str(BASE_DIR / "static" / "uploads")
app.config["MAX_CONTENT_LENGTH"] = 3 * 1024 * 1024
ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}

STATUS_LABELS = {
    "new": "Новый",
    "assigned": "Назначен",
    "in_progress": "В работе",
    "completed": "Завершён",
    "cancelled": "Отменён",
}
PAYMENT_LABELS = {
    "created": "Ожидает оплаты",
    "hold": "Безопасная сделка",
    "authorized": "Средства заморожены",
    "released": "Оплачено мастеру",
    "returned": "Возврат",
    "failed": "Ошибка оплаты",
}

TICKET_STATUS_LABELS = {
    "open": "Открыто",
    "in_progress": "В работе",
    "waiting_user": "Ждём клиента",
    "closed": "Закрыто",
}

TICKET_PRIORITY_LABELS = {
    "low": "Низкий",
    "normal": "Обычный",
    "high": "Высокий",
    "critical": "Критичный",
}

VERIFICATION_STATUS_LABELS = {
    "unsubmitted": "Не отправлена",
    "pending": "На проверке",
    "verified": "Проверен",
    "rejected": "Отклонена",
}

SMART_QUESTIONS = {
    "Сантехника": [
        "Что именно сломалось?",
        "Есть ли протечка сейчас?",
        "Нужно ли купить материалы?",
        "Есть ли доступ к стояку или перекрытию воды?",
    ],
    "Электрика": [
        "Что не работает: розетка, свет, автомат или проводка?",
        "Есть ли запах гари или искры?",
        "Нужно ли срочно приехать сегодня?",
        "Сколько точек нужно проверить?",
    ],
    "Уборка": [
        "Сколько комнат?",
        "Нужна ли уборка после ремонта?",
        "Нужно ли мыть окна?",
        "Есть ли домашние животные?",
    ],
    "Сборка мебели": [
        "Какая мебель: шкаф, кухня, стол, кровать?",
        "Есть ли инструкция и все детали?",
        "Нужен ли демонтаж старой мебели?",
        "Есть ли лифт или сложный подъём?",
    ],
    "Мелкий ремонт": [
        "Какие работы нужно выполнить?",
        "Нужны ли материалы мастера?",
        "Есть ли фото проблемы?",
        "Сколько примерно задач в заказе?",
    ],
    "Техника": [
        "Какая техника?",
        "Нужно подключение, установка или диагностика?",
        "Есть ли гарантия производителя?",
        "Нужны ли расходники или крепления?",
    ],
}

PAYMENT_EVENT_LABELS = {
    "created": "Создан платёж",
    "authorized": "Средства заморожены",
    "paid": "Оплачено",
    "released": "Выплата мастеру",
    "refund": "Возврат клиенту",
    "failed": "Ошибка оплаты",
}

DISPUTE_STATUS_LABELS = {
    "open": "Открыт",
    "review": "На рассмотрении",
    "resolved_refund": "Возврат клиенту",
    "resolved_payout": "Выплата мастеру",
    "resolved_rework": "Повторный выезд",
    "closed": "Закрыт",
}


def db():
    if "db" not in g:
        g.db = sqlite3.connect(app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(error=None):
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()


def one(sql, params=()):
    return db().execute(sql, params).fetchone()


def all_rows(sql, params=()):
    return db().execute(sql, params).fetchall()


def run(sql, params=()):
    cur = db().execute(sql, params)
    db().commit()
    return cur


def allowed_image(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS


def password_errors(password):
    errors = []
    if len(password) < 8:
        errors.append("минимум 8 символов")
    if not any(ch.isdigit() for ch in password):
        errors.append("хотя бы одна цифра")
    if not any(ch.isalpha() for ch in password):
        errors.append("хотя бы одна буква")
    if password.lower() in {"password", "qwerty", "12345678", "homehero", "admin123", "demo123"}:
        errors.append("пароль слишком простой")
    return errors


def is_verified(user):
    return user is not None and user["verification_status"] == "verified"


def avatar_src(user):
    try:
        filename = user["avatar_file"]
    except Exception:
        filename = None
    if filename:
        return url_for("static", filename=f"uploads/{filename}")
    return ""


def notify_user(user_id, title, message):
    if not user_id:
        return
    try:
        run(
            "INSERT INTO notifications(user_id, title, message, created_at) VALUES (?, ?, ?, ?)",
            (user_id, title, message, datetime.now().isoformat(timespec="seconds")),
        )
    except Exception:
        pass


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row

    connection.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT NOT NULL UNIQUE,
        phone TEXT DEFAULT '',
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'customer',
        city TEXT DEFAULT 'Москва',
        bio TEXT DEFAULT '',
        avatar TEXT DEFAULT 'HH',
        avatar_file TEXT DEFAULT '',
        balance INTEGER NOT NULL DEFAULT 0,
        verification_status TEXT NOT NULL DEFAULT 'unsubmitted',
        passport_series TEXT DEFAULT '',
        passport_number TEXT DEFAULT '',
        birth_date TEXT DEFAULT '',
        passport_issued_by TEXT DEFAULT '',
        passport_issue_date TEXT DEFAULT '',
        passport_photo_file TEXT DEFAULT '',
        selfie_photo_file TEXT DEFAULT '',
        verification_comment TEXT DEFAULT '',
        verified_at TEXT DEFAULT '',
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        description TEXT NOT NULL,
        icon TEXT NOT NULL,
        base_price INTEGER NOT NULL
    );

    CREATE TABLE IF NOT EXISTS master_profiles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL UNIQUE,
        categories TEXT NOT NULL DEFAULT '',
        experience_years INTEGER NOT NULL DEFAULT 1,
        hourly_rate INTEGER NOT NULL DEFAULT 1200,
        verified INTEGER NOT NULL DEFAULT 0,
        documents_status TEXT NOT NULL DEFAULT 'На проверке',
        safety_badge TEXT DEFAULT 'Базовая проверка',
        completed_orders INTEGER NOT NULL DEFAULT 0,
        rating REAL NOT NULL DEFAULT 5.0,
        FOREIGN KEY (user_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id INTEGER NOT NULL,
        master_id INTEGER,
        category_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        description TEXT NOT NULL,
        address TEXT NOT NULL,
        scheduled_at TEXT NOT NULL,
        budget INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'new',
        payment_status TEXT NOT NULL DEFAULT 'hold',
        created_at TEXT NOT NULL,
        FOREIGN KEY (customer_id) REFERENCES users(id),
        FOREIGN KEY (master_id) REFERENCES users(id),
        FOREIGN KEY (category_id) REFERENCES categories(id)
    );

    CREATE TABLE IF NOT EXISTS reviews (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER NOT NULL UNIQUE,
        customer_id INTEGER NOT NULL,
        master_id INTEGER NOT NULL,
        rating INTEGER NOT NULL,
        text TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (order_id) REFERENCES orders(id),
        FOREIGN KEY (customer_id) REFERENCES users(id),
        FOREIGN KEY (master_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        order_id INTEGER,
        amount INTEGER NOT NULL,
        type TEXT NOT NULL,
        description TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (order_id) REFERENCES orders(id)
    );

    CREATE TABLE IF NOT EXISTS support_tickets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        order_id INTEGER,
        assigned_to INTEGER,
        topic TEXT NOT NULL,
        message TEXT NOT NULL,
        priority TEXT NOT NULL DEFAULT 'normal',
        status TEXT NOT NULL DEFAULT 'open',
        created_at TEXT NOT NULL,
        updated_at TEXT,
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (assigned_to) REFERENCES users(id),
        FOREIGN KEY (order_id) REFERENCES orders(id)
    );

    CREATE TABLE IF NOT EXISTS support_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticket_id INTEGER NOT NULL,
        sender_id INTEGER NOT NULL,
        message TEXT NOT NULL,
        is_internal INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        FOREIGN KEY (ticket_id) REFERENCES support_tickets(id),
        FOREIGN KEY (sender_id) REFERENCES users(id)
    );


    CREATE TABLE IF NOT EXISTS order_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER NOT NULL,
        sender_id INTEGER NOT NULL,
        message TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (order_id) REFERENCES orders(id),
        FOREIGN KEY (sender_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS order_photos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER NOT NULL,
        uploaded_by INTEGER NOT NULL,
        photo_type TEXT NOT NULL,
        filename TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (order_id) REFERENCES orders(id),
        FOREIGN KEY (uploaded_by) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS warranties (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER NOT NULL UNIQUE,
        expires_at TEXT NOT NULL,
        terms TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (order_id) REFERENCES orders(id)
    );

    CREATE TABLE IF NOT EXISTS complaints (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        target_user_id INTEGER,
        order_id INTEGER,
        reason TEXT NOT NULL,
        details TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'open',
        created_at TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (target_user_id) REFERENCES users(id),
        FOREIGN KEY (order_id) REFERENCES orders(id)
    );

    CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        message TEXT NOT NULL,
        is_read INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS promo_codes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT NOT NULL UNIQUE,
        discount_percent INTEGER NOT NULL,
        active INTEGER NOT NULL DEFAULT 1,
        description TEXT DEFAULT ''
    );

    CREATE TABLE IF NOT EXISTS master_settings (
        user_id INTEGER PRIMARY KEY,
        work_status TEXT NOT NULL DEFAULT 'offline',
        urgent_enabled INTEGER NOT NULL DEFAULT 0,
        pro_until TEXT DEFAULT '',
        reliability_score INTEGER NOT NULL DEFAULT 95,
        FOREIGN KEY (user_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS master_availability (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        master_id INTEGER NOT NULL,
        weekday TEXT NOT NULL,
        start_time TEXT NOT NULL,
        end_time TEXT NOT NULL,
        FOREIGN KEY (master_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS portfolio_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        master_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        filename TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (master_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS support_templates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        body TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS support_ratings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticket_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        rating INTEGER NOT NULL,
        comment TEXT DEFAULT '',
        created_at TEXT NOT NULL,
        FOREIGN KEY (ticket_id) REFERENCES support_tickets(id),
        FOREIGN KEY (user_id) REFERENCES users(id)
    );


    CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        amount INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'created',
        provider TEXT NOT NULL DEFAULT 'DemoPay',
        card_mask TEXT DEFAULT '',
        created_at TEXT NOT NULL,
        FOREIGN KEY (order_id) REFERENCES orders(id),
        FOREIGN KEY (user_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS payment_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        payment_id INTEGER NOT NULL,
        event TEXT NOT NULL,
        note TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (payment_id) REFERENCES payments(id)
    );

    CREATE TABLE IF NOT EXISTS disputes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER NOT NULL,
        opened_by INTEGER NOT NULL,
        reason TEXT NOT NULL,
        customer_position TEXT NOT NULL,
        master_position TEXT DEFAULT '',
        resolution TEXT DEFAULT '',
        status TEXT NOT NULL DEFAULT 'open',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (order_id) REFERENCES orders(id),
        FOREIGN KEY (opened_by) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS dispute_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        dispute_id INTEGER NOT NULL,
        sender_id INTEGER NOT NULL,
        message TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (dispute_id) REFERENCES disputes(id),
        FOREIGN KEY (sender_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS order_intake_answers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER NOT NULL,
        question TEXT NOT NULL,
        answer TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (order_id) REFERENCES orders(id)
    );

    CREATE TABLE IF NOT EXISTS service_areas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        city TEXT NOT NULL,
        base_trip_price INTEGER NOT NULL DEFAULT 0,
        avg_arrival_minutes INTEGER NOT NULL DEFAULT 60,
        active INTEGER NOT NULL DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS favorites (
        user_id INTEGER NOT NULL,
        master_id INTEGER NOT NULL,
        PRIMARY KEY (user_id, master_id),
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (master_id) REFERENCES users(id)
    );
    """)

    # Lightweight migrations for older local databases
    user_cols = {row["name"] for row in connection.execute("PRAGMA table_info(users)").fetchall()}
    user_migrations = {
        "avatar_file": "TEXT DEFAULT ''",
        "balance": "INTEGER NOT NULL DEFAULT 0",
        "verification_status": "TEXT NOT NULL DEFAULT 'unsubmitted'",
        "passport_series": "TEXT DEFAULT ''",
        "passport_number": "TEXT DEFAULT ''",
        "birth_date": "TEXT DEFAULT ''",
        "passport_issued_by": "TEXT DEFAULT ''",
        "passport_issue_date": "TEXT DEFAULT ''",
        "passport_photo_file": "TEXT DEFAULT ''",
        "selfie_photo_file": "TEXT DEFAULT ''",
        "verification_comment": "TEXT DEFAULT ''",
        "verified_at": "TEXT DEFAULT ''",
    }
    for col, ddl in user_migrations.items():
        if col not in user_cols:
            connection.execute(f"ALTER TABLE users ADD COLUMN {col} {ddl}")

    connection.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            order_id INTEGER,
            amount INTEGER NOT NULL,
            type TEXT NOT NULL,
            description TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (order_id) REFERENCES orders(id)
        )
    """)

    ticket_cols = {row["name"] for row in connection.execute("PRAGMA table_info(support_tickets)").fetchall()}
    if "assigned_to" not in ticket_cols:
        connection.execute("ALTER TABLE support_tickets ADD COLUMN assigned_to INTEGER")
    if "priority" not in ticket_cols:
        connection.execute("ALTER TABLE support_tickets ADD COLUMN priority TEXT NOT NULL DEFAULT 'normal'")
    if "updated_at" not in ticket_cols:
        connection.execute("ALTER TABLE support_tickets ADD COLUMN updated_at TEXT")
    connection.execute("""
        CREATE TABLE IF NOT EXISTS support_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id INTEGER NOT NULL,
            sender_id INTEGER NOT NULL,
            message TEXT NOT NULL,
            is_internal INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY (ticket_id) REFERENCES support_tickets(id),
            FOREIGN KEY (sender_id) REFERENCES users(id)
        )
    """)


    connection.executescript("""
        CREATE TABLE IF NOT EXISTS order_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            sender_id INTEGER NOT NULL,
            message TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS order_photos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            uploaded_by INTEGER NOT NULL,
            photo_type TEXT NOT NULL,
            filename TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS warranties (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL UNIQUE,
            expires_at TEXT NOT NULL,
            terms TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS complaints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            target_user_id INTEGER,
            order_id INTEGER,
            reason TEXT NOT NULL,
            details TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            is_read INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS promo_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL UNIQUE,
            discount_percent INTEGER NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            description TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS master_settings (
            user_id INTEGER PRIMARY KEY,
            work_status TEXT NOT NULL DEFAULT 'offline',
            urgent_enabled INTEGER NOT NULL DEFAULT 0,
            pro_until TEXT DEFAULT '',
            reliability_score INTEGER NOT NULL DEFAULT 95
        );

        CREATE TABLE IF NOT EXISTS master_availability (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            master_id INTEGER NOT NULL,
            weekday TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS portfolio_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            master_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            filename TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS support_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            body TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS support_ratings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            rating INTEGER NOT NULL,
            comment TEXT DEFAULT '',
            created_at TEXT NOT NULL
        );
    """)

    order_cols = {row["name"] for row in connection.execute("PRAGMA table_info(orders)").fetchall()}
    order_migrations = {
        "urgent": "INTEGER NOT NULL DEFAULT 0",
        "promo_code": "TEXT DEFAULT ''",
        "discount": "INTEGER NOT NULL DEFAULT 0",
        "final_price": "INTEGER NOT NULL DEFAULT 0",
    }
    for col, ddl in order_migrations.items():
        if col not in order_cols:
            connection.execute(f"ALTER TABLE orders ADD COLUMN {col} {ddl}")

    connection.executescript("""
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'created',
            provider TEXT NOT NULL DEFAULT 'DemoPay',
            card_mask TEXT DEFAULT '',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS payment_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            payment_id INTEGER NOT NULL,
            event TEXT NOT NULL,
            note TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS disputes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            opened_by INTEGER NOT NULL,
            reason TEXT NOT NULL,
            customer_position TEXT NOT NULL,
            master_position TEXT DEFAULT '',
            resolution TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'open',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS dispute_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dispute_id INTEGER NOT NULL,
            sender_id INTEGER NOT NULL,
            message TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS order_intake_answers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS service_areas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            city TEXT NOT NULL,
            base_trip_price INTEGER NOT NULL DEFAULT 0,
            avg_arrival_minutes INTEGER NOT NULL DEFAULT 60,
            active INTEGER NOT NULL DEFAULT 1
        );
    """)

    service_areas = [
        ("Центр", "Москва", 0, 35, 1),
        ("Север", "Москва", 300, 45, 1),
        ("Юг", "Москва", 300, 50, 1),
        ("Запад", "Москва", 250, 45, 1),
        ("Восток", "Москва", 350, 55, 1),
        ("Подмосковье", "Москва и область", 700, 90, 1),
    ]
    connection.executemany(
        "INSERT OR IGNORE INTO service_areas(name, city, base_trip_price, avg_arrival_minutes, active) VALUES (?, ?, ?, ?, ?)",
        service_areas,
    )


    categories = [
        ("Сантехника", "Протечки, смесители, трубы, подключение техники", "🚿", 2500),
        ("Электрика", "Розетки, свет, диагностика, срочный выезд", "💡", 3000),
        ("Уборка", "Клининг квартиры, генеральная уборка, после ремонта", "🧹", 2200),
        ("Сборка мебели", "Шкафы, кухни, столы, стеллажи, гардеробные", "🛠️", 2800),
        ("Мелкий ремонт", "Мастер на час, крепления, отделочные работы", "🏠", 3500),
        ("Техника", "Установка, подключение и настройка бытовой техники", "📦", 2600),
    ]
    connection.executemany(
        "INSERT OR IGNORE INTO categories(name, description, icon, base_price) VALUES (?, ?, ?, ?)",
        categories,
    )

    now = datetime.now().isoformat(timespec="seconds")
    demo_users = [
        ("Администратор", "admin@homehero.ru", "+7 900 000-00-00", "admin123", "admin", "Москва", "Администрирование платформы", "AD"),
        ("Сотрудник поддержки", "support@homehero.ru", "+7 900 100-10-10", "support123", "support", "Москва", "Поддержка клиентов, споры и безопасность", "SP"),
        ("Ольга Петрова", "olga@example.ru", "+7 916 111-22-33", "demo123", "customer", "Москва", "Семейный пользователь, ценит гарантию качества", "ОП"),
        ("Алексей Смирнов", "alex@example.ru", "+7 925 222-33-44", "demo123", "customer", "Москва", "Молодой профессионал, хочет всё в пару кликов", "АС"),
        ("Иван Кузнецов", "ivan.master@example.ru", "+7 903 333-44-55", "demo123", "master", "Москва", "Сантехник и мастер на час. Даю гарантию.", "ИК"),
        ("Марина Орлова", "marina.clean@example.ru", "+7 901 444-55-66", "demo123", "master", "Москва", "Клининг квартир и уборка после ремонта.", "МО"),
        ("Дмитрий Волков", "dmitry.electric@example.ru", "+7 909 555-66-77", "demo123", "master", "Москва", "Электрик с опытом, безопасный монтаж.", "ДВ"),
    ]
    for name, email, phone, password, role, city, bio, avatar in demo_users:
        connection.execute(
            """
            INSERT OR IGNORE INTO users
            (name, email, phone, password_hash, role, city, bio, avatar, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (name, email, phone, generate_password_hash(password), role, city, bio, avatar, now),
        )


    promo_codes = [
        ("FIRST10", 10, 1, "Скидка 10% на первый заказ"),
        ("CLEAN15", 15, 1, "Скидка на уборку"),
        ("FRIEND500", 5, 1, "Реферальная скидка для друзей"),
        ("URGENT5", 5, 1, "Скидка на срочный вызов"),
    ]
    connection.executemany(
        "INSERT OR IGNORE INTO promo_codes(code, discount_percent, active, description) VALUES (?, ?, ?, ?)",
        promo_codes,
    )

    support_templates = [
        ("Мастер опаздывает", "Здравствуйте! Мы уже проверяем статус мастера. Если задержка подтвердится, предложим перенос, замену исполнителя или отмену заказа."),
        ("Работа выполнена плохо", "Пожалуйста, приложите фото результата. Мы проверим заказ и предложим повторный выезд, компенсацию или возврат."),
        ("Нужен возврат", "Мы открыли проверку по оплате. До решения спорной ситуации средства не будут перечислены исполнителю."),
        ("Экстренная ситуация", "Если есть угроза жизни или здоровью, сначала обратитесь в экстренные службы. Мы зафиксировали обращение и передадим данные по заказу."),
    ]
    connection.executemany(
        "INSERT OR IGNORE INTO support_templates(title, body) VALUES (?, ?)",
        support_templates,
    )


    # Demo accounts are pre-verified so the project can be tested immediately.
    connection.execute("UPDATE users SET verification_status='verified', verified_at=? WHERE email IN ('admin@homehero.ru','support@homehero.ru','olga@example.ru','alex@example.ru','ivan.master@example.ru','marina.clean@example.ru','dmitry.electric@example.ru')", (now,))

    masters = connection.execute("SELECT id, email FROM users WHERE role='master'").fetchall()
    for master in masters:
        if "ivan" in master["email"]:
            data = (master["id"], "Сантехника,Мелкий ремонт,Сборка мебели", 6, 1600, 1, "Паспорт проверен", "Проверенный мастер", 128, 4.9)
        elif "marina" in master["email"]:
            data = (master["id"], "Уборка", 4, 1300, 1, "Паспорт проверен", "Проверенный мастер", 96, 4.8)
        else:
            data = (master["id"], "Электрика,Техника", 8, 1800, 1, "Паспорт проверен", "Проверенный мастер", 143, 5.0)
        connection.execute(
            """
            INSERT OR IGNORE INTO master_profiles
            (user_id, categories, experience_years, hourly_rate, verified, documents_status, safety_badge, completed_orders, rating)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            data,
        )

    for master in masters:
        connection.execute(
            "INSERT OR IGNORE INTO master_settings(user_id, work_status, urgent_enabled, reliability_score) VALUES (?, ?, ?, ?)",
            (master["id"], "online", 1, 96),
        )
        existing_availability = connection.execute("SELECT COUNT(*) AS c FROM master_availability WHERE master_id=?", (master["id"],)).fetchone()["c"]
        if existing_availability == 0:
            for weekday in ["Пн", "Вт", "Ср", "Чт", "Пт"]:
                connection.execute(
                    "INSERT INTO master_availability(master_id, weekday, start_time, end_time) VALUES (?, ?, ?, ?)",
                    (master["id"], weekday, "09:00", "19:00"),
                )

    review_count = connection.execute("SELECT COUNT(*) AS c FROM reviews").fetchone()["c"]
    if review_count == 0:
        customer = connection.execute("SELECT id FROM users WHERE email='olga@example.ru'").fetchone()["id"]
        master = connection.execute("SELECT id FROM users WHERE email='ivan.master@example.ru'").fetchone()["id"]
        category = connection.execute("SELECT id FROM categories WHERE name='Сантехника'").fetchone()["id"]
        cur = connection.execute(
            """
            INSERT INTO orders(customer_id, master_id, category_id, title, description, address, scheduled_at, budget, status, payment_status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (customer, master, category, "Починить смеситель", "Капает смеситель на кухне", "Москва, ул. Примерная, 10", (datetime.now() - timedelta(days=5)).isoformat(timespec="minutes"), 3000, "completed", "released", now),
        )
        connection.execute(
            "INSERT INTO reviews(order_id, customer_id, master_id, rating, text, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (cur.lastrowid, customer, master, 5, "Мастер приехал вовремя, всё сделал аккуратно и объяснил стоимость.", now),
        )

    connection.commit()
    connection.close()


@app.before_request
def load_user():
    user_id = session.get("user_id")
    g.user = one("SELECT * FROM users WHERE id=?", (user_id,)) if user_id else None


@app.context_processor
def globals_for_templates():
    try:
        categories = all_rows("SELECT * FROM categories ORDER BY name")
    except Exception:
        categories = []
    return {
        "nav_categories": categories,
        "status_labels": STATUS_LABELS,
        "payment_labels": PAYMENT_LABELS,
        "ticket_status_labels": TICKET_STATUS_LABELS,
        "ticket_priority_labels": TICKET_PRIORITY_LABELS,
        "verification_status_labels": VERIFICATION_STATUS_LABELS,
        "payment_event_labels": PAYMENT_EVENT_LABELS,
        "dispute_status_labels": DISPUTE_STATUS_LABELS,
        "avatar_src": avatar_src,
        "is_verified": is_verified,
        "current_year": datetime.now().year,
    }


def login_required(view):
    @wraps(view)
    def wrapped(**kwargs):
        if g.user is None:
            flash("Сначала войдите в аккаунт.", "warning")
            return redirect(url_for("login", next=request.path))
        return view(**kwargs)
    return wrapped


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped(**kwargs):
            if g.user is None:
                flash("Сначала войдите в аккаунт.", "warning")
                return redirect(url_for("login"))
            if g.user["role"] not in roles:
                abort(403)
            return view(**kwargs)
        return wrapped
    return decorator


def verification_required(view):
    @wraps(view)
    def wrapped(**kwargs):
        if g.user is None:
            flash("Сначала войдите в аккаунт.", "warning")
            return redirect(url_for("login"))
        if not is_verified(g.user):
            flash("Для заказа услуг и принятия заказов нужно пройти верификацию.", "warning")
            return redirect(url_for("verification", next=request.path))
        return view(**kwargs)
    return wrapped


def refresh_rating(master_id):
    stats = one("SELECT AVG(rating) AS r, COUNT(*) AS c FROM reviews WHERE master_id=?", (master_id,))
    completed = one("SELECT COUNT(*) AS c FROM orders WHERE master_id=? AND status='completed'", (master_id,))["c"]
    run("UPDATE master_profiles SET rating=?, completed_orders=? WHERE user_id=?", (round(stats["r"] or 5, 2), completed, master_id))


def order_or_404(order_id):
    order = one(
        """
        SELECT o.*, c.name AS category_name, c.icon AS category_icon,
               cu.name AS customer_name, cu.phone AS customer_phone,
               mu.name AS master_name, mu.phone AS master_phone
        FROM orders o
        JOIN categories c ON c.id=o.category_id
        JOIN users cu ON cu.id=o.customer_id
        LEFT JOIN users mu ON mu.id=o.master_id
        WHERE o.id=?
        """,
        (order_id,),
    )
    if not order:
        abort(404)
    if g.user["role"] != "admin" and g.user["id"] not in [order["customer_id"], order["master_id"]]:
        abort(403)
    return order


def ticket_or_404(ticket_id):
    ticket = one(
        """
        SELECT t.*, u.name AS user_name, u.email AS user_email, u.phone AS user_phone,
               a.name AS assigned_name,
               o.title AS order_title
        FROM support_tickets t
        JOIN users u ON u.id=t.user_id
        LEFT JOIN users a ON a.id=t.assigned_to
        LEFT JOIN orders o ON o.id=t.order_id
        WHERE t.id=?
        """,
        (ticket_id,),
    )
    if not ticket:
        abort(404)
    if g.user["role"] not in ("admin", "support") and ticket["user_id"] != g.user["id"]:
        abort(403)
    return ticket


@app.route("/")
def index():
    categories = all_rows("SELECT * FROM categories ORDER BY id")
    top_masters = all_rows(
        """
        SELECT u.*, mp.rating, mp.completed_orders, mp.categories, mp.hourly_rate, mp.verified
        FROM users u JOIN master_profiles mp ON mp.user_id=u.id
        WHERE u.role='master' AND u.is_active=1
        ORDER BY mp.rating DESC, mp.completed_orders DESC
        LIMIT 3
        """
    )
    stats = {
        "masters": one("SELECT COUNT(*) AS c FROM users WHERE role='master'")["c"],
        "orders": one("SELECT COUNT(*) AS c FROM orders")["c"],
        "reviews": one("SELECT COUNT(*) AS c FROM reviews")["c"],
    }
    return render_template("index.html", categories=categories, top_masters=top_masters, stats=stats)


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form["name"].strip()
        email = request.form["email"].strip().lower()
        phone = request.form.get("phone", "").strip()
        password = request.form["password"]
        role = request.form.get("role", "customer")
        city = request.form.get("city", "Москва").strip() or "Москва"
        agree_terms = request.form.get("agree_terms")
        pwd_errors = password_errors(password)
        if not name or not email or not password:
            flash("Заполните имя, email и пароль.", "danger")
        elif pwd_errors:
            flash("Пароль слишком слабый: " + ", ".join(pwd_errors) + ".", "danger")
        elif not agree_terms:
            flash("Чтобы создать аккаунт, нужно принять пользовательское соглашение и политику обработки данных.", "warning")
        elif one("SELECT id FROM users WHERE email=?", (email,)):
            flash("Пользователь с таким email уже существует.", "danger")
        else:
            avatar = "".join(part[0] for part in name.split()[:2]).upper() or "HH"
            cur = run(
                """
                INSERT INTO users(name,email,phone,password_hash,role,city,avatar,created_at)
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (name, email, phone, generate_password_hash(password), role, city, avatar, datetime.now().isoformat(timespec="seconds")),
            )
            if role == "master":
                run("INSERT INTO master_profiles(user_id, categories, experience_years, hourly_rate) VALUES (?,?,?,?)", (cur.lastrowid, "Мелкий ремонт", 1, 1200))
            flash("Аккаунт создан. Теперь можно войти.", "success")
            return redirect(url_for("login"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        user = one("SELECT * FROM users WHERE email=?", (email,))
        if user is None or not check_password_hash(user["password_hash"], request.form["password"]):
            flash("Неверный email или пароль.", "danger")
        elif not user["is_active"]:
            flash("Аккаунт заблокирован. Обратитесь в поддержку.", "danger")
        else:
            session.clear()
            session["user_id"] = user["id"]
            flash(f"Добро пожаловать, {user['name']}!", "success")
            return redirect(request.args.get("next") or url_for("dashboard"))
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Вы вышли из аккаунта.", "info")
    return redirect(url_for("index"))


@app.route("/dashboard")
@login_required
def dashboard():
    if g.user["role"] == "admin":
        orders = all_rows(
            """
            SELECT o.*, c.name AS category_name, c.icon AS category_icon, cu.name AS customer_name, mu.name AS master_name
            FROM orders o JOIN categories c ON c.id=o.category_id
            JOIN users cu ON cu.id=o.customer_id LEFT JOIN users mu ON mu.id=o.master_id
            ORDER BY o.created_at DESC LIMIT 8
            """
        )
    elif g.user["role"] == "support":
        orders = all_rows(
            """
            SELECT o.*, c.name AS category_name, c.icon AS category_icon, cu.name AS customer_name, mu.name AS master_name
            FROM orders o JOIN categories c ON c.id=o.category_id
            JOIN users cu ON cu.id=o.customer_id LEFT JOIN users mu ON mu.id=o.master_id
            ORDER BY o.created_at DESC LIMIT 6
            """
        )
    elif g.user["role"] == "master":
        orders = all_rows(
            """
            SELECT o.*, c.name AS category_name, c.icon AS category_icon, u.name AS customer_name
            FROM orders o JOIN categories c ON c.id=o.category_id JOIN users u ON u.id=o.customer_id
            WHERE o.master_id=? ORDER BY o.created_at DESC LIMIT 6
            """,
            (g.user["id"],),
        )
    else:
        orders = all_rows(
            """
            SELECT o.*, c.name AS category_name, c.icon AS category_icon, u.name AS master_name
            FROM orders o JOIN categories c ON c.id=o.category_id LEFT JOIN users u ON u.id=o.master_id
            WHERE o.customer_id=? ORDER BY o.created_at DESC LIMIT 6
            """,
            (g.user["id"],),
        )
    if g.user["role"] in ("admin", "support"):
        tickets = all_rows("""
            SELECT t.*, u.name AS user_name
            FROM support_tickets t JOIN users u ON u.id=t.user_id
            WHERE t.status != 'closed'
            ORDER BY CASE t.priority WHEN 'critical' THEN 1 WHEN 'high' THEN 2 WHEN 'normal' THEN 3 ELSE 4 END, t.created_at DESC
            LIMIT 5
        """)
    else:
        tickets = all_rows("SELECT * FROM support_tickets WHERE user_id=? ORDER BY created_at DESC LIMIT 3", (g.user["id"],))
    return render_template("dashboard.html", orders=orders, tickets=tickets)


@app.route("/verification", methods=["GET", "POST"])
@login_required
def verification():
    if request.method == "POST":
        passport_series = request.form.get("passport_series", "").strip()
        passport_number = request.form.get("passport_number", "").strip()
        birth_date = request.form.get("birth_date", "").strip()
        passport_issued_by = request.form.get("passport_issued_by", "").strip()
        passport_issue_date = request.form.get("passport_issue_date", "").strip()
        consent = request.form.get("consent_pd")
        passport_photo = request.files.get("passport_photo_file")
        selfie_photo = request.files.get("selfie_photo_file")

        def save_verification_file(file_obj, prefix):
            if not file_obj or not file_obj.filename:
                return ""
            if not allowed_image(file_obj.filename):
                return None
            ext = secure_filename(file_obj.filename).rsplit(".", 1)[1].lower()
            filename = f"{prefix}_{g.user['id']}_{int(datetime.now().timestamp())}.{ext}"
            Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)
            file_obj.save(Path(app.config["UPLOAD_FOLDER"]) / filename)
            return filename

        if not consent:
            flash("Нужно дать отдельное согласие на обработку паспортных данных.", "warning")
        elif len(passport_series) < 4 or len(passport_number) < 6 or not birth_date or not passport_issued_by or not passport_issue_date:
            flash("Заполните паспортные данные полностью.", "danger")
        else:
            saved_passport = save_verification_file(passport_photo, "passport")
            saved_selfie = save_verification_file(selfie_photo, "selfie")

            if saved_passport is None or saved_selfie is None:
                flash("Фото должны быть в формате PNG, JPG, JPEG или WEBP.", "danger")
            elif not saved_passport and not g.user["passport_photo_file"]:
                flash("Загрузите фото паспорта.", "danger")
            elif not saved_selfie and not g.user["selfie_photo_file"]:
                flash("Загрузите селфи с паспортом.", "danger")
            else:
                run(
                    """
                    UPDATE users
                    SET passport_series=?, passport_number=?, birth_date=?, passport_issued_by=?,
                        passport_issue_date=?, passport_photo_file=COALESCE(NULLIF(?, ''), passport_photo_file),
                        selfie_photo_file=COALESCE(NULLIF(?, ''), selfie_photo_file),
                        verification_status='pending',
                        verification_comment='', verified_at=''
                    WHERE id=?
                    """,
                    (
                        passport_series,
                        passport_number,
                        birth_date,
                        passport_issued_by,
                        passport_issue_date,
                        saved_passport,
                        saved_selfie,
                        g.user["id"],
                    ),
                )
                flash("Данные и фотографии отправлены на проверку. После подтверждения можно будет заказывать услуги или принимать заказы.", "success")
                return redirect(url_for("dashboard"))

    return render_template("verification.html")


@app.route("/wallet", methods=["GET", "POST"])
@login_required
def wallet():
    if request.method == "POST":
        if g.user["role"] != "master":
            abort(403)
        amount = request.form.get("amount", type=int) or 0
        if amount <= 0 or amount > g.user["balance"]:
            flash("Некорректная сумма вывода.", "danger")
        else:
            now = datetime.now().isoformat(timespec="seconds")
            cur = run(
                "INSERT INTO support_tickets(user_id, topic, message, priority, status, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                (g.user["id"], "Вывод средств", f"Мастер запросил вывод {amount} ₽. Баланс: {g.user['balance']} ₽.", "normal", "open", now, now),
            )
            run(
                "INSERT INTO support_messages(ticket_id, sender_id, message, created_at) VALUES (?,?,?,?)",
                (cur.lastrowid, g.user["id"], f"Прошу вывести {amount} ₽ на мои реквизиты.", now),
            )
            flash("Заявка на вывод отправлена в поддержку.", "success")
            return redirect(url_for("ticket_detail", ticket_id=cur.lastrowid))

    transactions = all_rows("SELECT * FROM transactions WHERE user_id=? ORDER BY created_at DESC", (g.user["id"],))
    return render_template("wallet.html", transactions=transactions)



@app.route("/catalog")
def catalog():
    return render_template("catalog.html", categories=all_rows("SELECT * FROM categories ORDER BY id"))


@app.route("/masters")
def masters():
    category = request.args.get("category", "").strip()
    city = request.args.get("city", "").strip()
    sort = request.args.get("sort", "rating")
    sql = """
    SELECT u.*, mp.categories, mp.experience_years, mp.hourly_rate, mp.verified, mp.documents_status,
           mp.safety_badge, mp.completed_orders, mp.rating
    FROM users u JOIN master_profiles mp ON mp.user_id=u.id
    WHERE u.role='master' AND u.is_active=1
    """
    params = []
    if category:
        sql += " AND mp.categories LIKE ?"
        params.append(f"%{category}%")
    if city:
        sql += " AND u.city LIKE ?"
        params.append(f"%{city}%")
    sql += " ORDER BY " + ("mp.hourly_rate ASC" if sort == "price" else "mp.completed_orders DESC" if sort == "orders" else "mp.rating DESC, mp.completed_orders DESC")
    return render_template("masters.html", masters=all_rows(sql, tuple(params)), selected_category=category, selected_city=city, sort=sort)


@app.route("/masters/<int:master_id>")
def master_detail(master_id):
    master = one(
        """
        SELECT u.*, mp.categories, mp.experience_years, mp.hourly_rate, mp.verified, mp.documents_status,
               mp.safety_badge, mp.completed_orders, mp.rating
        FROM users u JOIN master_profiles mp ON mp.user_id=u.id
        WHERE u.id=? AND u.role='master'
        """,
        (master_id,),
    )
    if master is None:
        abort(404)
    reviews = all_rows("SELECT r.*, u.name AS customer_name FROM reviews r JOIN users u ON u.id=r.customer_id WHERE r.master_id=? ORDER BY r.created_at DESC", (master_id,))
    is_favorite = False
    if g.user:
        is_favorite = one("SELECT 1 FROM favorites WHERE user_id=? AND master_id=?", (g.user["id"], master_id)) is not None
    settings = one("SELECT * FROM master_settings WHERE user_id=?", (master_id,))
    availability = all_rows("SELECT * FROM master_availability WHERE master_id=? ORDER BY id", (master_id,))
    portfolio = all_rows("SELECT * FROM portfolio_items WHERE master_id=? ORDER BY created_at DESC", (master_id,))
    return render_template("master_detail.html", master=master, reviews=reviews, is_favorite=is_favorite, settings=settings, availability=availability, portfolio=portfolio)


@app.post("/favorites/<int:master_id>")
@login_required
def toggle_favorite(master_id):
    if one("SELECT 1 FROM favorites WHERE user_id=? AND master_id=?", (g.user["id"], master_id)):
        run("DELETE FROM favorites WHERE user_id=? AND master_id=?", (g.user["id"], master_id))
        flash("Мастер удалён из избранного.", "info")
    else:
        run("INSERT INTO favorites(user_id, master_id) VALUES (?,?)", (g.user["id"], master_id))
        flash("Мастер добавлен в избранное.", "success")
    return redirect(url_for("master_detail", master_id=master_id))


@app.route("/orders/new", methods=["GET", "POST"])
@login_required
@verification_required
def new_order():
    categories = all_rows("SELECT * FROM categories ORDER BY name")
    selected_master_id = request.args.get("master_id", type=int)
    selected_category_id = request.args.get("category_id", type=int)
    master = one("SELECT * FROM users WHERE id=? AND role='master'", (selected_master_id,)) if selected_master_id else None
    promo_codes = all_rows("SELECT * FROM promo_codes WHERE active=1 ORDER BY discount_percent DESC")
    service_areas = all_rows("SELECT * FROM service_areas WHERE active=1 ORDER BY id")

    if request.method == "POST":
        title = request.form["title"].strip()
        description = request.form["description"].strip()
        address = request.form["address"].strip()
        scheduled_at = request.form["scheduled_at"].strip()
        budget = int(request.form["budget"])
        urgent = 1 if request.form.get("urgent") else 0
        promo_code = request.form.get("promo_code", "").strip().upper()
        service_area = request.form.get("service_area", "").strip()
        discount = 0

        area = one("SELECT * FROM service_areas WHERE name=?", (service_area,)) if service_area else None
        if area:
            budget += area["base_trip_price"]

        if promo_code:
            promo = one("SELECT * FROM promo_codes WHERE code=? AND active=1", (promo_code,))
            if promo:
                discount = int(budget * promo["discount_percent"] / 100)
            else:
                flash("Промокод не найден или неактивен.", "warning")
                promo_code = ""

        if urgent:
            budget = int(budget * 1.2)

        final_price = max(0, budget - discount)

        if not title or not description or not address or not scheduled_at:
            flash("Заполните все обязательные поля.", "danger")
        else:
            now = datetime.now().isoformat(timespec="seconds")
            if service_area:
                description = f"{description}\n\nРайон обслуживания: {service_area}."
            cur = run(
                """
                INSERT INTO orders(customer_id, master_id, category_id, title, description, address, scheduled_at, budget, status, payment_status, created_at, urgent, promo_code, discount, final_price)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    g.user["id"],
                    request.form.get("master_id", type=int),
                    int(request.form["category_id"]),
                    title,
                    description,
                    address,
                    scheduled_at,
                    final_price,
                    "assigned" if request.form.get("master_id") else "new",
                    "created",
                    now,
                    urgent,
                    promo_code,
                    discount,
                    final_price,
                ),
            )
            order_id = cur.lastrowid

            # Smart intake questionnaire answers
            for key, value in request.form.items():
                if key.startswith("question_") and value.strip():
                    question = key.replace("question_", "").replace("_", " ")
                    run(
                        "INSERT INTO order_intake_answers(order_id, question, answer, created_at) VALUES (?, ?, ?, ?)",
                        (order_id, question, value.strip(), now),
                    )

            # Client problem photo at order creation
            problem_photo = request.files.get("problem_photo")
            if problem_photo and problem_photo.filename and allowed_image(problem_photo.filename):
                ext = secure_filename(problem_photo.filename).rsplit(".", 1)[1].lower()
                filename = f"order_{order_id}_problem_{int(datetime.now().timestamp())}.{ext}"
                Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)
                problem_photo.save(Path(app.config["UPLOAD_FOLDER"]) / filename)
                run(
                    "INSERT INTO order_photos(order_id, uploaded_by, photo_type, filename, created_at) VALUES (?, ?, ?, ?, ?)",
                    (order_id, g.user["id"], "problem", filename, now),
                )

            if request.form.get("master_id"):
                notify_user(request.form.get("master_id", type=int), "Новый заказ", f"Вам назначен заказ #{order_id}: {title}")
            flash("Заявка создана. Теперь можно пройти демо-оплату и заморозить средства безопасной сделкой.", "success")
            return redirect(url_for("payment_page", order_id=order_id))

    return render_template(
        "new_order.html",
        categories=categories,
        selected_master_id=selected_master_id,
        selected_category_id=selected_category_id,
        master=master,
        promo_codes=promo_codes,
        service_areas=service_areas,
        smart_questions=SMART_QUESTIONS,
    )

@app.route("/orders")
@login_required
def orders():
    if g.user["role"] == "admin":
        rows = all_rows(
            """
            SELECT o.*, c.name AS category_name, c.icon AS category_icon, cu.name AS customer_name, mu.name AS master_name
            FROM orders o JOIN categories c ON c.id=o.category_id
            JOIN users cu ON cu.id=o.customer_id LEFT JOIN users mu ON mu.id=o.master_id
            ORDER BY o.created_at DESC
            """
        )
    elif g.user["role"] == "master":
        rows = all_rows(
            """
            SELECT o.*, c.name AS category_name, c.icon AS category_icon, u.name AS customer_name
            FROM orders o JOIN categories c ON c.id=o.category_id JOIN users u ON u.id=o.customer_id
            WHERE o.master_id=? OR o.master_id IS NULL ORDER BY o.created_at DESC
            """,
            (g.user["id"],),
        )
    else:
        rows = all_rows(
            """
            SELECT o.*, c.name AS category_name, c.icon AS category_icon, u.name AS master_name
            FROM orders o JOIN categories c ON c.id=o.category_id LEFT JOIN users u ON u.id=o.master_id
            WHERE o.customer_id=? ORDER BY o.created_at DESC
            """,
            (g.user["id"],),
        )
    return render_template("orders.html", orders=rows)


@app.route("/orders/<int:order_id>", methods=["GET", "POST"])
@login_required
def order_detail(order_id):
    order = order_or_404(order_id)
    review = one("SELECT * FROM reviews WHERE order_id=?", (order_id,))
    now = datetime.now().isoformat(timespec="seconds")

    if request.method == "POST":
        action = request.form.get("action")

        if action == "accept" and g.user["role"] == "master":
            if not is_verified(g.user):
                flash("Мастер может принимать заказы только после верификации.", "warning")
                return redirect(url_for("verification"))
            if order["master_id"] in (None, g.user["id"]):
                run("UPDATE orders SET master_id=?, status='assigned' WHERE id=?", (g.user["id"], order_id))
                notify_user(order["customer_id"], "Заказ принят", f"Мастер принял заказ #{order_id}.")
                flash("Вы приняли заказ.", "success")

        elif action == "status" and g.user["role"] in ("master", "admin"):
            status = request.form["status"]
            if status in STATUS_LABELS:
                payment = "released" if status == "completed" else order["payment_status"]
                if status == "completed" and order["master_id"] and order["payment_status"] != "released":
                    payout = int(order["budget"] * 0.85)
                    fee = order["budget"] - payout
                    run("UPDATE users SET balance = balance + ? WHERE id=?", (payout, order["master_id"]))
                    run(
                        "INSERT INTO transactions(user_id, order_id, amount, type, description, created_at) VALUES (?,?,?,?,?,?)",
                        (order["master_id"], order_id, payout, "earning", f"Выплата за заказ #{order_id}. Комиссия HomeHero: {fee} ₽", now),
                    )
                    expires = (datetime.now() + timedelta(days=30)).date().isoformat()
                    run(
                        "INSERT OR IGNORE INTO warranties(order_id, expires_at, terms, created_at) VALUES (?, ?, ?, ?)",
                        (order_id, expires, "Гарантия 30 дней: повторная проверка, компенсация или повторный выезд по решению поддержки.", now),
                    )
                    notify_user(order["customer_id"], "Заказ завершён", f"Заказ #{order_id} завершён. Гарантия действует до {expires}.")
                    notify_user(order["master_id"], "Начисление", f"На баланс начислено {payout} ₽ за заказ #{order_id}.")
                run("UPDATE orders SET status=?, payment_status=? WHERE id=?", (status, payment, order_id))
                if status == "completed" and order["master_id"]:
                    refresh_rating(order["master_id"])
                flash("Статус обновлён.", "success")

        elif action == "cancel" and g.user["id"] == order["customer_id"]:
            run("UPDATE orders SET status='cancelled', payment_status='returned' WHERE id=?", (order_id,))
            notify_user(order["master_id"], "Заказ отменён", f"Клиент отменил заказ #{order_id}.")
            flash("Заказ отменён.", "info")

        elif action == "review" and g.user["id"] == order["customer_id"] and order["status"] == "completed" and review is None:
            text = request.form["text"].strip()
            if order["master_id"] and text:
                run(
                    "INSERT INTO reviews(order_id, customer_id, master_id, rating, text, created_at) VALUES (?,?,?,?,?,?)",
                    (order_id, g.user["id"], order["master_id"], int(request.form["rating"]), text, now),
                )
                refresh_rating(order["master_id"])
                notify_user(order["master_id"], "Новый отзыв", f"Клиент оставил отзыв по заказу #{order_id}.")
                flash("Спасибо за отзыв.", "success")

        elif action == "order_message":
            message = request.form.get("message", "").strip()
            if message:
                run("INSERT INTO order_messages(order_id, sender_id, message, created_at) VALUES (?, ?, ?, ?)", (order_id, g.user["id"], message, now))
                other_id = order["master_id"] if g.user["id"] == order["customer_id"] else order["customer_id"]
                notify_user(other_id, "Новое сообщение", f"Новое сообщение по заказу #{order_id}.")
                flash("Сообщение отправлено.", "success")

        elif action in ("before_photo", "after_photo"):
            file_obj = request.files.get("order_photo")
            if file_obj and file_obj.filename and allowed_image(file_obj.filename):
                ext = secure_filename(file_obj.filename).rsplit(".", 1)[1].lower()
                filename = f"order_{order_id}_{action}_{int(datetime.now().timestamp())}.{ext}"
                Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)
                file_obj.save(Path(app.config["UPLOAD_FOLDER"]) / filename)
                photo_type = "before" if action == "before_photo" else "after"
                run("INSERT INTO order_photos(order_id, uploaded_by, photo_type, filename, created_at) VALUES (?, ?, ?, ?, ?)", (order_id, g.user["id"], photo_type, filename, now))
                flash("Фото загружено.", "success")
            else:
                flash("Загрузите фото PNG, JPG, JPEG или WEBP.", "danger")

        elif action == "open_dispute":
            reason = request.form.get("reason", "").strip()
            position = request.form.get("customer_position", "").strip()
            if reason and position:
                cur = run(
                    "INSERT INTO disputes(order_id, opened_by, reason, customer_position, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (order_id, g.user["id"], reason, position, "open", now, now),
                )
                run(
                    "INSERT INTO dispute_messages(dispute_id, sender_id, message, created_at) VALUES (?, ?, ?, ?)",
                    (cur.lastrowid, g.user["id"], position, now),
                )
                run("UPDATE orders SET payment_status='hold' WHERE id=?", (order_id,))
                notify_user(order["master_id"], "Открыт спор", f"По заказу #{order_id} открыт спор.")
                flash("Спор открыт. Средства остаются замороженными до решения поддержки.", "warning")
                return redirect(url_for("dispute_detail", dispute_id=cur.lastrowid))

        elif action == "complaint":
            reason = request.form.get("reason", "").strip()
            details = request.form.get("details", "").strip()
            target = order["master_id"] if g.user["id"] == order["customer_id"] else order["customer_id"]
            if reason and details:
                run(
                    "INSERT INTO complaints(user_id, target_user_id, order_id, reason, details, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (g.user["id"], target, order_id, reason, details, now),
                )
                cur = run(
                    "INSERT INTO support_tickets(user_id, order_id, topic, message, priority, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (g.user["id"], order_id, "Жалоба по заказу", f"{reason}: {details}", "high", "open", now, now),
                )
                run("INSERT INTO support_messages(ticket_id, sender_id, message, created_at) VALUES (?, ?, ?, ?)", (cur.lastrowid, g.user["id"], details, now))
                flash("Жалоба отправлена в поддержку.", "success")
                return redirect(url_for("ticket_detail", ticket_id=cur.lastrowid))

        elif action == "emergency":
            cur = run(
                "INSERT INTO support_tickets(user_id, order_id, topic, message, priority, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (g.user["id"], order_id, "Срочная помощь по заказу", "Пользователь нажал тревожную кнопку. Требуется быстрая реакция поддержки.", "critical", "open", now, now),
            )
            run("INSERT INTO support_messages(ticket_id, sender_id, message, created_at) VALUES (?, ?, ?, ?)", (cur.lastrowid, g.user["id"], "Нужна срочная помощь по заказу.", now))
            flash("Срочное обращение создано. Если есть угроза жизни или здоровью, звоните в экстренные службы.", "warning")
            return redirect(url_for("ticket_detail", ticket_id=cur.lastrowid))

        elif action == "repeat" and g.user["id"] == order["customer_id"]:
            cur = run(
                """
                INSERT INTO orders(customer_id, master_id, category_id, title, description, address, scheduled_at, budget, status, payment_status, created_at, urgent, final_price)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    g.user["id"],
                    order["master_id"],
                    order["category_id"],
                    "Повтор: " + order["title"],
                    order["description"],
                    order["address"],
                    order["scheduled_at"],
                    order["budget"],
                    "assigned" if order["master_id"] else "new",
                    "hold",
                    now,
                    order["urgent"] if "urgent" in order.keys() else 0,
                    order["budget"],
                ),
            )
            flash("Повторный заказ создан.", "success")
            return redirect(url_for("order_detail", order_id=cur.lastrowid))

        return redirect(url_for("order_detail", order_id=order_id))

    messages = all_rows("""
        SELECT m.*, u.name AS sender_name
        FROM order_messages m JOIN users u ON u.id=m.sender_id
        WHERE m.order_id=?
        ORDER BY m.created_at ASC
    """, (order_id,))
    photos = all_rows("SELECT * FROM order_photos WHERE order_id=? ORDER BY created_at DESC", (order_id,))
    warranty = one("SELECT * FROM warranties WHERE order_id=?", (order_id,))
    complaints = all_rows("SELECT * FROM complaints WHERE order_id=? ORDER BY created_at DESC", (order_id,))
    payments = all_rows("SELECT * FROM payments WHERE order_id=? ORDER BY created_at DESC", (order_id,))
    intake_answers = all_rows("SELECT * FROM order_intake_answers WHERE order_id=? ORDER BY id", (order_id,))
    disputes = all_rows("SELECT * FROM disputes WHERE order_id=? ORDER BY created_at DESC", (order_id,))
    return render_template("order_detail.html", order=order, review=review, messages=messages, photos=photos, warranty=warranty, complaints=complaints, payments=payments, intake_answers=intake_answers, disputes=disputes)

@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    master_profile = one("SELECT * FROM master_profiles WHERE user_id=?", (g.user["id"],)) if g.user["role"] == "master" else None
    categories = all_rows("SELECT * FROM categories ORDER BY name")
    if request.method == "POST":
        avatar_file = request.files.get("avatar_file")
        saved_avatar = None
        if avatar_file and avatar_file.filename:
            if allowed_image(avatar_file.filename):
                ext = secure_filename(avatar_file.filename).rsplit(".", 1)[1].lower()
                saved_avatar = f"user_{g.user['id']}_{int(datetime.now().timestamp())}.{ext}"
                Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)
                avatar_file.save(Path(app.config["UPLOAD_FOLDER"]) / saved_avatar)
            else:
                flash("Аватар должен быть PNG, JPG, JPEG или WEBP.", "danger")
                return redirect(url_for("profile"))

        if saved_avatar:
            run("UPDATE users SET name=?, phone=?, city=?, bio=?, avatar_file=? WHERE id=?", (request.form["name"].strip(), request.form.get("phone", "").strip(), request.form.get("city", "").strip(), request.form.get("bio", "").strip(), saved_avatar, g.user["id"]))
        else:
            run("UPDATE users SET name=?, phone=?, city=?, bio=? WHERE id=?", (request.form["name"].strip(), request.form.get("phone", "").strip(), request.form.get("city", "").strip(), request.form.get("bio", "").strip(), g.user["id"]))

        if g.user["role"] == "master":
            run(
                "UPDATE master_profiles SET categories=?, experience_years=?, hourly_rate=? WHERE user_id=?",
                (",".join(request.form.getlist("categories")), int(request.form.get("experience_years", 1)), int(request.form.get("hourly_rate", 1200)), g.user["id"]),
            )
        flash("Профиль обновлён.", "success")
        return redirect(url_for("profile"))
    return render_template("profile.html", master_profile=master_profile, categories=categories)


@app.route("/become-master", methods=["GET", "POST"])
@login_required
def become_master():
    categories = all_rows("SELECT * FROM categories ORDER BY name")
    if request.method == "POST":
        run("UPDATE users SET role='master' WHERE id=?", (g.user["id"],))
        run(
            "INSERT OR IGNORE INTO master_profiles(user_id,categories,experience_years,hourly_rate) VALUES (?,?,?,?)",
            (g.user["id"], ",".join(request.form.getlist("categories")), int(request.form["experience_years"]), int(request.form["hourly_rate"])),
        )
        flash("Профиль мастера создан. Документы отправлены на проверку.", "success")
        return redirect(url_for("dashboard"))
    return render_template("become_master.html", categories=categories)


@app.route("/support", methods=["GET", "POST"])
@login_required
def support():
    if request.method == "POST":
        topic = request.form["topic"].strip()
        message = request.form["message"].strip()
        priority = request.form.get("priority", "normal")
        if topic and message:
            now = datetime.now().isoformat(timespec="seconds")
            cur = run(
                "INSERT INTO support_tickets(user_id, order_id, topic, message, priority, status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                (g.user["id"], request.form.get("order_id", type=int), topic, message, priority, "open", now, now),
            )
            run(
                "INSERT INTO support_messages(ticket_id, sender_id, message, created_at) VALUES (?,?,?,?)",
                (cur.lastrowid, g.user["id"], message, now),
            )
            flash("Обращение отправлено в поддержку. Ответ появится в чате заявки.", "success")
            return redirect(url_for("ticket_detail", ticket_id=cur.lastrowid))
        flash("Заполните тему и сообщение.", "danger")
    user_orders = all_rows("SELECT id,title FROM orders WHERE customer_id=? OR master_id=? ORDER BY created_at DESC", (g.user["id"], g.user["id"]))
    my_tickets = all_rows("SELECT * FROM support_tickets WHERE user_id=? ORDER BY created_at DESC LIMIT 5", (g.user["id"],))
    return render_template("support.html", orders=user_orders, tickets=my_tickets)


@app.route("/support-panel", methods=["GET", "POST"])
@login_required
@role_required("admin", "support")
def support_panel():
    if request.method == "POST":
        ticket_id = request.form.get("ticket_id", type=int)
        action = request.form.get("action")
        if action == "take" and ticket_id:
            run("UPDATE support_tickets SET assigned_to=?, status='in_progress', updated_at=? WHERE id=?", (g.user["id"], datetime.now().isoformat(timespec="seconds"), ticket_id))
            flash("Обращение взято в работу.", "success")
        elif action == "close" and ticket_id:
            run("UPDATE support_tickets SET status='closed', updated_at=? WHERE id=?", (datetime.now().isoformat(timespec="seconds"), ticket_id))
            flash("Обращение закрыто.", "success")
        return redirect(url_for("support_panel"))

    status_filter = request.args.get("status", "active")
    if status_filter == "closed":
        where = "WHERE t.status='closed'"
    elif status_filter == "all":
        where = ""
    else:
        where = "WHERE t.status!='closed'"

    tickets = all_rows(f"""
        SELECT t.*, u.name AS user_name, u.email AS user_email, a.name AS assigned_name, o.title AS order_title
        FROM support_tickets t
        JOIN users u ON u.id=t.user_id
        LEFT JOIN users a ON a.id=t.assigned_to
        LEFT JOIN orders o ON o.id=t.order_id
        {where}
        ORDER BY CASE t.priority WHEN 'critical' THEN 1 WHEN 'high' THEN 2 WHEN 'normal' THEN 3 ELSE 4 END,
                 CASE t.status WHEN 'open' THEN 1 WHEN 'in_progress' THEN 2 WHEN 'waiting_user' THEN 3 ELSE 4 END,
                 t.created_at DESC
    """)
    stats = {
        "open": one("SELECT COUNT(*) AS c FROM support_tickets WHERE status='open'")["c"],
        "progress": one("SELECT COUNT(*) AS c FROM support_tickets WHERE status='in_progress'")["c"],
        "closed": one("SELECT COUNT(*) AS c FROM support_tickets WHERE status='closed'")["c"],
        "critical": one("SELECT COUNT(*) AS c FROM support_tickets WHERE priority='critical' AND status!='closed'")["c"],
    }
    return render_template("support_panel.html", tickets=tickets, stats=stats, status_filter=status_filter)


@app.route("/tickets/<int:ticket_id>", methods=["GET", "POST"])
@login_required
def ticket_detail(ticket_id):
    ticket = ticket_or_404(ticket_id)

    if request.method == "POST":
        action = request.form.get("action")
        now = datetime.now().isoformat(timespec="seconds")

        if action == "reply":
            message = request.form.get("message", "").strip()
            if message:
                run(
                    "INSERT INTO support_messages(ticket_id, sender_id, message, created_at) VALUES (?,?,?,?)",
                    (ticket_id, g.user["id"], message, now),
                )
                if g.user["role"] in ("admin", "support"):
                    run("UPDATE support_tickets SET assigned_to=COALESCE(assigned_to, ?), status='waiting_user', updated_at=? WHERE id=?", (g.user["id"], now, ticket_id))
                else:
                    run("UPDATE support_tickets SET status='open', updated_at=? WHERE id=?", (now, ticket_id))
                flash("Сообщение отправлено.", "success")
            else:
                flash("Введите сообщение.", "warning")

        elif action == "internal" and g.user["role"] in ("admin", "support"):
            message = request.form.get("message", "").strip()
            if message:
                run(
                    "INSERT INTO support_messages(ticket_id, sender_id, message, is_internal, created_at) VALUES (?,?,?,?,?)",
                    (ticket_id, g.user["id"], message, 1, now),
                )
                flash("Внутренняя заметка добавлена.", "success")

        elif action == "update" and g.user["role"] in ("admin", "support"):
            status = request.form.get("status")
            priority = request.form.get("priority")
            assigned_to = request.form.get("assigned_to", type=int) or g.user["id"]
            if status in TICKET_STATUS_LABELS and priority in TICKET_PRIORITY_LABELS:
                run("UPDATE support_tickets SET status=?, priority=?, assigned_to=?, updated_at=? WHERE id=?", (status, priority, assigned_to, now, ticket_id))
                flash("Параметры обращения обновлены.", "success")

        elif action == "close":
            if g.user["role"] in ("admin", "support") or ticket["user_id"] == g.user["id"]:
                run("UPDATE support_tickets SET status='closed', updated_at=? WHERE id=?", (now, ticket_id))
                flash("Обращение закрыто.", "success")

        return redirect(url_for("ticket_detail", ticket_id=ticket_id))

    ticket = ticket_or_404(ticket_id)
    if g.user["role"] in ("admin", "support"):
        messages = all_rows("""
            SELECT m.*, u.name AS sender_name, u.role AS sender_role
            FROM support_messages m JOIN users u ON u.id=m.sender_id
            WHERE m.ticket_id=?
            ORDER BY m.created_at ASC
        """, (ticket_id,))
        support_users = all_rows("SELECT id, name FROM users WHERE role IN ('support','admin') AND is_active=1 ORDER BY role DESC, name")
    else:
        messages = all_rows("""
            SELECT m.*, u.name AS sender_name, u.role AS sender_role
            FROM support_messages m JOIN users u ON u.id=m.sender_id
            WHERE m.ticket_id=? AND m.is_internal=0
            ORDER BY m.created_at ASC
        """, (ticket_id,))
        support_users = []
    support_templates = all_rows("SELECT * FROM support_templates ORDER BY title")
    return render_template("ticket_detail.html", ticket=ticket, messages=messages, support_users=support_users, support_templates=support_templates)



@app.route("/admin", methods=["GET", "POST"])
@login_required
@role_required("admin")
def admin():
    if request.method == "POST":
        action = request.form.get("action")
        user_id = request.form.get("user_id", type=int)
        ticket_id = request.form.get("ticket_id", type=int)
        if action == "verify" and user_id:
            run("UPDATE users SET verification_status='verified', verification_comment='', verified_at=? WHERE id=?", (datetime.now().isoformat(timespec="seconds"), user_id))
            run("UPDATE master_profiles SET verified=1, documents_status='Паспорт проверен', safety_badge='Проверенный мастер' WHERE user_id=?", (user_id,))
            flash("Пользователь подтверждён.", "success")
        elif action == "reject_verification" and user_id:
            comment = request.form.get("comment", "Данные не прошли проверку").strip() or "Данные не прошли проверку"
            run("UPDATE users SET verification_status='rejected', verification_comment=? WHERE id=?", (comment, user_id))
            run("UPDATE master_profiles SET verified=0, documents_status='Отклонено', safety_badge='Не проверен' WHERE user_id=?", (user_id,))
            flash("Верификация отклонена.", "warning")
        elif action == "block" and user_id:
            run("UPDATE users SET is_active=0 WHERE id=?", (user_id,))
            flash("Пользователь заблокирован.", "warning")
        elif action == "unblock" and user_id:
            run("UPDATE users SET is_active=1 WHERE id=?", (user_id,))
            flash("Пользователь разблокирован.", "success")
        elif action == "close_ticket" and ticket_id:
            run("UPDATE support_tickets SET status='closed' WHERE id=?", (ticket_id,))
            flash("Обращение закрыто.", "success")
        return redirect(url_for("admin"))
    users = all_rows("SELECT * FROM users ORDER BY created_at DESC")
    pending_verifications = all_rows("SELECT * FROM users WHERE verification_status='pending' ORDER BY created_at DESC")
    masters_list = all_rows("SELECT u.*, mp.verified, mp.documents_status, mp.rating, mp.completed_orders FROM users u JOIN master_profiles mp ON mp.user_id=u.id WHERE u.role='master' ORDER BY mp.verified ASC")
    tickets = all_rows("SELECT t.*, u.name AS user_name FROM support_tickets t JOIN users u ON u.id=t.user_id ORDER BY t.created_at DESC")
    return render_template("admin.html", users=users, pending_verifications=pending_verifications, masters=masters_list, tickets=tickets)






@app.route("/notifications", methods=["GET", "POST"])
@login_required
def notifications():
    if request.method == "POST":
        run("UPDATE notifications SET is_read=1 WHERE user_id=?", (g.user["id"],))
        flash("Уведомления отмечены как прочитанные.", "success")
        return redirect(url_for("notifications"))
    rows = all_rows("SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC", (g.user["id"],))
    return render_template("notifications.html", notifications=rows)


@app.route("/master-tools", methods=["GET", "POST"])
@login_required
@role_required("master", "admin")
def master_tools():
    if g.user["role"] != "master" and request.args.get("master_id") is None:
        master_id = g.user["id"]
    else:
        master_id = request.args.get("master_id", type=int) or g.user["id"]

    if request.method == "POST":
        action = request.form.get("action")
        now = datetime.now().isoformat(timespec="seconds")

        if action == "settings":
            work_status = request.form.get("work_status", "offline")
            urgent_enabled = 1 if request.form.get("urgent_enabled") else 0
            run(
                "INSERT OR IGNORE INTO master_settings(user_id) VALUES (?)",
                (master_id,),
            )
            run(
                "UPDATE master_settings SET work_status=?, urgent_enabled=? WHERE user_id=?",
                (work_status, urgent_enabled, master_id),
            )
            flash("Статус мастера обновлён.", "success")

        elif action == "availability":
            run("DELETE FROM master_availability WHERE master_id=?", (master_id,))
            for weekday in ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]:
                start = request.form.get(f"{weekday}_start", "").strip()
                end = request.form.get(f"{weekday}_end", "").strip()
                if start and end:
                    run(
                        "INSERT INTO master_availability(master_id, weekday, start_time, end_time) VALUES (?, ?, ?, ?)",
                        (master_id, weekday, start, end),
                    )
            flash("Календарь занятости сохранён.", "success")

        elif action == "portfolio":
            title = request.form.get("title", "").strip() or "Работа мастера"
            file_obj = request.files.get("portfolio_photo")
            if file_obj and file_obj.filename and allowed_image(file_obj.filename):
                ext = secure_filename(file_obj.filename).rsplit(".", 1)[1].lower()
                filename = f"portfolio_{master_id}_{int(datetime.now().timestamp())}.{ext}"
                Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)
                file_obj.save(Path(app.config["UPLOAD_FOLDER"]) / filename)
                run(
                    "INSERT INTO portfolio_items(master_id, title, filename, created_at) VALUES (?, ?, ?, ?)",
                    (master_id, title, filename, now),
                )
                flash("Работа добавлена в портфолио.", "success")
            else:
                flash("Загрузите изображение PNG, JPG, JPEG или WEBP.", "danger")

        elif action == "pro":
            pro_until = (datetime.now() + timedelta(days=30)).date().isoformat()
            run("INSERT OR IGNORE INTO master_settings(user_id) VALUES (?)", (master_id,))
            run("UPDATE master_settings SET pro_until=?, reliability_score=MIN(reliability_score+2, 100) WHERE user_id=?", (pro_until, master_id))
            run(
                "INSERT INTO transactions(user_id, amount, type, description, created_at) VALUES (?, ?, ?, ?, ?)",
                (master_id, -990, "pro_subscription", "Подписка Pro на 30 дней: приоритет в выдаче и расширенная аналитика.", now),
            )
            flash("Подписка Pro активирована на 30 дней.", "success")

        return redirect(url_for("master_tools"))

    settings = one("SELECT * FROM master_settings WHERE user_id=?", (master_id,))
    if not settings:
        run("INSERT OR IGNORE INTO master_settings(user_id) VALUES (?)", (master_id,))
        settings = one("SELECT * FROM master_settings WHERE user_id=?", (master_id,))
    availability = all_rows("SELECT * FROM master_availability WHERE master_id=? ORDER BY id", (master_id,))
    portfolio = all_rows("SELECT * FROM portfolio_items WHERE master_id=? ORDER BY created_at DESC", (master_id,))
    orders = all_rows("SELECT * FROM orders WHERE master_id=? ORDER BY created_at DESC", (master_id,))
    return render_template("master_tools.html", settings=settings, availability=availability, portfolio=portfolio, orders=orders)


@app.route("/admin-analytics")
@login_required
@role_required("admin")
def admin_analytics():
    total_orders = one("SELECT COUNT(*) AS c FROM orders")["c"]
    completed_orders = one("SELECT COUNT(*) AS c FROM orders WHERE status='completed'")["c"]
    active_users = one("SELECT COUNT(*) AS c FROM users WHERE is_active=1")["c"]
    masters_count = one("SELECT COUNT(*) AS c FROM users WHERE role='master'")["c"]
    revenue = one("SELECT COALESCE(SUM(budget), 0) AS s FROM orders WHERE status='completed'")["s"]
    commission = int(revenue * 0.15)
    tickets_open = one("SELECT COUNT(*) AS c FROM support_tickets WHERE status!='closed'")["c"]
    pending_verifications = one("SELECT COUNT(*) AS c FROM users WHERE verification_status='pending'")["c"]
    complaints_count = one("SELECT COUNT(*) AS c FROM complaints WHERE status='open'")["c"]
    promo_stats = all_rows("SELECT * FROM promo_codes ORDER BY discount_percent DESC")
    top_masters = all_rows("""
        SELECT u.name, mp.rating, mp.completed_orders, ms.reliability_score
        FROM users u
        JOIN master_profiles mp ON mp.user_id=u.id
        LEFT JOIN master_settings ms ON ms.user_id=u.id
        WHERE u.role='master'
        ORDER BY mp.rating DESC, mp.completed_orders DESC
        LIMIT 5
    """)
    return render_template(
        "admin_analytics.html",
        total_orders=total_orders,
        completed_orders=completed_orders,
        active_users=active_users,
        masters_count=masters_count,
        revenue=revenue,
        commission=commission,
        tickets_open=tickets_open,
        pending_verifications=pending_verifications,
        complaints_count=complaints_count,
        promo_stats=promo_stats,
        top_masters=top_masters,
    )


@app.route("/guarantee")
def guarantee():
    return render_template("guarantee.html")


@app.route("/referral")
@login_required
def referral():
    code = f"FRIEND{g.user['id']}"
    return render_template("referral.html", code=code)





@app.route("/orders/<int:order_id>/payment", methods=["GET", "POST"])
@login_required
def payment_page(order_id):
    order = order_or_404(order_id)
    if g.user["id"] != order["customer_id"] and g.user["role"] not in ("admin", "support"):
        abort(403)

    now = datetime.now().isoformat(timespec="seconds")
    payment = one("SELECT * FROM payments WHERE order_id=? ORDER BY created_at DESC LIMIT 1", (order_id,))

    if request.method == "POST":
        action = request.form.get("action")
        card_mask = request.form.get("card_mask", "**** 4242").strip() or "**** 4242"

        if action == "demo_pay":
            if not payment:
                cur = run(
                    "INSERT INTO payments(order_id, user_id, amount, status, provider, card_mask, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (order_id, g.user["id"], order["budget"], "created", "DemoPay", card_mask, now),
                )
                payment_id = cur.lastrowid
            else:
                payment_id = payment["id"]

            run(
                "UPDATE payments SET status='authorized', card_mask=?, amount=? WHERE id=?",
                (card_mask, order["budget"], payment_id),
            )
            run(
                "INSERT INTO payment_events(payment_id, event, note, created_at) VALUES (?, ?, ?, ?)",
                (payment_id, "authorized", "Демо-оплата прошла: средства заморожены безопасной сделкой.", now),
            )
            run("UPDATE orders SET payment_status='hold' WHERE id=?", (order_id,))
            notify_user(order["customer_id"], "Оплата заморожена", f"По заказу #{order_id} средства находятся в безопасной сделке.")
            if order["master_id"]:
                notify_user(order["master_id"], "Заказ оплачен", f"По заказу #{order_id} средства заморожены до завершения работы.")
            flash("Демо-оплата прошла успешно. Средства заморожены.", "success")
            return redirect(url_for("order_detail", order_id=order_id))

        elif action == "demo_fail":
            if not payment:
                cur = run(
                    "INSERT INTO payments(order_id, user_id, amount, status, provider, card_mask, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (order_id, g.user["id"], order["budget"], "failed", "DemoPay", card_mask, now),
                )
                payment_id = cur.lastrowid
            else:
                payment_id = payment["id"]
                run("UPDATE payments SET status='failed' WHERE id=?", (payment_id,))
            run(
                "INSERT INTO payment_events(payment_id, event, note, created_at) VALUES (?, ?, ?, ?)",
                (payment_id, "failed", "Демо-ошибка оплаты: карта отклонена.", now),
            )
            run("UPDATE orders SET payment_status='failed' WHERE id=?", (order_id,))
            flash("Смоделирована ошибка оплаты.", "warning")
            return redirect(url_for("payment_page", order_id=order_id))

        elif action == "refund" and g.user["role"] in ("admin", "support"):
            if payment:
                run("UPDATE payments SET status='refund' WHERE id=?", (payment["id"],))
                run(
                    "INSERT INTO payment_events(payment_id, event, note, created_at) VALUES (?, ?, ?, ?)",
                    (payment["id"], "refund", "Поддержка оформила демо-возврат клиенту.", now),
                )
            run("UPDATE orders SET payment_status='returned' WHERE id=?", (order_id,))
            flash("Демо-возврат оформлен.", "success")
            return redirect(url_for("order_detail", order_id=order_id))

    payment = one("SELECT * FROM payments WHERE order_id=? ORDER BY created_at DESC LIMIT 1", (order_id,))
    events = []
    if payment:
        events = all_rows("SELECT * FROM payment_events WHERE payment_id=? ORDER BY created_at DESC", (payment["id"],))
    return render_template("payment.html", order=order, payment=payment, events=events)


@app.route("/payments")
@login_required
def payments():
    if g.user["role"] in ("admin", "support"):
        rows = all_rows("""
            SELECT p.*, o.title AS order_title, u.name AS user_name
            FROM payments p
            JOIN orders o ON o.id=p.order_id
            JOIN users u ON u.id=p.user_id
            ORDER BY p.created_at DESC
        """)
    else:
        rows = all_rows("""
            SELECT p.*, o.title AS order_title, u.name AS user_name
            FROM payments p
            JOIN orders o ON o.id=p.order_id
            JOIN users u ON u.id=p.user_id
            WHERE p.user_id=?
            ORDER BY p.created_at DESC
        """, (g.user["id"],))
    return render_template("payments.html", payments=rows)


@app.route("/disputes")
@login_required
def disputes():
    if g.user["role"] in ("admin", "support"):
        rows = all_rows("""
            SELECT d.*, o.title AS order_title, u.name AS opened_by_name
            FROM disputes d
            JOIN orders o ON o.id=d.order_id
            JOIN users u ON u.id=d.opened_by
            ORDER BY d.updated_at DESC
        """)
    else:
        rows = all_rows("""
            SELECT d.*, o.title AS order_title, u.name AS opened_by_name
            FROM disputes d
            JOIN orders o ON o.id=d.order_id
            JOIN users u ON u.id=d.opened_by
            WHERE d.opened_by=? OR o.customer_id=? OR o.master_id=?
            ORDER BY d.updated_at DESC
        """, (g.user["id"], g.user["id"], g.user["id"]))
    return render_template("disputes.html", disputes=rows)


@app.route("/disputes/<int:dispute_id>", methods=["GET", "POST"])
@login_required
def dispute_detail(dispute_id):
    dispute = one("""
        SELECT d.*, o.title AS order_title, o.customer_id, o.master_id, o.budget,
               opener.name AS opened_by_name
        FROM disputes d
        JOIN orders o ON o.id=d.order_id
        JOIN users opener ON opener.id=d.opened_by
        WHERE d.id=?
    """, (dispute_id,))
    if not dispute:
        abort(404)
    if g.user["role"] not in ("admin", "support") and g.user["id"] not in (dispute["opened_by"], dispute["customer_id"], dispute["master_id"]):
        abort(403)

    now = datetime.now().isoformat(timespec="seconds")
    if request.method == "POST":
        action = request.form.get("action")

        if action == "message":
            message = request.form.get("message", "").strip()
            if message:
                run("INSERT INTO dispute_messages(dispute_id, sender_id, message, created_at) VALUES (?, ?, ?, ?)", (dispute_id, g.user["id"], message, now))
                run("UPDATE disputes SET updated_at=? WHERE id=?", (now, dispute_id))
                flash("Сообщение добавлено к спору.", "success")

        elif action == "resolve" and g.user["role"] in ("admin", "support"):
            status = request.form.get("status")
            resolution = request.form.get("resolution", "").strip()
            if status in DISPUTE_STATUS_LABELS:
                run("UPDATE disputes SET status=?, resolution=?, updated_at=? WHERE id=?", (status, resolution, now, dispute_id))
                if status == "resolved_refund":
                    run("UPDATE orders SET payment_status='returned' WHERE id=?", (dispute["order_id"],))
                elif status == "resolved_payout":
                    run("UPDATE orders SET payment_status='released' WHERE id=?", (dispute["order_id"],))
                elif status == "resolved_rework":
                    run("UPDATE orders SET status='in_progress' WHERE id=?", (dispute["order_id"],))
                notify_user(dispute["customer_id"], "Спор обновлён", f"По заказу #{dispute['order_id']} принято решение поддержки.")
                notify_user(dispute["master_id"], "Спор обновлён", f"По заказу #{dispute['order_id']} принято решение поддержки.")
                flash("Решение по спору сохранено.", "success")

        return redirect(url_for("dispute_detail", dispute_id=dispute_id))

    messages = all_rows("""
        SELECT m.*, u.name AS sender_name, u.role AS sender_role
        FROM dispute_messages m
        JOIN users u ON u.id=m.sender_id
        WHERE m.dispute_id=?
        ORDER BY m.created_at ASC
    """, (dispute_id,))
    return render_template("dispute_detail.html", dispute=dispute, messages=messages)


@app.route("/areas")
def areas():
    rows = all_rows("SELECT * FROM service_areas WHERE active=1 ORDER BY id")
    return render_template("areas.html", areas=rows)


@app.route("/for-masters")
def for_masters():
    categories = all_rows("SELECT * FROM categories ORDER BY id")
    return render_template("for_masters.html", categories=categories)


@app.route("/admin-crm")
@login_required
@role_required("admin")
def admin_crm():
    unassigned_orders = all_rows("""
        SELECT o.*, c.name AS customer_name, cat.name AS category_name
        FROM orders o
        JOIN users c ON c.id=o.customer_id
        JOIN categories cat ON cat.id=o.category_id
        WHERE o.master_id IS NULL AND o.status='new'
        ORDER BY o.created_at DESC
    """)
    risky_masters = all_rows("""
        SELECT u.id, u.name, u.email, mp.rating, mp.completed_orders, COALESCE(ms.reliability_score, 95) AS reliability_score,
               (SELECT COUNT(*) FROM complaints c WHERE c.target_user_id=u.id AND c.status='open') AS open_complaints
        FROM users u
        JOIN master_profiles mp ON mp.user_id=u.id
        LEFT JOIN master_settings ms ON ms.user_id=u.id
        WHERE u.role='master'
        ORDER BY open_complaints DESC, reliability_score ASC, mp.rating ASC
        LIMIT 10
    """)
    payout_requests = all_rows("""
        SELECT t.*, u.name AS user_name
        FROM support_tickets t JOIN users u ON u.id=t.user_id
        WHERE t.topic LIKE '%вывод%' OR t.topic LIKE '%баланс%'
        ORDER BY t.created_at DESC
        LIMIT 10
    """)
    active_disputes = all_rows("""
        SELECT d.*, o.title AS order_title, u.name AS opened_by_name
        FROM disputes d
        JOIN orders o ON o.id=d.order_id
        JOIN users u ON u.id=d.opened_by
        WHERE d.status NOT IN ('closed', 'resolved_refund', 'resolved_payout', 'resolved_rework')
        ORDER BY d.updated_at DESC
    """)
    return render_template("admin_crm.html", unassigned_orders=unassigned_orders, risky_masters=risky_masters, payout_requests=payout_requests, active_disputes=active_disputes)



@app.route("/contacts")
def contacts():
    return render_template("contacts.html")


@app.route("/legal")
def legal():
    return render_template("legal.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


@app.route("/safety")
def safety():
    return render_template("safety.html")


@app.errorhandler(403)
def forbidden(error):
    return render_template("error.html", code=403, title="Нет доступа", message="У вас нет прав для этого действия."), 403


@app.errorhandler(404)
def not_found(error):
    return render_template("error.html", code=404, title="Страница не найдена", message="Такой страницы не существует."), 404


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
