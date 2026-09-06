// frontend/src/api/client.ts
// Thin axios wrapper: attaches the JWT, exposes typed calls for every
// backend endpoint the dashboard needs.

import axios from "axios";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

export const apiClient = axios.create({ baseURL: API_BASE_URL });

let currentToken: string | null = localStorage.getItem("sentinel_token");

apiClient.interceptors.request.use((config) => {
  if (currentToken) {
    config.headers.Authorization = `Bearer ${currentToken}`;
  }
  return config;
});

export function setToken(token: string) {
  currentToken = token;
  localStorage.setItem("sentinel_token", token);
}

export function clearToken() {
  currentToken = null;
  localStorage.removeItem("sentinel_token");
}

export async function login(apiKey: string): Promise<string> {
  const resp = await apiClient.post("/auth/token", { api_key: apiKey });
  const token = resp.data.access_token as string;
  setToken(token);
  return token;
}

export interface ReturnListItem {
  order_id: string;
  merchant_id: string;
  status: string;
  risk_score: number | null;
  band: "Green" | "Yellow" | "Red" | null;
  order_value: number;
  category: string | null;
  created_at: string;
  scored_at: string | null;
}

export interface EvidencePack {
  base_value: number;
  predicted_value: number;
  contributions: Record<string, number>;
  reasons: string[];
}

export interface ReturnDetail {
  order_id: string;
  mode: "sync" | "async";
  status: string;
  risk_score: number | null;
  band: "Green" | "Yellow" | "Red" | null;
  recommended_action: string | null;
  evidence: EvidencePack | null;
}

export async function listReturns(params: {
  band?: string; category?: string; page?: number; page_size?: number;
}) {
  const resp = await apiClient.get("/returns", { params });
  return resp.data as { items: ReturnListItem[]; total: number; page: number; page_size: number };
}

export async function getReturn(orderId: string) {
  const resp = await apiClient.get(`/returns/${orderId}`);
  return resp.data as ReturnDetail;
}

export async function getMetrics() {
  const resp = await apiClient.get("/metrics");
  return resp.data;
}

export async function getThresholdCurve() {
  const resp = await apiClient.get("/simulate/threshold-curve");
  return resp.data as Array<{
    target_automation_rate: number; actual_automation_rate: number;
    loss_reduction_pct: number; green_threshold: number; red_threshold: number;
  }>;
}

export async function updateThresholds(green_threshold: number, red_threshold: number) {
  const resp = await apiClient.post("/config/thresholds", { green_threshold, red_threshold });
  return resp.data;
}

export async function recordOutcome(orderId: string, outcomeLabel: 0 | 1) {
  const resp = await apiClient.post(`/returns/${orderId}/outcome`, {
    order_id: orderId, outcome_label: outcomeLabel,
  });
  return resp.data;
}
