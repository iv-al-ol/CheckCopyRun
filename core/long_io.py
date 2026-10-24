"""I/O-обёртки с поддержкой длинных путей Windows (>260).

Каждая функция принимает путь и внутри применяет
to_long_path из core.paths. Использование — только для
файловых операций. Для сравнения путей, отображения в UI
и передачи в explorer/subprocess — обычные функции os/shutil.

Пример:

    from core import long_io

    long_io.copy2(src, dst)
    with long_io.open(path, "rb") as f: ...
    for root, dirs, names in long_io.walk(top): ...

Особенность walk: возвращает (root, dirs, names) с путями,
начинающимися с того же префикса, что и top. Если top был
длинным, все root префиксованы; для os.path.relpath(root, top)
нужно передавать to_long_path(top), а не исходный top.
"""

from __future__ import annotations

import builtins
import os
import shutil
from collections.abc import Iterator
from typing import IO, Any

from core.paths import to_long_path


def open(
    path: str | os.PathLike,
    mode: str = "r",
    *args: Any, **kwargs: Any,
) -> IO[Any]:
    return builtins.open(to_long_path(path), mode, *args, **kwargs)


def copy2(
    src: str | os.PathLike,
    dst: str | os.PathLike,
    *args: Any, **kwargs: Any,
) -> str:
    return shutil.copy2(
        to_long_path(src), to_long_path(dst),
        *args, **kwargs,
    )


def copyfile(
    src: str | os.PathLike,
    dst: str | os.PathLike,
    *args: Any, **kwargs: Any,
) -> str:
    return shutil.copyfile(
        to_long_path(src), to_long_path(dst),
        *args, **kwargs,
    )


def replace(
    src: str | os.PathLike,
    dst: str | os.PathLike,
) -> None:
    os.replace(to_long_path(src), to_long_path(dst))


def rename(
    src: str | os.PathLike,
    dst: str | os.PathLike,
) -> None:
    os.rename(to_long_path(src), to_long_path(dst))


def remove(path: str | os.PathLike) -> None:
    os.remove(to_long_path(path))


def unlink(path: str | os.PathLike) -> None:
    os.unlink(to_long_path(path))


def rmdir(path: str | os.PathLike) -> None:
    os.rmdir(to_long_path(path))


def rmtree(path: str | os.PathLike, **kwargs: Any) -> None:
    shutil.rmtree(to_long_path(path), **kwargs)


def makedirs(path: str | os.PathLike, **kwargs: Any) -> None:
    os.makedirs(to_long_path(path), **kwargs)


def mkdir(path: str | os.PathLike, **kwargs: Any) -> None:
    os.mkdir(to_long_path(path), **kwargs)


def stat(
    path: str | os.PathLike,
    *args: Any, **kwargs: Any,
) -> os.stat_result:
    return os.stat(to_long_path(path), *args, **kwargs)


def isfile(path: str | os.PathLike) -> bool:
    return os.path.isfile(to_long_path(path))


def isdir(path: str | os.PathLike) -> bool:
    return os.path.isdir(to_long_path(path))


def exists(path: str | os.PathLike) -> bool:
    return os.path.exists(to_long_path(path))


def getsize(path: str | os.PathLike) -> int:
    return os.path.getsize(to_long_path(path))


def getmtime(path: str | os.PathLike) -> float:
    return os.path.getmtime(to_long_path(path))


def listdir(path: str | os.PathLike) -> list[str]:
    return os.listdir(to_long_path(path))


def scandir(path: str | os.PathLike) -> Iterator[os.DirEntry]:
    return os.scandir(to_long_path(path))


def disk_usage(path: str | os.PathLike) -> shutil._ntuple_diskusage:
    return shutil.disk_usage(to_long_path(path))


def walk(
    top: str | os.PathLike,
    **kwargs: Any,
) -> Iterator[tuple[str, list[str], list[str]]]:
    """os.walk с префиксом на top.

    Возвращаемые root/dirs — с тем же префиксом, что и
    to_long_path(top). Для relpath используйте to_long_path(top)
    как start.
    """
    return os.walk(to_long_path(top), **kwargs)
