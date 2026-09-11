"""One-off corrective pass: re-normalize actor_group values already stored
in events.json using collector.py's ACTOR_GROUP_ALIASES table, plus a
generic case-variant collapse for anything not covered by an explicit alias.

Pure string processing -- no Gemini calls, no network access. Safe to run
any time an alias is added to ACTOR_GROUP_ALIASES to retroactively fix
already-stored events instead of waiting for/paying for a full AI backfill.

Usage: python tools/normalize_actor_group.py
"""

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import collector  # noqa: E402


def main():
    db = collector.load_database_strict()
    events = db["events"]

    before_counts = Counter(
        e["actor_group"] for e in events if e.get("actor_group")
    )

    # Pass 1: explicit alias table (collector.ACTOR_GROUP_ALIASES).
    changed = 0
    for event in events:
        raw = event.get("actor_group")
        if not raw:
            continue
        canonical = collector.canonicalize_actor_group(raw)
        if canonical != raw:
            event["actor_group"] = canonical
            changed += 1

    # Pass 2: generic case-variant collapse for anything the alias table
    # didn't cover -- if the same lowercase form still has more than one
    # distinct casing in the data, keep whichever casing is most frequent
    # and remap the rest to it.
    after_pass1_counts = Counter(
        e["actor_group"] for e in events if e.get("actor_group")
    )
    by_lower = {}
    for value, count in after_pass1_counts.items():
        by_lower.setdefault(value.lower(), []).append((value, count))

    case_canonical = {}
    for lower_key, variants in by_lower.items():
        if len(variants) <= 1:
            continue
        variants.sort(key=lambda item: item[1], reverse=True)
        winner = variants[0][0]
        for value, _ in variants:
            if value != winner:
                case_canonical[value] = winner

    if case_canonical:
        print("Case-variant collapses applied:")
        for old, new in case_canonical.items():
            print(f"   {old!r} -> {new!r}")
        for event in events:
            raw = event.get("actor_group")
            if raw in case_canonical:
                event["actor_group"] = case_canonical[raw]
                changed += 1

    after_counts = Counter(
        e["actor_group"] for e in events if e.get("actor_group")
    )

    print(f"\nDistinct actor_group values before: {len(before_counts)}")
    print(f"Distinct actor_group values after:  {len(after_counts)}")
    print(f"Event fields rewritten: {changed}")

    merged = set(before_counts) - set(after_counts)
    if merged:
        print("\nValues eliminated by merging:")
        for value in sorted(merged):
            print(f"   {value!r} ({before_counts[value]} event(s))")

    if changed:
        collector.atomic_json_write(collector.OUTPUT_FILE, db)
        print(f"\n{collector.OUTPUT_FILE} written.")
    else:
        print("\nNo changes; events.json left untouched.")


if __name__ == "__main__":
    main()
