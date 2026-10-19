import { Alert, Button, Checkbox, Group, Paper, Stack, Text } from "@mantine/core";
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
  exampleConfirmed?: boolean;
  onExampleConfirmed?: (confirmed: boolean) => void;
}

export function TeamPaymentPanel({ card, onCard, billing, onBilling, order, busy, footer, onExample, hasExample = false, exampleConfirmed = false, onExampleConfirmed }: Props) {
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
              免税州〔{TAX_FREE_STATE_LABEL}〕真实城市与街道，门牌号随机；请核对或替换为你的实际账单地址。
            </Alert>
          )}
          <BillingForm value={billing} onChange={onBilling} disabled={busy} independentCountry compact />
          {hasExample && <Checkbox mt="sm" disabled={busy} checked={exampleConfirmed}
            onChange={(e) => onExampleConfirmed?.(e.currentTarget.checked)}
            label="已替换示例并确认是实际账单地址" />}
        </div>
        {!order && (
          <Text size="sm" c="dimmed">填写卡片和账单后点击确认支付；生成结账链接时只读取金额。</Text>
        )}
        {footer}
      </Stack>
    </Paper>
  );
}
