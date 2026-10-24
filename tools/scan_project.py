"""
Сканирование структуры проекта.

Интерактивный запуск:
    python tools/scan_project.py

CLI-режим:
    python tools/scan_project.py -s python
    python tools/scan_project.py -s full -o dump.md --format markdown
    python tools/scan_project.py -s custom -e .py .toml .md
    python tools/scan_project.py -s full --no-timestamp -y

Сканирование только определённых папок:
    python tools/scan_project.py -s python -d src,tests
    python tools/scan_project.py -s full -d src/api,docs/v2
    python tools/scan_project.py -s folders -d src,tests
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import re
import subprocess
import sys
import time
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# ============================================================================
# Настройки сканирования
# ============================================================================

EXCLUDE_DIRS = {
    ".venv",
    "venv",
    "env",
    "__pycache__",
    ".git",
    ".hg",
    ".svn",
    ".idea",
    ".vscode",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "build",
    "dist",
    "node_modules",
    ".tox",
    ".eggs",
    ".cache",
    ".ipynb_checkpoints",
}

EXCLUDE_DIR_PATTERNS = {"*.egg-info"}

# Полностью прячем — ни в дереве, ни в содержимом.
# Это либо артефакты сборки, либо наши собственные снапшоты.
EXCLUDE_FILES_ALWAYS = {
    "*.pyc",
    "*.pyo",
    "*.pyd",
    "*.so",
    "*.dll",
    "*.exe",
    "*.o",
    "*.a",
    "*.lock",
    "*.log",
    "*.dat",
    ".DS_Store",
    "Thumbs.db",
    "project_snapshot*.txt",
    "project_snapshot*.md",
    "project_tree*.txt",
    "project_tree*.md",
    "project_python*.txt",
    "project_python*.md",
    "project_configs*.txt",
    "project_configs*.md",
    "project_docs*.txt",
    "project_docs*.md",
    "project_for_ai*.txt",
    "project_for_ai*.md",
    "project_custom*.txt",
    "project_custom*.md",
    "project_folders*.txt",
    "project_folders*.md",
    Path(__file__).name,
}

# Жёсткий чёрный список для чтения текста.
# Даже если пользователь явно передал .png в --ext — не будем пытаться.
NEVER_TEXT_EXTENSIONS = {
    # картинки / графика
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".bmp",
    ".ico",
    ".webp",
    ".tiff",
    ".tif",
    ".heic",
    ".avif",
    ".psd",
    ".ai",
    ".sketch",
    ".fig",
    ".xd",
    # документы
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".xlsm",
    ".ppt",
    ".pptx",
    ".msg",
    ".oft",
    ".odt",
    ".ods",
    ".odp",
    ".rtf",
    # архивы / бинарники
    ".zip",
    ".tar",
    ".gz",
    ".7z",
    ".rar",
    ".bz2",
    ".xz",
    ".zst",
    ".class",
    ".jar",
    ".war",
    ".dylib",
    ".lib",
    # БД / данные
    ".db",
    ".sqlite",
    ".sqlite3",
    ".bin",
    # медиа
    ".mp3",
    ".mp4",
    ".wav",
    ".ogg",
    ".webm",
    ".mov",
    ".avi",
    ".mkv",
    ".flac",
    # шрифты
    ".woff",
    ".woff2",
    ".ttf",
    ".otf",
    ".eot",
}

# Файлы, которые могут содержать секреты — при обнаружении предупреждаем
SENSITIVE_FILE_PATTERNS = {
    ".env",
    ".env.*",
    ".netrc",
    ".npmrc",
    ".pypirc",
    "*.pem",
    "*.key",
    "*.pfx",
    "*.p12",
    "*.kdbx",
    "id_rsa*",
    "id_dsa*",
    "id_ecdsa*",
    "id_ed25519*",
    "credentials*",
    "secrets*",
}

ALL_TEXT_EXTENSIONS = frozenset(
    {
        ".py",
        ".pyi",
        ".toml",
        ".cfg",
        ".ini",
        ".json",
        ".yaml",
        ".yml",
        ".md",
        ".txt",
        ".rst",
        ".html",
        ".css",
        ".js",
        ".ts",
        ".bat",
        ".sh",
        ".ps1",
        ".sql",
    }
)

INCLUDE_EXTENSIONLESS_PATTERNS = {
    "Dockerfile*",
    "Makefile*",
    ".gitignore",
    ".dockerignore",
    ".editorconfig",
    ".flake8",
    "LICENSE*",
}

MAX_FILE_SIZE = 200 * 1024

EXT_TO_LANG = {
    ".py": "python",
    ".pyi": "python",
    ".toml": "toml",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".md": "markdown",
    ".rst": "rst",
    ".txt": "text",
    ".html": "html",
    ".css": "css",
    ".js": "javascript",
    ".ts": "typescript",
    ".sh": "bash",
    ".bat": "batch",
    ".ps1": "powershell",
    ".sql": "sql",
    ".ini": "ini",
    ".cfg": "ini",
    ".env": "dotenv",
    ".svg": "xml",
}

SEP_MAJOR = "=" * 78
SEP_MINOR = "-" * 78
SEP_FILE = "─" * 78

READ_BATCH_SIZE = 32
READ_WORKERS = 8
GIT_TIMEOUT = 20


# ============================================================================
# Сценарии
# ============================================================================


@dataclass(frozen=True)
class Scenario:
    id: str
    title: str
    description: str
    output: str
    tree_only: bool = False
    # None — спросить у пользователя
    extensions: frozenset[str] | None = ALL_TEXT_EXTENSIONS
    max_size: int | None = MAX_FILE_SIZE
    fmt: str = "markdown"
    # Если True — сценарию нужен список папок (интерактивно или через --dirs)
    ask_dirs: bool = False


SCENARIOS: list[Scenario] = [
    Scenario(
        id="full",
        title="Полный снимок проекта",
        description="Дерево + содержимое всех текстовых файлов (Python, TOML, MD, JSON).",
        output="project_snapshot.md",
    ),
    Scenario(
        id="tree",
        title="Только структура проекта",
        description="Только дерево файлов и папок, без содержимого.",
        output="project_tree.md",
        tree_only=True,
        extensions=frozenset(),
    ),
    Scenario(
        id="python",
        title="Только Python-код",
        description="Дерево + содержимое только .py и .pyi файлов.",
        output="project_python.md",
        extensions=frozenset({".py", ".pyi"}),
    ),
    Scenario(
        id="configs",
        title="Только конфигурация",
        description="Дерево + содержимое конфигов: TOML, JSON, YAML, INI, CFG, .env.",
        output="project_configs.md",
        extensions=frozenset(
            {
                ".toml",
                ".json",
                ".yaml",
                ".yml",
                ".ini",
                ".cfg",
                ".env",
            }
        ),
    ),
    Scenario(
        id="docs",
        title="Только документация",
        description="Дерево + содержимое .md, .txt, .rst файлов.",
        output="project_docs.md",
        extensions=frozenset({".md", ".txt", ".rst"}),
    ),
    Scenario(
        id="ai",
        title="Python + конфигурация (для ИИ)",
        description=(
            "Дерево + содержимое .py, .toml, .json, .yaml, .md. "
            "Markdown-формат — оптимальный набор для чата с ИИ."
        ),
        output="project_for_ai.md",
        extensions=frozenset(
            {
                ".py",
                ".pyi",
                ".toml",
                ".json",
                ".yaml",
                ".yml",
                ".md",
            }
        ),
        fmt="markdown",
    ),
    Scenario(
        id="folders",
        title="Определённые папки",
        description=(
            "Спросит список папок (через запятую), затем — все текстовые "
            "файлы внутри них. Можно указать имена (src, tests) или "
            "относительные пути (src/api, docs/v2)."
        ),
        output="project_folders.md",
        extensions=ALL_TEXT_EXTENSIONS,
        ask_dirs=True,
    ),
    Scenario(
        id="custom",
        title="Свои расширения",
        description="Ввести расширения вручную (через пробел).",
        output="project_custom.md",
        extensions=None,
    ),
    Scenario(
        id="custom-size",
        title="Свой размер файла",
        description=(
            "Полный снимок, но с указанием максимального размера файла в КБ "
            "(по умолчанию 200)."
        ),
        output="project_snapshot.md",
        max_size=None,
    ),
]


# ============================================================================
# Фильтр папок
# ============================================================================


def parse_dir_filter(items: str | Iterable[str] | None) -> tuple[str, ...]:
    """
    Преобразует строку/список в кортеж нормализованных путей-фильтров.
    Допускает разделение запятыми, убирает пробелы и крайние слэши,
    \\ приводит к /.
    """
    if items is None:
        return ()
    if isinstance(items, str):
        raw_items: Iterable[str] = [items]
    else:
        raw_items = items

    result: list[str] = []
    seen: set[str] = set()
    for chunk in raw_items:
        for token in str(chunk).split(","):
            t = token.strip().replace("\\", "/").strip("/")
            if t and t not in seen:
                seen.add(t)
                result.append(t)
    return tuple(result)


def matches_dir_filter(rel: Path, dir_filter: tuple[str, ...]) -> bool:
    """
    Проверяет, попадает ли относительный путь в фильтр.
    - если в токене есть '/', трактуем как относительный путь от корня
      (совпадение по префиксу директорий);
    - иначе — совпадение по имени любой родительской папки.
    """
    if not dir_filter:
        return True
    dir_parts = rel.parts[:-1]
    if not dir_parts:
        return False
    for token in dir_filter:
        if "/" in token:
            prefix = tuple(token.split("/"))
            if len(dir_parts) >= len(prefix) and dir_parts[: len(prefix)] == prefix:
                return True
        else:
            if token in dir_parts:
                return True
    return False


# ============================================================================
# Фильтрация файлов/папок
# ============================================================================


def should_skip_dir(name: str) -> bool:
    if name in EXCLUDE_DIRS:
        return True
    return any(fnmatch.fnmatch(name, pat) for pat in EXCLUDE_DIR_PATTERNS)


def should_hide_from_tree(name: str) -> bool:
    """Полностью исключить файл — ни в дереве, ни в содержимом."""
    return any(fnmatch.fnmatch(name, pat) for pat in EXCLUDE_FILES_ALWAYS)


def is_never_text(path: Path) -> bool:
    """Жёсткий запрет на попытку декодировать файл как текст."""
    return path.suffix.lower() in NEVER_TEXT_EXTENSIONS


def is_text_file(path: Path, include_ext: frozenset[str]) -> bool:
    if is_never_text(path):
        return False
    suffix = path.suffix.lower()
    if suffix and suffix in include_ext:
        return True
    if path.name.lower() in include_ext:
        return True
    return any(
        fnmatch.fnmatch(path.name, pat) for pat in INCLUDE_EXTENSIONLESS_PATTERNS
    )


def is_sensitive(path: Path) -> bool:
    name = path.name.lower()
    return any(fnmatch.fnmatch(name, pat.lower()) for pat in SENSITIVE_FILE_PATTERNS)


# ============================================================================
# Сбор файлов
# ============================================================================


def _collect_files_git(root: Path) -> list[Path] | None:
    """
    Возвращает список файлов через `git ls-files`, уважая .gitignore.
    None, если git недоступен или мы не в репозитории.
    """
    try:
        r = subprocess.run(
            ["git", "ls-files", "-z", "-co", "--exclude-standard"],
            cwd=str(root),
            capture_output=True,
            check=False,
            timeout=GIT_TIMEOUT,
        )
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        return None
    if r.returncode != 0:
        return None

    files: list[Path] = []
    data = r.stdout.decode("utf-8", errors="replace")
    for name in data.split("\0"):
        if not name:
            continue
        rel = Path(name)
        if any(should_skip_dir(part) for part in rel.parts[:-1]):
            continue
        if should_hide_from_tree(rel.name):
            continue
        full = root / rel
        if full.is_symlink() or not full.is_file():
            continue
        files.append(full)

    files.sort()
    return files


def _collect_files_walk(root: Path) -> list[Path]:
    files: list[Path] = []
    for cur, dirs, names in os.walk(str(root), followlinks=False):
        cur_path = Path(cur)
        dirs[:] = [
            d
            for d in dirs
            if not should_skip_dir(d) and not (cur_path / d).is_symlink()
        ]
        for name in names:
            if should_hide_from_tree(name):
                continue
            p = cur_path / name
            if p.is_symlink():
                continue
            files.append(p)
    files.sort()
    return files


def collect_files(root: Path, dir_filter: tuple[str, ...] = ()) -> list[Path]:
    files = _collect_files_git(root)
    if files is None:
        files = _collect_files_walk(root)
    if dir_filter:
        filtered: list[Path] = []
        for f in files:
            try:
                rel = f.relative_to(root)
            except ValueError:
                continue
            if matches_dir_filter(rel, dir_filter):
                filtered.append(f)
        files = filtered
    return files


def derive_dirs(files: list[Path], root: Path) -> list[Path]:
    dirs: set[Path] = set()
    for f in files:
        parent = f.parent
        while parent != root and parent != root.parent:
            dirs.add(parent)
            parent = parent.parent
    return sorted(dirs)


# ============================================================================
# Дерево
# ============================================================================


@dataclass
class TreeNode:
    name: str
    is_dir: bool
    children: dict[str, TreeNode] = field(default_factory=dict)


def build_tree(files: list[Path], dirs: list[Path], root: Path) -> TreeNode:
    root_node = TreeNode(name=root.name or str(root), is_dir=True)

    for d in dirs:
        try:
            rel = d.relative_to(root)
        except ValueError:
            continue
        node = root_node
        for part in rel.parts:
            node = node.children.setdefault(part, TreeNode(name=part, is_dir=True))

    for f in files:
        try:
            rel = f.relative_to(root)
        except ValueError:
            continue
        node = root_node
        for part in rel.parts[:-1]:
            node = node.children.setdefault(part, TreeNode(name=part, is_dir=True))
        node.children[rel.parts[-1]] = TreeNode(name=rel.parts[-1], is_dir=False)

    return root_node


def render_tree(node: TreeNode, prefix: str = "") -> Iterator[str]:
    items = sorted(
        node.children.values(),
        key=lambda n: (not n.is_dir, n.name.lower()),
    )
    for i, child in enumerate(items):
        is_last = i == len(items) - 1
        connector = "└── " if is_last else "├── "
        suffix = "/" if child.is_dir else ""
        yield f"{prefix}{connector}{child.name}{suffix}"
        if child.is_dir:
            ext = "    " if is_last else "│   "
            yield from render_tree(child, prefix + ext)


# ============================================================================
# Чтение файлов
# ============================================================================


@dataclass
class FileRead:
    path: Path
    status: str  # "ok" | "big" | "binary" | "error"
    content: str | None
    size: int


PY_CODING_RE = re.compile(rb"coding[:=]\s*([-\w.]+)")


def detect_python_encoding(head: bytes) -> str | None:
    for line in head.split(b"\n", 2)[:2]:
        m = PY_CODING_RE.search(line)
        if m:
            try:
                return m.group(1).decode("ascii")
            except UnicodeDecodeError:
                return None
    return None


def read_text_safe(path: Path) -> str | None:
    try:
        raw = path.read_bytes()
    except OSError:
        return None

    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]

    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass

    if path.suffix.lower() in (".py", ".pyi"):
        enc = detect_python_encoding(raw[:2048])
        if enc:
            try:
                return raw.decode(enc)
            except (UnicodeDecodeError, LookupError):
                pass

    try:
        return raw.decode("cp1251")
    except UnicodeDecodeError:
        return None


def read_one(path: Path, max_size: int) -> FileRead:
    try:
        size = path.stat().st_size
    except OSError:
        return FileRead(path, "error", None, 0)

    if size > max_size:
        return FileRead(path, "big", None, size)

    # Даже если .png попал в include_ext — не читаем как текст.
    if is_never_text(path):
        return FileRead(path, "binary", None, size)

    content = read_text_safe(path)
    if content is None:
        return FileRead(path, "binary", None, size)
    return FileRead(path, "ok", content, size)


# ============================================================================
# Прогресс (без внешних зависимостей)
# ============================================================================


class Progress:
    def __init__(self, total: int, enabled: bool | None = None):
        self.total = total
        if enabled is None:
            enabled = _is_tty()
        self.enabled = bool(enabled) and total > 0
        self.count = 0
        self._last_ts = 0.0
        self._bar_len = 30

    def tick(self) -> None:
        self.count += 1
        if not self.enabled:
            return
        now = time.monotonic()
        if now - self._last_ts < 0.15 and self.count < self.total:
            return
        self._last_ts = now
        frac = self.count / self.total
        filled = int(self._bar_len * frac)
        bar = "█" * filled + "░" * (self._bar_len - filled)
        pct = int(100 * frac)
        print(f"\r  [{bar}] {self.count}/{self.total} ({pct}%)", end="", flush=True)

    def done(self) -> None:
        if self.enabled and self.count > 0:
            print()


def _is_tty() -> bool:
    try:
        return sys.stdout.isatty()
    except AttributeError:
        return False


# ============================================================================
# Секреты
# ============================================================================


def filter_sensitive(
    files: list[Path],
    root: Path,
    assume_yes: bool,
    interactive: bool,
) -> list[Path]:
    sensitive = [f for f in files if is_sensitive(f)]
    if not sensitive:
        return files

    sens_set = set(sensitive)

    if assume_yes:
        print(
            f"  ⚠  Включено {len(sensitive)} потенциально секретных файлов (--yes).",
            file=sys.stderr,
        )
        return files

    if not interactive or not _is_tty():
        print(
            f"  ⚠  Исключено {len(sensitive)} потенциально секретных файлов "
            f"(нет TTY для подтверждения).",
            file=sys.stderr,
        )
        return [f for f in files if f not in sens_set]

    print(f"\n  ⚠  Найдены файлы, которые могут содержать секреты ({len(sensitive)}):")
    for f in sensitive[:15]:
        try:
            print(f"      {f.relative_to(root)}")
        except ValueError:
            print(f"      {f}")
    if len(sensitive) > 15:
        print(f"      ... и ещё {len(sensitive) - 15} файл(ов)")
    print()

    try:
        ans = input("  Включить их в снапшот? (y/N): ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        ans = ""

    if ans in ("y", "yes", "д", "да"):
        return files
    print("  Секретные файлы исключены.")
    return [f for f in files if f not in sens_set]


# ============================================================================
# Форматирование
# ============================================================================


def format_size(num_bytes: int) -> str:
    val = float(num_bytes)
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if val < 1024:
            return f"{val:.1f} {unit}"
        val /= 1024
    return f"{val:.1f} ТБ"


def _fence_for(content: str) -> str:
    longest = 0
    cur = 0
    for ch in content:
        if ch == "`":
            cur += 1
            longest = max(longest, cur)
        else:
            cur = 0
    return "`" * max(3, longest + 1)


def _write_header(
    f,
    root: Path,
    n_dirs: int,
    n_files: int,
    tree_only: bool,
    max_size: int,
    fmt: str,
    dir_filter: tuple[str, ...],
) -> None:
    ts = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    if fmt == "markdown":
        f.write(f"# Снимок проекта: {root.name}\n\n")
        f.write(f"- **Дата:** {ts}\n")
        f.write(f"- **Корень:** `{root}`\n")
        f.write(f"- **Всего директорий:** {n_dirs}\n")
        f.write(f"- **Всего файлов:** {n_files}\n")
        if dir_filter:
            f.write(f"- **Папки:** {', '.join(f'`{d}`' for d in dir_filter)}\n")
        if not tree_only:
            f.write(f"- **Максимальный размер файла:** {format_size(max_size)}\n")
        f.write("\n")
    else:
        f.write(SEP_MAJOR + "\n")
        f.write(f"СНИМОК ПРОЕКТА: {root.name}\n")
        f.write(SEP_MAJOR + "\n")
        f.write(f"Дата:              {ts}\n")
        f.write(f"Корень:            {root}\n")
        f.write(f"Всего директорий:  {n_dirs}\n")
        f.write(f"Всего файлов:      {n_files}\n")
        if dir_filter:
            f.write(f"Папки:             {', '.join(dir_filter)}\n")
        if not tree_only:
            f.write(f"Максимальный размер: {format_size(max_size)}\n")
        f.write("\n")


def _write_tree_section(f, root: Path, tree: TreeNode, fmt: str) -> None:
    root_name = root.name or str(root)
    if fmt == "markdown":
        f.write("## Структура\n\n```\n")
        f.write(root_name + "/\n")
        for line in render_tree(tree):
            f.write(line + "\n")
        f.write("```\n\n")
    else:
        f.write(SEP_MINOR + "\n")
        f.write("СТРУКТУРА\n")
        f.write(SEP_MINOR + "\n")
        f.write(root_name + "/\n")
        for line in render_tree(tree):
            f.write(line + "\n")
        f.write("\n")


def _write_assets_section(f, root: Path, files: list[Path], fmt: str) -> int:
    """Сводка по бинарным файлам (ассетам). Возвращает их количество."""
    assets = [p for p in files if is_never_text(p)]
    if not assets:
        return 0

    rows: list[tuple[Path, int]] = []
    total = 0
    for p in assets:
        try:
            rel = p.relative_to(root)
        except ValueError:
            rel = p
        try:
            size = p.stat().st_size
        except OSError:
            size = 0
        rows.append((rel, size))
        total += size

    if fmt == "markdown":
        f.write("## Ассеты\n\n")
        for rel, size in rows:
            f.write(f"- `{rel}` — {format_size(size)}\n")
        f.write(f"\n_Всего: {len(rows)} файл(ов), {format_size(total)}._\n\n")
    else:
        f.write(SEP_MINOR + "\n")
        f.write("АССЕТЫ\n")
        f.write(SEP_MINOR + "\n")
        for rel, size in rows:
            f.write(f"{rel}  ({format_size(size)})\n")
        f.write(f"\nВсего: {len(rows)} файл(ов), {format_size(total)}\n\n")

    return len(rows)


def _write_file_block(f, rel: Path, content: str, ext: str, fmt: str) -> None:
    if fmt == "markdown":
        lang = EXT_TO_LANG.get(ext, "")
        fence = _fence_for(content)
        f.write(f"### `{rel}`\n\n")
        f.write(f"{fence}{lang}\n")
        f.write(content.rstrip("\n"))
        f.write(f"\n{fence}\n\n")
    else:
        f.write("\n" + SEP_FILE + "\n")
        f.write(f"ФАЙЛ: {rel}\n")
        f.write(SEP_FILE + "\n")
        f.write(content.rstrip())
        f.write("\n")


def _write_file_skipped(f, rel: Path, reason: str, fmt: str) -> None:
    if fmt == "markdown":
        f.write(f"### `{rel}`\n\n")
        f.write(f"_Файл пропущен: {reason}._\n\n")
    else:
        f.write(f"\n### {rel}  ({reason})\n")


def _write_content_section(
    f,
    root: Path,
    candidates: list[Path],
    max_size: int,
    fmt: str,
    stats: dict,
) -> None:
    if fmt == "markdown":
        f.write("## Содержимое\n\n")
    else:
        f.write(SEP_MAJOR + "\n")
        f.write("СОДЕРЖИМОЕ ФАЙЛОВ\n")
        f.write(SEP_MAJOR + "\n")

    if not candidates:
        return

    prog = Progress(total=len(candidates))
    workers = min(READ_WORKERS, max(1, len(candidates)))

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for start in range(0, len(candidates), READ_BATCH_SIZE):
            batch = candidates[start : start + READ_BATCH_SIZE]
            for r in ex.map(lambda p: read_one(p, max_size), batch):
                prog.tick()
                try:
                    rel = r.path.relative_to(root)
                except ValueError:
                    rel = r.path

                if r.status == "ok":
                    stats["included"] += 1
                    _write_file_block(
                        f, rel, r.content or "", r.path.suffix.lower(), fmt
                    )
                elif r.status == "big":
                    stats["skipped_big"] += 1
                    _write_file_skipped(
                        f,
                        rel,
                        f"{format_size(r.size)} — не включён",
                        fmt,
                    )
                elif r.status == "binary":
                    stats["skipped_binary"] += 1
    prog.done()
    f.write("\n")


def _write_summary(f, stats: dict, fmt: str) -> None:
    if fmt == "markdown":
        f.write("## Итого\n\n")
        f.write(f"- Файлов включено: **{stats['included']}**\n")
        f.write(f"- Пропущено (нетекстовые): {stats['skipped_binary']}\n")
        f.write(f"- Пропущено (большие): {stats['skipped_big']}\n")
        if stats.get("assets"):
            f.write(f"- Ассетов в структуре: {stats['assets']}\n")
    else:
        f.write(SEP_MAJOR + "\n")
        f.write("ИТОГО\n")
        f.write(SEP_MAJOR + "\n")
        f.write(f"Файлов включено:          {stats['included']}\n")
        f.write(f"Пропущено (нетекстовые):  {stats['skipped_binary']}\n")
        f.write(f"Пропущено (большие):      {stats['skipped_big']}\n")
        if stats.get("assets"):
            f.write(f"Ассетов в структуре:      {stats['assets']}\n")


# ============================================================================
# Основное сканирование
# ============================================================================


def scan(
    root: Path,
    output: Path,
    tree_only: bool,
    include_ext: frozenset[str],
    max_size: int,
    fmt: str,
    assume_yes: bool,
    interactive: bool,
    dir_filter: tuple[str, ...] = (),
) -> dict:
    print()
    if dir_filter:
        print(f"  Папки: {', '.join(dir_filter)}")
    print("  Собираю список файлов...")

    files = collect_files(root, dir_filter)
    files = filter_sensitive(files, root, assume_yes, interactive)

    dirs = derive_dirs(files, root)
    tree = build_tree(files, dirs, root)

    stats = {
        "dirs": len(dirs),
        "files": len(files),
        "included": 0,
        "skipped_binary": 0,
        "skipped_big": 0,
        "assets": 0,
    }

    output.parent.mkdir(parents=True, exist_ok=True)

    print("  Пишу снимок...")
    with output.open("w", encoding="utf-8") as f:
        _write_header(
            f, root, len(dirs), len(files), tree_only, max_size, fmt, dir_filter
        )
        _write_tree_section(f, root, tree, fmt)
        stats["assets"] = _write_assets_section(f, root, files, fmt)

        if not tree_only:
            candidates = [p for p in files if is_text_file(p, include_ext)]
            _write_content_section(f, root, candidates, max_size, fmt, stats)

        _write_summary(f, stats, fmt)

    return stats


def _print_result(output: Path, stats: dict) -> None:
    try:
        size_kb = output.stat().st_size / 1024
    except OSError:
        size_kb = 0.0
    print()
    print("  " + "=" * 60)
    print(f"  Готово: {output}")
    print(f"  Размер: {size_kb:.1f} КБ")
    print(f"  Файлов включено: {stats['included']} из {stats['files']}")
    if stats.get("assets"):
        print(f"  Ассетов в структуре: {stats['assets']}")
    print("  " + "=" * 60)


# ============================================================================
# Меню
# ============================================================================


def print_menu(root: Path) -> None:
    print()
    print("=" * 70)
    print("  Сканирование проекта")
    print("=" * 70)
    print()
    print(f"  Корень проекта: {root}")
    print()
    print("  Выберите сценарий:")
    print()
    for i, sc in enumerate(SCENARIOS, start=1):
        print(f"  {i}. {sc.title}")
        print(f"     {sc.description}")
        print()
    print("  0. Выход")
    print()


def ask_choice() -> int | None:
    while True:
        try:
            raw = input("  Ваш выбор: ").strip()
        except (KeyboardInterrupt, EOFError):
            print()
            return None
        if not raw:
            continue
        if raw == "0":
            return None
        if raw.isdigit():
            n = int(raw)
            if 1 <= n <= len(SCENARIOS):
                return n
            print(f"  Введите число от 1 до {len(SCENARIOS)} или 0 для выхода.")
            continue
        print("  Некорректный ввод. Введите число.")


def _normalize_extensions(tokens: list[str]) -> set[str]:
    result: set[str] = set()
    for t in tokens:
        t = t.strip()
        if not t:
            continue
        if not t.startswith("."):
            t = "." + t
        result.add(t.lower())
    return result


def ask_extensions() -> frozenset[str] | None:
    print()
    print("  Введите расширения через пробел, например: .py .toml .md")
    print("  Можно без точки — она добавится автоматически.")
    print()
    try:
        raw = input("  Расширения: ").strip()
    except (KeyboardInterrupt, EOFError):
        print()
        return None
    if not raw:
        return None
    result = _normalize_extensions(raw.split())
    return frozenset(result) if result else None


def ask_max_size_kb() -> int | None:
    print()
    print("  Максимальный размер файла в КБ (Enter — по умолчанию 200):")
    print()
    try:
        raw = input("  Размер: ").strip()
    except (KeyboardInterrupt, EOFError):
        print()
        return None
    if not raw:
        return MAX_FILE_SIZE
    if not raw.isdigit() or int(raw) < 1:
        print("  Некорректное значение, беру по умолчанию.")
        return MAX_FILE_SIZE
    return int(raw) * 1024


def ask_dirs() -> tuple[str, ...] | None:
    print()
    print("  Папки для сканирования через запятую.")
    print(
        "  Можно указывать имена (src, tests) или относительные пути "
        "(src/api, docs/v2)."
    )
    print("  Пример: src,tests,docs/v2")
    print()
    try:
        raw = input("  Папки: ").strip()
    except (KeyboardInterrupt, EOFError):
        print()
        return None
    if not raw:
        return None
    result = parse_dir_filter(raw)
    return result if result else None


# ============================================================================
# Оркестрация
# ============================================================================


def _resolve_extensions(
    scenario: Scenario,
    ext_override: frozenset[str] | None,
    interactive: bool,
) -> frozenset[str] | None:
    if ext_override is not None:
        return ext_override
    if scenario.extensions is not None:
        return scenario.extensions
    if interactive:
        result = ask_extensions()
        if result is None:
            print("  Список расширений пуст, возврат в меню.")
            return None
        return result
    print(
        f"  Ошибка: для сценария '{scenario.id}' нужно указать --ext.", file=sys.stderr
    )
    return None


def _resolve_max_size(
    scenario: Scenario,
    max_size_override: int | None,
    interactive: bool,
) -> int | None:
    if max_size_override is not None:
        return max_size_override
    if scenario.max_size is not None:
        return scenario.max_size
    if interactive:
        result = ask_max_size_kb()
        if result is None:
            return None
        return result
    print(
        f"  Ошибка: для сценария '{scenario.id}' нужно указать --max-kb.",
        file=sys.stderr,
    )
    return None


def _resolve_dir_filter(
    scenario: Scenario,
    dirs_override: tuple[str, ...] | None,
    interactive: bool,
) -> tuple[str, ...] | None:
    """
    Возвращает кортеж папок (возможно пустой) или None при отмене.
    """
    if dirs_override is not None:
        return dirs_override
    if not scenario.ask_dirs:
        return ()
    if interactive:
        result = ask_dirs()
        if result is None:
            print("  Список папок пуст, возврат в меню.")
            return None
        return result
    print(
        f"  Ошибка: для сценария '{scenario.id}' нужно указать --dirs.", file=sys.stderr
    )
    return None


def _resolve_output(
    root: Path,
    scenario: Scenario,
    output_override: Path | None,
    no_timestamp: bool,
) -> Path:
    if output_override is not None:
        return output_override
    base = Path(scenario.output)
    if no_timestamp:
        return root / base
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return root / f"{base.stem}_{ts}{base.suffix}"


def run_scan(
    root: Path,
    scenario: Scenario,
    *,
    output_override: Path | None = None,
    ext_override: frozenset[str] | None = None,
    max_size_override: int | None = None,
    dirs_override: tuple[str, ...] | None = None,
    fmt_override: str | None = None,
    no_timestamp: bool = False,
    assume_yes: bool = False,
    interactive: bool = False,
) -> bool:
    extensions = _resolve_extensions(scenario, ext_override, interactive)
    if extensions is None:
        return False

    max_size = _resolve_max_size(scenario, max_size_override, interactive)
    if max_size is None:
        return False

    dir_filter = _resolve_dir_filter(scenario, dirs_override, interactive)
    if dir_filter is None:
        return False

    fmt = fmt_override or scenario.fmt
    output = _resolve_output(root, scenario, output_override, no_timestamp)

    try:
        stats = scan(
            root=root,
            output=output,
            tree_only=scenario.tree_only,
            include_ext=extensions,
            max_size=max_size,
            fmt=fmt,
            assume_yes=assume_yes,
            interactive=interactive,
            dir_filter=dir_filter,
        )
    except OSError as e:
        print(f"\n  Ошибка ввода-вывода: {e}", file=sys.stderr)
        return False

    _print_result(output, stats)
    return True


def interactive_loop() -> None:
    root = Path.cwd().resolve()
    while True:
        print_menu(root)
        choice = ask_choice()
        if choice is None:
            print("  Выход.")
            return

        scenario = SCENARIOS[choice - 1]
        try:
            ok = run_scan(root, scenario, interactive=True)
        except KeyboardInterrupt:
            print("\n  Сканирование прервано.")
            return

        if not ok:
            continue

        print()
        print("  Нажмите Enter, чтобы вернуться в меню, или 0 для выхода.")
        try:
            if input("  > ").strip() == "0":
                return
        except (KeyboardInterrupt, EOFError):
            print()
            return


# ============================================================================
# CLI
# ============================================================================


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="scan_project",
        description="Снимок проекта в Markdown или plain-text.",
    )
    p.add_argument(
        "-s",
        "--scenario",
        choices=[s.id for s in SCENARIOS],
        help="Сценарий. Без него запускается интерактивное меню.",
    )
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Путь к выходному файлу (по умолчанию — в корне проекта с таймстампом).",
    )
    p.add_argument(
        "-e",
        "--ext",
        nargs="*",
        default=None,
        help="Расширения (переопределяют сценарий), напр.: .py .toml",
    )
    p.add_argument(
        "-d",
        "--dirs",
        default=None,
        help=(
            "Сканировать только указанные папки, через запятую. "
            "Можно указывать имена (src,tests) или относительные пути "
            "(src/api,docs/v2)."
        ),
    )
    p.add_argument(
        "--max-kb",
        type=int,
        default=None,
        help="Максимальный размер файла в КБ.",
    )
    p.add_argument(
        "--format",
        choices=["markdown", "text"],
        default=None,
        help="Формат вывода (по умолчанию — из сценария).",
    )
    p.add_argument(
        "--no-timestamp",
        action="store_true",
        help="Не добавлять таймстамп к имени файла.",
    )
    p.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Не спрашивать подтверждений; потенциально секретные файлы "
        "будут включены.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.scenario is None:
        try:
            interactive_loop()
        except KeyboardInterrupt:
            print("\n  Прервано.", file=sys.stderr)
            return 130
        return 0

    scenario = next(s for s in SCENARIOS if s.id == args.scenario)
    root = Path.cwd().resolve()

    ext_override: frozenset[str] | None = None
    if args.ext is not None:
        normalized = _normalize_extensions(args.ext)
        if not normalized:
            print("  Ошибка: --ext пуст.", file=sys.stderr)
            return 2
        ext_override = frozenset(normalized)

    max_size_override: int | None = None
    if args.max_kb is not None:
        if args.max_kb < 1:
            print("  Ошибка: --max-kb должен быть >= 1.", file=sys.stderr)
            return 2
        max_size_override = args.max_kb * 1024

    dirs_override: tuple[str, ...] | None = None
    if args.dirs is not None:
        parsed = parse_dir_filter(args.dirs)
        if not parsed:
            print("  Ошибка: --dirs пуст.", file=sys.stderr)
            return 2
        dirs_override = parsed

    try:
        ok = run_scan(
            root,
            scenario,
            output_override=args.output,
            ext_override=ext_override,
            max_size_override=max_size_override,
            dirs_override=dirs_override,
            fmt_override=args.format,
            no_timestamp=args.no_timestamp,
            assume_yes=args.yes,
            interactive=False,
        )
    except KeyboardInterrupt:
        print("\n  Прервано.", file=sys.stderr)
        return 130

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
