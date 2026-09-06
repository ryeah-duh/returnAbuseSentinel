"""
check_files.py — Run this INSIDE your project folder, right after downloading
everything and BEFORE running setup_structure.py. It just verifies you have
every file the new production build needs, with none missing or misnamed.

Usage:
    cd return-abuse-sentinel
    python check_files.py
"""
import os

EXPECTED = [
    "requirements.txt", "env.example.txt", "docker-compose.yml", "alembic.ini",
    "config.py", "database.py", "db_models.py", "auth.py", "schemas.py", "main.py",
    "ml_core.py", "feature_store.py", "kafka_client.py", "scorer_worker.py",
    "webhook_dispatcher.py", "pdf_export.py", "drift_monitor.py",
    "threshold_optimizer.py", "train.py", "retrain.py", "ingest.py",
    "env.py", "001_initial_schema.py", "Dockerfile.api.txt", "Dockerfile.scorer.txt",
    "Dockerfile.webhook.txt", "prometheus.yml", "bootstrap.py",
    "package.json", "vite.config.ts", "tsconfig.json", "index.html", "Dockerfile.txt",
    "main.tsx", "App.tsx", "App.css.txt", "api_client.ts",
    "setup_structure.py", "DEPLOY.md",
]

# Files that belong to the OLD static demo — flag if found mixed in here,
# they should live in a separate folder instead.
OLD_DEMO_FILES = ["train_model.py", "evidence_engine.py", "dashboard.py"]


def main():
    missing = [f for f in EXPECTED if not os.path.exists(f)]
    present = [f for f in EXPECTED if os.path.exists(f)]
    old_demo_found = [f for f in OLD_DEMO_FILES if os.path.exists(f)]

    print(f"Present: {len(present)}/{len(EXPECTED)}")

    if missing:
        print("\nMISSING (re-download these from the chat file panel):")
        for m in missing:
            print(" -", m)
    else:
        print("All expected new-architecture files found.")

    if old_demo_found:
        print("\nWARNING: found old static-demo files mixed into this folder:")
        for f in old_demo_found:
            print(" -", f)
        print("These belong to the OLD simple demo, not this Docker stack.")
        print("Move them to a separate folder — they won't break anything here,")
        print("but they're not used by setup_structure.py or docker-compose.")

    if not missing:
        print("\nSafe to run: python setup_structure.py")


if __name__ == "__main__":
    main()
