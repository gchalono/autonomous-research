"""Project artifact directory: atomic writes, versioned prompt history.

Files are written to a temp sibling and atomically renamed, so a crash can
never expose a half-written final report as a completed artifact. Prompt
versions and audit findings are never overwritten -- each version gets its
own file.
"""
from __future__ import annotations

import json
import os


def project_dir(root: str, project_id: str) -> str:
    path = os.path.join(root, project_id)
    os.makedirs(path, exist_ok=True)
    return path


def atomic_write(path: str, content: str) -> str:
    """Write via temp file + os.replace. Returns the final path."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(content)
    os.replace(tmp, path)
    return path


def write_text(root: str, project_id: str, filename: str, content: str) -> str:
    return atomic_write(os.path.join(project_dir(root, project_id), filename), content)


def write_json(root: str, project_id: str, filename: str, payload: dict) -> str:
    return write_text(root, project_id, filename, json.dumps(payload, indent=2))


def read_text(root: str, project_id: str, filename: str) -> str:
    with open(os.path.join(project_dir(root, project_id), filename),
              encoding="utf-8") as fh:
        return fh.read()


def artifact_exists(root: str, project_id: str, filename: str) -> bool:
    return os.path.exists(os.path.join(project_dir(root, project_id), filename))


def append_line(root: str, project_id: str, filename: str, line: str) -> str:
    """Append one line (used for the structured run log; appends are not
    atomic, but a torn last line is harmless in a log)."""
    path = os.path.join(project_dir(root, project_id), filename)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line.rstrip("\n") + "\n")
    return path
