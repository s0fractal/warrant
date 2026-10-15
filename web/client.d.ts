export type StoreFiles = Record<string, string>;
export interface VerificationReport {
  report: "warrant.verify-report@v0";
  grade: "base" | "settlement";
  ok: boolean;
  records: number;
  errors: number;
  warnings: number;
  findings: { level: "ERR" | "WARN"; subject: string; message: string }[];
}
export const LIMITS: Readonly<{
  bytes: number;
  files: number;
  timeout: number;
}>;
export function toHex(bytes: Uint8Array): string;
export function fromHex(hex: string): Uint8Array;
export function normalizePath(path: string): string | null;
export function validateFiles(files: StoreFiles): void;
export function identifyRecord(hex: string): Promise<string>;
export function callVerifier(
  operation: "verify",
  files: StoreFiles,
  options?: { trust?: string; signal?: AbortSignal },
): Promise<{
  report: VerificationReport;
  checks: {
    check: string;
    filedVerdict: string;
    verdict?: string;
    result?: string;
    atp_spent?: number;
    error?: string;
  }[];
}>;
