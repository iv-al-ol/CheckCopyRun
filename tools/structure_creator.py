# create_structure.py
"""
Генератор структуры проекта по дереву из structure.txt.

Особенности:
- Читает structure.txt рядом со скриптом (UTF-8).
- Если файл был сохранён в CP866, символы дерева автоматически
  восстанавливаются (вФЬ→├, вФВ→│, вФА→─, вФФ→└).
- Комментарии после '#' игнорируются.
- Корневая строка (напр. 'CheckCopyRun/') опциональна: если она есть —
  создаётся папка и всё уходит внутрь неё; если нет — всё разворачивается
  прямо в текущей папке (рядом со скриптом).
"""

import re
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
TREE_FILE = BASE_DIR / "structure.txt"

# CP866-порча символов дерева (E2 94 xx при неверной кодировке).
MOJIBAKE_MAP = {
    "вФЬ": "├",
    "вФВ": "│",
    "вФА": "─",
    "вФФ": "└",
}

NAME_RE = re.compile(r"[│├└─\s]*([^│├└─\s#][^#]*?)\s*(?:#.*)?$")


def fix_mojibake(text: str) -> str:
    for bad, good in MOJIBAKE_MAP.items():
        text = text.replace(bad, good)
    return text


def parse_tree(text: str):
    """Возвращает список кортежей (depth, name, is_dir)."""
    entries = []
    for raw in text.splitlines():
        if not raw.strip():
            continue
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue

        m = NAME_RE.search(line)
        if not m:
            continue
        name = m.group(1).strip()
        if not name:
            continue

        idx = line.index(name)
        depth = idx // 4          # один уровень = 4 символа префикса

        is_dir = name.endswith("/")
        if is_dir:
            name = name[:-1]

        entries.append((depth, name, is_dir))
    return entries


def create_structure(tree_text: str, root: Path = Path()):
    entries = parse_tree(tree_text)
    if not entries:
        print("Не удалось распарсить дерево.")
        return

    first_depth, first_name, first_is_dir = entries[0]
    has_root = (first_depth == 0 and first_is_dir)

    if has_root:
        root = root / first_name
        root.mkdir(parents=True, exist_ok=True)
        entries = entries[1:]
        print(f"[DIR ] {root}  (корень)")

    if not entries:
        return

    # stack[k] — папка уровня k. Родитель записи с глубиной d — stack[d-1].
    # Значит, длина стека должна быть ровно d перед обработкой записи.
    # ЭТО КЛЮЧЕВОЕ ИСПРАВЛЕНИЕ: раньше было "+1", из-за чего соседи
    # складывались в первую попавшуюся папку (в вашем случае — в assets).
    stack = [root]
    for depth, name, is_dir in entries:
        while len(stack) > depth:
            stack.pop()
        if not stack:             # защита от совсем кривого дерева
            stack = [root]

        parent = stack[-1]
        target = parent / name

        if is_dir:
            target.mkdir(parents=True, exist_ok=True)
            stack.append(target)
            print(f"[DIR ] {target}")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.touch(exist_ok=True)
            print(f"[FILE] {target}")


def main():
    if not TREE_FILE.exists():
        print(f"Файл не найден: {TREE_FILE}")
        print("Положите structure.txt рядом со скриптом.")
        sys.exit(1)

    text = TREE_FILE.read_text(encoding="utf-8")

    if "вФ" in text:
        print("Обнаружена CP866-порча символов дерева — восстанавливаю.\n")
        text = fix_mojibake(text)

    create_structure(text, root=BASE_DIR)
    print("\nГотово.")


if __name__ == "__main__":
    main()
