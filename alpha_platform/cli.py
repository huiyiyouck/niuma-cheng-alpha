"""CLI 入口与唯一组装点（设计 §3.2、§3.1.0）。

`BrainClient` 只在这里构造并传入各业务函数——不建模块级单例、不用全局变量，
替身注入因此不需要 monkey-patch。
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from . import classify, config as config_mod, credentials, db, precheck, report, submit, sync
from .client import AuthError, BrainClient, RateLimitError

# 退出码（设计 §3.2）
OK = 0
GENERAL_FAILURE = 1
AUTH_FAILED = 2
BAD_ARGS = 3
FINGERPRINT_INVALID = 4      # 安全语义：要人重新确认
RESUMABLE_INTERRUPT = 5      # 韧性语义：重跑同一命令即可
IN_FLIGHT_PENDING = 6        # 存在待核对记录，先跑 submit --reconcile

STAGES = ("IS", "OS")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m alpha_platform")
    sub = parser.add_subparsers(dest="command", required=True)

    p_sync = sub.add_parser("sync", help="同步平台库存")
    mode = p_sync.add_mutually_exclusive_group(required=True)
    mode.add_argument("--full", action="store_true", help="时间窗自适应切片全量同步 + 窗口级对账")
    mode.add_argument("--incremental", action="store_true", help="按水位拉新增")
    p_sync.add_argument("--stage", choices=("IS", "OS", "all"), default="all")
    p_sync.add_argument("--no-resume", dest="resume", action="store_false", help="忽略断点，从头切片")
    p_sync.add_argument("--split-threshold", type=int)
    p_sync.add_argument("--page-size", type=int)

    p_classify = sub.add_parser("classify", help="按 checks 规则分流")
    p_classify.add_argument("--threshold", type=float)
    p_classify.add_argument("--scope", choices=("all", "unclassified"), default="all")

    p_precheck = sub.add_parser("precheck", help="提交前预判（两阶段短路）")
    p_precheck.add_argument("--batch-size", type=int)
    p_precheck.add_argument("--limit", type=int, help="本次最多处理条数")
    p_precheck.add_argument("--reset", nargs="+", metavar="ALPHA_ID")
    p_precheck.add_argument("--retry-pending", action="store_true", help="把待定记录一并纳入候选集")

    p_report = sub.add_parser("report", help="漏斗报告")
    p_report.add_argument("--format", choices=("text", "json"), default="text")
    p_report.add_argument("--output", type=Path)
    p_report.add_argument("--status", help="输出该状态的记录清单")

    p_submit = sub.add_parser("submit", help="人工确认后提交（唯一不可逆动作）")
    action = p_submit.add_mutually_exclusive_group(required=True)
    action.add_argument("--dry-run", action="store_true", help="打印清单与指纹，提交接口零调用")
    action.add_argument("--confirm", metavar="FINGERPRINT", help="校验指纹后逐条提交")
    action.add_argument("--reconcile", action="store_true", help="按平台真实状态收敛 in_flight")

    return parser


def main(argv: list[str] | None = None, *, client_factory=None) -> int:
    args = build_parser().parse_args(argv)
    cfg = config_mod.load(project_root=Path.cwd()).with_overrides(
        classify_threshold=getattr(args, "threshold", None),
        split_threshold=getattr(args, "split_threshold", None),
        page_size=getattr(args, "page_size", None),
        batch_size=getattr(args, "batch_size", None),
    )
    _setup_logging(cfg)
    conn = db.connect(cfg.db_path)

    try:
        return _dispatch(args, cfg, conn, client_factory)
    except AuthError as exc:
        print(f"认证失败：{exc}", file=sys.stderr)
        return AUTH_FAILED
    except submit.FingerprintMismatch as exc:
        print(f"{exc}", file=sys.stderr)
        return FINGERPRINT_INVALID
    except submit.InFlightPending as exc:
        print(f"{exc}", file=sys.stderr)
        return IN_FLIGHT_PENDING
    except precheck.ResetGuardError as exc:
        print(f"{exc}", file=sys.stderr)
        return BAD_ARGS
    except RateLimitError as exc:
        print(f"{exc}；断点已保存，稍后重跑同一命令即可", file=sys.stderr)
        return RESUMABLE_INTERRUPT
    finally:
        conn.close()


def _dispatch(args, cfg, conn, client_factory) -> int:
    if args.command == "sync":
        client = _make_client(cfg, client_factory)
        stages = STAGES if args.stage == "all" else (args.stage,)
        for stage in stages:
            if args.full:
                result = sync.full_sync(client, conn, stage=stage, config=cfg, resume=args.resume)
                _print_sync(stage, result)
            else:
                result = sync.incremental_sync(client, conn, stage=stage, config=cfg)
                print(f"[{stage}] 增量新增 {result.fetched} 条，本地共 {result.local_count} 条")
        return OK

    if args.command == "classify":
        counts = classify.run(conn, threshold=cfg.classify_threshold, scope=args.scope)
        for status, n in counts.items():
            print(f"{status:<12}{n}")
        print(f"守恒断言：{'通过' if classify.conservation_holds(conn) else '未通过'}")
        return OK

    if args.command == "precheck":
        client = _make_client(cfg, client_factory)
        counts = precheck.run(
            client, conn, config=cfg, batch_size=cfg.batch_size, limit=args.limit,
            reset=args.reset, retry_pending=args.retry_pending,
        )
        print(f"预判完成：{counts}")
        return OK

    if args.command == "report":
        if args.status:
            text = report.render_list(report.list_by_status(conn, args.status))
        else:
            text = report.render(report.build(conn), fmt=args.format)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(text, encoding="utf-8")
            print(f"报告已写入 {args.output}")
        else:
            print(text)
        return OK

    if args.command == "submit":
        return _submit(args, cfg, conn, client_factory)

    return BAD_ARGS


def _submit(args, cfg, conn, client_factory) -> int:
    if args.dry_run:
        result = submit.dry_run(conn)
        for item in result.items:
            print(f"{item['alpha_id']:<16}{item['expression']}")
        print(f"\n共 {len(result.items)} 条；指纹 {result.fingerprint}")
        print(f"确认提交请跑：submit --confirm {result.fingerprint}")
        return OK

    client = _make_client(cfg, client_factory)

    if args.reconcile:
        report_ = submit.reconcile(client, conn, snapshot_dir=cfg.snapshot_dir)
        for detail in report_.details:
            print(f"{detail['alpha_id']:<16}{detail['action']}")
        print(f"收敛为已提交 {report_.resolved_submitted}、退回待确认 {report_.resolved_reverted}、"
              f"未能收敛 {report_.unresolved}")
        return IN_FLIGHT_PENDING if report_.unresolved else OK

    result = submit.confirm(client, conn, fingerprint=args.confirm, snapshot_dir=cfg.snapshot_dir)
    print(f"提交成功 {result.succeeded}、失败 {result.failed}")
    print(f"快照已写入 {result.snapshot_path}（不入 git，建议异地备份）")
    return OK if result.failed == 0 else GENERAL_FAILURE


def _make_client(cfg, client_factory):
    if client_factory is not None:
        return client_factory()
    return BrainClient(credentials.load(project_root=Path.cwd()))


def _print_sync(stage: str, result) -> None:
    print(f"[{stage}] 本地 {result.local_count} 条，平台报告 {result.total_reported} 条")
    print(f"[{stage}] 窗口级对账：{'通过' if result.reconciled else '不一致'}")
    for slice_info in result.mismatched_slices:
        print(f"    窗口 {slice_info['slice']}：报告 {slice_info['reported']} / 实拉 {slice_info['fetched']}")
    if result.offset_ceiling_detected:
        print(f"[{stage}] 已检出 offset 封顶，留痕见 meta.offset_ceiling_detected")


def _setup_logging(cfg) -> None:
    """白名单式日志落 data/logs/（N7）——凭据、Authorization 头、cookie 一律不记录。

    只配置本包的 logger，不碰 root：既不污染调用方的日志配置，也避免
    `basicConfig` 在 root 已有 handler 时静默失效。
    """
    log_dir = Path(cfg.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    path = (log_dir / "alpha-platform.log").resolve()

    logger = logging.getLogger("alpha_platform")
    logger.setLevel(logging.INFO)
    already = any(
        isinstance(h, logging.FileHandler) and Path(h.baseFilename) == path
        for h in logger.handlers
    )
    if not already:
        handler = logging.FileHandler(path, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)
