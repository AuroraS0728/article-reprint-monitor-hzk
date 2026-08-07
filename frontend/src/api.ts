const csrfToken = (): string => document.cookie.split("; ").find((item) => item.startsWith("csrftoken="))?.split("=")[1] ?? "";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) { super(message); this.status = status; }
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.method && !["GET", "HEAD"].includes(options.method)) headers.set("X-CSRFToken", csrfToken());
  const response = await fetch(`/api/v1${path}`, { credentials: "same-origin", ...options, headers });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new ApiError(response.status, payload?.error?.message ?? "请求失败");
  return (payload?.data ?? payload) as T;
}
