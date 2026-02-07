/**
 * API client for AaltoHub v2 backend
 */
import axios, { AxiosInstance, AxiosError } from 'axios';

/** Extract error detail message from API error response */
export function getApiErrorMessage(error: unknown, fallback: string): string {
  if (axios.isAxiosError(error)) {
    return error.response?.data?.detail || fallback;
  }
  return fallback;
}

// API base URL configuration:
// - Development: empty string → requests go to same origin → Vite proxy forwards to backend
// - Production (Vercel): empty string → Vercel serverless proxy forwards to EC2 backend
// - Override: set VITE_API_URL to an absolute URL (e.g. http://localhost:8000)
const API_BASE_URL = import.meta.env.VITE_API_URL || '';

// Create axios instance
const apiClient: AxiosInstance = axios.create({
  baseURL: `${API_BASE_URL}/api`,
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Request interceptor to add auth token
apiClient.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('access_token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// Token refresh mutex — prevents concurrent 401 responses from each
// independently refreshing the token (which would invalidate the first
// refresh and force-logout the user).
let refreshPromise: Promise<string> | null = null;

// Response interceptor to handle network errors and token refresh
apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    // Network error (backend unreachable) — no response at all
    if (!error.response) {
      const networkError: Error & { isNetworkError?: boolean } = new Error('Backend server is not reachable. Please make sure the backend is running.');
      networkError.isNetworkError = true;
      return Promise.reject(networkError);
    }

    const originalRequest = error.config as typeof error.config & { _retry?: boolean };

    // If 401 and not already retried, try to refresh token
    if (error.response?.status === 401 && !originalRequest._retry) {
      originalRequest._retry = true;

      try {
        // If a refresh is already in progress, wait for it instead of
        // firing a second refresh request. The promise is kept alive until
        // all waiters have consumed the new token to prevent redundant
        // refresh cycles that could invalidate single-use refresh tokens.
        if (!refreshPromise) {
          refreshPromise = (async () => {
            const refreshToken = localStorage.getItem('refresh_token');
            if (!refreshToken) throw new Error('No refresh token');

            const response = await axios.post(`${API_BASE_URL}/api/auth/refresh`, {
              refresh_token: refreshToken,
            });

            const { access_token, refresh_token: newRefreshToken } = response.data;
            localStorage.setItem('access_token', access_token);
            localStorage.setItem('refresh_token', newRefreshToken);
            return access_token;
          })();

          // Clear the shared promise after a short delay so concurrent
          // requests reuse the same result, but future requests after the
          // window will trigger a fresh refresh if needed.
          refreshPromise.finally(() => {
            setTimeout(() => { refreshPromise = null; }, 2000);
          });
        }

        const newAccessToken = await refreshPromise;
        originalRequest.headers.Authorization = `Bearer ${newAccessToken}`;
        return apiClient(originalRequest);
      } catch (refreshError) {
        // Refresh failed, logout user
        refreshPromise = null;
        localStorage.removeItem('access_token');
        localStorage.removeItem('refresh_token');
        localStorage.removeItem('user');
        window.location.href = '/login';
        return Promise.reject(refreshError);
      }
    }

    return Promise.reject(error);
  }
);

// ============================================================
// Auth API
// ============================================================

export interface SendCodeRequest {
  phone_or_username: string;
}

export interface SendCodeResponse {
  success: boolean;
  message: string;
  phone_code_hash?: string;
  requires_2fa: boolean;
}

export interface VerifyCodeRequest {
  phone_or_username: string;
  code: string;
  phone_code_hash: string;
}

export interface Verify2FARequest {
  phone_or_username: string;
  password: string;
  phone_code_hash: string;
}

export interface User {
  id: string;
  telegram_id: number;
  phone_number?: string;
  username?: string;
  first_name?: string;
  last_name?: string;
  role: 'admin' | 'user';
  created_at: string;
  updated_at: string;
}

export interface AuthResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  user: User;
}

export const authApi = {
  sendCode: (data: SendCodeRequest) =>
    apiClient.post<SendCodeResponse>('/auth/send-code', data),

  verifyCode: (data: VerifyCodeRequest) =>
    apiClient.post<AuthResponse>('/auth/verify-code', data),

  verify2FA: (data: Verify2FARequest) =>
    apiClient.post<AuthResponse>('/auth/verify-2fa', data),

  getMe: () => apiClient.get<User>('/auth/me'),

  logout: () => apiClient.post('/auth/logout'),
};

// ============================================================
// Groups API
// ============================================================

export interface TelegramGroup {
  telegram_id: number;
  title: string;
  username?: string;
  member_count?: number;
  group_type?: 'group' | 'supergroup' | 'channel';
  is_registered?: boolean;
  photo_url?: string;  // Group profile photo URL (optional)
}

export interface RegisteredGroup {
  id: string;
  telegram_id: number;
  title: string;
  username?: string;
  member_count?: number;
  group_type?: 'group' | 'supergroup' | 'channel';
  visibility: 'public' | 'private';
  invite_link?: string;
  description?: string;
  registered_by?: string;
  created_at: string;
}

export interface RegisterGroupsRequest {
  groups: Array<{
    telegram_id: number;
    title: string;
    username?: string;
    member_count?: number;
    group_type?: string;
    visibility: 'public' | 'private';
  }>;
}

export interface RegisterGroupsResponse {
  success: boolean;
  registered_groups: RegisteredGroup[];
}

