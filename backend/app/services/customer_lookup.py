"""Customer identity resolution. Deterministic and evidence-based: no fuzzy matching.

Order:
1. A customer id present on the record (email customer_id, widget org_id, partner tenant, call
   customer_id) that exists in the customer master.
2. Partner tickets with tenant=null: EXACT match of `end_customer` against the customer legal
   name (case/whitespace-insensitive). Profiling: 65/65 null-tenant tickets resolve this way.
3. WhatsApp: EXACT match of `customer_hint`.
Anything else stays `unresolved` and is routed to manual verification. A phone country code may
give a REGION hint, but never a customer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.models.reference import Customer


def _name_key(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip().casefold()


@dataclass(frozen=True)
class Resolution:
    customer: Customer | None
    method: str  # direct | partner_end_customer_name | whatsapp_customer_hint | unresolved
    region: str | None
    region_source: str | None
    reason: str | None = None


class CustomerDirectory:
    def __init__(self, customers: list[Customer]) -> None:
        self.by_id = {c.customer_id: c for c in customers}
        self.by_name: dict[str, Customer] = {}
        duplicates: set[str] = set()
        for c in customers:
            key = _name_key(c.name)
            if key in self.by_name:
                duplicates.add(key)
            self.by_name[key] = c
        for key in duplicates:  # ambiguous names never resolve automatically
            del self.by_name[key]

    def resolve(
        self, channel: str, customer_id: str | None, name_hint: str | None, phone_hint: str | None = None
    ) -> Resolution:
        if customer_id:
            customer = self.by_id.get(customer_id)
            if customer:
                return Resolution(customer, "direct", customer.region, "customer_master")
            return Resolution(None, "unresolved", None, None, "customer_id_not_in_master")
        if name_hint:
            customer = self.by_name.get(_name_key(name_hint))
            if customer:
                method = "partner_end_customer_name" if channel == "partner_portal" else "whatsapp_customer_hint"
                return Resolution(customer, method, customer.region, "customer_master")
        region = region_from_phone(phone_hint)
        return Resolution(
            None,
            "unresolved",
            region,
            "phone_country_code" if region else None,
            "customer_name_not_matched" if name_hint else "customer_identity_missing",
        )


def region_from_phone(phone: str | None) -> str | None:
    if not phone:
        return None
    compact = phone.replace(" ", "")
    if compact.startswith("+971"):
        return "UAE"
    if compact.startswith("+91"):
        return "IN"
    return None
