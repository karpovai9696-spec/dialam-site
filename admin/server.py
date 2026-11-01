#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Единая админ-панель для 4 брендов (Диалам+, Консалтинг, Диамедика, Салюшенс).

Запуск:  python admin/server.py --port 8090
Адрес:   http://127.0.0.1:8090/

Только стандартная библиотека Python 3.11+. Без pip-зависимостей.
Пароль администратора: env ADMIN_PASSWORD (по умолчанию admin123).
"""

import argparse
import hashlib
import json
import os
import re
import secrets
import sqlite3
import ssl
import sys
import threading
import time
from collections import deque
from datetime import datetime, timezone
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "admin.db")
EXPORTS_DIR = os.path.join(BASE_DIR, "exports")
STATIC_DIR = os.path.join(BASE_DIR, "static")

# Пути, которые нельзя отдавать как статику
PROTECTED_DIRS = ("/data/", "/exports/", "/static/../")
AUDIT_LOG = os.path.join(BASE_DIR, "audit.log")
SESSIONS_FILE = os.path.join(BASE_DIR, "sessions.json")
TLS_ENABLED = False

ITEM_TYPES = {
    "branch":   ["city", "address", "phone", "email", "hours", "map_url", "is_active"],
    "license":  ["number", "issued_by", "issued_at", "file_url", "note"],
    "news":     ["title", "date", "excerpt", "body", "image_url", "published",
                 "branch"],
    "vacancy":  ["title", "city", "employment", "salary", "description",
                 "requirements", "contact_email", "published", "branch"],
    "staff":    ["name", "role", "branch", "phone", "email", "education",
                 "accreditation", "photo"],
    "service":  ["name", "category", "description", "price", "is_active"],
    "document": ["title", "category", "file_url", "published"],
    "setting":  ["key", "value"],
}

SITE_FIELDS = ["slug", "name", "brand", "domain", "tagline", "description",
               "legal_name", "inn", "ogrn", "license_number", "license_issued_by",
               "license_date", "phone", "email", "address", "theme", "is_active"]

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{0,63}$")

# ---------------------------------------------------------------------------
# Сессии (в памяти прототипа)
# ---------------------------------------------------------------------------
SESSIONS = {}          # token -> {"expires": float, "csrf": str}
SESSIONS_LOCK = threading.Lock()
SESSION_TTL = 72 * 3600  # 72 часа


class RateLimiter:
    """Простой in-memory limiter по IP/ключу."""

    def __init__(self, limit, window):
        self.limit = limit
        self.window = window
        self.hits = {}
        self.lock = threading.Lock()

    def _prune(self, key, now):
        q = self.hits.get(key)
        while q and q[0] <= now - self.window:
            q.popleft()
        if not q:
            self.hits.pop(key, None)
        return q

    def blocked(self, key):
        now = time.time()
        with self.lock:
            q = self._prune(key, now)
            return bool(q and len(q) >= self.limit)

    def hit(self, key):
        now = time.time()
        with self.lock:
            self.hits.setdefault(key, deque()).append(now)

    def allow(self, key):
        with self.lock:
            now = time.time()
            q = self._prune(key, now)
            if q and len(q) >= self.limit:
                return False
            self.hits.setdefault(key, deque()).append(now)
            return True

    def reset(self, key):
        with self.lock:
            self.hits.pop(key, None)


LOGIN_LIMITER = RateLimiter(10, 15 * 60)   # 10 неудачных попыток / 15 минут
API_LIMITER = RateLimiter(300, 60)         # 300 API-запросов / минута
AUDIT_LOCK = threading.Lock()


def audit(event, **fields):
    """Журнал действий администратора: JSONL, без паролей и токенов."""
    try:
        record = {"ts": datetime.now(timezone.utc).isoformat(), "event": event}
        record.update(fields)
        line = json.dumps(record, ensure_ascii=False)
        with AUDIT_LOCK:
            with open(AUDIT_LOG, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception:
        pass


def load_sessions():
    try:
        with open(SESSIONS_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return
    now = time.time()
    with SESSIONS_LOCK:
        for token, sess in data.items():
            if isinstance(sess, dict) and sess.get("expires", 0) > now and sess.get("csrf"):
                SESSIONS[token] = sess


def save_sessions():
    with SESSIONS_LOCK:
        data = {k: dict(v) for k, v in SESSIONS.items()}
    try:
        tmp = SESSIONS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, SESSIONS_FILE)
        try:
            os.chmod(SESSIONS_FILE, 0o600)
        except OSError:
            pass
    except Exception:
        pass


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_password():
    return os.environ.get("ADMIN_PASSWORD", "admin123")


def create_session():
    token = secrets.token_hex(32)
    csrf = secrets.token_hex(32)
    with SESSIONS_LOCK:
        SESSIONS[token] = {"expires": time.time() + SESSION_TTL, "csrf": csrf}
    save_sessions()
    return token, csrf


def get_session(token):
    if not token:
        return None
    with SESSIONS_LOCK:
        sess = SESSIONS.get(token)
        if not sess:
            return None
        if sess["expires"] < time.time():
            SESSIONS.pop(token, None)
            return None
        return sess


def check_session(token):
    return get_session(token) is not None


def destroy_session(token):
    with SESSIONS_LOCK:
        SESSIONS.pop(token, None)
    save_sessions()


# ---------------------------------------------------------------------------
# База данных
# ---------------------------------------------------------------------------

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS sites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    brand TEXT DEFAULT '',
    domain TEXT DEFAULT '',
    tagline TEXT DEFAULT '',
    description TEXT DEFAULT '',
    legal_name TEXT DEFAULT '',
    inn TEXT DEFAULT '',
    ogrn TEXT DEFAULT '',
    license_number TEXT DEFAULT '',
    license_issued_by TEXT DEFAULT '',
    license_date TEXT DEFAULT '',
    phone TEXT DEFAULT '',
    email TEXT DEFAULT '',
    address TEXT DEFAULT '',
    theme TEXT DEFAULT 'mint',
    is_active INTEGER DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id INTEGER NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    type TEXT NOT NULL,
    data TEXT NOT NULL DEFAULT '{}',
    sort_order INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_items_site_type ON items(site_id, type);
"""

# Версионируемые миграции SQLite. Версия хранится в PRAGMA user_version.
MIGRATIONS = {
    1: [
        "CREATE INDEX IF NOT EXISTS idx_items_site_sort ON items(site_id, sort_order, id);",
        "CREATE INDEX IF NOT EXISTS idx_items_updated ON items(updated_at);",
    ],
    2: [
        # Оптимистичная блокировка для предотвращения потерянных обновлений.
        "ALTER TABLE sites ADD COLUMN version INTEGER NOT NULL DEFAULT 1;",
        "ALTER TABLE items ADD COLUMN version INTEGER NOT NULL DEFAULT 1;",
    ],
}


