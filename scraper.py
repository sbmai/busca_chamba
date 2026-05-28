"""
Peru Finance & Strategy Job Scraper
====================================
Usage:
    python scraper.py                        # run all scrapers
    python scraper.py --scraper bumeran      # run one scraper
    python scraper.py --no-export            # skip Excel output
    python scraper.py --output mis_jobs.xlsx # custom filename
"""

import sqlite3
import logging
import argparse
from datetime import datetime

from scrapers.linkedin import LinkedInScraper
from scrapers.bumeran import BumeranScraper
from scrapers.computrabajo import ComputrabajoScraper
from scrapers.indeed import IndeedScraper
from scrapers.empresas_peru import EmpresasPeruScraper
from filters import filter_jobs
from export import export_to_excel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)-22s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("scraper")

DB_PATH = "jobs.db"

SCRAPERS = {
    "linkedin":      LinkedInScraper,
    "bumeran":       BumeranScraper,
    "computrabajo":  ComputrabajoScraper,
    "indeed":        IndeedScraper,
    "empresas":      EmpresasPeruScraper,
}


# ── Database ──────────────────────────────────────────────────────────────────

def init_db(conn: sqlite3.Connection) -> None:
    # Create table (fresh install)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            title             TEXT    NOT NULL,
            company           TEXT    DEFAULT '',
            location          TEXT    DEFAULT '',
            salary            TEXT    DEFAULT '',
            date_posted       TEXT    DEFAULT '',
            url               TEXT    UNIQUE NOT NULL,
            source            TEXT    NOT NULL,
            seniority         TEXT    DEFAULT '',
            scraped_at        TEXT    NOT NULL,
            primera_vez_visto TEXT    DEFAULT '',
            tipo_fuente       TEXT    DEFAULT 'Portal',
            fecha_ingreso_db  TEXT    DEFAULT ''
        )
    """)

    # ── Migrations (safe to run on existing DB) ───────────────────────────────
    # Add primera_vez_visto column if upgrading from older schema
    try:
        conn.execute("ALTER TABLE jobs ADD COLUMN primera_vez_visto TEXT DEFAULT ''")
        logger.info("Migration: added column primera_vez_visto")
    except sqlite3.OperationalError:
        pass  # column already exists

    # Backfill primera_vez_visto from scraped_at for existing rows
    conn.execute(
        "UPDATE jobs SET primera_vez_visto = DATE(scraped_at) WHERE primera_vez_visto = ''"
    )

    # Deduplicate existing rows (keep oldest id) before creating unique index
    conn.execute("""
        DELETE FROM jobs WHERE id NOT IN (
            SELECT MIN(id) FROM jobs
            GROUP BY lower(title), lower(company), lower(source)
        )
    """)

    # Unique index on (title, company, source) to prevent content-level duplicates
    try:
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_dedup_content
            ON jobs(title COLLATE NOCASE, company COLLATE NOCASE, source COLLATE NOCASE)
        """)
    except sqlite3.OperationalError as e:
        logger.warning(f"Could not create dedup index (non-fatal): {e}")

    # Add tipo_fuente column (fresh installs get it from CREATE TABLE above)
    try:
        conn.execute("ALTER TABLE jobs ADD COLUMN tipo_fuente TEXT DEFAULT 'Portal'")
        logger.info("Migration: added column tipo_fuente")
    except sqlite3.OperationalError:
        pass  # column already exists

    # Backfill portal scrapers as "Portal", company pages as "Empresa Directa"
    conn.execute("""
        UPDATE jobs SET tipo_fuente = 'Portal'
        WHERE tipo_fuente = '' OR tipo_fuente IS NULL
    """)

    # Add fecha_ingreso_db column (records when job was first inserted)
    try:
        conn.execute("ALTER TABLE jobs ADD COLUMN fecha_ingreso_db TEXT DEFAULT ''")
        logger.info("Migration: added column fecha_ingreso_db")
    except sqlite3.OperationalError:
        pass  # column already exists

    # Backfill fecha_ingreso_db from scraped_at for rows that predate this column
    conn.execute("""
        UPDATE jobs SET fecha_ingreso_db = scraped_at
        WHERE fecha_ingreso_db = '' OR fecha_ingreso_db IS NULL
    """)

    conn.execute("CREATE INDEX IF NOT EXISTS idx_scraped_at      ON jobs(scraped_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_source          ON jobs(source)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tipo_fuente     ON jobs(tipo_fuente)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_fecha_ingreso   ON jobs(fecha_ingreso_db)")
    conn.commit()


