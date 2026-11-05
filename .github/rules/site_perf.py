#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Обязательный performance-инструмент для сайтов workspace.

Команды:
  audit <site>              отчёт: изображения, страницы, JS/CSS
  optimize <site> --apply   WebP + lazy/decoding/width/height/fallback
  check <site>              проверка, exit 1 при нарушениях (включая PNG-фолбэк
                            у фото: должен быть JPG, AGENTS.md §2.9)

Фолбэк для onerror: для JPG-исходника — сам JPG, для непрозрачного PNG-фото
генерируется соседний .jpg (PNG-фото весит как исходник, AGENTS.md §2.9);
для графики с прозрачностью и логотипов фолбэком остаётся PNG/SVG.

Пример:
  python tools/site_perf.py audit dialam-site
  python tools/site_perf.py optimize dialam-site --apply
  python tools/site_perf.py check dialam-site
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print(
        "ОШИБКА: не найден Pillow. Запусти инструмент через bundled Python:\n"
        r'  C:\Users\Сисадмин\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe tools\site_perf.py ...'
    )
    raise SystemExit(2)

WORKSPACE = Path(__file__).resolve().parents[1]
SKIP_DIRS = {
    ".git", "node_modules", "dist", "build", "verify-shots", "notes",
    ".github", ".tmp-build", "site-packages", "dsh-runtimes", "uv-tools",
    "admin",
}
LOGO_MARKERS = ("logo", "gerb", "emblem", "favicon", "sogaz", "kapital")
RASTER_EXT = {".jpg", ".jpeg", ".png", ".webp", ".avif"}
REFERENCES_EXT = RASTER_EXT | {".svg"}
PHOTO_FAIL_BYTES = 80 * 1024
LARGE_BYTES = 30 * 1024
MIN_OPTIMIZE_BYTES = 20 * 1024
JPG_FALLBACK_QUALITY = 85
IMG_RE = re.compile(r"<img\b[^>]*>", re.S | re.I)
SRC_RE = re.compile(r'\bsrc\s*=\s*"([^"]+)"', re.I)
CLASS_RE = re.compile(r'\bclass\s*=\s*"([^"]*)"', re.I)
ONERROR_RE = re.compile(r'\bonerror\s*=\s*"([^"]*)"', re.I)
JS_SRC_RE = re.compile(r"\bsrc\s*=\s*'([^']+)'", re.I)


def skip_path(path: Path, root: Path) -> bool:
    try:
        rel = path.relative_to(root)
    except ValueError:
        return True
    return any(part in SKIP_DIRS for part in rel.parts)


def iter_files(root: Path, suffixes: set[str]):
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in suffixes and not skip_path(p, root):
            yield p


def image_size(path: Path) -> tuple[int | None, int | None]:
    try:
        with Image.open(path) as im:
            return im.size
    except Exception:
        return None, None


def has_alpha(im: Image.Image) -> bool:
    """Нужна ли прозрачность (тогда фолбэком остаётся PNG)."""
    if im.mode in ("RGBA", "LA", "PA"):
        return "A" in im.getbands()
    if im.mode == "P":
        return "transparency" in im.info
    return False


def jpg_fallback(p: Path, apply: bool, quality: int) -> tuple[Path, bool] | None:
    """JPG-фолбэк для непрозрачного PNG-фото (правило AGENTS.md §2.9).

    Возвращает (путь, создан_сейчас) или None, если фолбэк не нужен:
    файл не PNG, у него есть прозрачность (логотип/графика) или ошибка чтения.
    В dry-run файл не создаётся, но путь возвращается для отчёта.
    """
    if p.suffix.lower() != ".png":
        return None
    try:
        with Image.open(p) as im:
            im.load()
            if has_alpha(im):
                return None
            out = p.with_suffix(".jpg")
            if out.exists() and out.stat().st_mtime >= p.stat().st_mtime:
                return out, False
            if apply:
                im.convert("RGB").save(out, "JPEG", quality=quality, optimize=True)
                return out, True
            return out, False
    except Exception as e:  # noqa: BLE001 - битый файл не должен ломать optimize
        print("  ! jpg-fallback", p.name, e)
        return None


