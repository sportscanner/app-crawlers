# Splitwise API — Integration Notes

Reference for the SportScanner games / Splitz feature.  
API base: `https://secure.splitwise.com/api/v3.0`  
Auth: Bearer token (`SPLITWISE_API_KEY` in `.dev.env` / production env)

---

## Rate Limits

**Splitwise does not publish specific numbers.**  
Their documentation states only:

> "The Self-Serve API has conservative rate and access limits, which are subject to change at any time."

- No per-minute / per-hour / per-day figures are disclosed
- Splitwise explicitly says the free API is **"not well suited to commercial projects"** if rate limits are an issue
- For production-scale usage, email `developers@splitwise.com` to negotiate limits
- **Recommendation for SportScanner**: expenses are only created when a game is finished — one API call per game. This is low-volume and very unlikely to hit limits.

---

## Authentication

| Property | Detail |
|---|---|
| Method | Bearer token (API key) — tied to a single Splitwise account |
| Token lifetime | **Forever** — OAuth tokens never expire unless explicitly revoked |
| Callback URL | Only one allowed per registered app |
| Multi-user | Not supported — the API key always acts as the registered account (Sportscanner) |

**Our setup**: Single `SPLITWISE_API_KEY` for the Sportscanner Splitwise account. All expenses are created by/from this account. The account acts as a silent payer (`owed_share=0`); game creator and participants are the debtors.

---

## Expense Creation Rules

### Required fields
- `cost` — total amount as a string (e.g. `"30.00"`)
- `currency_code` — **required** (breaking change in v3.0; was optional in v2). We always pass `"GBP"`.
- At least one user entry with balanced `paid_share` / `owed_share`

### Share validation
- `SUM(paid_share across all users)` must equal `cost` exactly
- `SUM(owed_share across all users)` must equal `cost` exactly
- Rounding errors will cause `"Shares is invalid"` — handle with `ROUND_HALF_UP` and assign remainder to first debtor

### Authenticated user requirement
- The API account **must** be included in every expense
- Creating an expense without the authenticated user returns: `"You cannot add an expense that does not involve yourself, unless that expense is in a group"`
- **Our workaround**: Sportscanner account has `paid_share=total_cost` and `owed_share=0.00` — it is technically "involved" (non-zero paid) but owes nothing

### Participant email behaviour
- If a participant email matches an **existing Splitwise account**, they are linked by user ID automatically
- If the email is **not registered on Splitwise**, Splitwise attempts to send an email invitation — this can fail silently if the email provider rejects Splitwise's invitation (e.g. some Outlook / corporate domains)
- **Confirmed working**: Gmail addresses (`@gmail.com`)
- **Confirmed failing**: `yasir_khalid@outlook.com`, `@sportscanner.co.uk` non-registered addresses → returns `"Shares is invalid"` (Splitwise's way of saying the user entry failed)
- **Fix for failing addresses**: the participant must create a free Splitwise account at `splitwise.com` using that email — once registered, they are found by email lookup and the expense succeeds

### Duplicate person error
- `"A person was included on this expense multiple times"` — triggered when the same Splitwise user appears in two slots (e.g. the API account's email also added as a participant email)
- **Our fix**: filter the SW account's own email from the debtors list before building the payload

---

## HTTP 200 ≠ Success

**Critical**: Splitwise returns `HTTP 200` even for failed expenses. Always check the `errors` field:

```python
data = response.json()
errors = data.get("errors", {})
if errors and any(errors.values()):
    # handle failure
```

Known `errors.base` values we've encountered:

| Error | Cause |
|---|---|
| `"Shares is invalid"` | Shares don't balance, OR a participant email failed to resolve (non-registered email on restrictive provider) |
| `"A person was included on this expense multiple times"` | Same Splitwise account added twice (via user_id AND email) |
| `"You cannot add an expense that does not involve yourself, unless that expense is in a group"` | Authenticated user not in the expense |
| `"There are zero people involved in this expense"` | JSON body format used instead of form-encoded — Splitwise only accepts `application/x-www-form-urlencoded` |

---

## Correct Request Format

Splitwise **only** accepts `application/x-www-form-urlencoded` (form data), not JSON body.

```python
# CORRECT
response = await client.post(url, data=payload, headers=headers)

# WRONG — returns "zero people involved" error
response = await client.post(url, json=payload, headers=headers)
```

User IDs must be passed as **strings**, not integers:
```python
"users__0__user_id": str(user_id)  # not int
```

---

## Categories

Pass `category_id` as a string in the payload. Sports = `"24"`.

Full list via: `GET /api/v3.0/get_categories`

| ID | Name |
|---|---|
| 5 | Entertainment |
| 24 | Sports |
| 25 | Food and drink |
| 31 | Transportation |

---

## Known Issues (v3.0)

- `GET /api/v3` (without `.0`) returns **404** — must use `/api/v3.0`
- Occasional `HTTP 200` with `null` body and expense not created (Splitwise backend issue, not our fault — handle gracefully with the `errors` check)
- OAuth token endpoint had a 404 period (GitHub issue #43) — using API key auth avoids this

---

## Terms of Service — Key Restrictions

- Cannot build a competing app
- Cannot reverse-engineer Splitwise
- Cannot monetize user data
- Cannot send unsolicited messages via the API
- Usage is subject to suspension at Splitwise's sole discretion for "excessive or abusive" use (thresholds not defined)
- Splitwise may change or remove the API at any time without notice

---

## What Is Not Documented

The following were not found in any official docs — contact `developers@splitwise.com` if these become a concern:

- Exact rate limit numbers
- Maximum participants per expense
- Maximum expense cost
- Webhook payload format and configuration
- Any SLA or uptime guarantees

---

## Our Integration Summary

| Config | Value |
|---|---|
| Account | Sportscanner (`yasir@sportscanner.co.uk`) |
| Splitwise user_id | `119503539` |
| Currency | GBP |
| Category | Sports (id=24) |
| Description format | `<venue_name> (YYYY-MM-DD HH:MM)` |
| Payer in expense | Sportscanner (paid=full, owes=0) |
| Debtors | Game creator + all participants |
| Triggered when | `PATCH /games/{id}/finish` called |
| Error handling | Logs error, stores `splitwise_expense_id=null`, game still marked FINISHED |