def expire_old_jobs(conn: sqlite3.Connection, days: int = 7) -> int:
    """Delete jobs first saved to the DB more than `days` days ago."""
    cursor = conn.execute(
        """DELETE FROM jobs
           WHERE fecha_ingreso_db != ''
             AND DATE(fecha_ingreso_db) < DATE('now', ?)""",
        (f"-{days} days",),
    )
    conn.commit()
    expired = cursor.rowcount
    if expired:
        logger.info(f"Expired {expired} jobs older than {days} days")
    else:
        logger.info("No expired jobs to remove")
    return expired


def save_jobs(conn: sqlite3.Connection, jobs: list) -> tuple[int, int]:
    saved = 0
    skipped = 0
    for job in jobs:
        try:
            now = datetime.now()
            conn.execute(
                """
                INSERT OR IGNORE INTO jobs
                    (title, company, location, salary, date_posted,
                     url, source, seniority, scraped_at, primera_vez_visto,
                     tipo_fuente, fecha_ingreso_db)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.get("title", ""),
                    job.get("company", ""),
                    job.get("location", ""),
                    job.get("salary", ""),
                    job.get("date_posted", ""),
                    job["url"],
                    job.get("source", ""),
                    job.get("seniority", ""),
                    now.isoformat(),
                    now.date().isoformat(),
                    job.get("tipo_fuente", "Portal"),
                    now.isoformat(),          # fecha_ingreso_db — never updated
                ),
            )
            if conn.execute("SELECT changes()").fetchone()[0]:
                saved += 1
            else:
                skipped += 1
        except Exception as e:
            logger.error(f"DB insert error for {job.get('url')}: {e}")
    conn.commit()
    return saved, skipped


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Peru Finance Job Scraper")
    parser.add_argument(
        "--scraper",
        choices=list(SCRAPERS.keys()),
        help="Run only one scraper (default: all)",
    )
    parser.add_argument("--no-export", action="store_true", help="Skip Excel export")
    parser.add_argument("--output", default="jobs_today.xlsx", help="Output Excel filename")
    args = parser.parse_args()

    to_run = (
        {args.scraper: SCRAPERS[args.scraper]}
        if args.scraper
        else SCRAPERS
    )

    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    # Auto-expire jobs older than 7 days to keep the DB and Excel fresh
    expired = expire_old_jobs(conn, days=7)
    logger.info(f"Expired {expired} jobs older than 7 days")

    all_raw: list = []
    for name, ScraperClass in to_run.items():
        sep = "─" * 48
        logger.info(sep)
        logger.info(f"  Scraping: {name.upper()}")
        logger.info(sep)
        try:
            scraper = ScraperClass()
            raw = scraper.scrape()
            logger.info(f"  {name}: {len(raw)} raw jobs collected")
            all_raw.extend(raw)
        except Exception as e:
            logger.error(f"  {name} FAILED: {e}", exc_info=True)

    logger.info(f"\nTotal raw jobs across all sources : {len(all_raw)}")

    filtered = filter_jobs(all_raw)
    logger.info(f"After keyword + seniority filter  : {len(filtered)}")

    saved, skipped = save_jobs(conn, filtered)
    logger.info(f"New jobs saved to DB              : {saved}")
    logger.info(f"Already in DB (duplicates)        : {skipped}")

    if not args.no_export:
        count = export_to_excel(conn, args.output)
        logger.info(f"Excel exported → {args.output}  ({count} rows)")

    conn.close()
    logger.info("Done.")


if __name__ == "__main__":
    main()
