# Контракт API админки: обзор и версионирование

## 1. `GET /api/overview`

Только для авторизованного администратора.

Параметры:

- `site_id` — необязательный ID сайта. Если не передан, «Требует внимания» собирается по всем брендам.
- `attention_limit` — сколько алертов вернуть, по умолчанию `5`, максимум `50`.

Ответ `200`:

```json
{
  "generated_at": "2026-11-01T09:00:00+00:00",
  "site_id": 1,
  "attention": {
    "total": 8,
    "items": [
      {
        "id": "branch_contact:1:7",
        "kind": "branch_contact",
        "severity": "warning",
        "title": "Филиал «Орёл»: не хватает контактов",
        "detail": "Не заполнено: телефон, адрес",
        "site_id": 1,
        "site_slug": "dialam",
        "section": "branch",
        "item_id": 7,
        "item_type": "branch",
        "action": {
          "kind": "edit_item",
          "section": "branch",
          "site_id": 1,
          "item_id": 7,
          "item_type": "branch"
        }
      }
    ],
    "hidden_count": 3,
    "empty": false
  },
  "content": [
    {
      "site_id": 1,
      "slug": "dialam",
      "name": "Диалам+",
      "counts": {"branch": 4, "news": 2, "staff": 4},
      "published": {"branch": 4, "news": 0},
      "total": 24,
      "published_total": 12
    }
  ],
  "branches": [
    {
      "city": "Волжск",
      "item_id": 2,
      "staff": 3,
      "vacancies": 0,
      "news": 2,
      "gaps": []
    }
  ],
  "recent": [
    {
      "at": "2026-11-01T08:59:00+00:00",
      "event": "item_update",
      "label": "Обновлена запись",
      "site_id": 1,
      "item_id": 12,
      "type": "news"
    }
  ],
  "actions": [
    {"id": "create_news", "label": "+ Новость", "kind": "create_item", "type": "news", "site_id": 1, "section": "news"},
    {"id": "create_vacancy", "label": "+ Вакансия", "kind": "create_item", "type": "vacancy", "site_id": 1, "section": "vacancy"},
    {"id": "review_publications", "label": "Проверить публикации", "kind": "open_section", "section": "news", "site_id": 1}
  ]
}
```

### Правила «Требует внимания»

| kind | severity | Условие |
|---|---|---|
| `site_legal` | critical / warning | не заполнены реквизиты сайта, ИНН, ОГРН, лицензия, телефон, e-mail или адрес |
| `license_missing` | critical | у сайта нет ни одной записи лицензии |
| `license_fields` | warning | у лицензии пусты номер, кем/когда выдана или файл |
| `branch_contact` | warning | у филиала пусты адрес, телефон или часы; «уточняется» считается пустым |
| `staff_fields` | warning | у сотрудника пусты ФИО, должность, филиал или аккредитация |
| `news_branch` | warning | у новости не указан филиал |
| `news_demo` | warning | заголовок начинается с «Демо-» |
| `vacancy_fields` | warning | у вакансии пусты филиал или контактный e-mail |
| `vacancy_demo` | warning | заголовок начинается с «Демо-» |
| `document_file` | warning | у документа нет ссылки на файл |
| `service_fields` | warning | у услуги пусты описание или цена |

Порядок: `critical` → `warning`; внутри — по `kind` и заголовку. UI показывает
первые 5, остальное — `hidden_count` и кнопка «Показать ещё».

### Пустое состояние

Если `attention.empty === true`, UI показывает «Всё под контролем» и не занимает
место под фиктивные алерты.

### Действия

- `create_item` — открыть модалку создания записи.
- `open_section` — перейти в раздел (`news`, `vacancy`, `settings` и т. д.).
- `edit_item` — открыть существующую запись по `item_id`.

---

## 2. Версионирование записей

У `sites` и `items` есть целочисленное поле `version`. При создании — `1`,
при каждом успешном `PUT`/`DELETE`-изменении увеличивается.

### Обновление

`PUT /api/sites/{id}` и `PUT /api/items/{id}` обязаны получить ожидаемую версию:

- в теле: `"expected_version": 3`;
- или в заголовке: `If-Match: "3"` / `If-Match: W/"3"`.

Без версии — `428 expected_version_required`.

Если версия не совпала — `409 version_conflict`:

```json
{
  "error": "version_conflict",
  "code": 409,
  "message": "Запись уже изменилась. Загрузите актуальную версию и повторите.",
  "expected_version": 3,
  "current_version": 4,
  "current": {"id": 12, "version": 4, "data": {}}
}
```

