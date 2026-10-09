/**
 * 浏览器端卡支付组件（宪法第 I 条的核心边界）。
 *
 * 铁律：**卡号 / 有效期 / CVV 只在浏览器内存在**，绝不 POST 到本平台后端。
 * 组件最终产出一个**不透明** `payment_method_token`，只有它会被发送给后端。
 *
 * 骨架阶段用本地状态演示边界；接入真实支付方式时，把 `tokenize()` 换上游/PSP 的
 * 托管字段组件（如 Stripe Elements），本组件以外的代码无需改动。
 */

import { useState } from "react";

export interface CardFieldsProps {
  /** 只回传不透明标识，不回传任何卡字段。 */
  onToken: (paymentMethodToken: string) => void;
  disabled?: boolean;
}

async function tokenize(cardNumber: string, expiry: string, cvv: string): Promise<string> {
  // TODO(tasks.md T029): 替换为真实 PSP / 上游支付 SDK 的 tokenization。
  // 这里只做长度校验并返回一个**假 token**，确保卡字段不会离开浏览器。
  if (cardNumber.replace(/\s/g, "").length < 12 || !expiry || cvv.length < 3) {
    throw new Error("请检查卡号 / 有效期 / CVV");
  }
  const fake = `pm_${Math.random().toString(36).slice(2, 10)}`;
  return fake;
}

export function CardFields({ onToken, disabled }: CardFieldsProps) {
  const [cardNumber, setCardNumber] = useState("");
  const [expiry, setExpiry] = useState("");
  const [cvv, setCvv] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function handleTokenize() {
    setBusy(true);
    setError(null);
    try {
      const token = await tokenize(cardNumber, expiry, cvv);
      // 关键：清空本地卡字段，只把 token 交给上层。
      setCardNumber("");
      setExpiry("");
      setCvv("");
      onToken(token);
    } catch (err) {
      setError(err instanceof Error ? err.message : "tokenization 失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <fieldset disabled={disabled || busy}>
      <legend>支付卡片（敏感字段不出浏览器）</legend>
      <label>
        卡号
        <input
          inputMode="numeric"
          autoComplete="off"
          value={cardNumber}
          onChange={(e) => setCardNumber(e.target.value)}
          placeholder="4242 4242 4242 4242"
        />
      </label>
      <label>
        有效期
        <input value={expiry} onChange={(e) => setExpiry(e.target.value)} placeholder="MM/YY" />
      </label>
      <label>
        CVV
        <input value={cvv} onChange={(e) => setCvv(e.target.value)} placeholder="123" />
      </label>
      {error && <p role="alert">{error}</p>}
      <button type="button" onClick={handleTokenize}>
        生成支付标识（不发送卡号）
      </button>
    </fieldset>
  );
}
