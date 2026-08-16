"""凭据加载（PRD #9、设计 §4.7、L1）。

红线：凭据只入内存 `Credentials` 实例；不写回任何文件；报错信息里不出现
文件内容——出错时只说路径与形态要求，绝不回显读到的东西。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .client import AuthError, Credentials

DEFAULT_FILENAME = ".brain_credentials"
PATH_ENV = "BRAIN_CREDENTIALS_PATH"


def resolve_path(project_root: Path | str | None = None) -> Path:
    override = os.environ.get(PATH_ENV)
    if override:
        return Path(override)
    root = Path(project_root) if project_root is not None else Path.cwd()
    return root / DEFAULT_FILENAME


def load(project_root: Path | str | None = None) -> Credentials:
    path = resolve_path(project_root)
    if not path.is_file():
        raise AuthError(
            f"凭据文件不存在：{path}（可用环境变量 {PATH_ENV} 指定其他位置）。"
            f" 格式为 JSON 数组 [email, password]"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AuthError(f"凭据文件无法解析：{path}（需为 JSON 数组 [email, password]）") from exc

    if not (isinstance(payload, list) and len(payload) == 2 and all(isinstance(x, str) for x in payload)):
        raise AuthError(f"凭据文件格式不符：{path} 需为 JSON 数组 [email, password]")

    return Credentials(email=payload[0], password=payload[1])
