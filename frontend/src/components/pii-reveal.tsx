"use client";

import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { Button, Input } from "@/components/ui";
import { ApiError, apiFetch } from "@/lib/api";
import type { RevealResponse } from "@/types/api";

/** DPO-only: reveal one original value with a recorded reason. The value is kept only in component state. */
export function PiiReveal({ ticketRef, token }: { ticketRef: string; token: string }) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const reveal = useMutation({
    mutationFn: () =>
      apiFetch<RevealResponse>(
        `/api/v1/tickets/${encodeURIComponent(ticketRef)}/pii/${encodeURIComponent(token.replace(/[<>]/g, ""))}/reveal`,
        { method: "POST", body: JSON.stringify({ reason }) },
      ),
  });

  if (reveal.data) {
    return (
      <span className="flex items-center gap-2">
        <span className="font-mono text-xs">{reveal.data.value}</span>
        <Button variant="secondary" className="px-2 py-0.5 text-xs" onClick={() => reveal.reset()}>
          Hide
        </Button>
      </span>
    );
  }
  if (!open) {
    return (
      <Button variant="secondary" className="px-2 py-0.5 text-xs" onClick={() => setOpen(true)}>
        Reveal
      </Button>
    );
  }
  return (
    <form
      className="flex flex-wrap items-center gap-1"
      onSubmit={(e) => {
        e.preventDefault();
        reveal.mutate();
      }}
    >
      <Input
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        placeholder="Reason (recorded in the audit log)"
        aria-label={`Reason to reveal ${token}`}
        className="max-w-56 py-1 text-xs"
      />
      <Button type="submit" className="px-2 py-1 text-xs" disabled={reason.trim().length < 10 || reveal.isPending}>
        Confirm
      </Button>
      {reveal.isError && (
        <span className="text-xs text-danger">{reveal.error instanceof ApiError ? reveal.error.message : "Failed"}</span>
      )}
    </form>
  );
}
