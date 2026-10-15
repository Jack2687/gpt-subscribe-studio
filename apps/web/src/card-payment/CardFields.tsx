/**
 * Stripe Payment Element：卡号只在 iframe 里，浏览器直接产出 ctoken_，不进本站。
 */

import { Alert, Text } from "@mantine/core";
import { useEffect, useRef, useState } from "react";

export type BillingDetails = {
  name?: string;
  line1?: string;
  city?: string;
  state?: string;
  postal_code?: string;
  country?: string;
};

export type StripeCardHandle = {
  tokenize: (billing: BillingDetails) => Promise<string>;
};

type Props = {
  publishableKey: string;
  amount?: string | null;
  currency?: string | null;
  customerSessionClientSecret?: string | null;
  checkoutUrl?: string | null;
  confirmReturnUrl?: string | null;
  onReady: (handle: StripeCardHandle | null) => void;
};

const ZERO_DECIMAL = new Set([
  "BIF",
  "CLP",
  "DJF",
  "GNF",
  "JPY",
  "KMF",
  "KRW",
  "MGA",
  "PYG",
  "RWF",
  "UGX",
  "VND",
  "VUV",
  "XAF",
  "XOF",
  "XPF",
]);

export function StripeCardFields({
  publishableKey,
  amount,
  currency,
  customerSessionClientSecret,
  checkoutUrl,
  confirmReturnUrl,
  onReady,
}: Props) {
  const onReadyRef = useRef(onReady);
  onReadyRef.current = onReady;
  const [hint, setHint] = useState("正在加载 Stripe 安全输入框…");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let paymentEl: { mount: (selector: string) => void; unmount: () => void } | null = null;

    async function mount() {
      try {
        await loadStripe();
        if (cancelled) return;
        if (!window.Stripe) throw new Error("Stripe.js 不可用");
        const stripe = window.Stripe(publishableKey);
        if (cancelled) return;
        const currencyCode = (currency || "usd").toLowerCase();
        const options: Record<string, unknown> = {
          mode: "subscription",
          currency: currencyCode,
          amount: Math.max(1, toMinor(amount, currencyCode)),
          setupFutureUsage: "off_session",
          paymentMethodTypes: ["card", "link"],
          allowedPaymentMethodTypes: ["card", "link"],
          appearance: {
            theme: "stripe",
            variables: {
              borderRadius: "8px",
              colorPrimary: "#4c6ef5",
              fontFamily: 'ui-sans-serif, system-ui, -apple-system, "PingFang SC", sans-serif',
            },
          },
        };
        if (customerSessionClientSecret) {
          options.customerSessionClientSecret = customerSessionClientSecret;
        }
        const elements = createElements(stripe, options);
        paymentEl = elements.create("payment", {
          layout: "tabs",
          wallets: { applePay: "never", googlePay: "never" },
        });
        paymentEl.mount("#dcp-payment");
        setHint("卡片由 Stripe 托管输入，不会发到本站。");
        onReadyRef.current({
          tokenize: async (billing: BillingDetails) => {
            const submitted = await elements.submit();
            if (submitted?.error) {
              throw new Error(submitted.error.message || "请检查卡片信息");
            }
            if (typeof stripe.createConfirmationToken !== "function") {
              throw new Error("当前 Stripe.js 不支持 confirmation token，请刷新页面重试");
            }
            const result = await stripe.createConfirmationToken({
              elements,
              params: {
                payment_method_data: {
                  billing_details: {
                    name: billing.name,
                    address: {
                      line1: billing.line1,
                      city: billing.city,
                      state: billing.state,
                      postal_code: billing.postal_code,
                      country: billing.country,
                    },
                  },
                },
                return_url: verifyUrl(confirmReturnUrl, checkoutUrl),
              },
            });
            if (result.error || !result.confirmationToken?.id) {
              throw new Error(result.error?.message ?? "生成支付确认失败");
            }
            return result.confirmationToken.id;
          },
        });
      } catch (err) {
        if (cancelled) return;
        const message = err instanceof Error ? err.message : "Stripe 输入框加载失败";
        setHint("");
        setError(message);
        onReadyRef.current(null);
      }
    }

    void mount();
    return () => {
      cancelled = true;
      onReadyRef.current(null);
      paymentEl?.unmount();
    };
  }, [publishableKey, amount, currency, customerSessionClientSecret, checkoutUrl, confirmReturnUrl]);

  return (
    <>
      <div id="dcp-payment" />
      {hint && !error && (
        <Text size="xs" c="dimmed" mt="xs">
          {hint}
        </Text>
      )}
      {error && (
        <Alert color="red" variant="light" mt="xs" role="alert">
          {error}
        </Alert>
      )}
    </>
  );
}

type StripeElements = {
  create: (type: string, options?: unknown) => { mount: (selector: string) => void; unmount: () => void };
  submit: () => Promise<{ error?: { message?: string } }>;
};

declare global {
  interface Window {
    Stripe?: (key: string) => {
      elements: (options?: unknown) => StripeElements;
      createConfirmationToken?: (data: unknown) => Promise<{
        confirmationToken?: { id: string };
        error?: { message?: string };
      }>;
    };
  }
}

