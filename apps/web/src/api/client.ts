export type Plan = "plus" | "pro_lite" | "pro" | "pro_max" | "team";

export interface Order {
  id: string;
  status: string;
  plan: string;
  billing_country: string;
  checkout_url?: string | null;
  publishable_key?: string | null;
  customer_session_client_secret?: string | null;
  amount?: string | null;
  currency?: string | null;
  billing?: {
    name?: string;
    line1?: string;
    city?: string;
    state?: string;
    postal_code?: string;
    country?: string;
  } | null;
  last_error?: string | null;
  next_action?: { type?: string; url?: string } | null;
  subscription?: { active: boolean; expires_at?: string | null; channel?: string | null } | null;
  checkout_kind?: string | null;
  seat_quantity?: number | null;
  workspace_name?: string | null;
  promo_code?: string | null;
  price_interval?: string | null;
}

const jsonHeaders = { "Content-Type": "application/json" };

async function readError(res: Response): Promise<string> {
  const detail = await res.json().catch(() => ({}));
  return detail?.detail?.message ?? detail?.detail ?? `请求失败（${res.status}）`;
}

export async function createOrder(input: {
  plan: Plan;
  billing_country: string;
  session: string;
  promo_code?: string;
  workspace_name?: string;
  seat_quantity?: number;
  price_interval?: "month" | "year";
}): Promise<Order> {
  const res = await fetch("/api/orders", {
    method: "POST",
    headers: { ...jsonHeaders, "Idempotency-Key": crypto.randomUUID() },
    body: JSON.stringify({
      plan: input.plan,
      billing_country: input.billing_country,
      session: input.session,
      promo_code: input.promo_code || "",
      workspace_name: input.workspace_name || "",
      seat_quantity: input.seat_quantity,
      price_interval: input.price_interval || "month",
      mode: {
        account_source: "customer_session",
        card_source: "customer",
        billing_mode: "standard",
        risk_acknowledged: false,
      },
    }),
  });
  if (!res.ok) throw new Error(await readError(res));
  return (await res.json()) as Order;
}

export async function payOrder(orderId: string, paymentMethodToken: string): Promise<Order> {
  const res = await fetch(`/api/orders/${orderId}/pay`, {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify({ payment_method_token: paymentMethodToken }),
  });
  if (!res.ok) throw new Error(await readError(res));
  return (await res.json()) as Order;
}

export async function verifyOrder(orderId: string): Promise<Order> {
  const res = await fetch(`/api/orders/${orderId}/verify`, { method: "POST" });
  if (!res.ok) throw new Error(await readError(res));
  return (await res.json()) as Order;
}

const ZERO_DECIMAL = new Set(["BIF", "CLP", "DJF", "GNF", "JPY", "KMF", "KRW", "MGA", "PYG", "RWF", "UGX", "VND", "VUV", "XAF", "XOF", "XPF"]);

export function formatAmount(amount?: string | null, currency?: string | null): string | null {
  if (amount == null || amount === "") return null;
  const value = Number(amount);
  const code = (currency || "").trim().toUpperCase();
  if (!Number.isFinite(value)) return [amount, code].filter(Boolean).join(" ");
  if (code) {
    try {
      return new Intl.NumberFormat("en", {
        style: "currency",
        currency: code,
        minimumFractionDigits: ZERO_DECIMAL.has(code) ? 0 : 2,
        maximumFractionDigits: ZERO_DECIMAL.has(code) ? 0 : 2,
      }).format(value);
    } catch {
      /* unknown currency code */
    }
  }
  return code ? `${amount} ${code}` : amount;
}

export async function getOrder(orderId: string): Promise<Order> {
  const res = await fetch(`/api/orders/${orderId}`);
  if (!res.ok) throw new Error(await readError(res));
  return (await res.json()) as Order;
}

export function isHostedOrder(order: Pick<Order, "plan" | "checkout_kind">): boolean {
  return order.checkout_kind === "hosted" || order.plan === "team";
}
