"""Region scoping (India / UAE data isolation) applied to every data query.

A user sees records of the regions in their scope. Records whose region is unknown (customer not
yet verified, no phone hint) are visible only to users scoped to ALL regions, because nobody can
show they belong to a narrower scope.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import InstrumentedAttribute

from app.api.deps import Principal
from app.models.identity import Region


def region_filter(principal: Principal, column: InstrumentedAttribute[Any]) -> Any:
    regions = [r.value for r in principal.user.regions]
    if set(regions) == {r.value for r in Region}:
        return or_(column.in_(regions), column.is_(None))
    return column.in_(regions)
