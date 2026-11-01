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
import sys
import threading
import time
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
SESSIONS = {}          # token -> expires (unix timestamp)
SESSIONS_LOCK = threading.Lock()
SESSION_TTL = 72 * 3600  # 72 часа


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_password():
    return os.environ.get("ADMIN_PASSWORD", "admin123")


def create_session():
    token = secrets.token_hex(32)
    with SESSIONS_LOCK:
        SESSIONS[token] = time.time() + SESSION_TTL
    return token


def check_session(token):
    if not token:
        return False
    with SESSIONS_LOCK:
        expires = SESSIONS.get(token)
        if not expires:
            return False
        if expires < time.time():
            SESSIONS.pop(token, None)
            return False
        return True


def destroy_session(token):
    with SESSIONS_LOCK:
        SESSIONS.pop(token, None)


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
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
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

    def require_auth(self):
        if check_session(self.session_cookie()):
            return True
        self.error(401, "Требуется вход в систему")
        return False

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
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)
        try:
            if path.startswith("/api/"):
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
            return self.api_post(path)
        except Exception as e:  # noqa: BLE001
            self.error(500, "Внутренняя ошибка сервера: %s" % e)

    def do_PUT(self):
        parsed = urlparse(self.path)
        try:
            if not parsed.path.startswith("/api/"):
                return self.error(404, "Не найдено")
            return self.api_put(parsed.path)
        except Exception as e:  # noqa: BLE001
            self.error(500, "Внутренняя ошибка сервера: %s" % e)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        try:
            if not parsed.path.startswith("/api/"):
                return self.error(404, "Не найдено")
            return self.api_delete(parsed.path)
        except Exception as e:  # noqa: BLE001
            self.error(500, "Внутренняя ошибка сервера: %s" % e)

    # ---- API GET ----------------------------------------------------------

    def api_get(self, path, qs):
        if path == "/api/health":
            return self.send_json(200, {"status": "ok", "time": now_iso()})
        if path == "/api/me":
            if check_session(self.session_cookie()):
                return self.send_json(200, {"authenticated": True, "role": "admin"})
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
            body = self.read_body()
            if body is None:
                return self.error(400, "Некорректный JSON")
            pwd = body.get("password", "")
            if not isinstance(pwd, str) or not secrets.compare_digest(pwd, get_password()):
                return self.error(401, "Неверный пароль")
            token = create_session()
            # cookie должна быть установлена до записи тела ответа (end_headers)
            self._pending_cookie = ("admin_session=%s; Path=/; HttpOnly; SameSite=Lax; Max-Age=%d"
                                    % (token, SESSION_TTL))
            return self.send_json(200, {"ok": True, "role": "admin"})

        if not self.require_auth():
            return

        if path == "/api/logout":
            tok = self.session_cookie()
            if tok:
                destroy_session(tok)
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
            return self.send_json(201, row_item(r))
        finally:
            conn.close()

    # ---- API PUT / DELETE ---------------------------------------------------

    def api_put(self, path):
        if not self.require_auth():
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
        conn = db()
        try:
            old = conn.execute("SELECT * FROM sites WHERE id=?", (site_id,)).fetchone()
            if not old:
                return self.error(404, "Сайт не найден")
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
            updates.append("updated_at=?")
            params += [now_iso(), site_id]
            conn.execute(f"UPDATE sites SET {', '.join(updates)} WHERE id=?", params)
            conn.commit()
            r = conn.execute("SELECT * FROM sites WHERE id=?", (site_id,)).fetchone()
            return self.send_json(200, row_site(r))
        finally:
            conn.close()

    def update_item(self, item_id):
        body = self.read_body()
        if body is None:
            return self.error(400, "Некорректный JSON")
        conn = db()
        try:
            old = conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
            if not old:
                return self.error(404, "Элемент не найден")
            typ = old["type"]
            data = clean_item_data(typ, body.get("data", {})) if "data" in body \
                else json.loads(old["data"])
            try:
                order = int(body.get("sort_order", old["sort_order"]))
            except (TypeError, ValueError):
                order = old["sort_order"]
            conn.execute(
                "UPDATE items SET data=?, sort_order=?, updated_at=? WHERE id=?",
                (json.dumps(data, ensure_ascii=False), order, now_iso(), item_id))
            conn.commit()
            r = conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
            return self.send_json(200, row_item(r))
        finally:
            conn.close()

    def api_delete(self, path):
        if not self.require_auth():
            return
        m = re.match(r"^/api/sites/(\d+)$", path)
        if m:
            conn = db()
            try:
                r = conn.execute("SELECT * FROM sites WHERE id=?", (m.group(1),)).fetchone()
                if not r:
                    return self.error(404, "Сайт не найден")
                conn.execute("DELETE FROM items WHERE site_id=?", (r["id"],))
                conn.execute("DELETE FROM sites WHERE id=?", (r["id"],))
                conn.commit()
            finally:
                conn.close()
            return self.send_json(200, {"ok": True})
        m = re.match(r"^/api/items/(\d+)$", path)
        if m:
            conn = db()
            try:
                cur = conn.execute("DELETE FROM items WHERE id=?", (m.group(1),))
                conn.commit()
                if cur.rowcount == 0:
                    return self.error(404, "Элемент не найден")
            finally:
                conn.close()
            return self.send_json(200, {"ok": True})
        return self.error(404, "Не найдено")

    # override: добавляем Set-Cookie после login
    def end_headers(self):
        cookie = getattr(self, "_pending_cookie", None)
        if cookie:
            self.send_header("Set-Cookie", cookie)
            self._pending_cookie = None
        super().end_headers()


def main():
    ap = argparse.ArgumentParser(description="Админ-панель Dialam (прототип)")
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()

    init_db()
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print("Админ-панель запущена: http://%s:%d/  (Ctrl+C для остановки)" % (args.host, args.port))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nОстановка сервера.")
        httpd.shutdown()


if __name__ == "__main__":
    main()
