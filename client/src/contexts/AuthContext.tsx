/**
 * Authentication Context
 * Manages global authentication state
 */
import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import { User, authApi, setAuthTokens, clearAuthTokens, getStoredUser, isAuthenticated } from '@/lib/api';

interface AuthContextType {
  user: User | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  login: (accessToken: string, refreshToken: string, user: User) => void;
  logout: () => void;
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider');
  }
  return context;
};

interface AuthProviderProps {
  children: ReactNode;
}

export const AuthProvider: React.FC<AuthProviderProps> = ({ children }) => {
  const [user, setUser] = useState<User | null>(() => {
    // Synchronous init from localStorage — no loading flash
    if (isAuthenticated()) {
      return getStoredUser();
    }
    return null;
  });
  const [isLoading, setIsLoading] = useState(() => {
    // Only show loading if we have a token but need to validate it
    return isAuthenticated() && !!getStoredUser();
  });

  // Background validation — user sees cached data instantly
  useEffect(() => {
    if (!isAuthenticated()) {
      setIsLoading(false);
      return;
    }

    let cancelled = false;

    authApi.getMe()
      .then((response) => {
        if (cancelled) return;
        setUser(response.data);
        localStorage.setItem('user', JSON.stringify(response.data));
      })
      .catch(() => {
        if (cancelled) return;
        // Token invalid — clear auth
        clearAuthTokens();
        setUser(null);
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });

    return () => { cancelled = true; };
  }, []);

  // Listen for forced logout from API interceptor (avoids full page reload)
  useEffect(() => {
    const handleForcedLogout = () => {
      setUser(null);
    };
    window.addEventListener('auth:logout', handleForcedLogout);
    return () => window.removeEventListener('auth:logout', handleForcedLogout);
  }, []);

  const login = (accessToken: string, refreshToken: string, userData: User) => {
    setAuthTokens(accessToken, refreshToken, userData);
    setUser(userData);
  };

  const logout = async () => {
    try {
      await authApi.logout();
    } catch {
      // Logout API failure is non-critical — always clear local tokens
    } finally {
      clearAuthTokens();
      setUser(null);
    }
  };

  const refreshUser = async () => {
    try {
      const response = await authApi.getMe();
      setUser(response.data);
      localStorage.setItem('user', JSON.stringify(response.data));
    } catch {
      clearAuthTokens();
      setUser(null);
    }
  };

  const value: AuthContextType = {
    user,
    isLoading,
    isAuthenticated: !!user,
    login,
    logout,
    refreshUser,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};
