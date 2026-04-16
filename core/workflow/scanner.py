from __future__ import annotations

"""文件扫描工具。"""

import os


def iter_scan_files(
    scan_roots: list[str],
    *,
    ignored_roots: list[str] | None = None,
) -> list[str]:
    """递归扫描文件，并跳过显式忽略的目录。"""

    results: list[str] = []
    ignored = [
        os.path.abspath(root)
        for root in (ignored_roots or [])
        if root and os.path.exists(root)
    ]

    for root in scan_roots:
        absolute_root = os.path.abspath(root)
        if not os.path.exists(absolute_root):
            continue
        if os.path.isfile(absolute_root):
            results.append(absolute_root)
            continue

        for current_root, dirs, files in os.walk(absolute_root):
            current_root_abs = os.path.abspath(current_root)
            dirs[:] = [
                name
                for name in dirs
                if not _is_ignored(os.path.join(current_root_abs, name), ignored)
            ]
            if _is_ignored(current_root_abs, ignored):
                continue
            for filename in files:
                file_path = os.path.join(current_root_abs, filename)
                if _is_ignored(file_path, ignored):
                    continue
                results.append(file_path)

    return list(dict.fromkeys(os.path.abspath(path) for path in results))


def _is_ignored(path: str, ignored_roots: list[str]) -> bool:
    """判断当前路径是否落在忽略目录下。"""

    absolute_path = os.path.abspath(path)
    for ignored_root in ignored_roots:
        try:
            if os.path.commonpath([absolute_path, ignored_root]) == ignored_root:
                return True
        except ValueError:
            continue
    return False