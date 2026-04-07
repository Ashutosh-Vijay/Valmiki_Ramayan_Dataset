"""
fill_transliteration.py

Fills null transliteration fields for Kaands 1-6 using the indic-transliteration library.
Uttara Kanda is skipped (already has transliteration filled).

Install dependency first:
    pip install indic-transliteration

Run:
    python fill_transliteration.py
"""

import json
import re
import sys
from pathlib import Path

try:
    from indic_transliteration import sanscript
    from indic_transliteration.sanscript import transliterate
except ImportError:
    print("ERROR: indic-transliteration not installed.")
    print("Run: pip install indic-transliteration")
    sys.exit(1)

DATA_PATH = Path(__file__).parent / "data" / "Valmiki_Ramayan_Shlokas.json"

# Matches embedded shloka numbers like ।।1.1.2।।  or ।। 7.18.20 ।।
SHLOKA_NUMBER_RE = re.compile(r"।।\s*[\d]+\.[\d]+\.[\d]+\s*।।")


def clean_shloka_text(text: str) -> str:
    """Remove embedded shloka number notation before transliterating."""
    return SHLOKA_NUMBER_RE.sub("", text).strip()


def main():
    print(f"Loading {DATA_PATH} ...")
    with open(DATA_PATH, encoding="utf-8") as f:
        data = json.load(f)

    total = len(data)
    filled = 0
    skipped_uttara = 0
    already_filled = 0

    # Track duplicate shloka_text within Kaands 1-6
    seen_texts: dict[str, list[tuple]] = {}

    for entry in data:
        if entry.get("kanda") == "Uttara Kanda":
            skipped_uttara += 1
            continue

        shloka_text = entry.get("shloka_text", "")
        key = shloka_text.strip()
        if key:
            loc = (entry.get("kanda"), entry.get("sarga"), entry.get("shloka"))
            seen_texts.setdefault(key, []).append(loc)

        if entry.get("transliteration") is not None:
            already_filled += 1
            continue

        if not shloka_text:
            continue

        clean_text = clean_shloka_text(shloka_text)
        iast = transliterate(clean_text, sanscript.DEVANAGARI, sanscript.IAST)
        entry["transliteration"] = iast
        filled += 1

    # Build duplicate report
    duplicates = {text: locs for text, locs in seen_texts.items() if len(locs) > 1}
    dup_entry_count = sum(len(v) for v in duplicates.values())

    print(f"Total entries        : {total}")
    print(f"Uttara Kanda skipped : {skipped_uttara}")
    print(f"Already had value    : {already_filled}")
    print(f"Filled now           : {filled}")
    print(f"\n--- Merged/Duplicate Shloka Report (Kaands 1-6) ---")
    print(f"Unique merged groups : {len(duplicates)}")
    print(f"Entries affected     : {dup_entry_count}")

    report_path = Path(__file__).parent / "merged_shlokas_report.txt"
    with open(report_path, "w", encoding="utf-8") as rf:
        rf.write(f"Unique merged groups : {len(duplicates)}\n")
        rf.write(f"Entries affected     : {dup_entry_count}\n\n")
        for text, locs in duplicates.items():
            rf.write(f"Locations: {locs}\n")
            rf.write(f"Text: {text[:120]}\n\n")
    print(f"Duplicate report written to: {report_path}")

    print(f"\nWriting back to {DATA_PATH} ...")
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

    print("Done.")


if __name__ == "__main__":
    main()
