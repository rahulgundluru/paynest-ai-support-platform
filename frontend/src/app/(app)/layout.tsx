"use client";

import { useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { AppShell } from "@/components/app-shell";
import { Alert, Spinner } from "@/components/ui";
import { useCurrentUser } from "@/hooks/use-auth";

export default function AuthenticatedLayout({ children }: { children: ReactNode }) {
  const router = useRouter();
  const { data: user, isLoading, isError } = useCurrentUser();

  useEffect(() => {
    if (!isLoading && user === null) router.replace("/login");
  }, [isLoading, user, router]);

  if (isError) {
    return (
      <div className="mx-auto max-w-md p-8">
        <Alert tone="danger">The API service could not be reached. Check that the backend is running.</Alert>
      </div>
    );
  }
  if (isLoading || !user) {
    return (
      <div className="p-8">
        <Spinner label="Checking session" />
      </div>
    );
  }
  return <AppShell user={user}>{children}</AppShell>;
}
