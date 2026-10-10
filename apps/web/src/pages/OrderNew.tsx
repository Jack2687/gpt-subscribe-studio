import { useEffect, useState } from "react";

import {
  createOrder,
  formatAmount,
  getOrder,
  isHostedOrder,
  payOrder,
  verifyOrder,
  type BillingInput,
  type Order,
  type Plan,
} from "../api/client";
import { isSettled, loadHistory, recordOrder, SUCCESS_STATUSES } from "../api/history";
import { StripeCardFields, type StripeCardHandle } from "../card-payment/CardFields";
import { HistoryList, ResultPanel } from "./ResultPanel";

const FAMILIES: { id: "plus" | "go" | "pro" | "team"; label: string; hint: string }[] = [
  { id: "plus", label: "Plus", hint: "官方 Plus" },
  { id: "go", label: "Go", hint: "官方 Go" },
  { id: "pro", label: "Pro", hint: "三档用量" },
  { id: "team", label: "Team", hint: "托管长链" },
];
const PRO_TIERS: { id: Plan; label: string; hint: string }[] = [
  { id: "pro_lite", label: "Standard", hint: "$100" },
  { id: "pro", label: "More", hint: "$200" },
  { id: "pro_max", label: "Max", hint: "$500" },
];

function isProFamily(value: Plan): boolean {
  return value === "pro_lite" || value === "pro" || value === "pro_max";
}

function familyOf(value: Plan): "plus" | "go" | "pro" | "team" {
  if (value === "go") return "go";
  if (value === "team") return "team";
  if (isProFamily(value)) return "pro";
  return "plus";
}

const SEAT_PRESETS = [2, 3, 5, 8, 10];
const REGIONS: { code: string; label: string }[] = [
  { code: "US", label: "美国" },
  { code: "PH", label: "菲律宾" },
  { code: "CL", label: "智利" },
  { code: "EG", label: "埃及" },
  { code: "JP", label: "日本" },
  { code: "GB", label: "英国" },
  { code: "TR", label: "土耳其" },
  { code: "BR", label: "巴西" },
  { code: "MX", label: "墨西哥" },
  { code: "IN", label: "印度" },
  { code: "ID", label: "印尼" },
  { code: "VN", label: "越南" },
  { code: "TH", label: "泰国" },
  { code: "MY", label: "马来西亚" },
  { code: "SG", label: "新加坡" },
  { code: "KR", label: "韩国" },
  { code: "AU", label: "澳大利亚" },
  { code: "CA", label: "加拿大" },
  { code: "DE", label: "德国" },
  { code: "NL", label: "荷兰" },
  { code: "PL", label: "波兰" },
  { code: "AR", label: "阿根廷" },
  { code: "SA", label: "沙特" },
  { code: "AE", label: "阿联酋" },
  { code: "ZA", label: "南非" },
];

