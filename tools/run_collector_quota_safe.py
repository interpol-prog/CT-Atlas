"""
Quota-safe launcher for collector.py.

Purpose:
- preserve collector.py as the main implementation;
- intercept only Gemini ARTICLE-SELECTION requests;
- stop immediately on a hard/daily/prepayment 429;
- keep ordinary transient 429 behaviour unchanged so collector.py can retry it;
- let collector.py save ai_article_selection_cache.json and exit safely with code 75.
"""

import json
import sys

import collector


_ORIGINAL_POST = collector.requests.post


def _flatten_error_payload(response):
    parts = []

    try:
        payload = response.json()
    except Exception:
        payload = None

    if payload is not None:
        try:
            parts.append(
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
        except Exception:
            parts.append(str(payload))

    try:
        parts.append(response.text or "")
    except Exception:
        pass

    return " ".join(parts).lower()


def _is_article_selection_request(kwargs):
    body = kwargs.get("json")

    if not isinstance(body, dict):
        return False

    instruction = str(
        body.get(
            "system_instruction",
            "",
        )
        or
        ""
    ).lower()

    if "final editorial relevance filter" in instruction:
        return True

    response_format = body.get("response_format")
    if not isinstance(response_format, dict):
        return False

    schema = response_format.get("schema")
    if not isinstance(schema, dict):
        return False

    properties = schema.get("properties")
    return (
        isinstance(properties, dict)
        and
        "results" in properties
    )


def _hard_quota_reason(response):
    if getattr(response, "status_code", None) != 429:
        return ""

    text = _flatten_error_payload(response)

    # Unambiguous billing/prepayment exhaustion.
    billing_markers = (
        "prepayment credits are depleted",
        "prepaid credits are depleted",
        "prepayment credit",
        "prepaid credit",
        "credits are depleted",
        "credit balance",
    )

    for marker in billing_markers:
        if marker in text:
            return marker

    # Daily/RPD quota identifiers used in Gemini / Google quota details.
    daily_markers = (
        "perday",
        "per day",
        "requestsperday",
        "requests_per_day",
        "requestperday",
        "request_per_day",
        "daily quota",
        "daily limit",
        "\"rpd\"",
    )

    quota_context = (
        "quota" in text
        or
        "resource_exhausted" in text
        or
        "too many requests" in text
    )

    if quota_context:
        for marker in daily_markers:
            if marker in text:
                return marker

    # Billing-account failures are also not cured by a short retry.
    if (
        "billing" in text
        and
        (
            "depleted" in text
            or
            "payment" in text
            or
            "credit" in text
            or
            "disabled" in text
        )
    ):
        return "billing"

    return ""


def quota_safe_post(url, *args, **kwargs):
    response = _ORIGINAL_POST(
        url,
        *args,
        **kwargs,
    )

    if (
        "generativelanguage.googleapis.com" in str(url)
        and
        _is_article_selection_request(kwargs)
        and
        getattr(response, "status_code", None) == 429
    ):
        reason = _hard_quota_reason(response)

        if reason:
            print(
                "   AI selection hard quota 429 detected; "
                "stopping immediately without retry storm."
            )
            print(
                f"   Hard quota indicator: {reason}"
            )

            raise collector.AISelectionQuotaError(
                "Gemini article-selection daily/prepayment quota reached. "
                "The run is stopping immediately; cached progress is preserved."
            )

    return response


collector.requests.post = quota_safe_post


if __name__ == "__main__":
    collector.main()