def run_migrations(conn):
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    for version in sorted(MIGRATIONS):
        if current >= version:
            continue
        for statement in MIGRATIONS[version]:
            conn.execute(statement)
        conn.execute("PRAGMA user_version = %d" % version)
        conn.commit()
        current = version


def seed(conn):
    ts = now_iso()

    def new_site(**kw):
        cols = {f: kw.get(f, "") for f in SITE_FIELDS}
        cols["is_active"] = int(kw.get("is_active", 1))
        names = ", ".join(cols.keys()) + ", created_at, updated_at"
        marks = ", ".join(["?"] * (len(cols) + 2))
        cur = conn.execute(
            f"INSERT INTO sites ({names}) VALUES ({marks})",
            list(cols.values()) + [ts, ts])
        return cur.lastrowid

    def new_item(site_id, typ, data, order=0):
        conn.execute(
            "INSERT INTO items (site_id, type, data, sort_order, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (site_id, typ, json.dumps(data, ensure_ascii=False), order, ts, ts))

    # ---------------- Диалам+ ----------------
    dialam = new_site(
        slug="dialam", name="Диалам+", brand="Диалам+",
        domain="dialam-plus.ru",
        tagline="Центр амбулаторного гемодиализа",
        description="Центры амбулаторного гемодиализа в четырёх городах России. "
                    "Заместительная почечная терапия по программе ОМС.",
        legal_name='ООО «Диалам+»', inn="1215211807", ogrn="1161215058400",
        license_number="ЛО-12-01-001016",
        license_issued_by="Министерство здравоохранения Республики Марий Эл",
        license_date="2019-05-16",
        phone="+7 (958) 843-20-66", email="dialam@list.ru",
        address="424019, Республика Марий Эл, г. Йошкар-Ола, ул. Анникова, д. 4а, пом. 7",
        theme="mint",
    )

    HOURS = "Пн–Сб 07:00–22:00, Вс — выходной"
    branches = [
        {"city": "Волжск", "address": "г. Волжск, ул. Зелёная, 4Б",
         "phone": "+7 (958) 843-20-66", "email": "dialam@list.ru",
         "hours": HOURS, "map_url": "", "is_active": True},
        {"city": "Йошкар-Ола", "address": "уточняется",
         "phone": "", "email": "dialam@list.ru",
         "hours": HOURS, "map_url": "", "is_active": True},
        {"city": "Орёл", "address": "уточняется",
         "phone": "", "email": "dialam@list.ru",
         "hours": HOURS, "map_url": "", "is_active": True},
        {"city": "Нижневартовск", "address": "уточняется",
         "phone": "", "email": "dialam@list.ru",
         "hours": HOURS, "map_url": "", "is_active": True},
    ]
    for i, b in enumerate(branches):
        new_item(dialam, "branch", b, i)

    new_item(dialam, "license", {
        "number": "ЛО-12-01-001016",
        "issued_by": "Министерство здравоохранения Республики Марий Эл",
        "issued_at": "2019-05-16",
        "file_url": "/licenzii.html",
        "note": "Разрешение на осуществление медицинской деятельности",
    })

    new_item(dialam, "news", {
        "title": "Демо-новость: замените в панели",
        "date": "2026-11-01",
        "excerpt": "Демонстрационная запись seed — замените реальной новостью через админ-панель.",
        "body": "Это демо-новость из начальных данных. Замените её реальным текстом "
                "в разделе «Новости» админ-панели.",
        "image_url": "", "published": False, "branch": "Волжск",
    }, 1)
    new_item(dialam, "news", {
        "title": "Демо-новость: замените в панели",
        "date": "2026-11-01",
        "excerpt": "Вторая демонстрационная запись seed — замените реальной новостью.",
        "body": "Это вторая демо-новость из начальных данных. Замените её реальным "
                "текстом в разделе «Новости» админ-панели.",
        "image_url": "", "published": False, "branch": "Нижневартовск",
    }, 2)

    new_item(dialam, "vacancy", {
        "title": "Врач-нефролог",
        "city": "Орёл", "employment": "Полная занятость",
        "salary": "по договорённости",
        "description": "Амбулаторный приём пациентов с хронической болезнью почек, "
                       "подбор и контроль программы диализа, ведение пациентов "
                       "на аппарате «искусственная почка».",
        "requirements": "Высшее медицинское образование, аккредитация по "
                        "нефрологии/терапии.",
        "contact_email": "dialam@list.ru", "published": True, "branch": "Орёл",
    }, 1)
    new_item(dialam, "vacancy", {
        "title": "Инженер по медицинскому оборудованию",
        "city": "Орёл", "employment": "Полная занятость",
        "salary": "по договорённости",
        "description": "Обслуживание и ремонт аппаратов гемодиализа («искусственная "
                       "почка»), подготовка техники к сеансам, контроль исправности "
                       "и ведение технической документации.",
        "requirements": "Профильное техническое образование, опыт обслуживания "
                        "медицинского оборудования приветствуется.",
        "contact_email": "dialam@list.ru", "published": True, "branch": "Нижневартовск",
    }, 2)

    staff = [
        {"name": "Палагин Виталий Александрович", "role": "Директор",
         "branch": "Волжск", "phone": "", "email": "dialam@list.ru",
         "education": "уточняется",
         "accreditation": "уточняется", "photo": ""},
        {"name": "Митюков Арсений Арсентьевич", "role": "Заведующий центром",
         "branch": "Волжск", "phone": "", "email": "dialam@list.ru",
         "education": "уточняется",
         "accreditation": "уточняется", "photo": ""},
        {"name": "Фадеева Анна Викторовна", "role": "Старшая медицинская сестра",
         "branch": "Волжск", "phone": "", "email": "dialam@list.ru",
         "education": "уточняется",
         "accreditation": "уточняется", "photo": ""},
    ]
    for i, s in enumerate(staff):
        new_item(dialam, "staff", s, i)

    services = [
        {"name": "Программный гемодиализ", "category": "Заместительная почечная терапия",
         "description": "Сеанс на аппарате «искусственная почка» по индивидуальной "
                        "программе под контролем медицинского персонала.",
         "price": "по ОМС", "is_active": True},
        {"name": "Гостевой диализ", "category": "Заместительная почечная терапия",
         "description": "Проведение сеанса гемодиализа для пациентов из других "
                        "городов и регионов в период поездки.",
         "price": "по ОМС", "is_active": True},
        {"name": "Консультация нефролога", "category": "Врачебный приём",
         "description": "Оценка функции почек, подбор терапии и графика диализа.",
         "price": "по ОМС", "is_active": True},
    ]
    for i, s in enumerate(services):
        new_item(dialam, "service", s, i)

    docs = [
        {"title": "Программа государственных гарантий", "category": "Пациентам",
         "file_url": "/programma-gos-garantii.html", "published": True},
        {"title": "Правила записи на приём", "category": "Пациентам",
         "file_url": "/pravila-zapisi.html", "published": True},
        {"title": "Лицензия на медицинскую деятельность (копия)", "category": "Документы",
         "file_url": "/licenzii.html", "published": True},
    ]
    for i, d in enumerate(docs):
        new_item(dialam, "document", d, i)

    settings = [
        ("hero_title", "Центры гемодиализа «Диалам+»"),
        ("hero_subtitle", "Заместительная почечная терапия рядом с домом: Волжск, "
                          "Йошкар-Ола, Орёл, Нижневартовск"),
        ("cta_text", "Записаться на консультацию"),
        ("legal_text", "ООО «Диалам+». ИНН 1215211807. ОГРН 1161215058400. "
                       "Лицензия ЛО-12-01-001016 от 16.05.2019."),
        ("footer_note", "Имеются противопоказания. Необходима консультация специалиста."),
    ]
    for i, (k, v) in enumerate(settings):
        new_item(dialam, "setting", {"key": k, "value": v}, i)

    # ---------------- остальные бренды ----------------
    consult = new_site(
        slug="consulting", name="Консалтинговая компания", brand="consulting",
        domain="", tagline="Консалтинг и сопровождение бизнес-проектов",
        description="Раздел заполняется через админ-панель.",
        legal_name="", email="", phone="", address="", theme="mint")
    new_item(consult, "branch", {"city": "Йошкар-Ола", "address": "уточняется",
                                 "phone": "", "email": "", "hours": "уточняется",
                                 "map_url": "", "is_active": True})
    new_item(consult, "setting", {"key": "hero_title", "value": "Консалтинговая компания"})
    new_item(consult, "setting", {"key": "hero_subtitle",
                                  "value": "Раздел находится в подготовке"})

    diamedica = new_site(
        slug="diamedica", name="Диамедика", brand="diamedica",
        domain="", tagline="Медицинский бренд «Диамедика»",
        description="Раздел заполняется через админ-панель.",
        legal_name="", email="", phone="", address="", theme="mint")
    new_item(diamedica, "branch", {"city": "уточняется", "address": "уточняется",
                                   "phone": "", "email": "", "hours": "уточняется",
                                   "map_url": "", "is_active": True})
    new_item(diamedica, "setting", {"key": "hero_title", "value": "Диамедика"})
    new_item(diamedica, "setting", {"key": "hero_subtitle",
                                    "value": "Раздел находится в подготовке"})

    salus = new_site(
        slug="salutions", name="Салюшенс", brand="salutions",
        domain="", tagline="Салюшенс — решения для здоровья",
        description="Раздел заполняется через админ-панель.",
        legal_name="", email="", phone="", address="", theme="mint")
    new_item(salus, "branch", {"city": "уточняется", "address": "уточняется",
                               "phone": "", "email": "", "hours": "уточняется",
                               "map_url": "", "is_active": True})
    new_item(salus, "setting", {"key": "hero_title", "value": "Салюшенс"})
    new_item(salus, "setting", {"key": "hero_subtitle",
                                "value": "Раздел находится в подготовке"})

    conn.commit()


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    os.makedirs(EXPORTS_DIR, exist_ok=True)
    conn = db()
    conn.executescript(SCHEMA)
    run_migrations(conn)
    n = conn.execute("SELECT COUNT(*) AS c FROM sites").fetchone()["c"]
    if n == 0:
        seed(conn)
    conn.close()


# ---------------------------------------------------------------------------
# Утилиты
# ---------------------------------------------------------------------------

def row_site(r):
    d = dict(r)
    d["is_active"] = bool(d["is_active"])
    return d


def row_item(r):
    d = dict(r)
    try:
        d["data"] = json.loads(d["data"])
    except (ValueError, TypeError):
        d["data"] = {}
    return d


def export_site(conn, site_id):
    srow = conn.execute("SELECT * FROM sites WHERE id=?", (site_id,)).fetchone()
    if not srow:
        return None
    site = row_site(srow)
    rows = conn.execute(
        "SELECT * FROM items WHERE site_id=? ORDER BY type, sort_order, id",
        (site_id,)).fetchall()
    by_type = {t: [] for t in ITEM_TYPES}
    for r in rows:
        it = row_item(r)
        by_type.setdefault(it["type"], []).append(it)
    return {
        "exported_at": now_iso(),
        "site": site,
        "branches": by_type.get("branch", []),
        "licenses": by_type.get("license", []),
        "news": by_type.get("news", []),
        "vacancies": by_type.get("vacancy", []),
        "staff": by_type.get("staff", []),
        "services": by_type.get("service", []),
        "documents": by_type.get("document", []),
        "settings": {it["data"].get("key"): it["data"].get("value")
                     for it in by_type.get("setting", [])},
    }


def public_site(conn, slug):
    exp = None
    srow = conn.execute("SELECT * FROM sites WHERE slug=?", (slug,)).fetchone()
    if srow and srow["is_active"]:
        exp = export_site(conn, srow["id"])
        exp["items"] = {k: v for k, v in {
            "branches": [i for i in exp["branches"] if i["data"].get("is_active", True)],
            "licenses": exp["licenses"],
            "news": [i for i in exp["news"] if i["data"].get("published", True)],
            "vacancies": [i for i in exp["vacancies"] if i["data"].get("published", True)],
            "staff": exp["staff"],
            "services": [i for i in exp["services"] if i["data"].get("is_active", True)],
            "documents": [i for i in exp["documents"] if i["data"].get("published", True)],
            "settings": exp["settings"],
        }.items() if v}
        for k in ("branches", "licenses", "news", "vacancies", "staff",
                  "services", "documents", "settings"):
            exp.pop(k, None)
    return exp


def clean_item_data(typ, data):
    """Фильтрует поля по схеме типа, приводит известные булевы поля."""
    if not isinstance(data, dict):
        return {}
    fields = ITEM_TYPES.get(typ, [])
    out = {}
    bool_fields = {"is_active", "published"}
    for f in fields:
        v = data.get(f, "" if f not in bool_fields else False)
        if f in bool_fields:
            v = bool(v)
        if isinstance(v, (str, int, float, bool)) or v is None:
            out[f] = v if v is not None else ""
        elif isinstance(v, (list, dict)):
            out[f] = v
    return out


# ---------------------------------------------------------------------------
# Обзор: контракт /api/overview
# ---------------------------------------------------------------------------

SECTION_BY_TYPE = {
    "branch": "branch", "license": "license", "news": "news",
    "vacancy": "vacancy", "staff": "staff", "service": "service",
    "document": "document", "setting": "settings",
}
FIELD_LABELS = {
    "legal_name": "юр. лицо", "inn": "ИНН", "ogrn": "ОГРН",
    "license_number": "номер лицензии", "license_issued_by": "кем выдана лицензия",
    "license_date": "дата лицензии", "phone": "телефон", "email": "e-mail",
    "address": "адрес", "hours": "часы работы", "number": "номер",
    "issued_by": "кем выдана", "issued_at": "дата выдачи", "file_url": "файл",
    "title": "заголовок", "branch": "филиал", "city": "город",
    "name": "название", "role": "должность", "accreditation": "аккредитация",
    "description": "описание", "price": "цена", "category": "категория",
    "published": "публикация", "is_active": "активность",
}
PLACEHOLDER_VALUES = {"", "-", "—", "уточняется", "нет данных", "не указано"}
SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}
PUBLISHED_TYPES = {"news", "vacancy", "document"}
ACTIVE_TYPES = {"branch", "service"}