def is_logo(src: str) -> bool:
    low = src.lower()
    return any(marker in low for marker in LOGO_MARKERS)


def local_src(src: str) -> bool:
    return bool(src) and not src.startswith(("http://", "https://", "data:", "//"))


def fallback_src(tag: str) -> str | None:
    """Путь из onerror-фолбэка (`this.src='...'`), если он задан."""
    m = ONERROR_RE.search(tag)
    if not m:
        return None
    inner = m.group(1)
    sm = JS_SRC_RE.search(inner) or SRC_RE.search(inner)
    return sm.group(1) if sm else None


def png_is_opaque_photo(path: Path) -> bool:
    """PNG без прозрачности — это фото; фолбэк для него должен быть JPG."""
    try:
        with Image.open(path) as im:
            im.load()
            return not has_alpha(im)
    except Exception:  # noqa: BLE001 - битый файл не ломает проверку
        return False


def resolve_src(root: Path, src: str) -> Path:
    clean = src.split("?", 1)[0].split("#", 1)[0]
    if clean.startswith("/"):
        return root / clean.lstrip("/")
    return root / clean


def parse_tags(root: Path):
    for html in iter_files(root, {".html"}):
        text = html.read_text(encoding="utf-8", errors="replace")
        for match in IMG_RE.finditer(text):
            tag = match.group(0)
            src_m = SRC_RE.search(tag)
            if not src_m:
                continue
            src = src_m.group(1)
            if not local_src(src):
                continue
            cls_m = CLASS_RE.search(tag)
            yield html, tag, src, cls_m.group(1) if cls_m else "", resolve_src(root, src)


def attrs(tag: str) -> dict[str, bool]:
    return {
        "loading": bool(re.search(r"\bloading\s*=", tag, re.I)),
        "decoding": bool(re.search(r"\bdecoding\s*=", tag, re.I)),
        "fetchpriority": bool(re.search(r"\bfetchpriority\s*=", tag, re.I)),
        "width": bool(re.search(r"\bwidth\s*=", tag, re.I)),
        "height": bool(re.search(r"\bheight\s*=", tag, re.I)),
    }


def audit(root: Path) -> int:
    if not root.is_dir():
        print(f"ОШИБКА: нет папки {root}")
        return 2
    print(f"\n=== AUDIT: {root.name} ===")
    images = list(iter_files(root, RASTER_EXT))
    total = sum(p.stat().st_size for p in images)
    by_fmt: dict[str, int] = {}
    for p in images:
        by_fmt[p.suffix.lower()] = by_fmt.get(p.suffix.lower(), 0) + p.stat().st_size
    print(f"Изображений: {len(images)}, всего {total/1024:.1f} KB")
    print("По форматам: " + ", ".join(
        f"{fmt} {size/1024:.0f} KB" for fmt, size in sorted(by_fmt.items())
    ))
    print("Самые большие:")
    for p in sorted(images, key=lambda x: x.stat().st_size, reverse=True)[:15]:
        print(f"  {p.stat().st_size/1024:8.1f} KB  {p.relative_to(root)}")

    htmls = list(iter_files(root, {".html"}))
    tags = list(parse_tags(root))
    webp_refs = sum(1 for _, _, src, _, _ in tags if ".webp" in src.lower())
    ref_paths = {path for _, _, _, _, path in tags if path.exists()}
    ref_total = sum(p.stat().st_size for p in ref_paths)
    print(f"Подключено в HTML: {len(ref_paths)} файлов, {ref_total/1024:.1f} KB")
    missing = {"loading": 0, "decoding": 0, "width": 0, "height": 0}
    for _, tag, src, _, _ in tags:
        a = attrs(tag)
        if is_logo(src):
            continue
        for key in missing:
            if not a[key]:
                missing[key] += 1
    print(f"HTML-страниц: {len(htmls)}, <img>: {len(tags)}, WebP-ссылок: {webp_refs}")
    print("Без атрибутов (не логотипы): " + ", ".join(
        f"{k}={v}" for k, v in missing.items()
    ))

    js = list(iter_files(root, {".js"}))
    css = list(iter_files(root, {".css"}))
    js_total = sum(p.stat().st_size for p in js)
    css_total = sum(p.stat().st_size for p in css)
    print(f"JS: {len(js)} файлов, {js_total/1024:.0f} KB; CSS: {len(css)} файлов, {css_total/1024:.0f} KB")
    big_js = [p for p in js if p.stat().st_size > 500 * 1024]
    if big_js:
        print("  Тяжёлые JS-чанки (>500 KB):")
        for p in sorted(big_js, key=lambda x: x.stat().st_size, reverse=True)[:8]:
            print(f"    {p.stat().st_size/1024:.0f} KB  {p.relative_to(root)}")
    return 0


