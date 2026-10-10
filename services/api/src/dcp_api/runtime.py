"""组装本进程内的开通流水线。不调用其它本地项目。"""

from __future__ import annotations

from dcp_account import FakeAccountAdapter, UpstreamAccountAdapter
from dcp_checkout import FakeCheckoutAdapter, UpstreamCheckoutAdapter
from dcp_core.config import use_fake_adapters
from dcp_orchestrator.pipeline import OrderPipeline, PipelineDeps
from dcp_payment import FakePaymentAdapter, UpstreamPaymentAdapter


def build_pipeline() -> OrderPipeline:
    if use_fake_adapters():
        return OrderPipeline(
            PipelineDeps(
                checkout=FakeCheckoutAdapter(),
                payment=FakePaymentAdapter(),
                account=FakeAccountAdapter(),
            )
        )
    return OrderPipeline(
        PipelineDeps(
            checkout=UpstreamCheckoutAdapter(),
            payment=UpstreamPaymentAdapter(),
            account=UpstreamAccountAdapter(),
        )
    )


__all__ = ["build_pipeline"]
