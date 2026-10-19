import type { BillingInput, TeamHostedContext } from "../api/client";
import type { StripeCardHandle } from "./CardFields";

/** Tokenize only through Stripe.js/Elements; this module never receives PAN/CVC. */
export async function createTeamPaymentMethod(
  handle: StripeCardHandle | null,
  billing: BillingInput,
  context: TeamHostedContext,
): Promise<string> {
  if (!handle) throw new Error("Stripe 安全输入框尚未就绪，请稍后重试。");
  const id = await handle.tokenize({ ...billing, email: context.customer_email || billing.email });
  if (!id.startsWith("pm_")) throw new Error("Team 需要 Stripe 返回的 PaymentMethod 标识。");
  return id;
}
