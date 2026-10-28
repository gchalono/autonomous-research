"""Project artifact directory: atomic writes, versioned prompt history.

Files are written to a temp sibling and atomically renamed, so a crash can
never expose a half-written final report as a completed artifact. Prompt
versions and audit findings are never overwritten -- each version gets its
own file.
"""
from __future__ import annotations

import json
import os
import tempfile
from ..security.permissions import safe_join


def project_dir(root: str, project_id: str) -> str:
    path = safe_join(root, project_id)
    os.makedirs(path, exist_ok=True)
    return path


def atomic_write(path: str, content: str) -> str:
    """Write via temp file + os.replace. Returns the final path."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    # Do not follow a pre-existing predictable <name>.tmp symlink.
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False,
                                         dir=os.path.dirname(os.path.abspath(path)),
                                         suffix=".tmp") as fh:
            tmp = fh.name
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if tmp and os.path.exists(tmp):
            os.unlink(tmp)
    return path


def write_text(root: str, project_id: str, filename: str, content: str) -> str:
    return atomic_write(safe_join(project_dir(root, project_id), filename), content)


def write_json(root: str, project_id: str, filename: str, payload: dict) -> str:
    return write_text(root, project_id, filename, json.dumps(payload, indent=2))


def read_text(root: str, project_id: str, filename: str) -> str:
    with open(safe_join(project_dir(root, project_id), filename),
              encoding="utf-8") as fh:
        return fh.read()


def artifact_exists(root: str, project_id: str, filename: str) -> bool:
    return os.path.exists(safe_join(project_dir(root, project_id), filename))


def append_line(root: str, project_id: str, filename: str, line: str) -> str:
    """Append one line (used for the structured run log; appends are not
    atomic, but a torn last line is harmless in a log)."""
    path = safe_join(project_dir(root, project_id), filename)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line.rstrip("\n") + "\n")
    return path
