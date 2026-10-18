import { Alert, Anchor, Button, Code, CopyButton, Group, Paper, Select, Stack, Stepper, Text } from "@mantine/core";
import { IconAlertCircle, IconCheck, IconCopy, IconExternalLink } from "@tabler/icons-react";
import { useEffect, useRef, useState } from "react";

import {
  createOrder,
  checkPromoEligibility,
  getOrder,
  isHostedOrder,
  payOrder,
  prepareTeam,
  pollTeam,
  verifyOrder,
  type BillingInput,
  type Order,
  type Plan,
  type PromoEligibility,
} from "../api/client";
import { SUCCESS_STATUSES, isSettled } from "../api/history";
import { subscribeOrderUpdates, type OrderUpdateEvent } from "../api/events";
import { BillingForm } from "../components/BillingForm";
import { OrderSummary } from "../components/OrderSummary";
import { PlanPicker, type TeamValues } from "../components/PlanPicker";
import { ResultPanel } from "../components/ResultPanel";
import { SessionField } from "../components/SessionField";
import { StripeCardFields, loadStripe, type StripeCardHandle } from "../card-payment/CardFields";
import { TeamPaymentPanel } from "../components/TeamPaymentPanel";
import { hostedCaptcha } from "../card-payment/hostedCaptcha";
import { createTeamPaymentMethod, emptyTeamCard } from "../card-payment/teamPayment";

interface Props {
  onRecord: (order: Order) => void;
}