def _is_blank(value):
    if value is None:
        return True
    return str(value).strip().lower() in PLACEHOLDER_VALUES


def _missing_fields(data, fields):
    return [FIELD_LABELS.get(f, f) for f in fields if _is_blank(data.get(f))]


def _field_list(items):
    return ", ".join(items)


def _overview_alert(alerts, kind, severity, title, detail, site, section, item=None):
    item_id = item["id"] if item else None
    item_type = item["type"] if item else None
    alerts.append({
        "id": "%s:%s:%s" % (kind, site["id"], item_id if item_id else "site"),
        "kind": kind,
        "severity": severity,
        "title": title,
        "detail": detail,
        "site_id": site["id"],
        "site_slug": site["slug"],
        "section": section,
        "item_id": item_id,
        "item_type": item_type,
        "action": {
            "kind": "edit_item" if item_id else "open_section",
            "section": section,
            "site_id": site["id"],
            "item_id": item_id,
            "item_type": item_type,
        },
    })


def _site_published_state(item):
    data = item.get("data") or {}
    if item["type"] in PUBLISHED_TYPES:
        return bool(data.get("published"))
    if item["type"] in ACTIVE_TYPES:
        return bool(data.get("is_active", True))
    return None


def _recent_events(site_id=None, limit=8):
    if not os.path.exists(AUDIT_LOG):
        return []
    lines = []
    try:
        with open(AUDIT_LOG, encoding="utf-8") as f:
            lines = f.readlines()[-250:]
    except OSError:
        return []
    labels = {
        "site_create": "Создан сайт", "site_update": "Обновлён сайт",
        "site_delete": "Удалён сайт", "item_create": "Создана запись",
        "item_update": "Обновлена запись", "item_delete": "Удалена запись",
        "export_file": "Сохранён экспорт",
    }
    events = []
    for line in reversed(lines):
        try:
            rec = json.loads(line)
        except (ValueError, TypeError):
            continue
        event = rec.get("event")
        if event not in labels:
            continue
        rec_site = rec.get("site_id")
        if site_id is not None and rec_site is not None and rec_site != site_id:
            continue
        events.append({
            "at": rec.get("ts"),
            "event": event,
            "label": labels.get(event, event),
            "site_id": rec_site,
            "item_id": rec.get("item_id"),
            "type": rec.get("type"),
        })
        if len(events) >= limit:
            break
    return events


