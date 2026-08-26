const csrfToken = (): string => document.cookie.split("; ").find((item) => item.startsWith("csrftoken="))?.split("=")[1] ?? "";

function flattenErrorMessage(value: unknown): string[] {
  if (typeof value === "string") return [value];
  if (Array.isArray(value)) return value.flatMap(flattenErrorMessage);
  if (value && typeof value === "object") {
    return Object.entries(value as Record<string, unknown>).flatMap(([field, detail]) =>
      flattenErrorMessage(detail).map((message) => `${field}: ${message}`)
    );
  }
  return [];
}

function payloadMessage(payload: unknown, fallback: string): string {
  if (payload && typeof payload === "object") {
    const wrapped = payload as { error?: { message?: string } };
    if (wrapped.error?.message) return wrapped.error.message;
    const flattened = flattenErrorMessage(payload).filter(Boolean);
    if (flattened.length) return flattened.join("；");
  }
  return fallback;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) { super(message); this.status = status; }
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.method && !["GET", "HEAD"].includes(options.method)) headers.set("X-CSRFToken", csrfToken());
  const response = await fetch(`/api/v1${path}`, { credentials: "same-origin", ...options, headers });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new ApiError(response.status, payloadMessage(payload, "请求失败"));
  return (payload?.data ?? payload) as T;
}

export async function downloadApiFile(path: string): Promise<void> {
  const response = await fetch(`/api/v1${path}`, { credentials: "same-origin" });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new ApiError(response.status, payloadMessage(payload, "文件生成失败"));
  }
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const encodedName = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
  const filename = encodedName ? decodeURIComponent(encodedName) : "文章转载监测.xlsx";
  const url = URL.createObjectURL(await response.blob());
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
