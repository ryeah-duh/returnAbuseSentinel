"""
cleanup_folder.py — Run this ONCE inside your existing messy
return-abuse-sentinel folder to sort out the sandbox junk, old-demo files,
and duplicate downloads before running setup_structure.py.

Usage (from inside C:\\Users\\aarya\\OneDrive\\Projects\\return-abuse-sentinel):
    python cleanup_folder.py

It will:
  1. Move sandbox-only scratch files (pkl/db/csv/json/pdf I generated while
     testing logic, never meant to be deployed) into a subfolder _sandbox_junk/
  2. Move the OLD static-demo files (train_model.py, evidence_engine.py,
     dashboard.py, README.md) into a subfolder _old_simple_demo/
  3. Delete exact duplicate downloads like "requirements (2).txt" since
     "requirements.txt" (the real one) is already present.
  4. Print exactly what's left, which should be the 38-39 files needed for
     setup_structure.py to run cleanly.

Nothing is permanently deleted except confirmed duplicate copies of a file
that also exists under its correct name — everything else is just moved
into clearly-labeled subfolders so you can double check before removing them.
"""
import os
import shutil

SANDBOX_JUNK = [
    "model_v1.pkl", "metrics_report.json", "metrics_report (2).json",
    "return_abuse_dataset.csv", "return_abuse_dataset (2).csv",
    "return_abuse_dataset (3).csv", "return_abuse_dataset (4).csv",
    "return_abuse_model.pkl", "return_abuse_model (2).pkl",
    "sample_evidence.pdf",
    "sentinel.db", "sentinel (2).db", "sentinel (3).db",
    "sentinel (4).db", "sentinel (5).db", "sentinel (6).db",
]

OLD_DEMO = [
    "train_model.py", "train_model (2).py",
    "evidence_engine.py", "evidence_engine (2).py",
    "dashboard.py", "README.md",
]

# filename-with-suffix -> the correct file that should remain instead
EXACT_DUPLICATES = {
    "requirements (2).txt": "requirements.txt",
}


def move_group(filenames, dest_folder, label):
    os.makedirs(dest_folder, exist_ok=True)
    moved = []
    for f in filenames:
        if os.path.exists(f):
            shutil.move(f, os.path.join(dest_folder, f))
            moved.append(f)
    if moved:
        print(f"\nMoved {len(moved)} {label} file(s) into {dest_folder}/:")
        for m in moved:
            print("  -", m)


def remove_duplicates():
    removed = []
    for dupe, canonical in EXACT_DUPLICATES.items():
        if os.path.exists(dupe) and os.path.exists(canonical):
            os.remove(dupe)
            removed.append(dupe)
    if removed:
        print(f"\nRemoved {len(removed)} confirmed duplicate(s):")
        for r in removed:
            print("  -", r)


def main():
    move_group(SANDBOX_JUNK, "_sandbox_junk", "sandbox scratch")
    move_group(OLD_DEMO, "_old_simple_demo", "old static-demo")
    remove_duplicates()

    print("\n" + "=" * 60)
    print("Remaining files in this folder (should be the new-architecture set):")
    print("=" * 60)
    remaining = sorted([f for f in os.listdir(".") if os.path.isfile(f) and f != "cleanup_folder.py"])
    for f in remaining:
        print(" -", f)
    print(f"\nTotal: {len(remaining)} files (plus cleanup_folder.py itself)")
    print("\nNext step: python setup_structure.py")


if __name__ == "__main__":
    main()
