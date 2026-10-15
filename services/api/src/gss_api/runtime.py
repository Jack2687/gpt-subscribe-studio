"""组装本进程内的开通流水线。不调用其它本地项目。"""

from __future__ import annotations

from gss_account import FakeAccountAdapter, UpstreamAccountAdapter
from gss_checkout import FakeCheckoutAdapter, UpstreamCheckoutAdapter
from gss_core.config import use_fake_adapters
from gss_orchestrator.pipeline import OrderPipeline, PipelineDeps
from gss_payment import FakePaymentAdapter, UpstreamPaymentAdapter


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
