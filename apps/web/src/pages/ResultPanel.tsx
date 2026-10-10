import { formatAmount, type Order } from "../api/client";
import { FAILED_STATUSES, SUCCESS_STATUSES, type HistoryRecord } from "../api/history";

export const STATUS_LABELS: Record<string, string> = {
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

interface ResultProps {
  order: Order;
  onReset: () => void;
}

export function ResultPanel({ order, onReset }: ResultProps) {
  const success = SUCCESS_STATUSES.includes(order.status);
  const failed = FAILED_STATUSES.includes(order.status);
  const amount = formatAmount(order.amount, order.currency);
  return (
    <section className={success ? "result result-ok" : failed ? "result result-fail" : "result"} role="status">
      <p className="status">
        {success ? "✅ 开通成功" : failed ? "❌ 开通失败" : `⏳ ${STATUS_LABELS[order.status] ?? order.status}`}
      </p>
      <p className="meta">
        订单 <code>{order.id}</code> · {order.plan} · {order.billing_country}
        {amount ? ` · ${amount}` : ""}
      </p>
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
      {order.last_error && !success && <p className="alert">{order.last_error}</p>}
      {(success || failed) && (
        <div className="actions">
          <button type="button" className="btn btn-primary" onClick={onReset}>
            再开通一单
          </button>
        </div>
      )}
    </section>
  );
}

export function HistoryList({ items }: { items: HistoryRecord[] }) {
  if (items.length === 0) return null;
  return (
    <section className="history">
      <h2>开通记录</h2>
      <p className="hint">仅保存在当前浏览器，最多 50 条。</p>
      <ul>
        {items.map((item) => {
          const success = SUCCESS_STATUSES.includes(item.status);
          const failed = FAILED_STATUSES.includes(item.status);
          const amount = formatAmount(item.amount, item.currency);
          return (
            <li key={item.id} className={success ? "h-ok" : failed ? "h-fail" : ""}>
              <strong>{success ? "成功" : failed ? "失败" : STATUS_LABELS[item.status] ?? item.status}</strong>
              <span>
                {" "}
                {item.plan} · {item.country}
                {amount ? ` · ${amount}` : ""} · {new Date(item.at).toLocaleString()}
              </span>
              {failed && item.error && <div className="h-error">{item.error}</div>}
              <div className="h-id">
                <code>{item.id}</code>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