UI не затирает чужие изменения: показывает сообщение «Ваши изменения не сохранены»,
загружает актуальную запись и открывает её заново.

### Удаление

`DELETE /api/items/{id}?version=3` или `DELETE /api/sites/{id}?version=2`
(также поддерживается `If-Match`). Без версии — `428`, при конфликте — `409`.

### Создание

`POST` версию не требует; сервер возвращает созданную запись с `version: 1`.

---

## 3. Полный перечень маршрутов

Сверяется автоматически: `python tools/check_admin_contract.py --strict admin`
(в CI — шаг «Admin API contract matches server routes»). Добавили маршрут в
`server.py` — допишите его сюда, иначе это станет расхождением контракта.

Обозначения: **session** — cookie `admin_session`; **csrf** — заголовок
`X-CSRF-Token` из `/api/me` или `/api/login` (для мутаций обязателен, чужой
`Origin` отклоняется); **version** — `expected_version` в теле, `If-Match`
или `?version=` (см. §2); **auth** — требуется вход.

### Служебные и публичные

| Метод | Путь | Доступ | Ответ / назначение |
|---|---|---|---|
| GET | `/api/health` | без auth | `{"status":"ok","time":<iso>}` |
| GET | `/api/me` | session | `{"authenticated":true,"role":"admin","csrf_token":<token>}`; без сессии — `401 {"authenticated":false}` |
| GET | `/api/public/sites` | без auth, CORS | `{"sites":[{slug,name,brand,domain,tagline}]}` — только `is_active=1` |
| GET | `/api/public/sites/{slug}.json` | без auth, CORS | публичный JSON сайта по slug; `404`, если сайта нет |

### Чтение (auth)

| Метод | Путь | Назначение |
|---|---|---|
| GET | `/api/overview?site_id=&attention_limit=` | сводка, см. §1 |
| GET | `/api/sites` | `{"sites":[…]}` + `counts` по типам элементов |
| GET | `/api/sites/{id}` | сайт (все поля `SITE_FIELDS`) или `404` |
| GET | `/api/sites/{id}/items?type=` | элементы сайта; `type` — из списка типов ниже; сортировка `sort_order, id` |
| GET | `/api/items/{id}` | элемент или `404` |
| GET | `/api/sites/{id}/export` | экспорт сайта для статики (JSON), `404` если сайта нет |

### Запись (session + csrf)

| Метод | Путь | Тело/параметры | Назначение |
|---|---|---|---|
| POST | `/api/login` | `{"password": "…"}` | ставит cookie `admin_session` (HttpOnly, SameSite=Lax, 72 ч), возвращает `csrf_token`; лимит неудачных попыток на IP |
| POST | `/api/logout` | — | уничтожает сессию, audit `logout` |
| POST | `/api/sites` | `slug`,`name` обязательны; остальные поля `SITE_FIELDS` | создаёт сайт, `version: 1`; slug — латиница/цифры/дефис, 2–64 симв. |
| POST | `/api/sites/{id}/items` | `type` (обязателен), `data` (объект), `sort_order` | создаёт элемент, `version: 1`; поля `data` очищаются по типу |
| POST | `/api/sites/{id}/export-file` | — | пишет `admin/exports/{slug}.json`, audit `export_file` |
| PUT | `/api/sites/{id}` | поля `SITE_FIELDS` + version | обновляет сайт, `version+1` |
| PUT | `/api/items/{id}` | поля `data` + version | обновляет элемент, `version+1` |
| DELETE | `/api/sites/{id}` | version | удаляет сайт; элементы удаляются каскадом (`ON DELETE CASCADE`) |
| DELETE | `/api/items/{id}` | version | удаляет элемент |

Ошибки версий — §2 (`428` без версии, `409 version_conflict`).

### Типы элементов и допустимые поля `data`

- `branch`: city, address, phone, email, hours, map_url, is_active
- `license`: number, issued_by, issued_at, file_url, note
- `news`: title, date, excerpt, body, image_url, published, branch
- `vacancy`: title, city, employment, salary, description, requirements, contact_email, published, branch
- `staff`: name, role, branch, phone, email, education, accreditation, photo
- `service`: name, category, description, price, is_active
- `document`: title, category, file_url, published
- `setting`: key, value

### Поля сайта (`SITE_FIELDS`)

slug, name, brand, domain, tagline, description, legal_name, inn, ogrn,
license_number, license_issued_by, license_date, phone, email, address, theme,
is_active.