def check(root: Path) -> int:
    if not root.is_dir():
        print(f"ОШИБКА: нет папки {root}")
        return 2
    errors: list[str] = []
    warnings: list[str] = []
    htmls = list(iter_files(root, {".html"}))
    tags = list(parse_tags(root))
    if not htmls:
        print(f"\n=== CHECK: {root.name} ===")
        print("HTML-страниц нет (SPA/приложение). Проверяю public-ассеты.")
        for p in sorted(iter_files(root, RASTER_EXT), key=lambda x: x.stat().st_size, reverse=True):
            if p.stat().st_size > 500 * 1024:
                warnings.append(f"большой public-ассет: {p.relative_to(root)} {p.stat().st_size/1024:.0f} KB")
        for w in warnings:
            print("WARN:", w)
        print("CHECK:", "PASS" if not errors else "FAIL")
        return 1 if errors else 0

    for html, tag, src, cls, path in tags:
        rel_html = html.relative_to(root)
        if not path.exists():
            errors.append(f"{rel_html}: нет файла {src}")
            continue
        size = path.stat().st_size
        a = attrs(tag)
        logo = is_logo(src)
        hero = "hero" in cls.lower() or "hero" in src.lower()
        if logo or path.suffix.lower() == ".svg":
            continue
        if size >= PHOTO_FAIL_BYTES and path.suffix.lower() not in (".webp", ".avif"):
            errors.append(
                f"{rel_html}: {src} {size/1024:.0f} KB — нужен WebP "
                f"(или <picture>/fallback)"
            )
        if size >= LARGE_BYTES:
            if not a["loading"]:
                errors.append(f"{rel_html}: {src} — нет loading")
            if not a["decoding"]:
                errors.append(f"{rel_html}: {src} — нет decoding")
            if not a["width"] or not a["height"]:
                errors.append(f"{rel_html}: {src} — нет width/height")
            if hero:
                if not a["fetchpriority"]:
                    errors.append(f"{rel_html}: hero {src} — нет fetchpriority")
                if re.search(r'\bloading\s*=\s*"lazy"', tag, re.I):
                    errors.append(f"{rel_html}: hero {src} — loading=lazy")
            elif re.search(r'\bloading\s*=\s*"eager"', tag, re.I):
                warnings.append(f"{rel_html}: {src} — eager вне hero")

        # Фолбэк onerror: для фотографии он должен быть JPG, не PNG (AGENTS §2.9)
        fallback = fallback_src(tag)
        if fallback and local_src(fallback):
            fallback_path = resolve_src(root, fallback)
            if fallback_path.suffix.lower() == ".png":
                if not fallback_path.exists():
                    errors.append(f"{rel_html}: {src} — нет файла фолбэка {fallback}")
                elif png_is_opaque_photo(fallback_path):
                    errors.append(
                        f"{rel_html}: {src} — фолбэк {fallback} в PNG; "
                        f"для фото нужен JPG (AGENTS §2.9)"
                    )

    # Оригиналы, на которые больше нет ссылок, не ошибка; но очень big warning.
    for p in sorted(iter_files(root, RASTER_EXT), key=lambda x: x.stat().st_size, reverse=True):
        if p.stat().st_size > 800 * 1024 and p.suffix.lower() not in (".webp", ".avif"):
            warnings.append(f"большой неиспользуемый оригинал: {p.relative_to(root)} {p.stat().st_size/1024:.0f} KB")

    print(f"\n=== CHECK: {root.name} ===")
    print(f"HTML: {len(htmls)}, <img>: {len(tags)}, ошибок: {len(errors)}, предупреждений: {len(warnings)}")
    for e in errors:
        print("ERROR:", e)
    for w in warnings:
        print("WARN:", w)
    print("CHECK:", "PASS" if not errors else "FAIL")
    return 1 if errors else 0


