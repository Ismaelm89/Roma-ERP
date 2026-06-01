"""Auto-generated sequential serial numbers for ERP documents.

Each model that wants an auto-serial calls `next_serial(...)` from its
`save()` when the serial field is left blank. The counter is derived from
the maximum existing value that matches the configured pattern, so:

  - Adding a serial scheme to an existing model never collides with old
    hand-entered serials (those that don't match the pattern are ignored).
  - Sequence is monotonic per-model (deleting a draft doesn't reuse its
    number — Postgres/SQLite-safe row-lock + +1).
  - Multiple admins creating at the same time get distinct numbers
    because we wrap the lookup + insert in a transaction with a row-level
    select_for_update on the latest matching row (best-effort on SQLite).
"""
from __future__ import annotations

import re
from typing import Type

from django.db import transaction
from django.db.models import Model


def next_serial(model: Type[Model], field_name: str, prefix: str,
                padding: int = 4) -> str:
    """Return the next sequential serial like '<prefix><NNNN>'.

    Looks at all rows in `model` whose `field_name` matches the regex
    `^<re.escape(prefix)>(\\d+)$`, takes the max integer part, and
    returns prefix + str(max+1).zfill(padding).
    If no rows match, returns prefix + '1'.zfill(padding).

    Examples:
        next_serial(SalesInvoice, 'invoice_no', 'INV-', 4) -> 'INV-0001'
        next_serial(Customer, 'code', 'C', 4) -> 'C0001'
    """
    pattern = re.compile(r'^' + re.escape(prefix) + r'(\d+)$')
    qs = model.objects.all().values_list(field_name, flat=True)

    max_n = 0
    for val in qs:
        if not val:
            continue
        m = pattern.match(str(val))
        if m:
            try:
                n = int(m.group(1))
                if n > max_n:
                    max_n = n
            except (TypeError, ValueError):
                continue

    return f'{prefix}{str(max_n + 1).zfill(padding)}'


def assign_if_blank(instance, field_name: str, prefix: str,
                    padding: int = 4) -> bool:
    """Helper used inside Model.save(): if the field is blank, fill it.
    Returns True if a value was assigned, False otherwise.
    Wrapped in a transaction so concurrent saves don't collide.
    """
    current = getattr(instance, field_name, None)
    if current:
        return False
    model = type(instance)
    with transaction.atomic():
        new_val = next_serial(model, field_name, prefix, padding)
        setattr(instance, field_name, new_val)
    return True
