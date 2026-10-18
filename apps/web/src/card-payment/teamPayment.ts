import type { TeamHostedContext } from "../api/client";
import type { BillingDetails } from "./CardFields";

export interface TeamCardDraft {
  number: string;
  exp_month: string;
  exp_year: string;
  cvc: string;
}

export function emptyTeamCard(): TeamCardDraft {
  return { number: "", exp_month: "", exp_year: "", cvc: "" };
}

/** Create a Stripe PaymentMethod in the browser; return only its opaque id. */
export async function createTeamPaymentMethod(
  publishableKey: string | null | undefined,
  card: TeamCardDraft,
  billing: BillingDetails,
  context?: TeamHostedContext,
): Promise<string> {
  if (!publishableKey?.startsWith("pk_")) {
    throw new Error("结账尚未取得 Stripe 公钥；请先生成结账，或打开官方长链付款。");
  }
  const number = card.number.replace(/[\s-]/g, "");
  const month = Number(card.exp_month);
  const year = card.exp_year.trim();
  if (!/^\d{12,19}$/.test(number) || !Number.isInteger(month) || month < 1 || month > 12
    || !/^(\d{2}|\d{4})$/.test(year) || !/^\d{3,4}$/.test(card.cvc)) {
    throw new Error("请检查卡号、有效期月份/年份和 CVC。");
  }
  if (!billing.name?.trim() || !billing.line1?.trim() || !billing.city?.trim()
    || !billing.country?.trim() || !billing.postal_code?.trim()) {
    throw new Error("请完整填写账单姓名、街道、城市、国家和邮编。");
  }
  const form = new URLSearchParams({
    type: "card",
    "card[number]": number,
    "card[cvc]": card.cvc,
    "card[exp_month]": String(month),
    "card[exp_year]": year.length === 2 ? `20${year}` : year,
    "billing_details[name]": billing.name.trim(),
    "billing_details[address][country]": billing.country.trim().toUpperCase(),
    "billing_details[address][line1]": billing.line1.trim(),
    "billing_details[address][city]": billing.city.trim(),
    "billing_details[address][state]": billing.state?.trim() || "",
    "billing_details[address][postal_code]": billing.postal_code.trim(),
    key: publishableKey,
    _stripe_version: context ? "2020-08-27;custom_checkout_beta=v1" : "2025-03-31.basil",
  });
  if (context) {
    if (context.customer_email) form.set("billing_details[email]", context.customer_email);
    form.set("guid", context.guid);
    form.set("muid", context.muid);
    form.set("sid", context.sid);
    form.set("client_attribution_metadata[client_session_id]", context.client_session_id);
    form.set("client_attribution_metadata[checkout_session_id]", context.session_id);
    form.set("client_attribution_metadata[checkout_config_id]", context.checkout_config_id);
    form.set("client_attribution_metadata[merchant_integration_source]", "checkout");
    form.set("client_attribution_metadata[merchant_integration_version]", "hosted_checkout");
    form.set("client_attribution_metadata[payment_method_selection_flow]", "merchant_specified");
  }
  const response = await fetch("https://api.stripe.com/v1/payment_methods", {
    method: "POST",
    credentials: "omit",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: form,
  });
  const body = (await response.json().catch(() => ({}))) as {
    id?: string;
    error?: { message?: string };
  };
  if (!response.ok || !body.id?.startsWith("pm_")) {
    // Keep PAN/CVC out of error messages and browser-local order history.
    const message = (body.error?.message || "Stripe PaymentMethod 创建失败")
      .replace(/\b\d{12,19}\b/g, "[已隐藏]")
      .split(number).join("[已隐藏]")
      .split(card.cvc).join("[已隐藏]");
    throw new Error(message);
  }
  return body.id;
}