def add_attrs(tag: str, extra: str) -> str:
    pos = tag.rfind(">")
    if pos < 0:
        return tag
    return tag[:pos].rstrip() + " " + extra.strip() + ">"


def optimize_tag(tag: str, original: str, webp: str, fallback: str, repo: Path) -> str:
    src_m = SRC_RE.search(tag)
    if not src_m:
        return tag
    tag = tag[:src_m.start(1)] + webp + tag[src_m.end(1):]
    cls_m = CLASS_RE.search(tag)
    cls = cls_m.group(1).lower() if cls_m else ""
    hero = "hero" in cls or "hero" in original.lower()
    logo = is_logo(original) or original.lower().endswith(".svg")
    extra: list[str] = []
    if not logo:
        if not re.search(r"\bloading\s*=", tag, re.I):
            extra.append('loading="eager"' if hero else 'loading="lazy"')
        if not re.search(r"\bdecoding\s*=", tag, re.I):
            extra.append('decoding="async"')
    if hero and not re.search(r"\bfetchpriority\s*=", tag, re.I):
        extra.append('fetchpriority="high"')
    if not re.search(r"\bwidth\s*=", tag, re.I) or not re.search(r"\bheight\s*=", tag, re.I):
        w, h = image_size(repo / original)
        if w and h:
            if not re.search(r"\bwidth\s*=", tag, re.I):
                extra.append(f'width="{w}"')
            if not re.search(r"\bheight\s*=", tag, re.I):
                extra.append(f'height="{h}"')
    if not re.search(r"\bonerror\s*=", tag, re.I):
        extra.append(f'onerror="this.onerror=null;this.src=\'{fallback}\'"')
    return add_attrs(tag, " ".join(extra)) if extra else tag


