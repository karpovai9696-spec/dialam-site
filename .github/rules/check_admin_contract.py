# -*- coding: utf-8 -*-
"""Сверка API_CONTRACT.md с маршрутами админки (dialam-site/admin/server.py).

Ловит дрейф контракта: эндпоинт описан в документации, но в коде его нет
(ERROR; при --strict это exit 1). Обратный случай (маршрут есть, в контракте
нет) — предупреждение: контракт может документировать подмножество, но при
--verbose список печатается.

Запуск (из корня репозитория dialam-site):
    python .github/rules/check_admin_contract.py --strict admin
    python tools/check_admin_contract.py dialam-site/admin --verbose
Синхронизация в репозиторий сайта: python tools/sync_site_perf.py --apply
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
DOC_RE = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE)\s+(/api/[A-Za-z0-9._\-/{}\[\]]+)")
EXACT_RE = re.compile(r'path\s*==\s*"(/api/[^"]*)"')
PREFIX_RE = re.compile(r'path\.startswith\(\s*"(/api/[^"]*)"')
REGEX_ROUTE_RE = re.compile(r'r"\^?(/api/[^"]*?)\$?"')
HANDLER_RE = re.compile(r"def (api_get|api_post|api_put|api_delete|do_GET|do_POST|do_PUT|do_DELETE)\b")
GROUP_RE = re.compile(r"\(\?P<[^>]+>\[\^/\]\+\)|\(\[\^/\]\+\)")
METHOD_BY_HANDLER = {
    "api_get": "GET", "api_post": "POST", "api_put": "PUT", "api_delete": "DELETE",
    "do_GET": "GET", "do_POST": "POST", "do_PUT": "PUT", "do_DELETE": "DELETE",
}


def norm(path: str) -> str:
    path = path.split("?", 1)[0].strip()
    path = re.sub(r"\{[^}]*\}", "{}", path)
    path = GROUP_RE.sub("{}", path)
    path = re.sub(r"\([^()]*\)", "{}", path)  # (\d+), (.*) и прочие группы
    path = path.replace("\\.", ".").rstrip("$").rstrip("/") or "/"
    return path


TABLE_ROW_RE = re.compile(r"\|\s*(GET|POST|PUT|PATCH|DELETE)\s*\|\s*`?(/api/[^`|\s]+)`?\s*\|")


def documented(doc: Path) -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    text = doc.read_text(encoding="utf-8", errors="replace")
    for match in DOC_RE.finditer(text):
        found.add((match.group(1), norm(match.group(2))))
    # markdown-таблицы: | GET | `/api/path` | ...
    for match in TABLE_ROW_RE.finditer(text):
        found.add((match.group(1), norm(match.group(2))))
    return found


def implemented(server: Path) -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    current = ""
    for line in server.read_text(encoding="utf-8", errors="replace").splitlines():
        handler = HANDLER_RE.search(line)
        if handler:
            current = METHOD_BY_HANDLER[handler.group(1)]
            continue
        if not current:
            continue
        for match in EXACT_RE.finditer(line):
            found.add((current, norm(match.group(1))))
        for match in PREFIX_RE.finditer(line):
            path = norm(match.group(1))
            if path in ("/api", "/"):
                continue  # общий guard «это API» — не маршрут
            found.add((current, path + "*"))
        for match in REGEX_ROUTE_RE.finditer(line):
            path = norm(match.group(1))
            if "{}" in path:
                found.add((current, path))
    return found


def covered(endpoint: tuple[str, str], impl: set[tuple[str, str]]) -> bool:
    method, path = endpoint
    for impl_method, impl_path in impl:
        if impl_method != method:
            continue
        if impl_path == path:
            return True
        if impl_path.endswith("*") and path.startswith(impl_path[:-1]):
            return True
        if "{}" in impl_path and "{}" in path and impl_path.count("/") == path.count("/"):
            return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description="Сверка API_CONTRACT.md и маршрутов админки")
    ap.add_argument("admin_dir", nargs="?", default="", help="папка админки (по умолчанию admin)")
    ap.add_argument("--strict", action="store_true", help="exit 1, если документированный эндпоинт не реализован")
    ap.add_argument("--verbose", action="store_true", help="печатать маршруты без документации")
    args = ap.parse_args()

    raw = Path(args.admin_dir) if args.admin_dir else Path("admin")
    admin = raw if raw.is_absolute() else (Path.cwd() / raw)
    if not admin.is_dir():
        admin = WORKSPACE / raw
    doc, server = admin / "API_CONTRACT.md", admin / "server.py"
    for path in (doc, server):
        if not path.is_file():
            print(f"ОШИБКА: нет файла {path}")
            return 2

    docs = documented(doc)
    impl = implemented(server)
    missing_impl = sorted(e for e in docs if not covered(e, impl))
    undocumented = sorted(e for e in impl if not covered((e[0], e[1].rstrip("*")), docs))

    print(f"=== {admin.name}: в контракте {len(docs)} эндпоинтов, в коде {len(impl)} маршрутов ===")
    for method, path in missing_impl:
        print(f"  ERROR документирован, но не найден в коде: {method} {path}")
    if args.verbose:
        for method, path in undocumented:
            print(f"  WARN  есть в коде, нет в контракте: {method} {path}")
    print(f"Расхождения: {len(missing_impl)} ошибок, {len(undocumented)} маршрутов вне контракта")
    return 1 if (missing_impl and args.strict) else 0


if __name__ == "__main__":
    raise SystemExit(main())
