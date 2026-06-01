# Roma ERP

Custom Django-based ERP for **Roma** — wholesale women's cotton pajamas, Egypt.
Stack: Django 5 + SQLite + Django Admin (Arabic / RTL). Runs locally on Windows.

## Status — Phase 1 + Phase 2 complete

End-to-end sales cycle works: Item → Stock → Invoice → Receipt → Ledger, with full Egyptian-style double-entry bookkeeping behind the scenes. Financial statements (Trial Balance, P&L, Balance Sheet) and inventory valuation are live and reconcile to the GL.

What's working today:

- **Home dashboard at `/`** — KPI cards (today's sales, MTD sales, cash, bank, AR, inventory value, low-stock count, overdue invoices), quick-action buttons, report links, top items / top customers MTD, and recent invoices
- **Admin UI in Arabic + RTL** for every entity
- **Item Variants**: Model + Size = unique SKU (auto-generated `ROM-{code}-{size}`), per-variant stock + Weighted Average Cost
- **Stock movements**: append-only log; WAC recalc on every inbound movement; cancel reverses cleanly
- **Sales Invoice posting** (atomic): writes stock-out, captures COGS at current WAC, and creates the AR/Sales/VAT + COGS/Inventory journal entry — all in one DB transaction
- **Sales Invoice cancellation**: reverses inventory and creates a balanced reversing journal entry (audit-friendly — original docs are immutable)
- **Customer Receipts** (cash / bank / cheque / POS) with multi-invoice allocation; posts Cash-or-Bank ↔ AR journal
- **Document-level discount %** on Sales Invoice (`خصم على إجمالي الفاتورة %`) — enter a percent, the amount is auto-computed against the post-line-discount subtotal and applied to the grand total
- **Default unit price on invoice lines**: when you pick a variant in a Sales Invoice line, JS auto-fills `unit_price` from `Item.wholesale_price` (or `base_price` as fallback). User-typed prices are respected — auto-fill only runs when the field is empty/zero. A server-side fallback in `SalesInvoiceLine.save()` covers programmatic line creation (CSV imports, scripts).
- **Inline Post / Cancel buttons** on the Sales Invoice and Receipt change pages — green "ترحيل" button when DRAFT, red "إلغاء" button when POSTED. No need to go back to the list view to post.
- **Arabic invoice print page** at `/sales/invoice/<id>/print/` — browser-print or save as PDF
- **Customer ledger** at `/sales/customer/<id>/ledger/` — opening balance + current balance card + AR journal lines + running balance
- **Current AR balance column** on the Customer list page (red if customer owes money, green if customer has a credit on account)
- **AR aging report** at `/sales/aging/` — 0-30 / 31-60 / 61-90 / 90+ buckets
- **Inventory valuation report** at `/inventory/valuation/` — per-SKU qty × WAC and a reconciliation against the Inventory GL balance (flags the variance in red if non-zero)
- **Trial Balance** at `/reports/trial-balance/` — by date, with debit/credit totals and a balanced/not-balanced flag
- **Income Statement (P&L)** at `/reports/pnl/` — date-range filter, revenue + expenses, net income/loss
- **Balance Sheet** at `/reports/balance-sheet/` — as-of date, Assets / Liabilities / Equity, automatic YTD net income roll-in to equity, balanced/not-balanced flag
- **Excel import** for items + variants and for customers (idempotent — re-importing updates existing rows by code)
- **Smoke test** (`smoke_test.py`) that exercises the full posting cycle and asserts AR sub-ledger = AR GL balance

## Run it

Double-click `runserver.bat` — or from PowerShell:

```powershell
cd C:\Users\MahmoudIsmael\Desktop\Roma-ERP
$env:PYTHONIOENCODING = "utf-8"
.\.venv\Scripts\python.exe manage.py runserver
```

Then open **http://127.0.0.1:8001/** (you'll be redirected to login first) and log in with:

- Username: `admin`
- Password: `roma2026`  (change it from the Users section right away)

## Day-to-day workflow

After login, you land on the **dashboard at `/`**. From there:

- **KPI cards** at the top: today's sales, cash position, total AR, inventory value, etc. — each card is clickable and drills down to the related list or report.
- **Quick-action buttons**: + New Sales Invoice, + New Receipt, + New Customer, + New Item, + New Stock Movement.
- **Reports section**: links to Trial Balance, P&L, Balance Sheet, Inventory Valuation, AR Aging, Customers-with-balance. Each opens in a new tab and is printable from the browser (Ctrl+P → Save as PDF). No paid PDF service required.
- **Top items / Top customers** this month, plus the last 8 posted invoices.

1. **Company setup** — go to *بيانات الشركة* in the admin and fill in name, tax ID, logo, address. The logo appears on every printed invoice.
2. **Items** — open *الأصناف*, add a model (e.g. code `101`, name `بيجاما صيفي`). In the same form, the inline variants section lets you tick which sizes exist. Each variant auto-gets a SKU like `ROM-101-L`.
3. **Opening stock** — open *حركات المخزون*, add rows of type *رصيد افتتاحي* with quantity + unit cost. The variant's `current_stock` and `average_cost` update automatically. *(Future phase: a dedicated opening-balance screen.)*
4. **Customers** — open *العملاء* and add them, or use Excel import (see below).
5. **Sales Invoice** — open *فواتير المبيعات* → *إضافة*. Pick customer, add line(s) — choose a variant and the `unit_price` auto-fills from the item's `wholesale_price`. Leave the price as-is or override. Optionally set the doc-level `خصم على إجمالي الفاتورة %`. Save as draft.
6. **Post the invoice** — on the invoice change page, click the green **"✓ ترحيل الفاتورة"** button at the bottom. Stock decrements, COGS posts, AR/Sales/VAT journal entry created — all atomic. (You can also bulk-post from the list view via the action dropdown.)
7. **Print** — click the **"🖨️ طباعة"** button in the same submit row, or the 🖨️ link in the invoices list. Browser print → save as PDF.
8. **Receipt** — open *سندات القبض* → add receipt with method + amount → in the inline grid, allocate amounts to specific invoices → save → click green **"✓ ترحيل سند القبض"** at the bottom.
9. **Customer ledger** — from the *العملاء* list, click *كشف حساب* on a row.
10. **AR aging** — visit `/sales/aging/` directly.

## Excel imports

### Items

Required header columns: `code`, `name_ar`. Optional: `name_en`, `category`, `fabric`, `base_price`, `description`, `sizes` (comma-separated, e.g. `"S,M,L,XL,XXL,XXXL"`), `active`.

```powershell
.\.venv\Scripts\python.exe manage.py import_items "C:\path\to\items.xlsx"
.\.venv\Scripts\python.exe manage.py import_items "C:\path\to\items.xlsx" --dry-run
```

Re-runs update existing items (matched by `code`). Variants for any size already present are kept; missing sizes are added.

### Customers

Required: `code`, `name_ar`. Optional: `name_en`, `tax_id`, `commercial_register`, `address`, `governorate`, `phone`, `email`, `payment_terms_days`, `credit_limit`, `opening_balance`, `active`.

```powershell
.\.venv\Scripts\python.exe manage.py import_customers "C:\path\to\customers.xlsx"
```

## Project layout

```
Roma-ERP/
├── manage.py
├── runserver.bat
├── smoke_test.py               (end-to-end regression — run after model changes)
├── db.sqlite3
├── .venv/                      (Python virtual env)
├── config/                     (Django project — settings.py, urls.py)
├── core/
│   ├── models.py               (Company, Account, JournalEntry, JournalLine)
│   ├── account_codes.py        (SYSTEM_ACCOUNTS — symbolic keys for posting)
│   └── management/commands/seed_coa.py
├── inventory/
│   ├── models.py               (Item, ItemVariant, StockMovement)
│   └── management/commands/import_items.py
├── sales/
│   ├── models.py               (Customer, SalesInvoice, Receipt, ReceiptAllocation)
│   ├── services.py             (post/cancel: invoice + receipt — atomic)
│   ├── views.py                (print_invoice, customer_ledger, aging_report)
│   ├── urls.py
│   └── management/commands/import_customers.py
├── templates/sales/            (Arabic RTL print templates)
├── static/
└── media/                      (uploaded item images + company logo)
```

## Common commands

```powershell
# Re-seed chart of accounts (idempotent — 23 accounts incl. Opening Balance Equity)
.\.venv\Scripts\python.exe manage.py seed_coa

# Schema changes
.\.venv\Scripts\python.exe manage.py makemigrations
.\.venv\Scripts\python.exe manage.py migrate

# End-to-end smoke test (creates SMOKE-prefixed test rows then verifies AR=GL)
.\.venv\Scripts\python.exe smoke_test.py

# Django shell
.\.venv\Scripts\python.exe manage.py shell

# Add another admin user
.\.venv\Scripts\python.exe manage.py createsuperuser
```

## Opening stock posting

Opening stock should be entered via `inventory.services.post_opening_balance()`, **not** by creating raw `StockMovement` rows. The service creates the movement AND a balanced journal entry (DR Inventory / CR Opening Balance Equity = `3310000`) in one atomic transaction, so the Inventory GL stays in sync with the physical quantities.

If you bulk-load opening balances via CSV/Excel/script, call the service directly:

```python
from decimal import Decimal
from inventory.services import post_opening_balance
from inventory.models import ItemVariant

v = ItemVariant.objects.get(sku_code='ROM-CF005-M')
post_opening_balance(variant=v, quantity=Decimal('231'), unit_cost=Decimal('286'))
```

Note: `StockMovement.apply_to_variant()` (used internally) still does not auto-post a journal entry. Movements of type `ADJUST_IN`, `ADJUST_OUT`, `WASTE` also need a corresponding journal — those services aren't built yet.

## Accounting model

Posting routines never live in admin or views — they're all in `sales/services.py` and run inside `transaction.atomic()`. They look up accounts via symbolic keys (`AR`, `SALES_REVENUE`, `VAT_OUTPUT`, `COGS`, `INVENTORY`, `CASH`, `BANK`, …) defined in `core/account_codes.py` against the COA codes in `seed_coa.py`. If you re-chart, only those two files need to change.

Posted accounting events:

| Event                | Debit                | Credit                              |
|----------------------|----------------------|-------------------------------------|
| Sales Invoice post   | AR (customer)        | Sales Revenue + VAT Output          |
| Sales Invoice post   | COGS                 | Inventory                           |
| Receipt post (cash)  | Cash                 | AR (customer)                       |
| Receipt post (bank)  | Bank                 | AR (customer)                       |
| Sales Invoice cancel | (reversing journal — exact mirror of the original entry) |

## What's NOT in v1 (deferred to later phases)

Per the agreed simple-MVP scope, these are intentionally out of v1:

- Purchases module (suppliers, POs, GRNs, purchase invoices, landed cost)
- Withholding tax (WHT) on payments
- Cash Flow Statement (indirect method)
- Opening-balance / inventory-adjustment journal posting (planned as the next slice)
- Multiple price lists
- Quotations, Sales Orders, Delivery Notes
- Audit log + period close
- ETA (Egyptian Tax Authority) e-invoicing integration
- Dashboard, profitability analytics, governorate/sales-rep analytics
- Post-dated cheques register
- Mobile-responsive frontend polish

These will be tackled once Phase 1 is in real use and any rough edges are smoothed.
