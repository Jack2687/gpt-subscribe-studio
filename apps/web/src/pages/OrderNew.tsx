import { Alert, Button, Code, CopyButton, Group, Paper, Stack, Stepper, Text } from "@mantine/core";
import { IconAlertCircle, IconCheck, IconCopy, IconExternalLink } from "@tabler/icons-react";
import { useEffect, useState } from "react";

import {
  createOrder,
  getOrder,
  isHostedOrder,
  payOrder,
  verifyOrder,
  type BillingInput,
  type Order,
  type Plan,
} from "../api/client";
import { SUCCESS_STATUSES, isSettled } from "../api/history";
import { BillingForm } from "../components/BillingForm";
import { OrderSummary } from "../components/OrderSummary";
import { PlanPicker, type TeamValues } from "../components/PlanPicker";
import { ResultPanel } from "../components/ResultPanel";
import { SessionField } from "../components/SessionField";
import { StripeCardFields, type StripeCardHandle } from "../card-payment/CardFields";

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
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const hosted = order ? isHostedOrder(order) : plan === "team";
  const step = result ? 2 : order ? 1 : 0;

  function finish(next: Order) {
    setResult(next);
    onRecord(next);
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
        if (isSettled(next.status)) onRecord(next);
      } catch {
        /* keep polling */
      }
    }, 4000);
    return () => window.clearInterval(timer);
  }, [result, onRecord]);

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
          setError("请先选择和 session 导出国家相同的地区。");
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
          workspace_name: plan === "team" ? team.workspace.trim() : "",
          seat_quantity: plan === "team" ? team.seats : undefined,
          price_interval: plan === "team" ? team.interval : undefined,
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

  return (
    <form onSubmit={submit}>
      <div className="order-layout">
        <Paper withBorder p="lg" radius="md">
          <Stepper active={step} size="sm" mb="lg" allowNextStepsSelect={false}>
            <Stepper.Step label="配置订单" description="session、套餐、地区" />
            <Stepper.Step label={hosted ? "长链支付" : "填卡支付"} description={hosted ? "打开链接付款" : "地址与卡片"} />
            <Stepper.Step label="结果" description="成功或失败" />
          </Stepper>

          {step === 0 && (
            <Stack gap="lg">
              <SessionField value={session} onChange={setSession} team={plan === "team"} disabled={busy} />
              <PlanPicker
                plan={plan}
                onPlan={setPlan}
                country={country}
                onCountry={setCountry}
                team={team}
                onTeam={setTeam}
                disabled={busy}
              />
              <Text size="xs" c="dimmed">
                session 从哪国网络导出，这里就选哪国。session 只在内存中使用，不写数据库；卡号由 Stripe 输入框处理，不经过本站。
              </Text>
            </Stack>
          )}

          {step === 1 && order && hosted && (
            <Stack gap="md">
              <Alert color="green" variant="light" icon={<IconCheck size={18} />} title="结账已创建">
                请打开长链付款，不要在本页填卡。付完回到这里点「我已支付，查询订阅」。
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
              </Group>
            </Stack>
          )}

          {step === 1 && order && !hosted && addr && (
            <Stack gap="lg">
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
                  onReady={setCard}
                />
              </div>
            </Stack>
          )}

          {step === 2 && result && <ResultPanel order={result} onReset={reset} />}

          {error && step < 2 && (
            <Alert mt="md" color="red" variant="light" icon={<IconAlertCircle size={18} />} role="alert">
              {error}
            </Alert>
          )}

          {step < 2 && (
            <Group mt="lg" justify="flex-end">
              <Button
                type="submit"
                size="md"
                loading={busy}
                disabled={Boolean(order && !hosted && !card)}
              >
                {!order
                  ? plan === "team"
                    ? `创建 Team 长链（${team.seats} 席）`
                    : "创建结账"
                  : hosted
                    ? "我已支付，查询订阅"
                    : "确认支付"}
              </Button>
            </Group>
          )}
        </Paper>

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
