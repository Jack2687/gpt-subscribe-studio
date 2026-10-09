/**
 * 后端 API 客户端。
 *
 * 注意：**卡号/CVV 永不经过这里**。任何卡片敏感字段都在 `card-payment/CardFields.tsx`
 * 内被替换为不透明的 `payment_method_token` 后才发送。
 */

export type AccountSource = "customer_session" | "platform_account";
export type CardSource = "customer" | "platform";
export type BillingMode = "standard" | "promo";
export type Plan = "plus" | "pro_lite" | "pro" | "pro_max";

export interface Mode {
  account_source: AccountSource;
  card_source: CardSource;
  billing_mode: BillingMode;
  risk_acknowledged: boolean;
}

export interface OrderCreateRequest {
  plan: Plan;
  billing_country: string;
  mode: Mode;
  session?: string;
  payment_method_token?: string;
}

export interface Order {
  id: string;
  status: string;
  plan: string;
  billing_country: string;
  mode: Mode;
  checkout_url?: string | null;
  subscription?: { active: boolean; expires_at?: string | null; channel?: string | null } | null;
}

const jsonHeaders = { "Content-Type": "application/json" };

export async function createOrder(req: OrderCreateRequest, idempotencyKey: string): Promise<Order> {
  const res = await fetch("/api/orders", {
    method: "POST",
    headers: { ...jsonHeaders, "Idempotency-Key": idempotencyKey },
    body: JSON.stringify(req),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail?.detail?.message ?? `创建订单失败（${res.status}）`);
  }
  return (await res.json()) as Order;
}

export async function getOrder(orderId: string): Promise<Order> {
  const res = await fetch(`/api/orders/${orderId}`);
  if (!res.ok) throw new Error(`查询订单失败（${res.status}）`);
  return (await res.json()) as Order;
}

export function subscribeOrderEvents(orderId: string, onEvent: (order: Order) => void): () => void {
  const source = new EventSource(`/api/orders/${orderId}/events`);
  source.onmessage = (event) => {
    try {
      onEvent(JSON.parse(event.data) as Order);
    } catch {
      /* 忽略心跳等非 JSON 消息 */
    }
  };
  return () => source.close();
}
