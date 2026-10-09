import { useState } from "react";

import { OrderNew } from "./pages/OrderNew";

/**
 * 骨架版单页应用：未选订单时显示下单表单，创建后显示订单号。
 * 正式版会接入路由与订单详情/SSE（tasks.md T022、T033）。
 */
export function App() {
  const [orderId, setOrderId] = useState<string | null>(null);

  return (
    <main style={{ maxWidth: 720, margin: "0 auto", padding: 24, fontFamily: "system-ui" }}>
      <h1>直卡协议 · 订阅代开控制台</h1>
      <p style={{ color: "#666" }}>
        本地自托管 · 凭证零持久化 · 卡敏感字段不出浏览器
      </p>

      {orderId ? (
        <section>
          <h2>订单已创建</h2>
          <p>
            订单号：<code>{orderId}</code>
          </p>
          <button type="button" onClick={() => setOrderId(null)}>
            再下一单
          </button>
        </section>
      ) : (
        <OrderNew onCreated={setOrderId} />
      )}
    </main>
  );
}