export function OrderNew({ onRecord }: Props) {
  const [plan, setPlan] = useState<Plan>("plus");
  const [country, setCountry] = useState("");
  const [session, setSession] = useState("");
  const [team, setTeam] = useState<TeamValues>({
    seats: 5,
    workspace: "Team Workspace",
    promoCode: "",
    interval: "month",
  });
  const [order, setOrder] = useState<Order | null>(null);
  const [result, setResult] = useState<Order | null>(null);
  const [addr, setAddr] = useState<BillingInput | null>(null);
  const [card, setCard] = useState<StripeCardHandle | null>(null);
  const [teamCard, setTeamCard] = useState(emptyTeamCard);
  const [teamBilling, setTeamBilling] = useState<BillingInput>({
    name: "", line1: "", city: "", state: "", postal_code: "", country: "US",
  });
  const [error, setError] = useState<string | null>(null);
  const [promo, setPromo] = useState<PromoEligibility | null>(null);
  const [promoCampaignId, setPromoCampaignId] = useState("");
  const [promoBusy, setPromoBusy] = useState(false);
  const [promoError, setPromoError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const hosted = order ? isHostedOrder(order) : plan === "team";
  const teamOrder = (order?.plan ?? plan) === "team";
  // Team 托管结账只要拿到 Stripe 公钥，就能和 Plus 一样站内填卡支付；
  // 没有公钥才退回「打开长链手动付款」。
  const linkOnly = Boolean(order && hosted && !order.publishable_key);
  const step = result ? 2 : order ? 1 : 0;

  function finish(next: Order) {
    setResult(next);
    onRecord(next);
  }

  function reset() {
    setOrder(null);
    setResult(null);
    setCard(null);
    setTeamCard(emptyTeamCard());
    setTeamBilling({ name: "", line1: "", city: "", state: "", postal_code: "", country: "US" });
    setAddr(null);
    setSession("");
    setError(null);
    setPromo(null);
    setPromoCampaignId("");
    setPromoError(null);
  }

  // 用 SSE 实时订阅订单状态，替代轮询
  useEffect(() => {
    if (!result || isSettled(result.status)) return;
    
    const id = result.id;
    console.log(`[订单 ${id}] 开始 SSE 订阅`);
    
    const unsubscribe = subscribeOrderUpdates(id, async (event: OrderUpdateEvent) => {
      console.log(`[订单 ${id}] SSE 更新:`, event);
      
      // 收到状态更新后，重新获取完整订单数据
      try {
        const next = await getOrder(id);
        setResult(next);
        if (isSettled(next.status)) {
          onRecord(next);
          console.log(`[订单 ${id}] 已结算，停止订阅`);
        }
      } catch (err) {
        console.error(`[订单 ${id}] 获取最新状态失败:`, err);
      }
    });
    
    return () => {
      console.log(`[订单 ${id}] 取消 SSE 订阅`);
      unsubscribe();
    };
  }, [result, onRecord]);

  // 3DS2（use_stripe_sdk）没有跳转链接：用 PaymentIntent 的 client_secret 让 Stripe.js 弹出验证窗口，
  // 验证结束后反复查询订阅状态，直到生效或超时。
  const handledSecret = useRef("");
  useEffect(() => {
    const secret = result?.next_action?.client_secret;
    if (!result || result.status !== "requires_action" || !secret || !result.publishable_key) return;
    if (handledSecret.current === secret) return;
    handledSecret.current = secret;
    const id = result.id;
    const key = result.publishable_key;
    void (async () => {
      try {
        await loadStripe(result.plan === "team" ? "v3" : "basil");
        if (!window.Stripe) throw new Error("Stripe.js 不可用");
        const stripe = window.Stripe(key);
        if (!stripe.handleNextAction) throw new Error("Stripe.js 未提供验证方法，请打开官方结账页完成验证");
        const outcome = await stripe.handleNextAction({ clientSecret: secret });
        if (outcome?.error) throw new Error(outcome.error.message || "3DS 验证失败");
        // 3DS 验证通过即视为扣款成功：直接按已支付交付，订阅查询只作附带信息。
        const paid = outcome?.paymentIntent?.status === "succeeded";
        const hostedTeam = result.plan === "team";
        let latest = hostedTeam ? await pollTeam(id) : await verifyOrder(id, paid);
        for (let i = 0; i < 10 && !isSettled(latest.status) && (hostedTeam || !paid) && !latest.subscription?.active; i += 1) {
          setResult(latest);
          await new Promise((resolve) => window.setTimeout(resolve, 3000));
          latest = hostedTeam ? await pollTeam(id) : await verifyOrder(id);
        }
        setResult(latest);
        if (isSettled(latest.status)) onRecord(latest);
      } catch (err) {
        handledSecret.current = "";
        const message = err instanceof Error ? err.message : "3DS 验证失败";
        // Keep the same secret marked as handled; retry requires a new action, not a render loop.
        handledSecret.current = secret;
        setResult((prev) => (prev ? { ...prev, last_error: `${message}；可打开官方结账页完成验证后查询。` } : prev));
      }
    })();
  }, [result, onRecord]);

  // 支付已提交但订阅还没确认（verifying）：自动重查，避免页面一直转圈。
  const verifyingId = result && result.plan !== "team" && result.status === "verifying" ? result.id : "";
  useEffect(() => {
    if (!verifyingId) return;
    let stopped = false;
    void (async () => {
      for (let i = 0; i < 15 && !stopped; i += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 4000));
        if (stopped) return;
        try {
          const latest = await verifyOrder(verifyingId);
          if (stopped) return;
          setResult(latest);
          if (isSettled(latest.status)) {
            onRecord(latest);
            return;
          }
        } catch {
          /* keep retrying */
        }
      }
    })();
    return () => {
      stopped = true;
    };
  }, [verifyingId, onRecord]);

  const teamPendingId = result?.plan === "team" && ["paying", "requires_action", "unknown", "verifying"].includes(result.status) ? result.id : "";
  useEffect(() => {
    if (!teamPendingId) return;
    let stopped = false;
    let timer: number | undefined;
    const update = async () => {
      try {
        const latest = await pollTeam(teamPendingId);
        if (stopped) return;
        setResult(latest);
        if (isSettled(latest.status)) { onRecord(latest); return; }
      } catch { /* The confirm is never replayed after a poll failure. */ }
      if (!stopped) timer = window.setTimeout(update, 4000);
    };
    timer = window.setTimeout(update, 4000);
    return () => { stopped = true; window.clearTimeout(timer); };
  }, [teamPendingId, onRecord]);

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
          setError("请先选择创建结账的地区。");
          return;
        }
        if (plan === "team" && (!Number.isInteger(team.seats) || team.seats < 2)) {
          setError("Team 需要填写席位，最少 2 人。");
          return;
        }
        const created = await createOrder({
          plan,
          billing_country: country,
          session,
          promo_code: plan === "team" ? team.promoCode.trim() : "",
          promo_campaign_id: plan === "plus" ? promoCampaignId : "",
          workspace_name: plan === "team" ? team.workspace.trim() : "",
          seat_quantity: plan === "team" ? team.seats : undefined,
          price_interval: plan === "team" ? team.interval : undefined,
        });
        if (!created.publishable_key && !isHostedOrder(created)) {
          throw new Error("结账已创建，但没有拿到 Stripe 公钥，无法加载安全输入框。");
        }
        setOrder(created);
        if (plan !== "team") {
          setAddr({
            name: created.billing?.name ?? "",
            line1: created.billing?.line1 ?? "",
            city: created.billing?.city ?? "",
            state: created.billing?.state ?? "",
            postal_code: created.billing?.postal_code ?? "",
            country: created.billing?.country ?? created.billing_country,
          });
        }
        setSession("");
        return;
      }
      if (linkOnly) {
        const checked = await verifyOrder(order.id);
        setOrder(checked);
        if (checked.subscription?.active || SUCCESS_STATUSES.includes(checked.status)) {
          finish(checked);
        } else {
          setError(checked.last_error || "还没开通。请先打开长链完成支付，再点查询。");
        }
        return;
      }
      if (!teamOrder && !card) {
        setError("Stripe 安全输入框还没准备好，请稍等几秒再试。");
        return;
      }
      const billing = teamOrder ? teamBilling : addr;
      if (!billing || !billing.name.trim() || !billing.line1.trim() || !billing.city.trim() || !billing.postal_code.trim()) {
        setError("请填写完整账单地址（姓名、街道、城市、邮编）。");
        return;
      }
      if (teamOrder && billing.country === "US" && !billing.state.trim()) {
        setError("请填写账单地址的州。");
        return;
      }
      let teamConfirm;
      let token: string;
      if (teamOrder) {
        const prepared = await prepareTeam(order.id, billing);
        setOrder(prepared.order);
        token = await createTeamPaymentMethod(prepared.context.publishable_key, teamCard, billing, prepared.context);
        const captcha = await hostedCaptcha(prepared.context);
        teamConfirm = { team_context_id: prepared.context.context_id, passive_captcha_token: captcha || undefined };
        setTeamCard(emptyTeamCard());
      } else {
        token = await card!.tokenize(billing);
      }
      try {
        finish(await payOrder(order.id, token, billing, teamConfirm));
      } catch (err) {
        const message = err instanceof Error ? err.message : "开通失败";
        const latest = await getOrder(order.id).catch(() => order);
        finish({ ...latest, status: isSettled(latest.status) ? latest.status : "unknown", last_error: message });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "开通失败");
    } finally {
      setBusy(false);
    }
  }

  const errorAlert = error && step < 2 ? (
    <Alert mt="md" color="red" variant="light" icon={<IconAlertCircle size={18} />} role="alert">
      {error}
    </Alert>
  ) : null;
  const primaryAction = step < 2 ? (
    <Group mt={teamOrder ? "xs" : "md"} justify="flex-end">
      <Button type="submit" size="md" loading={busy}
        disabled={Boolean(order && !linkOnly && !teamOrder && !card)} fullWidth={teamOrder}>
        {!order
          ? plan === "team" ? `生成 Team 结账链接（${team.seats} 席）` : "创建结账"
          : linkOnly ? "我已支付，查询订阅" : "确认支付"}
      </Button>
    </Group>
  ) : null;
  const showTeamPayment = teamOrder && step < 2;

  return (
    <form onSubmit={submit}>
      <div className={`order-layout${showTeamPayment ? " order-layout--team" : ""}`}>
        <Paper className="order-main" withBorder p="lg" radius="md">
          <Stepper active={step} size="sm" mb="lg" allowNextStepsSelect={false}>
            <Stepper.Step label="配置订单" description="session、套餐、地区" />
            <Stepper.Step label={linkOnly ? "长链支付" : "填卡支付"} description={linkOnly ? "打开链接付款" : "地址与卡片"} />
            <Stepper.Step label="结果" description="成功或失败" />
          </Stepper>

          {step === 0 && (
            <Stack gap={teamOrder ? "md" : "lg"}>
              <SessionField value={session} onChange={setSession} team={plan === "team"} disabled={busy} />
              <PlanPicker
                compact={teamOrder}
                plan={plan}
                onPlan={(next) => {
                  setPlan(next);
                  if (next === "team" && !country) setCountry("EG");
                  if (next !== "team") setTeamCard(emptyTeamCard());
                  if (next !== "plus") {
                    setPromo(null);
                    setPromoCampaignId("");
                    setPromoError(null);
                  }
                }}
                country={country}
                onCountry={setCountry}
                team={team}
                onTeam={setTeam}
                disabled={busy}
              />
              {plan === "plus" && (
                <Paper withBorder p="md" radius="md">
                  <Stack gap="sm">
                    <Group justify="space-between" align="center">
                      <Text fw={600}>Plus 优惠资格</Text>
                      <Button
                        type="button"
                        variant="light"
                        size="xs"
                        loading={promoBusy}
                        disabled={busy || !session.trim()}
                        onClick={async () => {
                          setPromoBusy(true);
                          setPromoError(null);
                          try {
                            const result = await checkPromoEligibility(session.trim());
                            setPromo(result);
                            const firstPlus = result.campaigns.find((item) => item.key === "plus");
                            setPromoCampaignId(firstPlus?.campaign_id ?? "");
                          } catch (err) {
                            setPromo(null);
                            setPromoCampaignId("");
                            setPromoError(err instanceof Error ? err.message : "优惠资格查询失败");
                          } finally {
                            setPromoBusy(false);
                          }
                        }}
                      >
                        检测资格
                      </Button>
                    </Group>
                    {promoError && <Alert color="red">{promoError}</Alert>}
                    {promo?.plus_eligible && promo.campaigns.some((item) => item.key === "plus") && (
                      <Select
                        label="选择活动"
                        description="创建结账时会提交上游返回的 campaign id。"
                        value={promoCampaignId || null}
                        onChange={(value) => setPromoCampaignId(value ?? "")}
                        data={promo.campaigns
                          .filter((item) => item.key === "plus")
                          .map((item) => ({
                            value: item.campaign_id,
                            label: `${item.discount_percentage ?? 0}% off · ${item.duration_num_periods ?? "?"} ${item.duration_period ?? "month"} · ${item.title ?? item.campaign_id}`,
                          }))}
                      />
                    )}
                    {promo && (!promo.plus_eligible || !promo.campaigns.some((item) => item.key === "plus")) && (
                      <Text size="sm" c="dimmed">当前账号没有 Plus 活动资格，将按正价结账。</Text>
                    )}
                    {!promo && !promoError && (
                      <Text size="xs" c="dimmed">检测会通过服务端配置的代理读取账号活动；不会创建结账。</Text>
                    )}
                  </Stack>
                </Paper>
              )}
              <Text size="xs" c="dimmed">
                结账地区由上面选的地区决定，出口代理会自动对齐；session 不要求从同一国家导出（系统会在结账前自动刷新对齐）。session 只在内存中使用，不写数据库；卡号由 Stripe 输入框处理，不经过本站。
              </Text>
            </Stack>
          )}

          {step === 1 && order && hosted && (
            <Stack gap="md">
              <Alert color="green" variant="light" icon={<IconCheck size={18} />} title="结账已创建">
                Team 官方付款链接已生成，可打开页面完成付款。金额、折扣和税费以官方结账页为准，付款后回到本页查询订阅。
              </Alert>
              <Code block style={{ wordBreak: "break-all", whiteSpace: "pre-wrap" }}>
                {order.checkout_url}
              </Code>
              <Group>
                <Button
                  component="a"
                  href={order.checkout_url || "#"}
                  target="_blank"
                  rel="noreferrer"
                  leftSection={<IconExternalLink size={16} />}
                  variant="light"
                >
                  打开长链
                </Button>
                <CopyButton value={order.checkout_url ?? ""}>
                  {({ copied, copy }) => (
                    <Button
                      variant="default"
                      onClick={copy}
                      leftSection={copied ? <IconCheck size={16} /> : <IconCopy size={16} />}
                    >
                      {copied ? "已复制" : "复制链接"}
                    </Button>
                  )}
                </CopyButton>
                {!linkOnly && (
                  <Button type="button" variant="default" loading={busy} onClick={async () => {
                    setBusy(true);
                    setError(null);
                    try {
                      const checked = await verifyOrder(order.id);
                      setOrder(checked);
                      if (checked.subscription?.active || SUCCESS_STATUSES.includes(checked.status)) finish(checked);
                      else setError(checked.last_error || "订阅尚未生效，请稍后再查询。");
                    } catch (err) {
                      setError(err instanceof Error ? err.message : "查询订阅失败");
                    } finally {
                      setBusy(false);
                    }
                  }}>
                    我已支付，查询订阅
                  </Button>
                )}
              </Group>
            </Stack>
          )}

          {step === 1 && order && !teamOrder && !linkOnly && addr && (
            <Stack gap="lg">
              {hosted && (
                <Alert color="blue" variant="light">
                  Team 托管结账已就绪：直接在下面填卡即可完成支付。如站内支付被拒，也可以
                  <Anchor href={order.checkout_url || "#"} target="_blank" rel="noreferrer">
                    打开长链
                  </Anchor>
                  手动付款，付完回本页点「我已支付，查询订阅」。
                </Alert>
              )}
              <Text fw={600}>账单地址</Text>
              <BillingForm value={addr} onChange={setAddr} disabled={busy} />
              <div>
                <Text fw={600} mb="xs">
                  卡片
                </Text>
                <StripeCardFields
                  publishableKey={order.publishable_key || ""}
                  amount={order.amount}
                  currency={order.currency}
                  customerSessionClientSecret={order.customer_session_client_secret}
                  checkoutUrl={order.checkout_url}
                  confirmReturnUrl={order.confirm_return_url}
                  requireSaveChoice={Boolean(order.promo_campaign_id)}
                  onReady={setCard}
                />
              </div>
            </Stack>
          )}

          {step === 2 && result && <ResultPanel order={result} onReset={reset} />}

          {!showTeamPayment && errorAlert}
          {!showTeamPayment && primaryAction}
        </Paper>

        {showTeamPayment && (
          <div className="order-payment">
            <TeamPaymentPanel card={teamCard} onCard={setTeamCard}
              billing={teamBilling} onBilling={setTeamBilling} order={order} busy={busy}
              footer={<>{errorAlert}{primaryAction}</>} />
          </div>
        )}

        <div className="order-side">
          <OrderSummary plan={plan} country={country} order={order} seats={team.seats} />
          {order && step < 2 && (
            <Text size="xs" c="dimmed" mt="xs">
              想改套餐或地区？刷新页面重新开始。
            </Text>
          )}
        </div>
      </div>
    </form>
  );
}
