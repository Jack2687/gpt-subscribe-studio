"""编排 worker（骨架）。

轮询待处理 Job、驱动状态机、断点续跑。真实实现见 tasks.md T020 / T027 / T032。

骨架阶段行为：
- 启动自检（配置、缺失的上游引用）；
- ``--once`` 只做一次自检后退出（便于 CI / 冒烟测试）；
- 默认空转轮询，不消费任何真实任务。
"""

from __future__ import annotations

import argparse
import logging
import time

from dcp_core import install_logging_filter
from dcp_core.config import load_settings, missing_upstreams

logger = logging.getLogger("dcp_orchestrator.worker")


def self_check() -> list[str]:
    """返回缺失的上游引用列表（空表示就绪）。"""

    settings = load_settings()
    missing = missing_upstreams(settings)
    logger.info(
        "worker 自检: bind=%s:%s promo=%s data=%s",
        settings.bind_host,
        settings.bind_port,
        settings.enable_promo_mode,
        settings.data_dir,
    )
    if missing:
        logger.warning("缺少上游引用（部分链路会 fail-fast）: %s", ", ".join(missing))
    return missing


def run(poll_interval: float = 5.0, once: bool = False) -> None:
    install_logging_filter()
    self_check()
    if once:
        return
    logger.info("worker 启动，轮询间隔 %.1fs（骨架阶段不消费真实任务）", poll_interval)
    while True:
        # TODO(tasks.md T020): 占锁取 Job → 驱动状态机 → 释放锁。
        time.sleep(poll_interval)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="直卡协议编排 worker（骨架）")
    parser.add_argument("--once", action="store_true", help="只做一次自检后退出")
    parser.add_argument("--poll-interval", type=float, default=5.0)
    args = parser.parse_args(argv)
    run(poll_interval=args.poll_interval, once=args.once)


if __name__ == "__main__":
    main()
