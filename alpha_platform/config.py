"""配置解析：默认值 → 配置文件 → 环境变量 → 命令行参数（后者覆盖前者）。

命令行那一层由 `cli.py` 在解析后覆盖到本对象上，不在此处理。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from pathlib import Path

CONFIG_FILENAME = "alpha-platform.json"
ENV_PREFIX = "ALPHA_PLATFORM_"

# 相关性阈值来源（PRD #6：阈值必带来源，不允许无来源硬编码）
SOURCE_CONVENTION = "convention_demo"
SOURCE_MANUAL = "manual"
SOURCE_PLATFORM = "platform"


@dataclass(frozen=True)
class Config:
    db_path: str = "data/inventory.db"
    snapshot_dir: str = "data/snapshots"
    log_dir: str = "data/logs"
    classify_threshold: float = 0.3
    correlation_threshold: float = 0.7
    correlation_threshold_source: str = SOURCE_CONVENTION
    split_threshold: int = 9000
    page_size: int = 100      # 平台 limit 至少支持 500（一手核验），默认保守
    batch_size: int = 20

    def with_overrides(self, **overrides) -> "Config":
        """命令行层覆盖：None 值表示「未指定」，不覆盖。"""
        effective = {k: v for k, v in overrides.items() if v is not None}
        if "correlation_threshold" in effective:
            effective.setdefault("correlation_threshold_source", SOURCE_MANUAL)
        return replace(self, **effective)


_NUMERIC = {
    "classify_threshold": float,
    "correlation_threshold": float,
    "split_threshold": int,
    "page_size": int,
    "batch_size": int,
}


def load(project_root: Path | str | None = None, env: dict | None = None) -> Config:
    env = os.environ if env is None else env
    values: dict = {}

    if project_root is not None:
        path = Path(project_root) / CONFIG_FILENAME
        if path.is_file():
            values.update(json.loads(path.read_text(encoding="utf-8")))

    for field_name in Config.__dataclass_fields__:
        raw = env.get(f"{ENV_PREFIX}{field_name.upper()}")
        if raw is not None:
            values[field_name] = raw

    for key, caster in _NUMERIC.items():
        if key in values:
            values[key] = caster(values[key])

    # 阈值被显式指定过（配置文件或环境变量）即视为手工来源，除非同时指定了来源
    if "correlation_threshold" in values and "correlation_threshold_source" not in values:
        values["correlation_threshold_source"] = SOURCE_MANUAL

    known = {k: v for k, v in values.items() if k in Config.__dataclass_fields__}
    return Config(**known)