function createElements(
  stripe: { elements: (options?: unknown) => StripeElements },
  options: Record<string, unknown>,
): StripeElements {
  const attempts: Record<string, unknown>[] = [options];
  if (options.customerSessionClientSecret) {
    const withoutCustomer = { ...options };
    delete withoutCustomer.customerSessionClientSecret;
    attempts.push(withoutCustomer);
  }
  if (options.allowedPaymentMethodTypes) {
    const withoutAllowed = { ...options };
    delete withoutAllowed.allowedPaymentMethodTypes;
    attempts.push(withoutAllowed);
  }
  let lastError: unknown;
  for (const attempt of attempts) {
    try {
      return stripe.elements(attempt);
    } catch (err) {
      lastError = err;
    }
  }
  throw lastError instanceof Error ? lastError : new Error("Stripe 输入框初始化失败");
}

function toMinor(amount: string | null | undefined, currency: string): number {
  const value = Number(amount);
  if (!Number.isFinite(value) || value <= 0) return 0;
  if (ZERO_DECIMAL.has(currency.toUpperCase())) return Math.round(value);
  return Math.round(value * 100);
}

function verifyUrl(confirmReturnUrl?: string | null, checkoutUrl?: string | null): string {
  if (String(confirmReturnUrl || "").startsWith("https://chatgpt.com/checkout/verify")) {
    return String(confirmReturnUrl);
  }
  const parts = String(checkoutUrl || "").split("/").filter(Boolean);
  const id = (parts[parts.length - 1] || "").split("?")[0];
  const processor = parts.includes("checkout") ? parts[parts.indexOf("checkout") + 1] || "" : "";
  if (id.startsWith("oaics_") || id.startsWith("cs_")) {
    const query = [`stripe_session_id=${id}`];
    if (processor && processor !== "verify") query.push(`processor_entity=${processor}`);
    query.push("source=chatgpt_web_merged");
    return `https://chatgpt.com/checkout/verify?${query.join("&")}`;
  }
  return "https://chatgpt.com/";
}

function bodyHasStripeVersion(body: unknown): boolean {
  if (typeof body === "string") return body.includes("_stripe_version");
  if (body instanceof URLSearchParams) return body.has("_stripe_version") || body.toString().includes("_stripe_version");
  return false;
}

function avoidDualStripeVersion(): void {
  const g = window as unknown as { __dcpStripeVersionPatched?: boolean };
  if (g.__dcpStripeVersionPatched) return;
  g.__dcpStripeVersionPatched = true;
  const origFetch = window.fetch.bind(window);
  window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
    const url = input instanceof Request ? input.url : String(input);
    if (url.includes("api.stripe.com") && bodyHasStripeVersion(init?.body)) {
      const headers = new Headers(init?.headers);
      headers.delete("Stripe-Version");
      init = { ...init, headers };
    }
    return origFetch(input, init);
  };
  const proto = XMLHttpRequest.prototype;
  const origOpen = proto.open;
  const origSet = proto.setRequestHeader;
  const origSend = proto.send;
  proto.open = function (this: XMLHttpRequest, method: string, url: string | URL, async?: boolean, username?: string | null, password?: string | null) {
    (this as XMLHttpRequest & { __dcpUrl?: string }).__dcpUrl = String(url);
    return origOpen.call(this, method, url, async ?? true, username, password);
  };
  proto.setRequestHeader = function (this: XMLHttpRequest, name: string, value: string) {
    if (name.toLowerCase() === "stripe-version") {
      (this as XMLHttpRequest & { __dcpVer?: string }).__dcpVer = value;
      return;
    }
    return origSet.call(this, name, value);
  };
  proto.send = function (this: XMLHttpRequest, body?: Document | XMLHttpRequestBodyInit | null) {
    const extra = this as XMLHttpRequest & { __dcpUrl?: string; __dcpVer?: string };
    const text = typeof body === "string" ? body : "";
    const dual = String(extra.__dcpUrl || "").includes("api.stripe.com") && text.includes("_stripe_version");
    if (extra.__dcpVer && !dual) origSet.call(this, "Stripe-Version", extra.__dcpVer);
    return origSend.call(this, body as XMLHttpRequestBodyInit);
  };
}

function loadStripe(): Promise<void> {
  avoidDualStripeVersion();
  if (window.Stripe) return Promise.resolve();
  return loadScript("https://js.stripe.com/basil/stripe.js").catch(() =>
    loadScript("https://js.stripe.com/v3/"),
  );
}

function loadScript(src: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const existing = document.querySelector(`script[data-dcp-stripe="${src}"]`);
    if (existing) {
      existing.addEventListener("load", () => resolve());
      existing.addEventListener("error", () => reject(new Error("Stripe.js 加载失败")));
      return;
    }
    const script = document.createElement("script");
    script.src = src;
    script.async = true;
    script.dataset.dcpStripe = src;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("Stripe.js 加载失败"));
    document.head.appendChild(script);
  });
}
