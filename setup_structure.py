"""
setup_structure.py — Run this ONCE after downloading all files from the chat,
to lay them into the correct folder structure and create the empty
__init__.py package markers Python needs.

Usage:
    1. Create a project folder, e.g. return-abuse-sentinel/
    2. Put this script in that folder.
    3. Download every file from the chat's file panel into the SAME folder
       (flat, no subfolders) — this script will move each one to its
       correct destination path and create missing __init__.py files.
    4. Run: python setup_structure.py

If a file is already in place, it's left alone. Nothing is deleted.
"""
import os
import shutil

# Maps the flat downloaded filename -> its correct destination path.
# Adjust left-hand filenames if your browser auto-renamed downloads
# (e.g. "requirements(1).txt").
FILE_MOVES = {
    "requirements.txt": "requirements.txt",
    "env.example.txt": ".env.example",
    "docker-compose.yml": "docker-compose.yml",
    "alembic.ini": "alembic.ini",

    "config.py": "app/config.py",
    "database.py": "app/database.py",
    "db_models.py": "app/models/db_models.py",
    "auth.py": "app/api/auth.py",
    "schemas.py": "app/api/schemas.py",
    "main.py": "app/api/main.py",
    "ml_core.py": "app/services/ml_core.py",
    "feature_store.py": "app/services/feature_store.py",
    "kafka_client.py": "app/services/kafka_client.py",
    "scorer_worker.py": "app/services/scorer_worker.py",
    "webhook_dispatcher.py": "app/services/webhook_dispatcher.py",
    "pdf_export.py": "app/services/pdf_export.py",
    "drift_monitor.py": "app/monitoring/drift_monitor.py",
    "threshold_optimizer.py": "app/pipelines/threshold_optimizer.py",
    "train.py": "app/pipelines/train.py",
    "retrain.py": "app/pipelines/retrain.py",
    "ingest.py": "app/pipelines/ingest.py",

    "env.py": "migrations/env.py",
    "001_initial_schema.py": "migrations/versions/001_initial_schema.py",

    "Dockerfile.api.txt": "Dockerfile.api",
    "Dockerfile.scorer.txt": "Dockerfile.scorer",
    "Dockerfile.webhook.txt": "Dockerfile.webhook",

    "prometheus.yml": "monitoring/prometheus.yml",
    "bootstrap.py": "scripts/bootstrap.py",

    "package.json": "frontend/package.json",
    "vite.config.ts": "frontend/vite.config.ts",
    "tsconfig.json": "frontend/tsconfig.json",
    "index.html": "frontend/index.html",
    "Dockerfile.txt": "frontend/Dockerfile",
    "main.tsx": "frontend/src/main.tsx",
    "App.tsx": "frontend/src/App.tsx",
    "App.css.txt": "frontend/src/App.css",
    "api_client.ts": "frontend/src/api/client.ts",
}

INIT_FILES = [
    "app/__init__.py", "app/api/__init__.py", "app/services/__init__.py",
    "app/models/__init__.py", "app/monitoring/__init__.py", "app/pipelines/__init__.py",
    "scripts/__init__.py",
]

DIRS_TO_ENSURE = ["artifacts", "migrations/versions", "monitoring/grafana/dashboards"]


def main():
    moved, skipped = [], []
    for src, dest in FILE_MOVES.items():
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        if os.path.exists(dest):
            skipped.append(dest)
            continue
        if os.path.exists(src):
            shutil.move(src, dest)
            moved.append(f"{src} -> {dest}")
        else:
            skipped.append(f"MISSING SOURCE: {src} (expected -> {dest})")

    for path in INIT_FILES:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if not os.path.exists(path):
            open(path, "w").close()

    for d in DIRS_TO_ENSURE:
        os.makedirs(d, exist_ok=True)

    print("=== Moved ===")
    for m in moved:
        print(" ", m)
    print("\n=== Skipped / already present / missing ===")
    for s in skipped:
        print(" ", s)
    print("\nDone. Now copy .env.example to .env and edit JWT_SECRET_KEY, then run docker-compose up -d --build")


if __name__ == "__main__":
    main()
