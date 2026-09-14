// 统一的后端 API 客户端。
// - /api/v1/*（登录、知乎资料）走 HttpOnly Cookie 鉴权，响应是 {request_id, data} 信封；
// - /v1/*（初始化、问卷、领域）走 X-User-Id 请求头，响应是裸 JSON。
// 两种风格在这里被抹平，页面代码只管调用。
'use client';

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://127.0.0.1:80';

export type MePayload = {
  user_id: string;
  avatar_id: string | null;
  avatar_status: string;
  zhihu_connected: boolean;
  zhihu: { fullname: string; avatar_url: string; headline: string };
};

export type InitSession = {
  id: string;
  user_id: string;
  import_job_id: string | null;
  status: string;
  current_step: string;
  input_data: Record<string, any>;
  generated_profile: Record<string, any>;
};

export type DomainNode = {
  id: string;
  label: string;
  parent_id: string | null;
  level: 'root' | 'category' | 'leaf';
};

export type ContentItem = {
  content_type: string;
  url: string;
  title: string;
  summary: string;
  created_at: number | null;
  like_count: number | null;
};

// 当前用户 ID：登录后由 /api/v1/me 获得；未登录时用本地联调账号。
let currentUserId = 'local-demo-user';

export function setApiUserId(id: string | null | undefined) {
  if (id) currentUserId = id;
}

export function getApiUserId() {
  return currentUserId;
}

async function request(path: string, method: string, body?: unknown) {
  const response = await fetch(`${API_BASE}${path}`, {
    method,
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      'X-User-Id': currentUserId,
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await response.text();
  let payload: any = null;
  try {
    payload = text ? JSON.parse(text) : null;
  } catch {
    payload = null;
  }
  if (!response.ok) {
    const message =
      payload?.detail || payload?.error?.message || `请求失败（HTTP ${response.status}）`;
    throw new Error(String(message));
  }
  return payload;
}

/** 调用 /v1/* 接口（裸 JSON 响应）。 */
export async function api<T = any>(path: string, method = 'GET', body?: unknown): Promise<T> {
  return request(path, method, body);
}

/** 调用 /api/v1/* 接口（{request_id, data} 信封响应）。 */
export async function apiEnvelope<T = any>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const payload = await request(path, method, body);
  return (payload?.data ?? payload) as T;
}

/** 读取当前登录用户；未登录时抛错。 */
export async function getMe(): Promise<MePayload> {
  return apiEnvelope<MePayload>('/api/v1/me');
}
