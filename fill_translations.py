"""
fill_translations.py

Fills null translation and explanation fields for Uttara Kanda shlokas
using the Gemini 2.5 Flash API with structured JSON output.

Designed to run daily via GitHub Actions, staying within the 20 RPD free limit.
Each run processes MAX_BATCHES_PER_RUN batches of BATCH_SIZE shlokas.

Math: 18 batches × 5 shlokas = 90 shlokas/day, using 18 of 20 daily requests.

Requires:
    pip install google-generativeai

Environment variable:
    GEMINI_API_KEY — set in GitHub Secrets, or locally in your shell.
"""

import json
import os
import re
import sys
import time
from pathlib import Path

try:
    import google.generativeai as genai
except ImportError:
    print("ERROR: google-generativeai not installed.")
    print("Run: pip install google-generativeai")
    sys.exit(1)

# ── Config ────────────────────────────────────────────────────────────────────

DATA_PATH = Path(__file__).parent / "data" / "Valmiki_Ramayan_Shlokas.json"

MODEL_NAME        = "gemini-2.5-flash"   # stable alias; update if Google changes it
BATCH_SIZE        = 5                    # shlokas per API call
MAX_BATCHES_PER_RUN = 18                 # 18 calls/day leaves 2 buffer under 20 RPD limit
SLEEP_BETWEEN_CALLS = 13                 # seconds; enforces < 5 RPM (60s / 5 = 12s minimum)
API_TEMPERATURE   = 0.2                  # low = more consistent, less creative


# ── Colophon detection ────────────────────────────────────────────────────────
# These are end-of-sarga markers and closing dedications, not narrative shlokas.

COLOPHON_RE = re.compile(
    r"इत्यार्षे"       # "ityārṣe" — standard sarga-end phrase
    r"|समाप्त"         # "samāpta" — completed
    r"|सम्पूर्णम्"     # "sampūrṇam" — complete
    r"|अर्पणमस्तु"     # closing dedication
)

def is_colophon(entry: dict) -> bool:
    text = entry.get("shloka_text", "")
    # Pure closings start with ।। (e.g., "।। इत्युत्तरकाण्डः समाप्तः ।।")
    return text.strip().startswith("।।") or bool(COLOPHON_RE.search(text))


# ── Prompt ────────────────────────────────────────────────────────────────────
# Matches the style already in the dataset:
#   translation  → "SanskritWord EnglishMeaning, SanskritWord EnglishMeaning, ..."
#   explanation  → one clear English prose sentence

SYSTEM_PROMPT = """You are a Sanskrit scholar specializing in Valmiki Ramayana.
Translate Uttara Kanda shlokas in the style of classical commentaries.

Translation style (match exactly):
  "शृण्वन् one who listens, रामायणम् Ramayana, भक्त्या with devotion, यः who, ..."

Explanation style:
  One clear English prose sentence conveying the full meaning.

Return ONLY a valid JSON array. No markdown, no code blocks, no extra text.

Schema:
[
  {
    "idx": <integer matching input idx>,
    "translation": "<word-by-word meaning>",
    "explanation": "<one prose sentence>"
  }
]"""

def build_prompt(batch: list[tuple[int, dict]]) -> str:
    shlokas_block = json.dumps(
        [
            {
                "idx": local_idx,
                "shloka_text": entry["shloka_text"],
                "transliteration": entry.get("transliteration", ""),
            }
            for local_idx, entry in batch
        ],
        ensure_ascii=False,
        indent=2,
    )
    return f"{SYSTEM_PROMPT}\n\nShlokas:\n{shlokas_block}"


# ── API call ──────────────────────────────────────────────────────────────────

def call_gemini(model, prompt: str) -> list[dict] | None:
    try:
        response = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json",
                temperature=API_TEMPERATURE,
            ),
        )
        parsed = json.loads(response.text)
        if not isinstance(parsed, list):
            print(f"  WARNING: Response was not a list: {type(parsed)}")
            return None
        return parsed
    except json.JSONDecodeError as e:
        print(f"  ERROR: Could not parse JSON response — {e}")
        print(f"  Raw response: {response.text[:300]}")
        return None
    except Exception as e:
        print(f"  ERROR: API call failed — {e}")
        return None


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: GEMINI_API_KEY environment variable not set.")
        sys.exit(1)

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(MODEL_NAME)
    print(f"Model: {MODEL_NAME}")

    print(f"Loading {DATA_PATH} ...")
    with open(DATA_PATH, encoding="utf-8") as f:
        data = json.load(f)

    # Collect global indices of Uttara Kanda shlokas that need translation
    todo: list[int] = []
    colophons_skipped = 0
    for i, entry in enumerate(data):
        if entry.get("kanda") != "Uttara Kanda":
            continue
        if is_colophon(entry):
            colophons_skipped += 1
            continue
        if entry.get("translation") is None:
            todo.append(i)

    total_remaining = len(todo)
    print(f"Colophons skipped        : {colophons_skipped}")
    print(f"Shlokas needing translation: {total_remaining}")

    if not total_remaining:
        print("All translations already filled. Nothing to do.")
        return

    # Slice today's work
    batches = [todo[i : i + BATCH_SIZE] for i in range(0, len(todo), BATCH_SIZE)]
    todays_batches = batches[:MAX_BATCHES_PER_RUN]
    todays_shloka_count = sum(len(b) for b in todays_batches)

    print(f"This run   : {len(todays_batches)} batches ({todays_shloka_count} shlokas)")
    print(f"After run  : {max(0, total_remaining - todays_shloka_count)} shlokas remaining")
    print()

    filled = 0
    failed_batches = 0

    for batch_num, batch_indices in enumerate(todays_batches, 1):
        # Build (local_idx, entry) pairs so the model can echo back idx for matching
        batch = [(local_idx, data[global_idx]) for local_idx, global_idx in enumerate(batch_indices)]

        first_entry = data[batch_indices[0]]
        print(
            f"Batch {batch_num:>2}/{len(todays_batches)} | "
            f"Sarga {first_entry['sarga']:>3} | "
            f"Shlokas {[data[i]['shloka'] for i in batch_indices]}"
        )

        prompt  = build_prompt(batch)
        results = call_gemini(model, prompt)

        if results is None:
            print(f"  FAILED — skipping entire batch.")
            failed_batches += 1
        else:
            results_by_idx = {r["idx"]: r for r in results if "idx" in r}

            for local_idx, global_idx in enumerate(batch_indices):
                result = results_by_idx.get(local_idx)
                if result is None:
                    print(f"  WARNING: No result for idx {local_idx} "
                          f"(Sarga {data[global_idx]['sarga']}, "
                          f"Shloka {data[global_idx]['shloka']})")
                    continue
                data[global_idx]["translation"] = result.get("translation")
                data[global_idx]["explanation"] = result.get("explanation")
                filled += 1

        # Save after every batch — so a mid-run crash doesn't lose completed work
        with open(DATA_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

        if batch_num < len(todays_batches):
            time.sleep(SLEEP_BETWEEN_CALLS)

    print()
    print(f"Filled this run  : {filled}")
    print(f"Failed batches   : {failed_batches}")
    print(f"Still remaining  : {max(0, total_remaining - filled)}")
    print("Done.")


if __name__ == "__main__":
    main()