def build_overview(conn, site_id=None, attention_limit=5):
    """Собирает контракт главного экрана. Никаких тяжёлых агрегатов вне SQLite."""
    site_rows = conn.execute("SELECT * FROM sites ORDER BY id").fetchall()
    sites = [row_site(r) for r in site_rows]
    if site_id is not None and not any(s["id"] == site_id for s in sites):
        return None
    items = [row_item(r) for r in conn.execute(
        "SELECT * FROM items ORDER BY site_id, type, sort_order, id").fetchall()]
    by_site = {s["id"]: [] for s in sites}
    for it in items:
        by_site.setdefault(it["site_id"], []).append(it)
    site_by_id = {s["id"]: s for s in sites}

    # Какие сайты попадают в «Требует внимания»/филиалы.
    attention_site_ids = [site_id] if site_id is not None else list(site_by_id)
    alerts = []

    for sid in attention_site_ids:
        site = site_by_id[sid]
        site_items = by_site.get(sid, [])
        by_type = {}
        for it in site_items:
            by_type.setdefault(it["type"], []).append(it)

        # 1. Реквизиты сайта.
        missing = _missing_fields(site, ["legal_name", "inn", "ogrn",
                                        "license_number", "phone", "email", "address"])
        if missing:
            critical = any(f in missing for f in ("юр. лицо", "ИНН", "ОГРН", "номер лицензии"))
            _overview_alert(
                alerts, "site_legal", "critical" if critical else "warning",
                "Реквизиты сайта заполнены не полностью",
                "Не заполнено: " + _field_list(missing),
                site, "settings")

        # 2. Лицензии.
        licenses = by_type.get("license", [])
        if not licenses:
            _overview_alert(
                alerts, "license_missing", "critical",
                "Не добавлена лицензия",
                "В разделе «Лицензии» нет ни одной записи.",
                site, "license")
        for lic in licenses:
            missing = _missing_fields(lic["data"], ["number", "issued_by", "issued_at", "file_url"])
            if missing:
                _overview_alert(
                    alerts, "license_fields", "warning",
                    "Лицензия заполнена не полностью",
                    "Не заполнено: " + _field_list(missing),
                    site, "license", lic)

        # 3. Филиалы: контакты и часы.
        for branch in by_type.get("branch", []):
            data = branch["data"]
            missing = _missing_fields(data, ["address", "phone", "hours"])
            if missing:
                city = (data.get("city") or "Без города").strip()
                _overview_alert(
                    alerts, "branch_contact", "warning",
                    "Филиал «%s»: не хватает контактов" % city,
                    "Не заполнено: " + _field_list(missing),
                    site, "branch", branch)

        # 4. Сотрудники.
        for staff in by_type.get("staff", []):
            data = staff["data"]
            missing = _missing_fields(data, ["name", "role", "branch", "accreditation"])
            if missing:
                name = (data.get("name") or "Сотрудник").strip()
                _overview_alert(
                    alerts, "staff_fields", "warning",
                    "Сотрудник «%s»: профиль неполный" % name,
                    "Не заполнено: " + _field_list(missing),
                    site, "staff", staff)

        # 5. Новости: филиал и демо-контент.
        for news in by_type.get("news", []):
            data = news["data"]
            title = (data.get("title") or "Без заголовка").strip()
            if _is_blank(data.get("branch")):
                _overview_alert(
                    alerts, "news_branch", "warning",
                    "Новость без филиала", title, site, "news", news)
            if str(title).lower().startswith("демо-"):
                _overview_alert(
                    alerts, "news_demo", "warning",
                    "Демо-новость в публичном контенте",
                    "Замените «%s» реальной новостью." % title,
                    site, "news", news)

        # 6. Вакансии: филиал, контакт и демо-контент.
        for vac in by_type.get("vacancy", []):
            data = vac["data"]
            title = (data.get("title") or "Без названия").strip()
            missing = _missing_fields(data, ["branch", "contact_email"])
            if missing:
                _overview_alert(
                    alerts, "vacancy_fields", "warning",
                    "Вакансия «%s»: профиль неполный" % title,
                    "Не заполнено: " + _field_list(missing),
                    site, "vacancy", vac)
            if str(title).lower().startswith("демо-"):
                _overview_alert(
                    alerts, "vacancy_demo", "warning",
                    "Демо-вакансия в публичном контенте",
                    "Замените «%s» реальной вакансией." % title,
                    site, "vacancy", vac)

        # 7. Документы и услуги.
        for doc in by_type.get("document", []):
            if _is_blank(doc["data"].get("file_url")):
                _overview_alert(
                    alerts, "document_file", "warning",
                    "Документ без файла",
                    (doc["data"].get("title") or "Документ"),
                    site, "document", doc)
        for svc in by_type.get("service", []):
            missing = _missing_fields(svc["data"], ["description", "price"])
            if missing:
                _overview_alert(
                    alerts, "service_fields", "warning",
                    "Услуга заполнена не полностью",
                    (svc["data"].get("name") or "Услуга") + ": " + _field_list(missing),
                    site, "service", svc)

    alerts.sort(key=lambda a: (SEVERITY_ORDER.get(a["severity"], 9), a["kind"], a["title"]))
    attention_limit = max(1, min(50, int(attention_limit or 5)))
    top_alerts = alerts[:attention_limit]
    attention = {
        "total": len(alerts),
        "items": top_alerts,
        "hidden_count": max(0, len(alerts) - len(top_alerts)),
        "empty": len(alerts) == 0,
    }

    # Пульс контента по всем брендам.
    content = []
    for site in sites:
        site_items = by_site.get(site["id"], [])
        counts = {}
        published = {}
        for it in site_items:
            counts[it["type"]] = counts.get(it["type"], 0) + 1
            state = _site_published_state(it)
            if state is True:
                published[it["type"]] = published.get(it["type"], 0) + 1
        content.append({
            "site_id": site["id"],
            "slug": site["slug"],
            "name": site["name"],
            "counts": counts,
            "published": published,
            "total": sum(counts.values()),
            "published_total": sum(published.values()),
        })

    # Покрытие филиалов выбранного бренда.
    branches = []
    if site_id is not None:
        selected_items = by_site.get(site_id, [])
        by_type = {}
        for it in selected_items:
            by_type.setdefault(it["type"], []).append(it)
        for branch in by_type.get("branch", []):
            city = (branch["data"].get("city") or "Без города").strip()
            staff_count = sum(1 for it in by_type.get("staff", [])
                              if str(it["data"].get("branch") or "").strip() == city)
            vacancy_count = sum(1 for it in by_type.get("vacancy", [])
                                if str(it["data"].get("branch") or it["data"].get("city") or "").strip() == city)
            news_count = sum(1 for it in by_type.get("news", [])
                             if str(it["data"].get("branch") or "").strip() == city)
            branches.append({
                "city": city,
                "item_id": branch["id"],
                "staff": staff_count,
                "vacancies": vacancy_count,
                "news": news_count,
                "gaps": _missing_fields(branch["data"], ["address", "phone", "hours"]),
            })

    actions = [
        {"id": "create_news", "label": "+ Новость", "kind": "create_item", "type": "news",
         "site_id": site_id, "section": "news"},
        {"id": "create_vacancy", "label": "+ Вакансия", "kind": "create_item", "type": "vacancy",
         "site_id": site_id, "section": "vacancy"},
        {"id": "review_publications", "label": "Проверить публикации", "kind": "open_section",
         "section": "news", "site_id": site_id},
    ]

    return {
        "generated_at": now_iso(),
        "site_id": site_id,
        "attention": attention,
        "content": content,
        "branches": branches,
        "recent": _recent_events(site_id),
        "actions": actions,
    }


