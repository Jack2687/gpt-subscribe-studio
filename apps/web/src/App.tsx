import { OrderNew } from "./pages/OrderNew";

export function App() {
  async function logout() {
    await fetch("/logout", { method: "POST" });
    window.location.href = "/login";
  }

  return (
    <main className="page">
      <header className="hero">
        <div className="topbar">
          <h1>直卡协议</h1>
          <button type="button" className="btn btn-ghost" onClick={() => void logout()}>
            退出
          </button>
        </div>
        <p>
          Plus / Pro 在本页填卡，建议粘贴整段 session JSON。Team 走托管长链，通常只贴 accessToken 就能出链；可填席位、优惠码和地区货币。卡号不经过本站服务器。
        </p>
      </header>
      <div className="card">
        <OrderNew />
      </div>
      <footer>
        <p>pay.example.com · 独立小工具，不依赖其它项目</p>
      </footer>
    </main>
  );
}
