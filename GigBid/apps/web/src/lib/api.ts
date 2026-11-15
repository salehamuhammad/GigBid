"use client";
/** Typed API client generated from FastAPI's OpenAPI schema (`make gen-api`). No hand-written fetch types. */
import createClient, { type Middleware } from "openapi-fetch";
import type { components, paths } from "./api/schema";

export type S = components["schemas"];
const KEY = "gigbid_token";

export const auth = {
  get: () => (typeof window === "undefined" ? null : window.localStorage.getItem(KEY)),
  set: (t: string) => window.localStorage.setItem(KEY, t),
  clear: () => window.localStorage.removeItem(KEY),
};

export const newTraceId = () => "tr-" + crypto.randomUUID().replace(/-/g, "").slice(0, 20);

const mw: Middleware = {
  async onRequest({ request }) {
    const t = auth.get();
    if (t) request.headers.set("Authorization", `Bearer ${t}`);
    // one trace id per user action: UI -> API -> graph -> MCP servers -> audit log
    request.headers.set("X-Trace-Id", newTraceId());
    return request;
  },
  async onResponse({ response }) {
    if (response.status === 401 && typeof window !== "undefined" && !window.location.pathname.startsWith("/signin")) {
      auth.clear();
      window.location.href = "/signin";
    }
    return response;
  },
};

export const api = createClient<paths>({ baseUrl: "" });
api.use(mw);

export function errorText(e: unknown): string {
  if (!e) return "Something went wrong";
  if (typeof e === "string") return e;
  const d = (e as { detail?: unknown }).detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((x: { msg?: string; loc?: string[] }) => `${(x.loc || []).slice(-1)[0] ?? ""}: ${x.msg}`).join("; ");
  return "Something went wrong";
}