def optimize(root: Path, apply: bool, quality: int, min_bytes: int) -> int:
    if not root.is_dir():
        print(f"ОШИБКА: нет папки {root}")
        return 2
    print(f"\n=== OPTIMIZE: {root.name} ({'APPLY' if apply else 'DRY RUN'}) ===")
    mapping: dict[str, str] = {}
    fallbacks: dict[str, str] = {}
    old_total = new_total = 0

    def fallback_for(p: Path, rel: str) -> str:
        """onerror-фолбэк: для непрозрачного PNG-фото — JPG (AGENTS.md §2.9)."""
        fb = jpg_fallback(p, apply, JPG_FALLBACK_QUALITY)
        if fb is None:
            return rel
        fpath, created = fb
        if created:
            print(f"  + {fpath.relative_to(root).as_posix()}: JPG-фолбэк (PNG-фото)")
        return fpath.relative_to(root).as_posix()

    for p in sorted(iter_files(root, {".jpg", ".jpeg", ".png"})):
        if p.stat().st_size < min_bytes or is_logo(p.name):
            continue
        rel = p.relative_to(root).as_posix()
        out = p.with_suffix(".webp")
        if out.exists() and out.stat().st_mtime >= p.stat().st_mtime:
            mapping[rel] = out.relative_to(root).as_posix()
            fallbacks[rel] = fallback_for(p, rel)
            old_total += p.stat().st_size
            new_total += out.stat().st_size
            continue
        if not (out.exists() and out.stat().st_mtime >= p.stat().st_mtime):
            try:
                im = Image.open(p)
                im.load()
                if im.mode not in ("RGB", "RGBA"):
                    im = im.convert("RGBA" if "A" in im.getbands() else "RGB")
                if apply:
                    im.save(out, "WEBP", quality=quality, method=6)
                else:
                    import io
                    buf = io.BytesIO()
                    im.save(buf, "WEBP", quality=quality, method=4)
                    # estimate below
            except Exception as e:
                print("  !", rel, e)
                continue
        if not out.exists() and not apply:
            # dry-run: estimate size by encoding
            import io
            im = Image.open(p)
            im.load()
            if im.mode not in ("RGB", "RGBA"):
                im = im.convert("RGBA" if "A" in im.getbands() else "RGB")
            buf = io.BytesIO()
            im.save(buf, "WEBP", quality=quality, method=4)
            new_size = len(buf.getvalue())
        else:
            new_size = out.stat().st_size if out.exists() else 0
        if new_size == 0 or new_size >= p.stat().st_size * 0.97:
            print(f"  - skip {rel}: WebP не меньше")
            if apply and out.exists():
                out.unlink()
            continue
        mapping[rel] = out.relative_to(root).as_posix()
        fallbacks[rel] = fallback_for(p, rel)
        old_total += p.stat().st_size
        new_total += new_size
        print(f"  + {rel}: {p.stat().st_size/1024:.1f} -> {new_size/1024:.1f} KB")
    changed = 0
    if apply:
        for html in iter_files(root, {".html"}):
            text = html.read_text(encoding="utf-8", errors="replace")
            def repl(m: re.Match) -> str:
                tag = m.group(0)
                sm = SRC_RE.search(tag)
                if not sm:
                    return tag
                src = sm.group(1)
                if src not in mapping:
                    return tag
                return optimize_tag(tag, src, mapping[src], fallbacks.get(src, src), root)
            new_text = IMG_RE.sub(repl, text)
            if new_text != text:
                html.write_text(new_text, encoding="utf-8")
                changed += 1
    print(f"Изображений: {len(mapping)}, вес: {old_total/1024:.1f} -> {new_total/1024:.1f} KB")
    print(f"HTML изменено: {changed if apply else '(dry run)'}")
    if not apply:
        print("Dry run. Для записи добавь --apply.")
    return 0


def resolve_root(arg: str) -> Path:
    """Папка сайта: абсолютный путь, путь от CWD (CI/вендорная копия) или
    от корня workspace (обычный вызов tools/site_perf.py check dialam-site)."""
    p = Path(arg)
    if p.is_absolute():
        return p
    from_cwd = (Path.cwd() / p).resolve()
    if from_cwd.is_dir():
        return from_cwd
    return (WORKSPACE / p).resolve()


def main() -> int:
    ap = argparse.ArgumentParser(description="Performance-инструмент сайтов")
    ap.add_argument("command", choices=["audit", "check", "optimize"])
    ap.add_argument("site", nargs="?", default=".", help="папка сайта")
    ap.add_argument("--apply", action="store_true", help="записать изменения")
    ap.add_argument("--quality", type=int, default=82, help="качество WebP (по умолчанию 82)")
    ap.add_argument("--min-kb", type=int, default=20, help="не конвертировать файлы меньше N КБ")
    args = ap.parse_args()
    root = resolve_root(args.site)
    if args.command == "audit":
        return audit(root)
    if args.command == "check":
        return check(root)
    return optimize(root, args.apply, args.quality, args.min_kb * 1024)


if __name__ == "__main__":
    raise SystemExit(main())
