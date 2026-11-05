# -*- coding: utf-8 -*-
"""Проверка битых внутренних ссылок и подключённых ассетов статического сайта.

`site_perf.py check` смотрит только `<img>`. Этот скрипт проверяет:
  - `<a href>` — внутренние ссылки (внешние, mailto:, tel:, #, javascript: пропускаются);
  - `<link href>` — CSS, иконки, manifest;
  - `<script src>`, `<source src|srcset>`, `<video/audio src>`;
  - якоря `page.html#id` — существование id на целевой странице.

Запуск:
    python tools/find_broken_links.py                # отчёт по всем сайтам
    python tools/find_broken_links.py --strict       # exit 1 при находках (для CI)
    python tools/find_broken_links.py dialam-site    # один сайт
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

WORKSPACE = Path(__file__).resolve().parents[1]
SITES = ("dialam-site", "diamedika-site", "consulting-site-v2", "portfolio-website")
SKIP_DIRS = {
    ".git", "node_modules", "dist", "build", "verify-shots", "notes",
    ".github", ".tmp-build", "site-packages", "dsh-runtimes", "uv-tools",
    "admin",
}
A_RE = re.compile(r'<a\b[^>]*\bhref\s*=\s*"([^"]*)"', re.I)
LINK_RE = re.compile(r'<link\b[^>]*\bhref\s*=\s*"([^"]*)"', re.I)
SCRIPT_RE = re.compile(r'<script\b[^>]*\bsrc\s*=\s*"([^"]*)"', re.I)
SOURCE_RE = re.compile(r'<(?:source|video|audio)\b[^>]*\bsrc\s*=\s*"([^"]*)"', re.I)
CSS_URL_RE = re.compile(r"url\(([^)]+)\)", re.I)
ID_RE = re.compile(r'\bid\s*=\s*"([^"]+)"', re.I)
HTML_EXT = {".html", ".htm"}
SKIP_SCHEMES = ("http://", "https://", "//", "mailto:", "tel:", "javascript:", "data:", "sms:")


def iter_files(root: Path, suffixes: set[str]):
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in suffixes:
            if any(part in SKIP_DIRS for part in p.relative_to(root).parts):
                continue
            yield p


def html_files(root: Path):
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in HTML_EXT:
            if any(part in SKIP_DIRS for part in p.relative_to(root).parts):
                continue
            yield p


def _target_exists(root: Path, base_dir: Path, href_path: str) -> Path | None:
    """Найти файл по пути ссылки; папка -> index.html.

    Для Vite-проектов публичные ассеты лежат в `public/`, а из HTML
    ссылаются как от корня (`/favicon.svg`), поэтому проверяются оба корня.
    """
    raw = unquote(href_path)
    if raw.startswith("/"):
        candidates = [root / raw.lstrip("/"), root / "public" / raw.lstrip("/")]
    else:
        candidates = [base_dir / raw]
    for candidate in candidates:
        candidate = candidate.resolve()
        if candidate.is_file():
            return candidate
        if candidate.is_dir():
            index = candidate / "index.html"
            if index.is_file():
                return index
    return None


def collect_ids(path: Path) -> set[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    return set(ID_RE.findall(text))


def check_site(root: Path) -> list[str]:
    problems: list[str] = []
    id_cache: dict[Path, set[str]] = {}
    for page in html_files(root):
        rel_page = page.relative_to(root).as_posix()
        try:
            text = page.read_text(encoding="utf-8", errors="replace")
        except OSError:
            problems.append(f"{rel_page}: не читается")
            continue
        refs: list[str] = []
        for pattern in (A_RE, LINK_RE, SCRIPT_RE, SOURCE_RE):
            refs.extend(pattern.findall(text))
        for ref in refs:
            href = ref.strip()
            if not href or href.startswith(SKIP_SCHEMES) or href.startswith("#"):
                continue
            if "{{" in href:  # шаблонные подстановки генератора — проверит сборка
                continue
            if "%BASE_URL%" in href:  # Vite-токен: подставляется base при сборке
                href = href.replace("%BASE_URL%", "/")
            parts = urlsplit(href)
            if parts.scheme or parts.netloc:
                continue
            target_path = parts.path
            anchor = parts.fragment
            if not target_path and not anchor:
                continue
            target = page
            if target_path:
                target = _target_exists(root, page.parent, target_path)
                if target is None:
                    problems.append(f"{rel_page}: нет файла для «{href}»")
                    continue
            if anchor:
                ids = id_cache.setdefault(target, collect_ids(target))
                if anchor not in ids:
                    problems.append(f"{rel_page}: нет якоря «#{anchor}» в {target.relative_to(root).as_posix()}")

    # CSS: url(...) на локальные файлы (шрифты, фоновые картинки)
    for css in iter_files(root, {".css"}):
        rel_css = css.relative_to(root).as_posix()
        try:
            text = css.read_text(encoding="utf-8", errors="replace")
        except OSError:
            problems.append(f"{rel_css}: не читается")
            continue
        for raw in CSS_URL_RE.findall(text):
            url = raw.strip().strip("\"'")
            if not url or url.startswith(("data:", "#", "var(", "http://", "https://", "//")):
                continue
            if "%BASE_URL%" in url:
                url = url.replace("%BASE_URL%", "/")
            path = urlsplit(url).path
            if not path:
                continue
            if _target_exists(root, css.parent, path) is None:
                problems.append(f"{rel_css}: нет файла для url(«{url}»)")
    return problems


def resolve_root(arg: str) -> Path:
    """Папка сайта: абсолютный путь, путь от CWD (CI/вендорная копия) или
    от корня workspace (локальный вызов по имени сайта)."""
    p = Path(arg)
    if p.is_absolute():
        return p
    from_cwd = (Path.cwd() / p).resolve()
    if from_cwd.is_dir():
        return from_cwd
    return (WORKSPACE / p).resolve()


def main() -> int:
    ap = argparse.ArgumentParser(description="Проверка битых внутренних ссылок")
    ap.add_argument("sites", nargs="*", help="папки сайтов (по умолчанию все из AGENTS.md)")
    ap.add_argument("--strict", action="store_true", help="exit 1 при находках")
    args = ap.parse_args()

    sites = tuple(args.sites) if args.sites else SITES
    total = 0
    for site in sites:
        root = resolve_root(site)
        if not root.is_dir():
            print(f"=== {site}: нет папки ===")
            total += 1
            continue
        problems = check_site(root)
        name = root.name
        total += len(problems)
        if not problems:
            print(f"=== {name}: ссылки в порядке ===")
            continue
        print(f"=== {name}: {len(problems)} проблем ===")
        for problem in problems:
            print("  " + problem)
    print()
    print(f"Всего проблем: {total}")
    if total and not args.strict:
        print("(отчёт: --strict вернёт exit 1)")
    return 1 if total and args.strict else 0


if __name__ == "__main__":
    raise SystemExit(main())
