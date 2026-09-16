/**
 * contracts/api-contract.md 의 응답 타입.
 *
 * 계약이 바뀌면 여기부터 고친다 — 타입이 어긋나면 빌드가 먼저 깨진다.
 * 계약 §0: **모든 값은 문자열이다.** 숫자·날짜도 문자열로 온다
 * (앞자리 0 보존, 부동소수 오차 방지). 그래서 number 를 쓰지 않는다.
 */

export interface ApiError {
  error: { code: string; message: string };
}

// ── §1 거래처 ────────────────────────────────────────────────────────
export interface Customer {
  code: string;
  name: string;
  customer_no: string;
  file_types: string[];
}

// ── §3 필드 정의 ─────────────────────────────────────────────────────
export interface FieldSpec {
  name: string;
  label: string;
  sheet?: string;
  type?: string;
  max_len?: number;
}

// ── §2 규칙 카드 ─────────────────────────────────────────────────────
export interface FixedValue {
  field: string;
  label: string;
  value: string;
  note?: string;
}

/** `kind` 는 아이콘을 고르는 데만 쓴다. 거래처별 분기를 프론트에 넣지 않는다. */
export type RuleKind = "table" | "csv_map" | "value_map" | "keyword_map" | "lookup" | string;

export interface RuleCard {
  id: string;
  kind: RuleKind;
  label: string;
  note?: string;
  columns: string[];
  rows: string[][];
}

export interface Preview {
  code: string;
  name: string;
  customer_no: string;
  fixed: FixedValue[];
  rules: RuleCard[];
  split: { by: string; label: string };
  todos: { field: string; label: string; note: string }[];
  footer: string;
}

// ── §4·§5 배치 ───────────────────────────────────────────────────────
export type BatchStatus =
  | "PARSING" | "NEEDS_REVIEW" | "READY" | "SENDING" | "SENT" | "SEND_FAILED";

export interface BatchFile {
  file_id: string;
  name: string;
  status: string;
  error?: string;
  row_count?: number;
}

export type Severity = "error" | "warn";

export interface Issue {
  field: string;
  severity: Severity;
  code: string;
  message: string;
}

export interface Row {
  row_id: string;
  _file_id: string;
  _file: string;
  _group: string;
  _line_no: string | number;
  _deleted?: boolean;
  fields: Record<string, string>;
  issues: Issue[];
  edited: string[];
}

export interface GridHints {
  pinned: string[];
  hidden: string[];
  width: Record<string, number>;
}

export interface Summary {
  row_count: string;
  total_qty: string;
  error_count: string;
  warn_count: string;
}

export interface Batch {
  batch_id: string;
  customer: string;
  status: BatchStatus;
  files: BatchFile[];
  columns: string[];
  grid: GridHints;
  rows: Row[];
  summary: Summary;
}

// ── §6 재검증 ────────────────────────────────────────────────────────
/** 값은 프론트가 주인이다. 서버는 issues/edited 만 돌려준다. */
export interface ValidateResult {
  status: BatchStatus;
  rows: { row_id: string; issues: Issue[]; edited: string[] }[];
  summary: Summary;
}

/** 누락은 삭제가 아니다 — 삭제는 `deleted: true` 명시뿐 (계약 §6.1). */
export interface RowEdit {
  row_id: string;
  fields?: Record<string, string>;
  deleted?: boolean;
}

// ── §7 전송 ──────────────────────────────────────────────────────────
export interface SendResult {
  status: "SENT" | "SEND_FAILED";
  sent_rows: number | string;
  sent_at?: string;
  attempts?: number;
  resend?: boolean;
  message: string;
}

// ── §8 헬스 ──────────────────────────────────────────────────────────
export interface Health {
  status: string;
  masters: { ok: boolean; detail: string };
  llm: { ok: boolean; provider: string; detail: string };
  eai_endpoint: string;
}

// ── §10 브랜드 콘솔 ──────────────────────────────────────────────────
export interface BrandCustomer {
  kunnr: string;
  name: string;
  sap_name: string;
  code: string;
  file_types: string[];
  brand_count: string;
  mapped_count: string;
}

export interface BrandKey {
  text: string;
  match: "contains" | "equals";
  note: string;
}

export interface BrandRow {
  zbrand: string;
  name: string;
  status: "mapped" | "unmapped";
  keys: BrandKey[];
}

export interface LogicTable {
  id: string;
  label: string;
  scope?: string;
  columns: string[];
  rows: string[][];
  on_no_match?: { action: string; message: string };
}

export interface LogicField {
  field: string;
  label: string;
  max_len?: string;
  source: string;
  explain?: string;
  todo?: string;
}

export interface BrandDetail {
  kunnr: string;
  name: string;
  sap_name: string;
  code: string;
  file_types: string[];
  owner?: string;
  configured: string;
  brands: BrandRow[];
  /** 규칙 미설정 고객이면 null — "설정 없음"과 "빈 설정"은 다르게 보여야 한다. */
  logic: {
    split: { by: string; label: string };
    tables: LogicTable[];
    rules: (LogicTable & { kind: string; source?: string; note?: string })[];
    fields: LogicField[];
    checks: { id: string; label: string; severity: string; description: string }[];
  } | null;
}
