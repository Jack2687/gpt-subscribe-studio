"""订单存储。

**骨架实现**：进程内内存存储 + 幂等键去重。
生产实现应替换为 SQLite（tasks.md T010 / ADR 0003），接口保持不变。

宪法第 I 条：此处**不得**保存 session / token / 卡字段。
"""

from __future__ import annotations

from typing import Dict, List, Optional

from dcp_contracts import Job, Order, OrderStatus


class InMemoryStore:
    """最小的订单 / 任务存储。"""

    def __init__(self) -> None:
        self.orders: Dict[str, Order] = {}
        self.jobs: Dict[str, Job] = {}
        self._idempotency: Dict[str, str] = {}

    # -- 幂等 ---------------------------------------------------------------- #
    def find_by_idempotency(self, key: Optional[str]) -> Optional[Order]:
        if not key:
            return None
        order_id = self._idempotency.get(key)
        return self.orders.get(order_id) if order_id else None

    # -- 订单 ---------------------------------------------------------------- #
    def create_order(self, order: Order, idempotency_key: Optional[str] = None) -> Order:
        self.orders[order.id] = order
        if idempotency_key:
            self._idempotency[idempotency_key] = order.id
        return order

    def get_order(self, order_id: str) -> Optional[Order]:
        return self.orders.get(order_id)

    def update_status(self, order_id: str, status: OrderStatus) -> Order:
        order = self.orders[order_id]
        order.status = status
        return order

    # -- 任务 ---------------------------------------------------------------- #
    def add_job(self, job: Job) -> Job:
        self.jobs[job.id] = job
        return job

    def jobs_for_order(self, order_id: str) -> List[Job]:
        return [job for job in self.jobs.values() if job.order_id == order_id]

    def clear(self) -> None:
        """测试用。"""

        self.orders.clear()
        self.jobs.clear()
        self._idempotency.clear()


#: 进程内单例（只在骨架/测试中使用；生产改注入）。
store = InMemoryStore()
