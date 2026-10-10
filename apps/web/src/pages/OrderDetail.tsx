import { useEffect, useState } from "react";

import { formatAmount, getOrder, isHostedOrder, type Order } from "../api/client";

const LABELS: Record<string, string> = {
  created: "已创建",
  pending_checkout: "正在生成结账",
  awaiting_payment: "等待支付",
  paying: "支付中",
  requires_action: "需要 3DS 验证",
  unknown: "状态待确认",
  verifying: "正在确认订阅",
  active: "订阅已生效",
  delivered: "已开通",
  rejected: "已拒绝",
  failed: "失败",
};

interface Props {
  orderId: string;
  onReset: () => void;
}

export function OrderDetail({ orderId, onReset }: Props) {
  const [order, setOrder] = useState<Order | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function refresh() {
      try {
        const next = await getOrder(orderId);
        if (!cancelled) setOrder(next);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "查询失败");
      }
    }
    void refresh();
    const timer = window.setInterval(refresh, 4000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [orderId]);

  if (!order) {
    return <p className="hint">{error ?? "正在读取订单…"}</p>;
  }

  const done = ["delivered", "active", "failed", "rejected"].includes(order.status);
  return (
    <section>
      <p className="status">{LABELS[order.status] ?? order.status}</p>
      <p className="meta">
        订单 <code>{order.id}</code> · {order.plan} · {order.billing_country}
        {order.seat_quantity ? ` · ${order.seat_quantity} 席` : ""}
        {formatAmount(order.amount, order.currency) ? ` · ${formatAmount(order.amount, order.currency)}` : ""}
      </p>
      {isHostedOrder(order) && order.checkout_url && (
        <p>
          Team 长链：{" "}
          <a href={order.checkout_url} target="_blank" rel="noreferrer">
            打开支付页
          </a>
        </p>
      )}
      {order.subscription?.active && (
        <p className="ok">
          订阅已生效
          {order.subscription.expires_at ? `，到期 ${order.subscription.expires_at}` : ""}
        </p>
      )}
      {order.next_action?.url && (
        <p>
          需要完成验证：{" "}
          <a href={order.next_action.url} target="_blank" rel="noreferrer">
            打开 3DS
          </a>
        </p>
      )}
      {order.last_error && <p className="alert">{order.last_error}</p>}
      {error && <p className="alert">{error}</p>}
      <div className="actions">
        {done && (
          <button type="button" className="btn btn-primary" onClick={onReset}>
            再开通一单
          </button>
        )}
      </div>
    </section>
  );
}
