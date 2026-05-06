"""Splitwise API v3.0 client.

Sportscanner acts as the silent payer (paid_share=full, owed_share=0).
The game creator and all participants are the debtors, splitting equally.
Splitwise resolves emails to existing accounts or sends invitation emails.
"""

from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

import httpx

from sportscanner.logger import logging as logger

SPLITWISE_API_BASE = "https://secure.splitwise.com/api/v3.0"
SPORTS_CATEGORY_ID = "24"


async def _get_sw_user(client: httpx.AsyncClient, headers: dict) -> Optional[dict]:
    """Return {id, email} for the authenticated API key, or None on failure."""
    r = await client.get(f"{SPLITWISE_API_BASE}/get_current_user", headers=headers)
    if r.status_code != 200:
        logger.error(
            f"Splitwise auth check failed {r.status_code} — "
            f"verify the API key at secure.splitwise.com/apps"
        )
        return None
    user = r.json().get("user", {})
    logger.info(f"Splitwise authenticated as user_id={user.get('id')} ({user.get('email')})")
    return {"id": str(user["id"]), "email": user.get("email", "").lower()}


def _classify_error(errors: dict) -> str:
    messages = " ".join(errors.get("base", []))
    if "multiple times" in messages:
        return "duplicate_person"
    if "Shares is invalid" in messages:
        return "unregistered_email"
    if "involve yourself" in messages:
        return "auth_failed"
    return "unknown"


def _build_payload(
    sw_user_id: str,
    total_cost: Decimal,
    description: str,
    debtors: list[str],
) -> dict:
    """Build the form-encoded payload for create_expense."""
    num = len(debtors)
    per_person = (total_cost / num).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    remainder = total_cost - (per_person * num)

    payload: dict = {
        "cost": str(total_cost),
        "description": description,
        "currency_code": "GBP",
        "category_id": SPORTS_CATEGORY_ID,
        "users__0__user_id": sw_user_id,
        "users__0__paid_share": str(total_cost),
        "users__0__owed_share": "0.00",
    }
    for idx, email in enumerate(debtors, start=1):
        owed = per_person + (remainder if idx == 1 else Decimal("0"))
        payload[f"users__{idx}__email"] = email
        payload[f"users__{idx}__paid_share"] = "0.00"
        payload[f"users__{idx}__owed_share"] = str(owed)
    return payload


async def _validate_email(
    client: httpx.AsyncClient,
    headers: dict,
    sw_user_id: str,
    email: str,
) -> bool:
    """Return True if Splitwise can add this email as a participant.

    Creates and immediately deletes a £1 test expense. The create+delete
    happens within milliseconds so the Splitwise notification queue does
    not fire for the test expense.
    """
    payload = _build_payload(sw_user_id, Decimal("1.00"), "(SportScanner validation)", [email])
    r = await client.post(f"{SPLITWISE_API_BASE}/create_expense", data=payload, headers=headers)
    data = r.json()
    errors = data.get("errors", {})
    if errors and any(errors.values()):
        logger.info(f"Splitwise email validation failed for {email}: {errors}")
        return False
    expenses = data.get("expenses", [])
    if expenses:
        await client.post(
            f"{SPLITWISE_API_BASE}/delete_expense/{expenses[0]['id']}",
            headers=headers,
        )
    return True


async def create_expense(
    description: str,
    total_cost: Decimal,
    creator_email: str,
    participant_emails: list[str],
    api_key: str,
) -> tuple[Optional[str], Optional[str], set[str]]:
    """Create a Splitwise expense in GBP under the Sports category.

    Returns (expense_id, error_category, failed_emails):
      - (id,   None,  set())     — full success, everyone notified
      - (id,   None,  {emails})  — partial success, some emails unreachable
      - (None, error, set())     — complete failure
    """
    headers = {"Authorization": f"Bearer {api_key}"}

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            sw_user = await _get_sw_user(client, headers)
            if sw_user is None:
                return None, "auth_failed", set()

            # Deduplicate, exclude the Splitwise API account's own email
            seen: set[str] = {sw_user["email"]}
            debtors: list[str] = []
            for email in [creator_email] + participant_emails:
                key = email.lower()
                if key not in seen:
                    seen.add(key)
                    debtors.append(email)

            if not debtors:
                logger.warning("No debtors after deduplication — skipping Splitwise expense")
                return None, "unknown", set()

            # --- First attempt: all debtors ---
            payload = _build_payload(sw_user["id"], total_cost, description, debtors)
            r = await client.post(
                f"{SPLITWISE_API_BASE}/create_expense", data=payload, headers=headers
            )
            data = r.json()
            errors = data.get("errors", {})

            if not (errors and any(errors.values())):
                # Full success
                expenses = data.get("expenses", [])
                if not expenses:
                    return None, "unknown", set()
                expense_id = str(expenses[0]["id"])
                num = len(debtors)
                per_person = (total_cost / num).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                logger.info(f"Splitwise expense {expense_id} — {num} debtors each owe £{per_person}")
                return expense_id, None, set()

            category = _classify_error(errors)
            if category != "unregistered_email":
                logger.error(f"Splitwise expense errors ({category}): {errors}")
                return None, category, set()

            # --- Identify which emails Splitwise rejects ---
            logger.info("Full expense failed (unregistered_email) — validating each debtor individually")
            failed: set[str] = set()
            valid: list[str] = []
            for email in debtors:
                ok = await _validate_email(client, headers, sw_user["id"], email)
                if ok:
                    valid.append(email)
                else:
                    failed.add(email)
                    logger.warning(f"Splitwise cannot reach {email} — will be marked as unnotified")

            if not valid:
                logger.error("All emails rejected by Splitwise")
                return None, "unregistered_email", failed

            # --- Retry with only the valid debtors ---
            payload = _build_payload(sw_user["id"], total_cost, description, valid)
            r2 = await client.post(
                f"{SPLITWISE_API_BASE}/create_expense", data=payload, headers=headers
            )
            data2 = r2.json()
            errors2 = data2.get("errors", {})
            if errors2 and any(errors2.values()):
                logger.error(f"Splitwise retry also failed: {errors2}")
                return None, _classify_error(errors2), failed

            expenses2 = data2.get("expenses", [])
            if not expenses2:
                return None, "unknown", failed

            expense_id = str(expenses2[0]["id"])
            logger.info(
                f"Splitwise expense {expense_id} — {len(valid)} notified, {len(failed)} unreachable"
            )
            return expense_id, None, failed

        except Exception as exc:
            logger.error(f"Splitwise create_expense failed: {exc}")
            return None, "unknown", set()
