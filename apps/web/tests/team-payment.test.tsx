import assert from "node:assert/strict";
import test from "node:test";
import { MantineProvider } from "@mantine/core";
import { renderToStaticMarkup } from "react-dom/server";

import { pollTeam, type Order, type TeamHostedContext } from "../src/api/client";
import { loadHistory, normalizeHistoryError } from "../src/api/history";
import { hostedCaptcha } from "../src/card-payment/hostedCaptcha";
import { TeamPaymentPanel } from "../src/components/TeamPaymentPanel";
import { PlanPicker } from "../src/components/PlanPicker";
import { OrderSummary } from "../src/components/OrderSummary";
import { createTeamPaymentMethod, emptyTeamCard } from "../src/card-payment/teamPayment";

const billing = { name: "", line1: "", city: "", state: "", postal_code: "", country: "US" };
const blankOrder: Order = {
  id: "order_fixture", plan: "team", billing_country: "EG", status: "awaiting_payment",
  checkout_url: "https://example.invalid/team", publishable_key: null,
};
function panel(order: Order | null) {
  return renderToStaticMarkup(
    <MantineProvider><TeamPaymentPanel card={emptyTeamCard()} onCard={() => {}}
      billing={billing} onBilling={() => {}} order={order} busy={false} /></MantineProvider>,
  );
}

test("Team card fields render before a checkout exists", () => {
  const html = panel(null);
  for (const label of ["卡号", "到期月份", "到期年份", "CVC", "Team 账单地址"]) assert.ok(html.includes(label));
  assert.ok(html.includes('data-testid="team-card-form"'));
  assert.ok(html.includes("先生成结账链接"));
});

test("Team card fields remain visible when a hosted checkout has no Stripe key", () => {
  const html = panel(blankOrder);
  assert.ok(html.includes('data-testid="team-card-form"'));
  assert.ok(html.includes("尚未取得 Stripe 公钥"));
});

test("Team panel still displays fields after checkout with a Stripe key", () => {
  const html = panel({ ...blankOrder, publishable_key: "pk_test_fixture" });
  assert.ok(html.includes('data-testid="team-card-number"'));
  assert.ok(!html.includes("尚未取得 Stripe 公钥"));
});

test("Missing Stripe key is reported before sending a request", async () => {
  await assert.rejects(createTeamPaymentMethod(null, emptyTeamCard(), billing), /Stripe 公钥/);
});

test("Team card data goes only to Stripe; only pm_ is returned", async () => {
  // Synthetic runtime-generated fixture, not a stored payment credential.
  const card = { number: `${"4"}${"2".repeat(15)}`, exp_month: "12", exp_year: "40", cvc: "123" };
  const original = globalThis.fetch;
  const calls: { url: string; init?: RequestInit }[] = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), init });
    return new Response(JSON.stringify({ id: "pm_fixture" }), { status: 200 });
  };
  try {
    const id = await createTeamPaymentMethod("pk_test_fixture", card,
      { name: "Test", line1: "Fixture Street", city: "Fixture City", state: "OR", postal_code: "00000", country: "US" });
    assert.equal(id, "pm_fixture");
    assert.equal(calls.length, 1);
    assert.equal(calls[0].url, "https://api.stripe.com/v1/payment_methods");
    assert.equal(calls[0].init?.credentials, "omit");
    const form = calls[0].init?.body as URLSearchParams;
    assert.equal(form.get("card[number]"), card.number);
    assert.equal(form.get("card[exp_year]"), "2040");
    assert.equal(form.get("billing_details[address][country]"), "US");
  } finally { globalThis.fetch = original; }
});


test("Team creation region and billing country have separate labels", () => {
  const html = panel({ ...blankOrder, currency: "EGP" });
  assert.ok(html.includes("支付账单国家"));
  assert.ok(html.includes("独立于创建结账地区"));
  assert.ok(!html.includes("需和所选地区一致"));
  const pricing = renderToStaticMarkup(<MantineProvider><PlanPicker plan="team" country="EG"
    onPlan={() => {}} onCountry={() => {}} team={{ seats: 2, workspace: "Fixture", promoCode: "", interval: "month" }}
    onTeam={() => {}} /></MantineProvider>);
  assert.ok(pricing.includes("创建结账地区"));
  assert.ok(pricing.includes("EG / EGP"));
  assert.ok(!pricing.includes("必须和 session 导出国家一致"));
  const summary = renderToStaticMarkup(<MantineProvider><OrderSummary plan="team" country="EG"
    order={{ ...blankOrder, currency: "EGP" }} seats={2} /></MantineProvider>);
  assert.ok(summary.includes("创建结账地区"));
});


