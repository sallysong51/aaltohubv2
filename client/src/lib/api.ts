/**
 * API client for AaltoHub v2 backend
 */
import axios, { AxiosInstance, AxiosError } from 'axios';

// API base URL - update this to your backend URL
const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://63.180.156.219:8000';

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

// Response interceptor to handle token refresh
apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const originalRequest = error.config as any;

    // If 401 and not already retried, try to refresh token
    if (error.response?.status === 401 && !originalRequest._retry) {
      originalRequest._retry = true;

      try {
        const refreshToken = localStorage.getItem('refresh_token');
        if (refreshToken) {
          const response = await axios.post(`${API_BASE_URL}/api/auth/refresh`, {
            refresh_token: refreshToken,
          });

          const { access_token, refresh_token: newRefreshToken } = response.data;
          localStorage.setItem('access_token', access_token);
          localStorage.setItem('refresh_token', newRefreshToken);

          // Retry original request with new token
          originalRequest.headers.Authorization = `Bearer ${access_token}`;
          return apiClient(originalRequest);
        }
      } catch (refreshError) {
        // Refresh failed, logout user
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
  registered_by?: string;
  admin_invited: boolean;
  admin_invite_error?: string;
  created_at: string;
  updated_at: string;
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
  failed_invites: Array<{
    group_id: string;
    title: string;
    error: string;
  }>;
}

export interface Message {
  id: string;
  telegram_message_id: number;
  group_id: string;
  sender_id?: number;
  sender_name?: string;
  sender_username?: string;
  content?: string;
  media_type: string;
  media_url?: string;
  media_thumbnail_url?: string;
  reply_to_message_id?: number;
  topic_id?: number;
  topic_title?: string;
  is_deleted: boolean;
  edited_at?: string;
  edit_count: number;
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

export const groupsApi = {
  getMyTelegramGroups: () =>
    apiClient.get<TelegramGroup[]>('/groups/my-telegram-groups'),

  registerGroups: (data: RegisterGroupsRequest) =>
    apiClient.post<RegisterGroupsResponse>('/groups/register', data),

  getRegisteredGroups: () =>
    apiClient.get<RegisteredGroup[]>('/groups/registered'),

  getGroupMessages: (groupId: string, page: number = 1, pageSize: number = 50) =>
    apiClient.get<MessagesListResponse>(`/groups/${groupId}/messages`, {
      params: { page, page_size: pageSize },
    }),

  retryInviteAdmin: (groupId: string) =>
    apiClient.post(`/groups/${groupId}/invite-admin`),
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

  getGroupMessages: (groupId: string, page: number = 1, pageSize: number = 50, days: number = 30) =>
    apiClient.get<MessagesListResponse>(`/admin/groups/${groupId}/messages`, {
      params: { page, page_size: pageSize, days },
    }),

  getFailedInvites: () =>
    apiClient.get<{ failed_invites: Array<{ id: string; telegram_id: number; title: string; error: string; created_at: string }> }>('/admin/failed-invites'),

  getStats: () => apiClient.get<AdminStats>('/admin/stats'),
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
      return JSON.parse(userStr);
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
