import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode } from "react";
import { forwardRef } from "react";

function cx(...classes: (string | false | null | undefined)[]) {
  return classes.filter(Boolean).join(" ");
}

export function Button({
  variant = "primary",
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" }) {
  return (
    <button
      className={cx(
        "inline-flex items-center justify-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-60",
        variant === "primary"
          ? "bg-accent text-accent-contrast hover:opacity-90"
          : "border border-border bg-surface text-text hover:bg-surface-muted",
        className,
      )}
      {...props}
    />
  );
}

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input(
  { className, ...props },
  ref,
) {
  return (
    <input
      ref={ref}
      className={cx(
        "w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-text",
        "placeholder:text-text-muted focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/30",
        className,
      )}
      {...props}
    />
  );
});

export function Card({ title, children, className }: { title?: string; children: ReactNode; className?: string }) {
  return (
    <section className={cx("rounded-lg border border-border bg-surface p-5", className)}>
      {title && <h2 className="mb-3 text-sm font-semibold text-text">{title}</h2>}
      {children}
    </section>
  );
}

export function Alert({ tone, children }: { tone: "danger" | "success" | "warning"; children: ReactNode }) {
  const tones = {
    danger: "bg-danger-bg text-danger",
    success: "bg-success-bg text-success",
    warning: "bg-warning-bg text-warning",
  };
  return (
    <div role={tone === "danger" ? "alert" : "status"} className={cx("rounded-md px-3 py-2 text-sm", tones[tone])}>
      {children}
    </div>
  );
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <div role="status" className="flex items-center gap-2 text-sm text-text-muted">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-border border-t-accent" aria-hidden />
      {label}…
    </div>
  );
}

export function Badge({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "success" | "danger" }) {
  const tones = {
    neutral: "bg-surface-muted text-text-muted",
    success: "bg-success-bg text-success",
    danger: "bg-danger-bg text-danger",
  };
  return <span className={cx("rounded px-1.5 py-0.5 text-xs font-medium", tones[tone])}>{children}</span>;
}