test("Prepared Hosted context supplies version, device and checkout attribution", async () => {
  const card = { number: `${"4"}${"2".repeat(15)}`, exp_month: "12", exp_year: "40", cvc: "123" };
  const ctx: TeamHostedContext = { context_id: "context_fixture", session_id: "cs_test_fixture", publishable_key: "pk_test_fixture",
    eid: "NA", amount_minor: 115000, currency: "egp", checkout_config_id: "config_updated", elements_session_id: "elements_fixture",
    client_session_id: "client_fixture", guid: "guid_fixture", muid: "muid_fixture", sid: "sid_fixture", customer_email: "fixture@example.invalid" };
  const original = globalThis.fetch;
  let body: URLSearchParams | undefined;
  globalThis.fetch = async (_, init) => {
    body = init?.body as URLSearchParams;
    return new Response(JSON.stringify({ id: "pm_fixture" }), { status: 200 });
  };
  try {
    await createTeamPaymentMethod("pk_test_fixture", card,
      { name: "Fixture", line1: "Fixture Street", city: "Fixture", state: "OR", country: "US", postal_code: "00000" }, ctx);
    assert.equal(body?.get("_stripe_version"), "2020-08-27;custom_checkout_beta=v1");
    assert.equal(body?.get("guid"), ctx.guid);
    assert.equal(body?.get("client_attribution_metadata[client_session_id]"), ctx.client_session_id);
    assert.equal(body?.get("client_attribution_metadata[checkout_config_id]"), ctx.checkout_config_id);
    assert.equal(body?.get("client_attribution_metadata[merchant_integration_version]"), "hosted_checkout");
    assert.equal(body?.get("billing_details[email]"), "fixture@example.invalid");
  } finally { globalThis.fetch = original; }
});

test("Live captcha widget executes with current site key and rqdata and is removed", async () => {
  const originalWindow = globalThis.window;
  const originalDocument = globalThis.document;
  const events: unknown[] = [];
  const container = { remove: () => events.push("container_removed") };
  Object.assign(globalThis, {
    window: { hcaptcha: {
      render: (_, options) => { events.push(options); return "widget_fixture"; },
      execute: async (_, options) => { events.push(options); return { response: "fresh_fixture_token" }; },
      remove: () => events.push("widget_removed"),
    } },
    document: { createElement: () => container, body: { appendChild: () => {} } },
  });
  try {
    const token = await hostedCaptcha({ passive_captcha: { site_key: "site_fixture", rqdata: "current_rqdata" } } as TeamHostedContext);
    assert.equal(token, "fresh_fixture_token");
    assert.deepEqual(events[0], { sitekey: "site_fixture", size: "invisible" });
    assert.deepEqual(events[1], { async: true, rqdata: "current_rqdata" });
    assert.deepEqual(events.slice(2), ["widget_removed", "container_removed"]);
  } finally { Object.assign(globalThis, { window: originalWindow, document: originalDocument }); }
});

test("Team polling uses read-only Hosted state route and never resubmits a card", async () => {
  const original = globalThis.fetch;
  const calls: string[] = [];
  globalThis.fetch = async (url, init) => { calls.push(String(url)); assert.equal(init?.body, undefined);
    return new Response(JSON.stringify({ ...blankOrder, status: "delivered" }), { status: 200 }); };
  try { assert.equal((await pollTeam("fixture")).status, "delivered"); assert.deepEqual(calls, ["/api/orders/fixture/team/poll"]); }
  finally { globalThis.fetch = original; }
});


test("Legacy blocked history drops unsupported region/card advice but preserves record data", () => {
  const old = "ChatGPT 未批准这次支付（blocked）。不是发卡行拒卡，是账号/地区风控。账单国家必须和 session 导出国家一致。";
  const expected = "ChatGPT 未批准本次结账（blocked），上游未提供明确原因。尚未确认扣款，请先核对账单。";
  assert.equal(normalizeHistoryError(old), expected);
  assert.ok(normalizeHistoryError(`risk_blocked。${old}`)?.includes("上游信息：risk_blocked"));
  assert.equal(normalizeHistoryError("card_declined: insufficient_funds"), "card_declined: insufficient_funds");
  const original = globalThis.localStorage;
  const record = { id: "old_fixture", plan: "pro_lite", country: "PH", status: "failed", at: 123, error: old };
  const values = new Map([["gss.history.v1", JSON.stringify([record])]]);
  Object.assign(globalThis, { localStorage: { getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value) } });
  try {
    assert.deepEqual(loadHistory(), [{ ...record, error: expected }]);
    assert.equal(JSON.parse(values.get("gss.history.v1"))[0].error, expected);
  } finally { Object.assign(globalThis, { localStorage: original }); }
});