export function OrderNew() {
  const [plan, setPlan] = useState<Plan>("plus");
  const [country, setCountry] = useState("");
  const [session, setSession] = useState("");
  const [seats, setSeats] = useState(5);
  const [workspace, setWorkspace] = useState("Team Workspace");
  const [promoCode, setPromoCode] = useState("");
  const [interval, setInterval] = useState<"month" | "year">("month");
  const [order, setOrder] = useState<Order | null>(null);
  const [result, setResult] = useState<Order | null>(null);
  const [history, setHistory] = useState(loadHistory);
  const [addr, setAddr] = useState<BillingInput | null>(null);
  const [card, setCard] = useState<StripeCardHandle | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const due = order ? formatAmount(order.amount, order.currency) : null;
  const hosted = order ? isHostedOrder(order) : plan === "team";

  function finish(next: Order) {
    setResult(next);
    setHistory(recordOrder(next));
  }

  function reset() {
    setOrder(null);
    setResult(null);
    setCard(null);
    setAddr(null);
    setSession("");
    setError(null);
  }

  // 支付后状态还没定（3DS、确认订阅中）时在原页面轮询，直到成功或失败。
  useEffect(() => {
    if (!result || isSettled(result.status)) return;
    const id = result.id;
    const timer = window.setInterval(async () => {
      try {
        const next = await getOrder(id);
        setResult(next);
        if (isSettled(next.status)) setHistory(recordOrder(next));
      } catch {
        /* keep polling */
      }
    }, 4000);
    return () => window.clearInterval(timer);
  }, [result]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      if (!order) {
        if (!session.trim()) {
          setError("请粘贴 ChatGPT session。");
          return;
        }
        if (!country) {
          setError("请先选择和 session 导出国家相同的地区。日本刀导出的选日本，不要选美国。");
          return;
        }
        if (plan === "team" && (!Number.isInteger(seats) || seats < 2)) {
          setError("Team 需要填写席位，最少 2 人。");
          return;
        }
        const created = await createOrder({
          plan,
          billing_country: country,
          session,
          promo_code: plan === "team" ? promoCode.trim() : "",
          workspace_name: plan === "team" ? workspace.trim() : "",
          seat_quantity: plan === "team" ? seats : undefined,
          price_interval: plan === "team" ? interval : undefined,
        });
        if (!isHostedOrder(created) && !created.publishable_key) {
          throw new Error("结账已创建，但没有拿到 Stripe 公钥，无法加载安全输入框。");
        }
        setOrder(created);
        setAddr({
          name: created.billing?.name ?? "",
          line1: created.billing?.line1 ?? "",
          city: created.billing?.city ?? "",
          state: created.billing?.state ?? "",
          postal_code: created.billing?.postal_code ?? "",
          country: created.billing?.country ?? created.billing_country,
        });
        setSession("");
        return;
      }
      if (isHostedOrder(order)) {
        const checked = await verifyOrder(order.id);
        setOrder(checked);
        if (checked.subscription?.active || SUCCESS_STATUSES.includes(checked.status)) {
          finish(checked);
        } else {
          setError(checked.last_error || "还没开通。请先打开长链完成支付，再点查询。");
        }
        return;
      }
      if (!card) {
        setError("Stripe 安全输入框还没准备好，请稍等几秒再试。");
        return;
      }
      if (!addr || !addr.name.trim() || !addr.line1.trim() || !addr.city.trim() || !addr.postal_code.trim()) {
        setError("请填写完整账单地址（姓名、街道、城市、邮编）。");
        return;
      }
      const token = await card.tokenize(addr);
      try {
        finish(await payOrder(order.id, token, addr));
      } catch (err) {
        const message = err instanceof Error ? err.message : "开通失败";
        const latest = await getOrder(order.id).catch(() => order);
        finish({ ...latest, status: isSettled(latest.status) ? latest.status : "failed", last_error: message });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "开通失败");
    } finally {
      setBusy(false);
    }
  }

  async function copyLink() {
    if (!order?.checkout_url) return;
    await navigator.clipboard.writeText(order.checkout_url);
    setError(null);
  }

  return (
    <form onSubmit={submit}>
      <fieldset disabled={busy || Boolean(order)}>
        <legend>ChatGPT session</legend>
        <textarea
          rows={4}
          placeholder={
            plan === "team"
              ? "Team 长链一般只需要 accessToken。有整段 JSON 也可以贴。只在内存使用，不写数据库。"
              : "请粘贴整段 session JSON（accessToken、sessionToken、cookies / oai-did）。Plus / Pro 页内填卡只贴 accessToken 经常不够。只在内存使用，不写数据库。"
          }
          value={session}
          onChange={(e) => setSession(e.target.value)}
        />
      </fieldset>

      <fieldset disabled={busy || Boolean(order)}>
        <legend>套餐</legend>
        <div className="plan-grid" role="radiogroup" aria-label="套餐">
          {FAMILIES.map((item) => (
            <button
              key={item.id}
              type="button"
              role="radio"
              aria-checked={familyOf(plan) === item.id}
              className="plan-btn"
              onClick={() => {
                if (item.id === "pro") {
                  setPlan(isProFamily(plan) ? plan : "pro_lite");
                  return;
                }
                setPlan(item.id);
              }}
            >
              {item.label}
              <small>{item.hint}</small>
            </button>
          ))}
        </div>
        {familyOf(plan) === "pro" && (
          <div className="plan-grid plan-tiers" role="radiogroup" aria-label="Pro 档位">
            {PRO_TIERS.map((item) => (
              <button
                key={item.id}
                type="button"
                role="radio"
                aria-checked={plan === item.id}
                className="plan-btn"
                onClick={() => setPlan(item.id)}
              >
                {item.label}
                <small>{item.hint}</small>
              </button>
            ))}
          </div>
        )}
        {familyOf(plan) === "pro" && (
          <p className="hint">Pro 三档是官方 Standard / More / Max。标的是美国价，其它地区以结账金额为准。</p>
        )}
        <label>
          地区
          <select required value={country} onChange={(e) => setCountry(e.target.value)}>
            <option value="">请选择（必须和 session 导出国家一致）</option>
            {REGIONS.map((item) => (
              <option key={item.code} value={item.code}>
                {item.label} ({item.code})
              </option>
            ))}
          </select>
        </label>
        {plan === "team" && (
          <div className="team-fields">
            <label>
              席位（最少 2 人）
              <input
                type="number"
                min={2}
                max={999}
                required
                value={seats}
                onChange={(e) => setSeats(Number(e.target.value))}
              />
            </label>
            <div className="seat-presets">
              {SEAT_PRESETS.map((count) => (
                <button
                  key={count}
                  type="button"
                  className="seat-chip"
                  aria-pressed={seats === count}
                  onClick={() => setSeats(count)}
                >
                  {count} 人
                </button>
              ))}
            </div>
            <div className="row">
              <label>
                计费周期
                <select value={interval} onChange={(e) => setInterval(e.target.value as "month" | "year")}>
                  <option value="month">按月</option>
                  <option value="year">按年</option>
                </select>
              </label>
              <label>
                空间名称
                <input value={workspace} maxLength={80} onChange={(e) => setWorkspace(e.target.value)} />
              </label>
            </div>
            <label>
              Team 优惠码（选填）
              <input
                value={promoCode}
                maxLength={80}
                placeholder="有活动码就填，没有留空"
                onChange={(e) => setPromoCode(e.target.value)}
              />
            </label>
            <p className="hint">席位会写入 ChatGPT Team 结账。金额按所选地区货币报价。</p>
          </div>
        )}
        <p className="hint">
          session 从哪国网络导出，这里就选哪国。Team 走 Stripe 托管长链；其它套餐仍在本页填卡。
        </p>
      </fieldset>

      {order && hosted ? (
        <fieldset>
          <legend>Team 托管长链</legend>
          <p className="ok">
            结账已创建（{order.billing_country}
            {order.currency ? ` · ${order.currency}` : ""}
            {order.seat_quantity ? ` · ${order.seat_quantity} 席` : ""}）。请打开长链付款，不要在本页填卡。
          </p>
          {due ? (
            <p className="amount">
              应付金额 <strong>{due}</strong>
            </p>
          ) : (
            <p className="hint">未从结账拿到金额，请以打开后的 Stripe 页面为准。</p>
          )}
          <p className="hosted-url">
            <code>{order.checkout_url}</code>
          </p>
          <div className="actions">
            <a className="btn btn-primary link-btn" href={order.checkout_url || "#"} target="_blank" rel="noreferrer">
              打开长链
            </a>
            <button type="button" className="btn btn-ghost" onClick={() => void copyLink()}>
              复制链接
            </button>
          </div>
        </fieldset>
      ) : order && !result ? (
        <fieldset disabled={busy}>
          <legend>卡片（Stripe 安全输入框）</legend>
          <p className="ok">
            结账已创建（{order.billing_country}
            {order.currency ? ` · ${order.currency}` : ""}）。下面的账单地址是自动生成的示例，用自己的真实卡请改成卡的账单地址（要和发卡行登记的一致）。
          </p>
          {addr && (
            <div className="billing-fields">
              <label>
                持卡人姓名
                <input value={addr.name} onChange={(e) => setAddr({ ...addr, name: e.target.value })} />
              </label>
              <label>
                街道地址
                <input value={addr.line1} onChange={(e) => setAddr({ ...addr, line1: e.target.value })} />
              </label>
              <div className="row">
                <label>
                  城市
                  <input value={addr.city} onChange={(e) => setAddr({ ...addr, city: e.target.value })} />
                </label>
                <label>
                  州 / 省
                  <input value={addr.state} onChange={(e) => setAddr({ ...addr, state: e.target.value })} />
                </label>
                <label>
                  邮编
                  <input
                    value={addr.postal_code}
                    onChange={(e) => setAddr({ ...addr, postal_code: e.target.value })}
                  />
                </label>
              </div>
              <p className="hint">国家固定为 {addr.country}，需和所选地区一致。</p>
            </div>
          )}
          {due ? (
            <p className="amount">
              应付金额 <strong>{due}</strong>
            </p>
          ) : (
            <p className="hint">未从结账拿到金额，支付前请以 Stripe 确认为准。</p>
          )}
          <StripeCardFields
            publishableKey={order.publishable_key || ""}
            amount={order.amount}
            currency={order.currency}
            customerSessionClientSecret={order.customer_session_client_secret}
            checkoutUrl={order.checkout_url}
            confirmReturnUrl={order.confirm_return_url}
            onReady={setCard}
          />
        </fieldset>
      ) : (
        <p className="hint">
          {plan === "team"
            ? "Team 长链由 ChatGPT 直接生成 Stripe 托管页，支付不经过本站。一般只贴 accessToken 即可。"
            : "先创建结账。成功后会加载 Stripe 官方填卡控件，卡号不会经过本站。页内填卡需要整段 session。"}
        </p>
      )}

      {result && <ResultPanel order={result} onReset={reset} />}
      {error && !result && (
        <p className="alert" role="alert">
          {error}
        </p>
      )}
      {!(result && !hosted) && (
      <div className="actions">
        <button
          type="submit"
          className="btn btn-primary"
          disabled={busy || Boolean(order && !hosted && !card)}
        >
          {busy
            ? order
              ? hosted
                ? "正在查询订阅…"
                : "正在支付…"
              : "正在创建结账…"
            : order
              ? hosted
                ? "我已支付，查询订阅"
                : `确认支付${due ? ` ${due}` : ""}`
              : plan === "team"
                ? `创建 Team 长链（${seats} 席）`
                : "创建结账"}
        </button>
      </div>
      )}
      <HistoryList items={history} />
    </form>
  );
}
