"""
ISO-NE & NYISO Preliminary Real-Time Five-Minute LMP Downloader
----------------------------------------------------------------
Uses the open-source `gridstatus` library to pull ISO-NE and NYISO
5-minute LMP data automatically every 2 minutes. No account required.

Install dependencies:
    pip install gridstatus pandas

Usage:
    python isone_download_5min_lmp.py

Output:
    - Timestamped CSVs saved to ./downloads/
    - Master files: isone_5min_lmp_MASTER.csv, nyiso_5min_lmp_MASTER.csv

Location options (edit LOCATIONS below):
    "ALL"                  → every hub, zone, and interface
    ["H.INTERNAL_HUB"]    → ISO-NE Hub only
    [".Z.MAINE", ".Z.CONNECTICUT", ...]  → specific load zones

All available ISO-NE zones:
    .Z.MAINE, .Z.NEWHAMPSHIRE, .Z.VERMONT, .Z.CONNECTICUT,
    .Z.RHODEISLAND, .Z.SEMASS, .Z.WCMASS, .Z.NEMASSBOST
"""

import os
import sys
import time
import gridstatus
from datetime import datetime
from collections import deque
import pandas as pd

# Force pandas to never truncate rows or columns in terminal output
pd.set_option("display.max_columns", None)   # show all columns, never add ...
pd.set_option("display.max_rows", None)       # never truncate rows in preview
pd.set_option("display.width", None)          # auto-detect terminal width
pd.set_option("display.max_colwidth", None)   # don't truncate long cell values

# ── Config ────────────────────────────────────────────────────────────────────

LOCATIONS       = "ALL"
# Always save files next to this script, not wherever the terminal was opened.
# This prevents "read-only file system" errors when the terminal's working
# directory happens to be / or another protected system folder.
SCRIPT_DIR      = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR      = os.path.join(SCRIPT_DIR, "downloads_ISO")
ISONE_MASTER    = os.path.join(OUTPUT_DIR, "isone_5min_lmp_MASTER.csv")
NYISO_MASTER    = os.path.join(OUTPUT_DIR, "nyiso_5min_lmp_MASTER.csv")
POLL_INTERVAL   = 120          # seconds between each fetch attempt (2 minutes)
RECENT_FILES_N  = 5            # how many recent downloaded files to display


# ── Master file helpers ───────────────────────────────────────────────────────

