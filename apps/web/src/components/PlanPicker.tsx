import {
  Chip,
  Group,
  NumberInput,
  Radio,
  Select,
  SegmentedControl,
  SimpleGrid,
  Stack,
  Text,
  TextInput,
  Paper,
} from "@mantine/core";

import type { Plan } from "../api/client";
import { FAMILIES, PRO_TIERS, REGIONS, SEAT_PRESETS, familyOf, isProFamily } from "../plans";

export interface TeamValues {
  seats: number;
  workspace: string;
  promoCode: string;
  interval: "month" | "year";
}

interface Props {
  plan: Plan;
  onPlan: (plan: Plan) => void;
  country: string;
  onCountry: (country: string) => void;
  team: TeamValues;
  onTeam: (team: TeamValues) => void;
  disabled?: boolean;
  compact?: boolean;
}

export function PlanPicker({ plan, onPlan, country, onCountry, team, onTeam, disabled, compact = false }: Props) {
  const family = familyOf(plan);

  function pickFamily(id: string) {
    if (id === "pro") {
      onPlan(isProFamily(plan) ? plan : "pro_lite");
      return;
    }
    onPlan(id as Plan);
  }

  return (
    <Stack gap={compact ? "sm" : "md"}>
      <Radio.Group label="套餐" value={family} onChange={pickFamily}>
        <SimpleGrid cols={{ base: 2, sm: 4 }} spacing="xs" mt="xs">
          {FAMILIES.map((item) => (
            <Radio.Card key={item.id} value={item.id} radius="md" p="sm" disabled={disabled}>
              <Group wrap="nowrap" align="flex-start" gap="xs">
                <Radio.Indicator />
                <div>
                  <Text fw={600} size="sm" lh={1.2}>
                    {item.label}
                  </Text>
                  <Text size="xs" c="dimmed">
                    {item.hint}
                  </Text>
                </div>
              </Group>
            </Radio.Card>
          ))}
        </SimpleGrid>
      </Radio.Group>

      {family === "pro" && (
        <div>
          <SegmentedControl
            fullWidth
            value={plan}
            onChange={(value) => onPlan(value as Plan)}
            disabled={disabled}
            data={PRO_TIERS.map((item) => ({
              value: item.id,
              label: `${item.label} · ${item.hint}`,
            }))}
          />
          <Text size="xs" c="dimmed" mt={6}>
            Pro 三档是官方 Standard / More / Max。标的是美国价，其它地区以结账金额为准。
          </Text>
        </div>
      )}

      <Select
        label={family === "team" ? "创建结账地区" : "地区"}
        description={family === "team"
          ? "决定结账币种；可选择埃及（EG / EGP），支付账单国家单独填写。"
          : "用于创建结账并对齐出口代理。"}
        placeholder="请选择"
        searchable
        withAsterisk
        data={REGIONS.map((item) => ({ value: item.code, label: `${item.label} (${item.code})` }))}
        value={country || null}
        onChange={(value) => onCountry(value ?? "")}
        disabled={disabled}
      />

      {family === "team" && (
        <Paper withBorder p={compact ? "sm" : "md"} radius="md">
          <Stack gap="sm">
            <NumberInput
              label="席位（最少 2 人）"
              min={2}
              max={999}
              allowDecimal={false}
              clampBehavior="strict"
              value={team.seats}
              onChange={(value) => onTeam({ ...team, seats: typeof value === "number" ? value : 2 })}
              disabled={disabled}
            />
            <Chip.Group
              multiple={false}
              value={String(team.seats)}
              onChange={(value) => onTeam({ ...team, seats: Number(value) })}
            >
              <Group gap={6}>
                {SEAT_PRESETS.map((count) => (
                  <Chip key={count} value={String(count)} size="xs" disabled={disabled}>
                    {count} 人
                  </Chip>
                ))}
              </Group>
            </Chip.Group>
            <SimpleGrid cols={{ base: 1, sm: 2 }}>
              <div>
                <Text size="sm" fw={500} mb={4}>
                  计费周期
                </Text>
                <SegmentedControl
                  fullWidth
                  value={team.interval}
                  onChange={(value) => onTeam({ ...team, interval: value as "month" | "year" })}
                  disabled={disabled}
                  data={[
                    { value: "month", label: "按月" },
                    { value: "year", label: "按年" },
                  ]}
                />
              </div>
              <TextInput
                label="空间名称"
                maxLength={80}
                value={team.workspace}
                onChange={(event) => onTeam({ ...team, workspace: event.currentTarget.value })}
                disabled={disabled}
              />
            </SimpleGrid>
            <TextInput
              label="Team 优惠码（选填）"
              placeholder="有活动码就填，没有留空"
              maxLength={80}
              value={team.promoCode}
              onChange={(event) => onTeam({ ...team, promoCode: event.currentTarget.value })}
              disabled={disabled}
            />
            <Text size="xs" c="dimmed">
              席位会写入 ChatGPT Team 结账，实际金额以长链页面为准。
            </Text>
          </Stack>
        </Paper>
      )}
    </Stack>
  );
}