# ---------------------------------------------------------------------------
# HTTP-обработчик
# ---------------------------------------------------------------------------

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".woff2": "font/woff2",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


class Handler(BaseHTTPRequestHandler):
    server_version = "DialamAdmin/1.0"

    # ---- helpers ----------------------------------------------------------

    def log_message(self, fmt, *args):
        sys.stderr.write("[admin] %s\n" % (fmt % args))

    def send_json(self, code, obj, cors=False):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if cors:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, If-Match")
        self.end_headers()
        self.wfile.write(body)

    def error(self, code, message):
        self.send_json(code, {"error": message, "code": code})

    def read_body(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0:
            return {}
        raw = self.rfile.read(min(length, 2 * 1024 * 1024))
        try:
            data = json.loads(raw.decode("utf-8"))
            return data if isinstance(data, dict) else {}
        except (ValueError, UnicodeDecodeError):
            return None

    def session_cookie(self):
        raw = self.headers.get("Cookie")
        if not raw:
            return None
        c = SimpleCookie()
        c.load(raw)
        m = c.get("admin_session")
        return m.value if m else None

    def client_ip(self):
        return self.client_address[0] if self.client_address else "unknown"

    def audit_action(self, event, **fields):
        audit(event, ip=self.client_ip(), **fields)

    def too_many(self, retry_after=60):
        self._retry_after = str(int(retry_after))
        return self.error(429, "Слишком много запросов, попробуйте позже")

    def require_csrf(self):
        sess = get_session(self.session_cookie())
        if not sess:
            self.error(401, "Требуется вход в систему")
            return False
        given = self.headers.get("X-CSRF-Token") or ""
        if not secrets.compare_digest(given, sess.get("csrf") or ""):
            self.error(403, "Неверный CSRF-токен")
            return False
        origin = self.headers.get("Origin")
        host = self.headers.get("Host")
        if origin and host and urlparse(origin).netloc != host:
            self.error(403, "Запрос с другого origin запрещён")
            return False
        return True

    def require_auth(self):
        if check_session(self.session_cookie()):
            return True
        self.error(401, "Требуется вход в систему")
        return False

    def expected_version(self, body=None, qs=None):
        """Версия из expected_version, If-Match или ?version=. None — не передана."""
        raw = None
        if isinstance(body, dict) and "expected_version" in body:
            raw = body.get("expected_version")
        if raw is None:
            match = re.search(r"\d+", self.headers.get("If-Match") or "")
            if match:
                raw = match.group(0)
        if raw is None and qs:
            raw = (qs.get("version") or [None])[0]
        if raw is None or raw == "":
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            return -1

    def require_version(self, old, expected, current_payload):
        if expected is None:
            return self.send_json(428, {
                "error": "expected_version_required",
                "code": 428,
                "message": "Передайте expected_version или If-Match: защита от потери изменений.",
                "current_version": old["version"],
            })
        if expected < 0:
            return self.error(400, "Некорректная expected_version")
        if expected != old["version"]:
            return self.send_json(409, {
                "error": "version_conflict",
                "code": 409,
                "message": "Запись уже изменилась. Загрузите актуальную версию и повторите.",
                "expected_version": expected,
                "current_version": old["version"],
                "current": current_payload,
            })
        return True

    def set_session_cookie(self, token):
        self._session_token = token

    # ---- static -----------------------------------------------------------

    def serve_static(self, path):
        if path == "/" or path == "":
            path = "/index.html"
        # защита от path traversal и доступа к защищённым директориям
        norm = os.path.normpath(path).replace("\\", "/")
        if ".." in norm or norm.startswith("/"):
            pass  # normpath убирает ..; leading slash нужен для join ниже
        if any(norm.startswith(p.rstrip("/")) and p in PROTECTED_DIRS for p in PROTECTED_DIRS):
            return self.error(404, "Не найдено")
        for bad in PROTECTED_DIRS:
            if ("/" + norm.strip("/") + "/").find(bad) != -1 or norm.lstrip("/").startswith(bad.strip("/")):
                return self.error(404, "Не найдено")
        full = os.path.realpath(os.path.join(STATIC_DIR, norm.lstrip("/")))
        if not full.startswith(os.path.realpath(STATIC_DIR)):
            return self.error(404, "Не найдено")
        if not os.path.isfile(full):
            # SPA: неизвестные пути без расширения отдаём index.html
            if "." not in os.path.basename(norm):
                full = os.path.join(STATIC_DIR, "index.html")
                if not os.path.isfile(full):
                    return self.error(404, "Не найдено")
            else:
                return self.error(404, "Не найдено")
        ext = os.path.splitext(full)[1].lower()
        ctype = MIME.get(ext, "application/octet-stream")
        with open(full, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    # ---- verbs ------------------------------------------------------------

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, If-Match")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)
        try:
            if path.startswith("/api/"):
                if path != "/api/health" and not API_LIMITER.allow(self.client_ip()):
                    return self.too_many(60)
                return self.api_get(path, qs)
            if path.startswith("/static/"):
                return self.serve_static(path[len("/static"):])
            return self.serve_static(path)
        except Exception as e:  # noqa: BLE001
            self.error(500, "Внутренняя ошибка сервера: %s" % e)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if not path.startswith("/api/"):
                return self.error(404, "Не найдено")
            if path != "/api/login" and not API_LIMITER.allow(self.client_ip()):
                return self.too_many(60)
            return self.api_post(path)
        except Exception as e:  # noqa: BLE001
            self.error(500, "Внутренняя ошибка сервера: %s" % e)

    def do_PUT(self):
        parsed = urlparse(self.path)
        try:
            if not parsed.path.startswith("/api/"):
                return self.error(404, "Не найдено")
            if not API_LIMITER.allow(self.client_ip()):
                return self.too_many(60)
            return self.api_put(parsed.path)
        except Exception as e:  # noqa: BLE001
            self.error(500, "Внутренняя ошибка сервера: %s" % e)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        try:
            if not parsed.path.startswith("/api/"):
                return self.error(404, "Не найдено")
            if not API_LIMITER.allow(self.client_ip()):
                return self.too_many(60)
            return self.api_delete(parsed.path, qs)
        except Exception as e:  # noqa: BLE001
            self.error(500, "Внутренняя ошибка сервера: %s" % e)

    # ---- API GET ----------------------------------------------------------

    def api_get(self, path, qs):
        if path == "/api/health":
            return self.send_json(200, {"status": "ok", "time": now_iso()})
        if path == "/api/me":
            sess = get_session(self.session_cookie())
            if sess:
                return self.send_json(200, {"authenticated": True, "role": "admin",
                                            "csrf_token": sess["csrf"]})
            return self.send_json(401, {"authenticated": False})
        m = re.match(r"^/api/public/sites/([a-z0-9\-]+)\.json$", path)
        if m:
            conn = db()
            try:
                data = public_site(conn, m.group(1))
            finally:
                conn.close()
            if data is None:
                return self.error(404, "Сайт не найден")
            return self.send_json(200, data, cors=True)
        if path == "/api/public/sites":
            conn = db()
            try:
                rows = conn.execute(
                    "SELECT slug, name, brand, domain, tagline FROM sites "
                    "WHERE is_active=1 ORDER BY id").fetchall()
            finally:
                conn.close()
            return self.send_json(200, {"sites": [dict(r) for r in rows]}, cors=True)

        # далее — только авторизованные запросы
        if not self.require_auth():
            return

        if path == "/api/overview":
            raw_site = (qs.get("site_id") or [""])[0]
            raw_limit = (qs.get("attention_limit") or ["5"])[0]
            try:
                overview_site_id = int(raw_site) if raw_site else None
                attention_limit = int(raw_limit)
            except ValueError:
                return self.error(400, "site_id и attention_limit должны быть числами")
            conn = db()
            try:
                data = build_overview(conn, overview_site_id, attention_limit)
            finally:
                conn.close()
            if data is None:
                return self.error(404, "Сайт не найден")
            return self.send_json(200, data)

        if path == "/api/sites":
            conn = db()
            try:
                rows = conn.execute("SELECT * FROM sites ORDER BY id").fetchall()
                counts = conn.execute(
                    "SELECT site_id, type, COUNT(*) AS c FROM items GROUP BY site_id, type"
                ).fetchall()
            finally:
                conn.close()
            sites = [row_site(r) for r in rows]
            cmap = {}
            for c in counts:
                cmap.setdefault(c["site_id"], {})[c["type"]] = c["c"]
            for s in sites:
                s["counts"] = cmap.get(s["id"], {})
            return self.send_json(200, {"sites": sites})

        m = re.match(r"^/api/sites/(\d+)$", path)
        if m:
            conn = db()
            try:
                r = conn.execute("SELECT * FROM sites WHERE id=?", (m.group(1),)).fetchone()
            finally:
                conn.close()
            if not r:
                return self.error(404, "Сайт не найден")
            return self.send_json(200, row_site(r))

        m = re.match(r"^/api/sites/(\d+)/items$", path)
        if m:
            typ = (qs.get("type") or [""])[0]
            if typ and typ not in ITEM_TYPES:
                return self.error(400, "Неизвестный тип элемента")
            conn = db()
            try:
                if conn.execute("SELECT id FROM sites WHERE id=?", (m.group(1),)).fetchone() is None:
                    return self.error(404, "Сайт не найден")
                if typ:
                    rows = conn.execute(
                        "SELECT * FROM items WHERE site_id=? AND type=? ORDER BY sort_order, id",
                        (m.group(1), typ)).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT * FROM items WHERE site_id=? ORDER BY type, sort_order, id",
                        (m.group(1),)).fetchall()
            finally:
                conn.close()
            return self.send_json(200, {"items": [row_item(r) for r in rows]})

        m = re.match(r"^/api/items/(\d+)$", path)
        if m:
            conn = db()
            try:
                r = conn.execute("SELECT * FROM items WHERE id=?", (m.group(1),)).fetchone()
            finally:
                conn.close()
            if not r:
                return self.error(404, "Элемент не найден")
            return self.send_json(200, row_item(r))

        m = re.match(r"^/api/sites/(\d+)/export$", path)
        if m:
            conn = db()
            try:
                data = export_site(conn, int(m.group(1)))
            finally:
                conn.close()
            if data is None:
                return self.error(404, "Сайт не найден")
            return self.send_json(200, data)

        return self.error(404, "Не найдено")

    # ---- API POST ---------------------------------------------------------

    def api_post(self, path):
        if path == "/api/login":
            ip = self.client_ip()
            if LOGIN_LIMITER.blocked(ip):
                return self.too_many(15 * 60)
            body = self.read_body()
            if body is None:
                return self.error(400, "Некорректный JSON")
            pwd = body.get("password", "")
            if not isinstance(pwd, str) or not secrets.compare_digest(pwd, get_password()):
                LOGIN_LIMITER.hit(ip)
                self.audit_action("login_failed")
                return self.error(401, "Неверный пароль")
            LOGIN_LIMITER.reset(ip)
            self.audit_action("login_ok")
            token, csrf = create_session()
            # cookie должна быть установлена до записи тела ответа (end_headers)
            secure = "; Secure" if TLS_ENABLED else ""
            self._pending_cookie = ("admin_session=%s; Path=/; HttpOnly; SameSite=Lax%s; Max-Age=%d"
                                    % (token, secure, SESSION_TTL))
            return self.send_json(200, {"ok": True, "role": "admin", "csrf_token": csrf})

        if not self.require_csrf():
            return

        if path == "/api/logout":
            tok = self.session_cookie()
            if tok:
                destroy_session(tok)
            self.audit_action("logout")
            return self.send_json(200, {"ok": True})

        if path == "/api/sites":
            body = self.read_body()
            if body is None:
                return self.error(400, "Некорректный JSON")
            return self.create_site(body)

        m = re.match(r"^/api/sites/(\d+)/items$", path)
        if m:
            body = self.read_body()
            if body is None:
                return self.error(400, "Некорректный JSON")
            return self.create_item(int(m.group(1)), body)

        m = re.match(r"^/api/sites/(\d+)/export-file$", path)
        if m:
            conn = db()
            try:
                srow = conn.execute("SELECT * FROM sites WHERE id=?", (m.group(1),)).fetchone()
                if not srow:
                    return self.error(404, "Сайт не найден")
                data = export_site(conn, srow["id"])
                slug = srow["slug"]
            finally:
                conn.close()
            if not SLUG_RE.match(slug):
                return self.error(400, "Некорректный slug сайта")
            os.makedirs(EXPORTS_DIR, exist_ok=True)
            fname = os.path.join(EXPORTS_DIR, slug + ".json")
            with open(fname, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self.audit_action("export_file", site_id=srow["id"], slug=slug)
            return self.send_json(200, {"ok": True, "path": "admin/exports/%s.json" % slug})

        return self.error(404, "Не найдено")

    def create_site(self, body):
        slug = (body.get("slug") or "").strip().lower()
        name = (body.get("name") or "").strip()
        if not SLUG_RE.match(slug):
            return self.error(400, "Slug: только латиница, цифры и дефис (2–64 симв.)")
        if not name:
            return self.error(400, "Не указано название сайта")
        conn = db()
        try:
            if conn.execute("SELECT 1 FROM sites WHERE slug=?", (slug,)).fetchone():
                return self.error(400, "Сайт с таким slug уже существует")
            ts = now_iso()
            vals = []
            for f in SITE_FIELDS:
                v = body.get(f, "")
                if f == "is_active":
                    v = 1 if v else 0
                elif not isinstance(v, str):
                    v = json.dumps(v, ensure_ascii=False)
                vals.append(v)
            cur = conn.execute(
                "INSERT INTO sites (%s, created_at, updated_at) VALUES (%s)"
                % (", ".join(SITE_FIELDS), ", ".join(["?"] * len(SITE_FIELDS))),
                vals + [ts, ts])
            conn.commit()
            r = conn.execute("SELECT * FROM sites WHERE id=?", (cur.lastrowid,)).fetchone()
            self.audit_action("site_create", site_id=cur.lastrowid, slug=slug)
            return self.send_json(201, row_site(r))
        finally:
            conn.close()

    def create_item(self, site_id, body):
        typ = body.get("type")
        if typ not in ITEM_TYPES:
            return self.error(400, "Неизвестный тип элемента")
        conn = db()
        try:
            if conn.execute("SELECT id FROM sites WHERE id=?", (site_id,)).fetchone() is None:
                return self.error(404, "Сайт не найден")
            data = clean_item_data(typ, body.get("data", {}))
            try:
                order = int(body.get("sort_order") or 0)
            except (TypeError, ValueError):
                order = 0
            ts = now_iso()
            cur = conn.execute(
                "INSERT INTO items (site_id, type, data, sort_order, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (site_id, typ, json.dumps(data, ensure_ascii=False), order, ts, ts))
            conn.commit()
            r = conn.execute("SELECT * FROM items WHERE id=?", (cur.lastrowid,)).fetchone()
            self.audit_action("item_create", item_id=cur.lastrowid, site_id=site_id, type=typ)
            return self.send_json(201, row_item(r))
        finally:
            conn.close()

    # ---- API PUT / DELETE ---------------------------------------------------

    def api_put(self, path):
        if not self.require_csrf():
            return
        m = re.match(r"^/api/sites/(\d+)$", path)
        if m:
            return self.update_site(int(m.group(1)))
        m = re.match(r"^/api/items/(\d+)$", path)
        if m:
            return self.update_item(int(m.group(1)))
        return self.error(404, "Не найдено")

    def update_site(self, site_id):
        body = self.read_body()
        if body is None:
            return self.error(400, "Некорректный JSON")
        expected = self.expected_version(body=body)
        conn = db()
        try:
            old = conn.execute("SELECT * FROM sites WHERE id=?", (site_id,)).fetchone()
            if not old:
                return self.error(404, "Сайт не найден")
            if not self.require_version(old, expected, row_site(old)):
                return
            updates, params = [], []
            for f in SITE_FIELDS:
                if f in body:
                    v = body[f]
                    if f == "is_active":
                        v = 1 if v else 0
                    elif not isinstance(v, str):
                        v = json.dumps(v, ensure_ascii=False)
                    updates.append(f"{f}=?")
                    params.append(v)
            if "slug" in body and not SLUG_RE.match(str(body["slug"]).strip().lower()):
                return self.error(400, "Некорректный slug")
            if not updates:
                return self.error(400, "Нет полей для обновления")
            updates.append("version = version + 1")
            updates.append("updated_at=?")
            params += [now_iso(), site_id, old["version"]]
            cur = conn.execute(
                f"UPDATE sites SET {', '.join(updates)} WHERE id=? AND version=?", params)
            if cur.rowcount == 0:
                current = conn.execute("SELECT * FROM sites WHERE id=?", (site_id,)).fetchone()
                conn.rollback()
                if not current:
                    return self.error(404, "Сайт не найден")
                return self.send_json(409, {
                    "error": "version_conflict", "code": 409,
                    "message": "Запись уже изменилась. Загрузите актуальную версию и повторите.",
                    "expected_version": expected,
                    "current_version": current["version"],
                    "current": row_site(current),
                })
            conn.commit()
            r = conn.execute("SELECT * FROM sites WHERE id=?", (site_id,)).fetchone()
            self.audit_action("site_update", site_id=site_id,
                              fields=sorted(set(body) & set(SITE_FIELDS)),
                              old_version=old["version"], new_version=r["version"])
            return self.send_json(200, row_site(r))
        finally:
            conn.close()

    def update_item(self, item_id):
        body = self.read_body()
        if body is None:
            return self.error(400, "Некорректный JSON")
        expected = self.expected_version(body=body)
        conn = db()
        try:
            old = conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
            if not old:
                return self.error(404, "Элемент не найден")
            if not self.require_version(old, expected, row_item(old)):
                return
            typ = old["type"]
            data = clean_item_data(typ, body.get("data", {})) if "data" in body \
                else json.loads(old["data"])
            try:
                order = int(body.get("sort_order", old["sort_order"]))
            except (TypeError, ValueError):
                order = old["sort_order"]
            cur = conn.execute(
                "UPDATE items SET data=?, sort_order=?, version = version + 1, updated_at=?"
                " WHERE id=? AND version=?",
                (json.dumps(data, ensure_ascii=False), order, now_iso(), item_id, old["version"]))
            if cur.rowcount == 0:
                current = conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
                conn.rollback()
                if not current:
                    return self.error(404, "Элемент не найден")
                return self.send_json(409, {
                    "error": "version_conflict", "code": 409,
                    "message": "Запись уже изменилась. Загрузите актуальную версию и повторите.",
                    "expected_version": expected,
                    "current_version": current["version"],
                    "current": row_item(current),
                })
            conn.commit()
            r = conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
            self.audit_action("item_update", item_id=item_id, type=typ,
                              old_version=old["version"], new_version=r["version"])
            return self.send_json(200, row_item(r))
        finally:
            conn.close()

    def api_delete(self, path, qs=None):
        if not self.require_csrf():
            return
        expected = self.expected_version(qs=qs)
        m = re.match(r"^/api/sites/(\d+)$", path)
        if m:
            conn = db()
            try:
                r = conn.execute("SELECT * FROM sites WHERE id=?", (m.group(1),)).fetchone()
                if not r:
                    return self.error(404, "Сайт не найден")
                if not self.require_version(r, expected, row_site(r)):
                    return
                cur = conn.execute(
                    "DELETE FROM sites WHERE id=? AND version=?", (r["id"], r["version"]))
                if cur.rowcount == 0:
                    current = conn.execute("SELECT * FROM sites WHERE id=?", (r["id"],)).fetchone()
                    conn.rollback()
                    if not current:
                        return self.error(404, "Сайт не найден")
                    return self.send_json(409, {
                        "error": "version_conflict", "code": 409,
                        "message": "Запись уже изменилась. Загрузите актуальную версию и повторите.",
                        "expected_version": expected,
                        "current_version": current["version"],
                        "current": row_site(current),
                    })
                conn.commit()
            finally:
                conn.close()
            self.audit_action("site_delete", site_id=r["id"], slug=r["slug"])
            return self.send_json(200, {"ok": True})

        m = re.match(r"^/api/items/(\d+)$", path)
        if m:
            conn = db()
            try:
                r = conn.execute("SELECT * FROM items WHERE id=?", (m.group(1),)).fetchone()
                if not r:
                    return self.error(404, "Элемент не найден")
                if not self.require_version(r, expected, row_item(r)):
                    return
                cur = conn.execute(
                    "DELETE FROM items WHERE id=? AND version=?", (r["id"], r["version"]))
                if cur.rowcount == 0:
                    current = conn.execute("SELECT * FROM items WHERE id=?", (r["id"],)).fetchone()
                    conn.rollback()
                    if not current:
                        return self.error(404, "Элемент не найден")
                    return self.send_json(409, {
                        "error": "version_conflict", "code": 409,
                        "message": "Запись уже изменилась. Загрузите актуальную версию и повторите.",
                        "expected_version": expected,
                        "current_version": current["version"],
                        "current": row_item(current),
                    })
                conn.commit()
            finally:
                conn.close()
            self.audit_action("item_delete", item_id=m.group(1))
            return self.send_json(200, {"ok": True})
        return self.error(404, "Не найдено")

    # override: добавляем Set-Cookie и security-заголовки
    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if TLS_ENABLED:
            self.send_header("Strict-Transport-Security", "max-age=31536000")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; script-src 'self'; "
                         "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                         "font-src 'self'; connect-src 'self'; "
                         "frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
        retry = getattr(self, "_retry_after", None)
        if retry:
            self.send_header("Retry-After", retry)
            self._retry_after = None
        cookie = getattr(self, "_pending_cookie", None)
        if cookie:
            self.send_header("Set-Cookie", cookie)
            self._pending_cookie = None
        super().end_headers()


def main():
    ap = argparse.ArgumentParser(description="Админ-панель Dialam (прототип)")
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--ssl-cert", default=os.environ.get("ADMIN_SSL_CERT", ""))
    ap.add_argument("--ssl-key", default=os.environ.get("ADMIN_SSL_KEY", ""))
    args = ap.parse_args()

    os.umask(0o077)
    load_sessions()
    init_db()
    global TLS_ENABLED
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    scheme = "http"
    if args.ssl_cert and args.ssl_key:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(args.ssl_cert, args.ssl_key)
        httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
        TLS_ENABLED = True
        scheme = "https"
    print("Админ-панель запущена: %s://%s:%d/  (Ctrl+C для остановки)" % (scheme, args.host, args.port))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nОстановка сервера.")
        httpd.shutdown()


if __name__ == "__main__":
    main()