def append_to_master(df, master_path: str, time_col: str = "Time"):
    """
    Append new rows to the master CSV. Dedupes on (Time + Location) so that
    running during the same 5-minute interval never adds duplicate rows.
    Returns: (min_time, max_time, total_row_count, was_duplicate)
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    if os.path.exists(master_path):
        existing = pd.read_csv(master_path)
        # CRITICAL: parse Time immediately so it's a Timestamp, not a string.
        # Without this, drop_duplicates sees str != Timestamp and misses dupes.
        if time_col in existing.columns:
            existing[time_col] = pd.to_datetime(existing[time_col], utc=True)
        rows_before = len(existing)
        combined = pd.concat([existing, df], ignore_index=True)
    else:
        rows_before = 0
        combined = df.copy()

    # Dedupe on Time + Location (same interval pulled twice = no new rows)
    dedupe_cols = [c for c in [time_col, "Location"] if c in combined.columns]
    if dedupe_cols:
        combined = combined.drop_duplicates(subset=dedupe_cols, keep="last")

    # Sort chronologically
    if time_col in combined.columns:
        combined[time_col] = pd.to_datetime(combined[time_col], utc=True)
        combined = combined.sort_values(time_col)

    combined.to_csv(master_path, index=False)

    rows_after = len(combined)
    was_duplicate = (rows_after == rows_before)

    if time_col in combined.columns and len(combined) > 0:
        return combined[time_col].min(), combined[time_col].max(), rows_after, was_duplicate
    return None, None, rows_after, was_duplicate


def count_intervals(master_path: str, time_col: str = "Time") -> int:
    """Count how many distinct 5-minute snapshots are in a master file."""
    if not os.path.exists(master_path):
        return 0
    existing = pd.read_csv(master_path)
    if time_col not in existing.columns:
        return 0
    return existing[time_col].nunique()


# ── Downloaders ───────────────────────────────────────────────────────────────

def download_lmp():
    """Fetch latest ISO-NE RT 5-Min LMPs, save snapshot, append to master."""
    iso = gridstatus.ISONE()

    print("----------- NE ISO ----------")
    print("Fetching latest ISO-NE Preliminary Real-Time 5-Minute LMPs...")
    df = iso.get_lmp(date="latest", market="REAL_TIME_5_MIN", locations=LOCATIONS)

    if df is None or df.empty:
        raise ValueError("No data returned. The market may not be active right now.")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = os.path.join(OUTPUT_DIR, f"isone_5min_lmp_{timestamp}.csv")
    df.to_csv(filepath, index=False)

    isone_range = append_to_master(df, ISONE_MASTER)
    was_duplicate = isone_range[3]

    # If duplicate, delete the snapshot we just saved (it's identical to what's
    # already in master, so keeping it would just waste disk space).
    # Safe to do because the master file is written and closed before this runs.
    if was_duplicate:
        os.remove(filepath)
        print(f"  (Duplicate interval — snapshot deleted, master unchanged)")
    else:
        print(f"✓ Saved {len(df)} rows → {filepath}")

    return filepath, df, isone_range, was_duplicate


def download_nyiso_lmp():
    """Fetch latest NYISO RT 5-Min LMPs, save snapshot, append to master."""
    nyiso = gridstatus.NYISO()

    print()
    print("----------- NY ISO ----------")
    print("Fetching latest NYISO Real-Time 5-Minute LMPs...")
    df = nyiso.get_lmp(date="latest", market="REAL_TIME_5_MIN", locations="ALL")

    if df is None or df.empty:
        raise ValueError("No NYISO data returned. The market may not be active right now.")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = os.path.join(OUTPUT_DIR, f"nyiso_5min_lmp_{timestamp}.csv")
    df.to_csv(filepath, index=False)

    nyiso_range = append_to_master(df, NYISO_MASTER)
    was_duplicate = nyiso_range[3]

    if was_duplicate:
        os.remove(filepath)
        print(f"  (Duplicate interval — snapshot deleted, master unchanged)")
    else:
        print(f"✓ Saved {len(df)} rows → {filepath}")

    return filepath, df, nyiso_range, was_duplicate


# ── Previews ──────────────────────────────────────────────────────────────────

def preview(df, label: str, rows: int = 10, max_cols: int = None):
    """Unified preview for any ISO dataframe. Optionally cap columns."""
    display_df = df.iloc[:, :max_cols] if max_cols else df
    actual_rows = min(rows, len(df))
    col_count = len(display_df.columns)
    total_cols = len(df.columns)
    col_note = f", first {col_count} of {total_cols} columns" if max_cols else f", {total_cols} columns"
    print(f"\n── {label} Preview (first {actual_rows} of {len(df)} rows{col_note}) ──")
    print(display_df.head(rows).to_string(index=False))


# ── Screen control ───────────────────────────────────────────────────────────

def clear_screen():
    """
    Clear output correctly depending on the environment:
    - VS Code terminal: uses ANSI escape codes (IPython is present but shouldn't
      be used here — clear_output only works in notebook cells, not terminals)
    - Google Colab / Jupyter notebook: uses IPython.display.clear_output
    - Standard terminal (Mac/Linux/Windows): uses ANSI escape codes
    """
    in_vscode   = "VSCODE_PID" in os.environ or "TERM_PROGRAM" in os.environ and os.environ.get("TERM_PROGRAM") == "vscode"
    in_notebook = "ipykernel" in sys.modules and not in_vscode

    if in_notebook:
        from IPython.display import clear_output
        clear_output(wait=True)
    else:
        # Works in VS Code terminal, standard terminals on Mac/Linux/Windows
        print("\033[2J\033[H", end="", flush=True)


# ── Summary printer ───────────────────────────────────────────────────────────

def print_summary(isone_range, nyiso_range,
                  isone_dup, nyiso_dup,
                  recent_isone, recent_nyiso,
                  last_run_time, run_count):

    fmt = "%B %d, %Y %I:%M:%S %p %Z"

    print()
    print("=" * 60)
    print("             MASTER DOCUMENTS SUMMARY")
    print(f"         (screen refreshed each cycle — run #{run_count})")
    print("=" * 60)

    # ── Recent files ──
    print("\n── Recent ISO-NE files downloaded ──")
    if recent_isone:
        for f in recent_isone:
            print(f"  {f}")
    else:
        print("  (none yet)")

    print("\n── Recent NYISO files downloaded ──")
    if recent_nyiso:
        for f in recent_nyiso:
            print(f"  {f}")
    else:
        print("  (none yet)")

    # ── Master doc ranges ──
    print()
    print("NE ISO MASTER DOC")
    if isone_range and isone_range[0] is not None:
        start, end, count, _ = isone_range
        print(f"  Spans:     {start.strftime(fmt)} → {end.strftime(fmt)}")
        print(f"  Rows:      {count} total rows")
        print(f"  Intervals: {count_intervals(ISONE_MASTER)} unique 5-minute snapshots")

    print()
    print("NY ISO MASTER DOC")
    if nyiso_range and nyiso_range[0] is not None:
        start, end, count, _ = nyiso_range
        print(f"  Spans:     {start.strftime(fmt)} → {end.strftime(fmt)}")
        print(f"  Rows:      {count} total rows")
        print(f"  Intervals: {count_intervals(NYISO_MASTER)} unique 5-minute snapshots")

    # ── Last run time ──
    print()
    print(f"Last execution: {last_run_time.strftime(fmt)}")

    # ── Duplicate / success notification (ALL CAPS, always last) ──
    print()
    if isone_dup and nyiso_dup:
        print("DUPLICATE DETECTED FOR BOTH ISO-NE AND NYISO — NO NEW DATA WAS ADDED TO EITHER MASTER FILE.")
    elif isone_dup:
        print("DUPLICATE DETECTED FOR ISO-NE — NO NEW DATA WAS ADDED TO THE ISO-NE MASTER FILE.")
        print("NYISO UPDATE SUCCESSFUL — NEW DATA HAS BEEN ADDED TO THE NYISO MASTER FILE.")
    elif nyiso_dup:
        print("DUPLICATE DETECTED FOR NYISO — NO NEW DATA WAS ADDED TO THE NYISO MASTER FILE.")
        print("ISO-NE UPDATE SUCCESSFUL — NEW DATA HAS BEEN ADDED TO THE ISO-NE MASTER FILE.")
    else:
        print("UPDATE SUCCESSFUL — NEW DATA HAS BEEN ADDED TO BOTH MASTER FILES.")

    print("=" * 60)


# ── Main loop ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":

    recent_isone = deque(maxlen=RECENT_FILES_N)   # keeps last N file paths
    recent_nyiso = deque(maxlen=RECENT_FILES_N)

    isone_range = nyiso_range = None
    isone_dup = nyiso_dup = False
    run_count = 0

    while True:
        run_count += 1
        last_run_time = datetime.now()

        # Clear screen at the start of every cycle so output replaces itself
        clear_screen()
        print(f"Scheduler running — cycle #{run_count} — fetching every {POLL_INTERVAL // 60} min.")
        print("Press Ctrl+C to stop.\n")

        # ── ISO-NE ──
        try:
            filepath, df, isone_range, isone_dup = download_lmp()
            preview(df, label="ISO-NE")
            if not isone_dup:
                recent_isone.append(filepath)
        except Exception as e:
            print(f"ISO-NE Error: {e}")
            isone_dup = False

        # ── NYISO ──
        try:
            nyiso_filepath, nyiso_df, nyiso_range, nyiso_dup = download_nyiso_lmp()
            preview(nyiso_df, label="NYISO", max_cols=10)
            if not nyiso_dup:
                recent_nyiso.append(nyiso_filepath)
        except Exception as e:
            print(f"NYISO Error: {e}")
            nyiso_dup = False

        # ── Summary (always last) ──
        print_summary(
            isone_range, nyiso_range,
            isone_dup, nyiso_dup,
            list(recent_isone), list(recent_nyiso),
            last_run_time, run_count,
        )

        print(f"\nSleeping {POLL_INTERVAL // 60} minutes until next fetch...\n")
        time.sleep(POLL_INTERVAL)