export interface Message {
  id: string;
  telegram_message_id: number;
  group_id: string;
  sender_id?: number;
  sender_name?: string;
  content?: string;
  media_type?: string;  // photo, video, document, audio, sticker, voice (null = text)
  media_url?: string;
  reply_to_message_id?: number;
  topic_id?: number;
  is_deleted: boolean;
  sent_at: string;
  created_at: string;
}

export interface MessagesListResponse {
  messages: Message[];
  total: number;
  page: number;
  page_size: number;
  has_more: boolean;
}

export interface InviteLink {
  id: string;
  token: string;
  expires_at?: string;
  is_revoked: boolean;
  used_count: number;
  max_uses?: number;
  created_at: string;
}

export interface CreateInviteLinkResponse {
  success: boolean;
  invite_link: string;
  token: string;
  expires_at?: string;
  max_uses?: number;
}

export const groupsApi = {
  getMyTelegramGroups: () =>
    apiClient.get<TelegramGroup[]>('/groups/my-telegram-groups'),

  registerGroups: (data: RegisterGroupsRequest) =>
    apiClient.post<RegisterGroupsResponse>('/groups/register', data),

  getRegisteredGroups: () =>
    apiClient.get<RegisteredGroup[]>('/groups/registered'),

  getGroupMessages: (groupId: string, page: number = 1, pageSize: number = 50, topicId?: number) =>
    apiClient.get<MessagesListResponse>(`/groups/${groupId}/messages`, {
      params: { page, page_size: pageSize, ...(topicId != null ? { topic_id: topicId } : {}) },
    }),

  getAggregatedMessages: (groupIds: string[], page: number = 1, pageSize: number = 50, topicId?: number) =>
    apiClient.get<MessagesListResponse>('/groups/messages/aggregated', {
      params: {
        group_ids: groupIds.join(','),
        page,
        page_size: pageSize,
        ...(topicId != null ? { topic_id: topicId } : {}),
      },
    }),

  getGroup: (groupId: string) =>
    apiClient.get<RegisteredGroup>(`/groups/${groupId}`),

  updateVisibility: (groupId: string, visibility: 'public' | 'private') =>
    apiClient.patch(`/groups/${groupId}/visibility`, null, {
      params: { visibility },
    }),

  getInviteLinks: (groupId: string) =>
    apiClient.get<InviteLink[]>(`/groups/${groupId}/invite-links`),

  createInviteLink: (groupId: string, expiresAt?: string, maxUses?: number) =>
    apiClient.post<CreateInviteLinkResponse>(`/groups/${groupId}/invite-link`, {
      expires_at: expiresAt,
      max_uses: maxUses,
    }),

  revokeInviteLink: (groupId: string, inviteId: string) =>
    apiClient.post(`/groups/${groupId}/invite-link/${inviteId}/revoke`),

  acceptInvite: (token: string) =>
    apiClient.post<{ success: boolean; group_id: string }>(`/groups/invite/${token}/accept`),

  deleteGroup: (groupId: string) =>
    apiClient.delete(`/groups/${groupId}`),
};

// ============================================================
// Admin API
// ============================================================

export interface AdminStats {
  total_users: number;
  total_groups: number;
  total_public_groups: number;
  total_messages: number;
  messages_last_24h: number;
}

export const adminApi = {
  getAllGroups: () => apiClient.get<RegisteredGroup[]>('/admin/groups'),

  getGroupMessages: (groupId: string, page: number = 1, pageSize: number = 50, days: number = 30, topicId?: number | null) =>
    apiClient.get<MessagesListResponse>(`/admin/groups/${groupId}/messages`, {
      params: { page, page_size: pageSize, days, ...(topicId != null ? { topic_id: topicId } : {}) },
    }),

  getStats: () => apiClient.get<AdminStats>('/admin/stats'),

  getAllUsers: () => apiClient.get<User[]>('/admin/users'),

  updateUserRole: (userId: string, role: 'admin' | 'user') =>
    apiClient.patch<{ success: boolean; user_id: string; new_role: string }>(
      `/admin/users/${userId}/role`,
      null,
      { params: { role } }
    ),

  getCrawlerStatus: () => apiClient.get('/admin/crawler-status'),

  getLiveCrawlerStatus: () => apiClient.get('/admin/live-crawler/status'),

  restartLiveCrawler: () => apiClient.post('/admin/live-crawler/restart'),

  triggerHistoricalCrawl: (groupId: string) =>
    apiClient.post(`/admin/groups/${groupId}/crawl`),

  getFailedMessages: (resolved: boolean = false, limit: number = 100) =>
    apiClient.get('/admin/failed-messages', { params: { resolved, limit } }),

  retryFailedMessage: (messageId: string) =>
    apiClient.post(`/admin/failed-messages/${messageId}/retry`),
};

// ============================================================
// Helper functions
// ============================================================

export const setAuthTokens = (accessToken: string, refreshToken: string, user: User) => {
  localStorage.setItem('access_token', accessToken);
  localStorage.setItem('refresh_token', refreshToken);
  localStorage.setItem('user', JSON.stringify(user));
};

export const clearAuthTokens = () => {
  localStorage.removeItem('access_token');
  localStorage.removeItem('refresh_token');
  localStorage.removeItem('user');
};

export const getStoredUser = (): User | null => {
  const userStr = localStorage.getItem('user');
  if (userStr) {
    try {
      const parsed = JSON.parse(userStr);
      if (parsed && typeof parsed === 'object' && parsed.id && parsed.role) {
        return parsed as User;
      }
      return null;
    } catch {
      return null;
    }
  }
  return null;
};

export const isAuthenticated = (): boolean => {
  return !!localStorage.getItem('access_token');
};

export default apiClient;
