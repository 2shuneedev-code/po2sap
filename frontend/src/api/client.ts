/**
 * API 호출 한 곳. 계약 §0 의 오류 형태를 여기서만 푼다.
 *
 * 화면은 `ApiFailure.message` 를 그대로 띄우면 된다 — 서버가 한국어로 준다.
 */

import type {
  Batch, BrandCustomer, BrandDetail, BrandKey, Customer, FieldSpec,
  Health, Preview, RowEdit, SendResult, ValidateResult,
} from "./types";

export class ApiFailure extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "ApiFailure";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, init);
  } catch {
    throw new ApiFailure(0, "NETWORK", "서버에 연결하지 못했습니다. 백엔드가 떠 있는지 확인하세요.");
  }

  if (!res.ok) {
    let code = "ERROR";
    let message = `요청이 실패했습니다 (HTTP ${res.status})`;
    try {
      const body = await res.json();
      if (body?.error) {
        code = String(body.error.code ?? code);
        message = String(body.error.message ?? message);
      }
    } catch {
      /* 본문이 JSON 이 아니면 기본 메시지로 둔다 */
    }
    throw new ApiFailure(res.status, code, message);
  }

  return (await res.json()) as T;
}

function json(body: unknown): RequestInit {
  return {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

export const api = {
  // ── 마스터 ──────────────────────────────────────────────────────
  health: () => request<Health>("/api/health"),
  customers: () => request<Customer[]>("/api/masters/customers"),
  fields: () => request<{ fields: FieldSpec[] }>("/api/masters/fields"),
  preview: (code: string) =>
    request<Preview>(`/api/masters/customers/${encodeURIComponent(code)}/preview`),

  // ── 배치 ────────────────────────────────────────────────────────
  upload: (customer: string, files: File[]) => {
    const form = new FormData();
    form.append("customer", customer);
    for (const f of files) form.append("files", f);
    return request<Batch>("/api/batches", { method: "POST", body: form });
  },
  batch: (id: string) => request<Batch>(`/api/batches/${encodeURIComponent(id)}`),
  validate: (id: string, rows: RowEdit[]) =>
    request<ValidateResult>(`/api/batches/${encodeURIComponent(id)}/validate`, json({ rows })),
  send: (id: string, rows: RowEdit[]) =>
    request<SendResult>(`/api/batches/${encodeURIComponent(id)}/send`, json({ rows })),

  // ── 브랜드 콘솔 ─────────────────────────────────────────────────
  brandCustomers: (params: { q?: string; filter?: string; limit?: number }) => {
    const qs = new URLSearchParams();
    if (params.q) qs.set("q", params.q);
    if (params.filter) qs.set("filter", params.filter);
    qs.set("limit", String(params.limit ?? 200));
    return request<{ total: string; customers: BrandCustomer[] }>(
      `/api/brands/customers?${qs}`,
    );
  },
  brandDetail: (kunnr: string) =>
    request<BrandDetail>(`/api/brands/customers/${encodeURIComponent(kunnr)}`),
  saveBrandKeys: (kunnr: string, zbrand: string, keys: BrandKey[]) =>
    request<BrandRowSaved>(
      `/api/brands/customers/${encodeURIComponent(kunnr)}/${encodeURIComponent(zbrand)}`,
      { ...json({ keys }), method: "PUT" },
    ),
};

export interface BrandRowSaved {
  kunnr: string;
  zbrand: string;
  status: "mapped" | "unmapped";
  keys: BrandKey[];
}
