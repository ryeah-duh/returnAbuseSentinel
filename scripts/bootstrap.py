"""
scripts/bootstrap.py — One-time local setup: run migrations, train the first
model, and issue an initial admin API key so you can log into the dashboard.

Run this ONCE after `docker-compose up -d` (with postgres/redis/kafka healthy):

    docker-compose exec api python -m scripts.bootstrap

It prints a raw admin API key to your terminal — copy it immediately, it is
never shown again (only its hash is stored).
"""
import logging
from app.database import init_db, SessionLocal
from app.models.db_models import Merchant
from app.api.auth import issue_api_key
from app.pipelines.train import main as train_main

logging.basicConfig(level="INFO", format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("bootstrap")


def main():
    logger.info("Step 1/3: Initializing database schema...")
    init_db()

    logger.info("Step 2/3: Training first model + seeding demo merchant...")
    train_main()

    logger.info("Step 3/3: Issuing admin API key for merchant M001...")
    db = SessionLocal()
    if not db.query(Merchant).filter_by(merchant_id="M001").first():
        db.add(Merchant(merchant_id="M001", name="Demo Fashion Co"))
        db.commit()
    admin_key = issue_api_key(db, "M001", "admin")
    ops_key = issue_api_key(db, "M001", "ops")
    auditor_key = issue_api_key(db, "M001", "auditor")
    db.close()

    print("\n" + "=" * 70)
    print("BOOTSTRAP COMPLETE — SAVE THESE KEYS NOW, THEY WON'T BE SHOWN AGAIN")
    print("=" * 70)
    print(f"Admin key   (full config access): {admin_key}")
    print(f"Ops key     (queue + evidence):   {ops_key}")
    print(f"Auditor key (read-only logs):     {auditor_key}")
    print("=" * 70)
    print("Exchange a key for a JWT with:")
    print('  curl -X POST http://localhost:8000/auth/token -H "Content-Type: application/json" \\')
    print(f'    -d \'{{"api_key": "{admin_key}"}}\'')
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
