import { useState } from "react";

import {
  createOrder,
  type AccountSource,
  type BillingMode,
  type CardSource,
  type Plan,
} from "../api/client";
import { CardFields } from "../card-payment/CardFields";

interface Props {
  onCreated: (orderId: string) => void;
}

const PLANS: Plan[] = ["plus", "pro_lite", "pro", "pro_max"];
const COUNTRIES = ["US", "JP", "PH", "GB", "TR", "BR"];

export function OrderNew({ onCreated }: Props) {
  const [plan, setPlan] = useState<Plan>("plus");
  const [country, setCountry] = useState("US");
  const [accountSource, setAccountSource] = useState<AccountSource>("customer_session");
  const [cardSource, setCardSource] = useState<CardSource>("customer");
  const [billingMode, setBillingMode] = useState<BillingMode>("standard");
  const [riskAck, setRiskAck] = useState(false);
  const [session, setSession] = useState("");
  const [pmToken, setPmToken] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const isPromo = billingMode === "promo";

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);

    if (isPromo && !riskAck) {
      setError("选择促销模式前必须勾选风险确认。");
      return;
    }
    if (accountSource === "customer_session" && !session.trim()) {
      setError("请粘贴你的 ChatGPT session。");
      return;
    }
    if (cardSource === "customer" && !pmToken) {
      setError("请先生成支付标识（卡号不会发送给后端）。");
      return;
    }

    setBusy(true);
    try {
      const order = await createOrder(
        {
          plan,
          billing_country: country,
          mode: {
            account_source: accountSource,
            card_source: cardSource,
            billing_mode: billingMode,
            risk_acknowledged: riskAck,
          },
          session: accountSource === "customer_session" ? session : undefined,
          payment_method_token: cardSource === "customer" ? pmToken ?? undefined : undefined,
        },
        crypto.randomUUID(),
      );
      setSession("");
      onCreated(order.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "提交失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit}>
      <fieldset disabled={busy}>
        <legend>账号来源</legend>
        <label>
          <input
            type="radio"
            checked={accountSource === "customer_session"}
            onChange={() => setAccountSource("customer_session")}
          />
          使用我的账号（粘贴 session）
        </label>
        <label>
          <input
            type="radio"
            checked={accountSource === "platform_account"}
            onChange={() => setAccountSource("platform_account")}
          />
          使用平台账号（开通后交付给我）
        </label>
        {accountSource === "customer_session" && (
          <textarea
            rows={3}
            placeholder="仅内存处理，不落库"
            value={session}
            onChange={(e) => setSession(e.target.value)}
          />
        )}
      </fieldset>

      <fieldset disabled={busy}>
        <legend>套餐与地区</legend>
        <select value={plan} onChange={(e) => setPlan(e.target.value as Plan)}>
          {PLANS.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
        <select value={country} onChange={(e) => setCountry(e.target.value)}>
          {COUNTRIES.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
        <small>账单国家必须与代理出口一致。</small>
      </fieldset>

      <fieldset disabled={busy}>
        <legend>支付方式</legend>
        <label>
          <input
            type="radio"
            checked={cardSource === "customer"}
            onChange={() => setCardSource("customer")}
          />
          我提供卡片
        </label>
        <label>
          <input
            type="radio"
            checked={cardSource === "platform"}
            onChange={() => setCardSource("platform")}
          />
          使用平台卡池
        </label>
        {cardSource === "customer" &&
          (pmToken ? (
            <p>
              已生成支付标识：<code>{pmToken}</code>
            </p>
          ) : (
            <CardFields onToken={setPmToken} disabled={busy} />
          ))}
      </fieldset>

      <fieldset disabled={busy}>
        <legend>计费模式</legend>
        <label>
          <input
            type="radio"
            checked={!isPromo}
            onChange={() => setBillingMode("standard")}
          />
          正价开通（默认）
        </label>
        <label>
          <input
            type="radio"
            checked={isPromo}
            onChange={() => setBillingMode("promo")}
          />
          促销模式（高风险）
        </label>
        {isPromo && (
          <label style={{ color: "#b00" }}>
            <input type="checkbox" checked={riskAck} onChange={(e) => setRiskAck(e.target.checked)} />
            我已知悉促销模式可能违反上游服务条款与支付合规要求，风险自负。
          </label>
        )}
      </fieldset>

      {error && <p role="alert" style={{ color: "#b00" }}>{error}</p>}
      <button type="submit">提交开通需求</button>
    </form>
  );
}
