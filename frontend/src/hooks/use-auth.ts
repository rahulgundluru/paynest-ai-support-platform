"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, apiFetch } from "@/lib/api";
import type { LoginResponse, Permission, User } from "@/types/api";

export const meQueryKey = ["auth", "me"] as const;

export function useCurrentUser() {
  return useQuery<User | null>({
    queryKey: meQueryKey,
    queryFn: async () => {
      try {
        return await apiFetch<User>("/api/v1/auth/me");
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) return null;
        throw error;
      }
    },
    staleTime: 60_000,
    retry: false,
  });
}

export function useLogin() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { email: string; password: string }) =>
      apiFetch<LoginResponse>("/api/v1/auth/login", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: (data) => queryClient.setQueryData(meQueryKey, data.user),
  });
}

export function useLogout() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiFetch<void>("/api/v1/auth/logout", { method: "POST" }),
    onSettled: () => {
      queryClient.clear();
      queryClient.setQueryData(meQueryKey, null);
    },
  });
}

export function hasPermission(user: User | null | undefined, permission: Permission): boolean {
  return Boolean(user?.permissions.includes(permission));
}
