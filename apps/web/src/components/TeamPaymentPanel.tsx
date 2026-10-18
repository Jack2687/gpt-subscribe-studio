import { Alert, Paper, Stack, Text } from "@mantine/core";
import type { ReactNode } from "react";

import type { BillingInput, Order } from "../api/client";
import { TeamCardForm } from "../card-payment/TeamCardForm";
import type { TeamCardDraft } from "../card-payment/teamPayment";
import { BillingForm } from "./BillingForm";

interface Props {
  card: TeamCardDraft;
  onCard: (card: TeamCardDraft) => void;
  billing: BillingInput;
  onBilling: (billing: BillingInput) => void;
  order: Order | null;
  busy: boolean;
  footer?: ReactNode;
}

export function TeamPaymentPanel({ card, onCard, billing, onBilling, order, busy, footer }: Props) {
  return (
    <Paper withBorder p="md" radius="md" className="team-payment-panel">
      <Stack gap="sm">
        <TeamCardForm value={card} onChange={onCard} disabled={busy} />
        <div>
          <Text fw={600} mb="xs">Team 账单地址</Text>
          <BillingForm value={billing} onChange={onBilling} disabled={busy} independentCountry compact />
        </div>
        {!order && (
          <Text size="sm" c="dimmed">先生成结账链接，再确认支付；填写内容会保留。</Text>
        )}
        {order && !order.publishable_key && (
          <Alert color="yellow" title="尚未取得 Stripe 公钥">
            卡片表单已保留，本次结账请使用下面的官方长链完成付款；不会发送卡片字段。
          </Alert>
        )}
        {footer}
      </Stack>
    </Paper>
  );
}
