export const CATEGORY_LABELS: Record<string, string> = {
  payroll: "Payroll",
  statutory: "Statutory",
  how_to: "How-To",
  reports: "Reports",
  leave_attendance: "Leave & Attendance",
  integration: "Integration",
  billing: "Billing",
  access_login: "Access / Login",
  onboarding: "Onboarding",
};

export const CHANNEL_LABELS: Record<string, string> = {
  email: "Email",
  widget: "Widget",
  partner_portal: "Partner portal",
  whatsapp: "WhatsApp",
  phone: "Phone",
};

/** Timestamps are shown in IST (the support desks' reference zone) with the zone stated. */
export function formatIst(iso: string | null | undefined): string {
  if (!iso) return "—";
  return (
    new Intl.DateTimeFormat("en-GB", {
      timeZone: "Asia/Kolkata",
      day: "2-digit",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(new Date(iso)) + " IST"
  );
}

export function humanize(value: string | null | undefined): string {
  return value ? value.replace(/_/g, " ") : "—";
}
