"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Alert, Button, Input } from "@/components/ui";
import { useCurrentUser, useLogin } from "@/hooks/use-auth";
import { ApiError } from "@/lib/api";

const schema = z.object({
  email: z.string().email("Enter a valid email address"),
  password: z.string().min(1, "Enter your password"),
});
type FormValues = z.infer<typeof schema>;

export default function LoginPage() {
  const router = useRouter();
  const { data: user } = useCurrentUser();
  const login = useLogin();
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<FormValues>({ resolver: zodResolver(schema) });

  useEffect(() => {
    if (user) router.replace("/dashboard");
  }, [user, router]);

  const onSubmit = handleSubmit((values) =>
    login.mutate(values, { onSuccess: () => router.replace("/dashboard") }),
  );

  const errorMessage =
    login.error instanceof ApiError
      ? login.error.status === 401
        ? "Invalid email or password."
        : `${login.error.message} (request ${login.error.requestId ?? "n/a"})`
      : login.error
        ? "The service could not be reached. Try again."
        : null;

  return (
    <main className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-sm rounded-lg border border-border bg-surface p-6 shadow-sm">
        <h1 className="text-lg font-semibold">PayNest Support Intelligence</h1>
        <p className="mt-1 text-sm text-text-muted">Sign in with your support operations account.</p>
        <form className="mt-6 space-y-4" onSubmit={onSubmit} noValidate>
          <div className="space-y-1">
            <label htmlFor="email" className="text-sm font-medium">
              Email
            </label>
            <Input id="email" type="email" autoComplete="username" {...register("email")} aria-invalid={!!errors.email} />
            {errors.email && <p className="text-xs text-danger">{errors.email.message}</p>}
          </div>
          <div className="space-y-1">
            <label htmlFor="password" className="text-sm font-medium">
              Password
            </label>
            <Input
              id="password"
              type="password"
              autoComplete="current-password"
              {...register("password")}
              aria-invalid={!!errors.password}
            />
            {errors.password && <p className="text-xs text-danger">{errors.password.message}</p>}
          </div>
          {errorMessage && <Alert tone="danger">{errorMessage}</Alert>}
          <Button type="submit" className="w-full" disabled={login.isPending}>
            {login.isPending ? "Signing in…" : "Sign in"}
          </Button>
        </form>
      </div>
    </main>
  );
}
