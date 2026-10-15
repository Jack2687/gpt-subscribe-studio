import { SimpleGrid, Stack, Text, TextInput } from "@mantine/core";

import type { BillingInput } from "../api/client";

interface Props {
  value: BillingInput;
  onChange: (value: BillingInput) => void;
  disabled?: boolean;
}

export function BillingForm({ value, onChange, disabled }: Props) {
  const set = (key: keyof BillingInput) => (event: React.ChangeEvent<HTMLInputElement>) =>
    onChange({ ...value, [key]: event.currentTarget.value });
  return (
    <Stack gap="sm">
      <Text size="sm" c="dimmed">
        下面是自动生成的示例地址。用自己的真实卡时，请改成发卡行登记的账单地址。
      </Text>
      <TextInput label="持卡人姓名" value={value.name} onChange={set("name")} disabled={disabled} />
      <TextInput label="街道地址" value={value.line1} onChange={set("line1")} disabled={disabled} />
      <SimpleGrid cols={{ base: 1, sm: 3 }}>
        <TextInput label="城市" value={value.city} onChange={set("city")} disabled={disabled} />
        <TextInput label="州 / 省" value={value.state} onChange={set("state")} disabled={disabled} />
        <TextInput label="邮编" value={value.postal_code} onChange={set("postal_code")} disabled={disabled} />
      </SimpleGrid>
      <TextInput
        label="国家"
        description="需和所选地区一致"
        value={value.country}
        readOnly
        disabled
      />
    </Stack>
  );
}
