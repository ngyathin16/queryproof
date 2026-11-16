import { z } from 'zod';

export const jsonObject = z.record(z.string(), z.json());
export type JsonObject = z.infer<typeof jsonObject>;
const row = z.union([jsonObject, z.array(z.json())]);
const column = z.object({ name: z.string(), type: z.string() });
export const snapshotSchema = z.object({
  id: z.string(), name: z.string().optional(),
  tables: z.record(z.string(), z.object({ columns: z.array(column), row_count: z.number() })),
});
export type Snapshot = z.infer<typeof snapshotSchema>;
export const examplesSchema = z.array(z.object({
  id: z.string(), title: z.string(), description: z.string(), sql: z.string(),
  contract: jsonObject, bundle: jsonObject,
}));
export type Example = z.infer<typeof examplesSchema>[number];
export const checkSchema = z.object({
  id: z.string(), title: z.string(), status: z.string(), explanation: z.string(),
  sql_location: z.json().optional(), contract_clause: z.json().optional(),
  diagnostic_sql: z.string().nullable().optional(), count: z.number().nullable().optional(),
  examples: z.array(row).optional().default([]), truncated: z.boolean().optional().default(false),
});
export type Check = z.infer<typeof checkSchema>;
const resultTable = z.object({ columns: z.array(z.string()), rows: z.array(row), total: z.union([z.number(), z.string(), z.null()]).optional(), row_count: z.number().optional() });
export type ResultTable = z.infer<typeof resultTable>;
export const resultSchema = z.object({
  status: z.string(), checks: z.array(checkSchema).default([]),
  original: resultTable.nullable().optional(), reference: resultTable.nullable().optional(),
  difference: jsonObject.nullable().optional(),
  proposal: z.object({ sql: z.string(), explanation: z.string() }).nullable().optional(),
  limitations: z.array(z.string()).default([]),
});
export type Result = z.infer<typeof resultSchema>;
export const runSchema = z.object({
  id: z.string(), status: z.enum(['running', 'completed', 'failed', 'interrupted']),
  snapshot_id: z.string(), contract: jsonObject, sql: z.string(), result: resultSchema.nullable().optional(),
  error: z.string().nullable().optional(), created_at: z.string(), parent_id: z.string().nullable().optional(),
});
export type Run = z.infer<typeof runSchema>;
export const providerSchema = z.object({
  model: z.string().nullable().optional(), provider: z.string().optional(),
  available: z.boolean().optional(), configured: z.boolean().optional(),
  endpoint: z.string().optional(), local: z.boolean().optional(),
}).passthrough();
export const assistanceSchema = z.object({
  status: z.string(), model: z.string().optional(), provider: z.string().optional(),
  proposal: z.union([z.string(), z.object({ sql: z.string(), explanation: z.string().optional() })]).nullable().optional(),
  sql: z.string().nullable().optional(), explanation: z.string().optional(), error: z.string().optional(),
  elapsed_seconds: z.number().optional(), usage: jsonObject.nullable().optional(),
  elapsed_ms: z.number().optional(), tokens: jsonObject.optional(), activity: z.array(z.json()).optional(),
  tool_activity: z.array(z.json()).optional(), tools: z.array(z.json()).optional(),
}).passthrough();
export type Assistance = z.infer<typeof assistanceSchema>;

export async function api<T>(path: string, schema: z.ZodType<T>, data?: unknown): Promise<T> {
  const response = await fetch(`/api${path}`, data === undefined ? undefined : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data),
  });
  const value: unknown = await response.json();
  if (!response.ok) {
    const error = z.object({ error: z.string() }).safeParse(value);
    throw new Error(error.success ? error.data.error : `Request failed (${response.status}).`);
  }
  const parsed = schema.safeParse(value);
  if (!parsed.success) throw new Error('The server returned an unexpected response. Your saved reviews have not been changed.');
  return parsed.data;
}

export function display(value: unknown): string {
  if (value === null || value === undefined) return 'Not defined';
  if (typeof value === 'string') return value;
  if (typeof value === 'number') return new Intl.NumberFormat('en', { maximumFractionDigits: 4 }).format(value);
  return JSON.stringify(value);
}

export function errorMessage(error: unknown): string { return error instanceof Error ? error.message : 'Something went wrong. Please try again.'; }

export function metricDisplay(value: unknown): string {
  if (value === null || value === undefined) return '—';
  const text = String(value);
  const decimal = /^([+-]?)(\d+)(?:\.(\d+))?$/.exec(text);
  if (!decimal) return text;
  const [, sign, whole, fractional] = decimal;
  const fraction = fractional?.replace(/0+$/, '');
  return `${sign}${whole?.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}${fraction ? `.${fraction}` : ''}`;
}
