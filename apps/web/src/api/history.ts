import type { Order } from "./client";

export interface HistoryRecord {
  id: string;
  plan: string;
  country: string;
  amount?: string | null;
  currency?: string | null;
  status: string;
  error?: string | null;
  at: number;
}

const KEY = "dcp.history.v1";
const MAX = 50;

export const SUCCESS_STATUSES = ["delivered", "active"];
export const FAILED_STATUSES = ["failed", "rejected"];

export function isSettled(status: string): boolean {
  return SUCCESS_STATUSES.includes(status) || FAILED_STATUSES.includes(status);
}

export function loadHistory(): HistoryRecord[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(KEY) || "[]");
    return Array.isArray(parsed) ? (parsed as HistoryRecord[]) : [];
  } catch {
    return [];
  }
}

export function recordOrder(order: Order): HistoryRecord[] {
  const next: HistoryRecord = {
    id: order.id,
    plan: order.plan,
    country: order.billing_country,
    amount: order.amount,
    currency: order.currency,
    status: order.status,
    error: order.last_error,
    at: Date.now(),
  };
  const list = [next, ...loadHistory().filter((item) => item.id !== order.id)].slice(0, MAX);
  try {
    localStorage.setItem(KEY, JSON.stringify(list));
  } catch {
    /* storage unavailable: records stay in memory only */
  }
  return list;
}
