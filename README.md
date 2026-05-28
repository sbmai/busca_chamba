# busca_chamba — Peru Finance & Strategy or [Insert Roles] Job Scraper

Scrapes senior finance, strategy, and business-development or [Insert Role] roles in Peru from
**LinkedIn**, **Bumeran**, **Computrabajo**, and **Indeed Peru**.

Results are stored in a local SQLite database (`jobs.db`) and exported to a
formatted Excel file (`jobs_today.xlsx`).

---

## Requirements

- Python 3.10+
- pip

## Installation

```bash
# 1. Clone or download this folder, then:
cd busca_chamba

# 2. (Optional but recommended) create a virtual environment
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Mac/Linux

# 3. Install dependencies
pip install -r requirements.txt
```

---

## Usage

```bash
# Run all scrapers → saves to jobs.db + exports jobs_today.xlsx
python scraper.py

# Run a single scraper only
python scraper.py --scraper bumeran
python scraper.py --scraper computrabajo
python scraper.py --scraper linkedin
python scraper.py --scraper indeed

# Custom output filename
python scraper.py --output empleos_mayo.xlsx

# Skip Excel export (DB only)
python scraper.py --no-export
```

---

## Output

### jobs_today.xlsx

| Empresa | Puesto | Ubicación | Salario | Fecha | Seniority | URL | Fuente |
|---------|--------|-----------|---------|-------|-----------|-----|--------|

- Color-coded by seniority (yellow = Director/C-Level, green = Gerente, blue = Jefe/Senior)
- URLs are clickable hyperlinks
- Frozen header row + auto-filter
- "Resumen" sheet with counts by source and seniority

### jobs.db (SQLite)

```sql
-- Query example
SELECT title, company, location, salary, source
FROM jobs
WHERE DATE(scraped_at) = DATE('now')
  AND seniority = 'Director / C-Level'
ORDER BY company;
```

---

## Roles searched

Searches these keywords in Spanish + English:

- Planeamiento Financiero / FP&A
- Gerente / Director de Finanzas
- CFO / Chief Financial Officer
- Finanzas Corporativas
- Controller
- Desarrollo de Negocios / Business Development
- Gerente / Director Comercial
- Estrategia Corporativa / Planeamiento Estratégico
- Gerente de Estrategia

**Seniority filter** — only keeps titles with:
`Gerente`, `Director`, `Jefe`, `Senior`, `CFO`, `Head of`, `VP`, `Controller`, `Superintendente`

**Excludes**: practicantes, asistentes, analistas junior, trainees, interns

---

## Scheduling (daily run)

### Windows Task Scheduler

```
Action: python C:\path\to\busca_chamba\scraper.py
Trigger: Daily at 08:00
```

Or add to your PATH and use:
```
python -m scraper
```

### Cron (Linux/Mac)

```cron
0 8 * * 1-5  cd /path/to/busca_chamba && python scraper.py
```

---

## Known limitations

| Site | Notes |
|------|-------|
| **LinkedIn** | Uses the public guest Jobs API — no login needed. May be rate-limited after heavy use. |
| **Bumeran** | Uses the internal JSON API with HTML fallback. Very reliable. |
| **Computrabajo** | HTML scraping with multiple selector fallbacks. Reliable. |
| **Indeed** | Has strong bot detection. Results vary; may require manual cookie injection for consistent access. |

If a site fails, the script continues with the others — no crash.

---

## Project structure

```
busca_chamba/
├── scraper.py            # Main entry point
├── filters.py            # Keyword + seniority filtering
├── export.py             # Excel export with formatting
├── requirements.txt
├── README.md
├── jobs.db               # Created on first run
├── jobs_today.xlsx       # Created on first run
└── scrapers/
    ├── __init__.py
    ├── base.py           # Base class: rotating user agents, retries
    ├── linkedin.py
    ├── bumeran.py
    ├── computrabajo.py
    └── indeed.py
```
