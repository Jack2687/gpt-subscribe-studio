import { Alert, Button, Group, Paper, Stack, Text } from "@mantine/core";
import type { ReactNode } from "react";

import type { BillingInput, Order } from "../api/client";
import { TeamCardForm, type TeamCardDraft } from "../card-payment/TeamCardForm";
import { BillingForm } from "./BillingForm";
import { TAX_FREE_STATE_LABEL } from "../card-payment/billingExamples";

interface Props {
  card: TeamCardDraft;
  onCard: (card: TeamCardDraft) => void;
  billing: BillingInput;
  onBilling: (billing: BillingInput) => void;
  order: Order | null;
  busy: boolean;
  footer?: ReactNode;
  onExample?: () => void;
  hasExample?: boolean;
}

export function TeamPaymentPanel({ card, onCard, billing, onBilling, order, busy, footer, onExample, hasExample = false }: Props) {
  return (
    <Paper withBorder p="md" radius="md" className="team-payment-panel">
      <Stack gap="sm">
        <TeamCardForm value={card} onChange={onCard} disabled={busy} />
        <div>
          <Group justify="space-between" align="center" mb="xs">
            <Text fw={600}>Team 账单地址</Text>
            {onExample && <Button type="button" size="xs" variant="light" disabled={busy} onClick={onExample}>随机示例地址</Button>}
          </Group>
          {hasExample && (
            <Alert color="blue" variant="light" mb="xs" title="已填充虚构示例">
              已按免税州〔{TAX_FREE_STATE_LABEL}〕真实城市与街道生成，可直接用于本次支付；也可自行修改。
            </Alert>
          )}
          <BillingForm value={billing} onChange={onBilling} disabled={busy} independentCountry compact />
        </div>
        {!order && (
          <Text size="sm" c="dimmed">填写卡片和账单后点击确认支付；生成结账链接时只读取金额。</Text>
        )}
        {footer}
      </Stack>
    </Paper>
  );
}
