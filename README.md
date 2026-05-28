# busca_chamba — Peru Senior Finance & Strategy Job Scraper

Automated daily job scraper for senior finance, strategy, and business development
roles in Peru. Aggregates listings from Computrabajo, LinkedIn, and 20+ direct
company career pages (Scotiabank, BBVA, Credicorp, Michael Page, Krealo, and more)
into a clean Excel report.

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
python scraper.py --scraper computrabajo
python scraper.py --scraper linkedin
python scraper.py --scraper empresas

# Custom output filename
python scraper.py --output empleos_mayo.xlsx

# Skip Excel export (DB only)
python scraper.py --no-export
```

---

## Sources

| Source | Method |
|--------|--------|
| **Computrabajo** | HTML scraping with multiple selector fallbacks |
| **LinkedIn** | Public guest Jobs API — no login required |
| **Scotiabank Peru** | Direct career page |
| **BBVA Peru** | Workday API |
| **Interbank** | Workday API + Oracle HCM |
| **Credicorp / Mibanco** | Workday API |
| **Alicorp** | Workday API + Phenom portal |
| **Krealo** | Direct career page |
| **Michael Page Peru** | Headhunter portal |
| **UNACEM** | Hiringroom ATS |
| **Panamerican Silver** | Hiringroom ATS |
| **Grupo Gloria** | Direct career page |
| **Bosch Peru** | SmartRecruiters API |
| **+ others** | See `empresa_urls.json` for full list |

---

## Output

### jobs_today.xlsx

| Estado | Fecha | Días en BD | Fuente | Empresa | Puesto | Sector | Ubicación | Seniority | Salario | URL |
|--------|-------|-----------|--------|---------|--------|--------|-----------|-----------|---------|-----|

- **Estado column:** 🆕 Nuevo = added today, 📋 Visto = added in last 7 days
- **Sorted by:** new jobs first, then by date
- **Auto-expires** jobs older than 7 days (DB retention for deduplication)
- URLs are clickable hyperlinks
- Frozen header row + auto-filter on all columns
- "Resumen" sheet: nuevos hoy, total activos (7 días), counts by source / sector / seniority

### jobs.db (SQLite)

```sql
-- Query example
SELECT title, company, location, salary, source
FROM jobs
WHERE DATE(fecha_ingreso_db) = DATE('now')
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
| **Bumeran** | Disabled — strong bot detection, JS-rendered site with no static content. |
| **Computrabajo** | HTML scraping with multiple selector fallbacks. Reliable. |
| **Indeed** | Disabled — strong bot detection. |
| **CSOD / Rankmi** | JS-rendered ATS portals — require browser automation (not yet implemented). |

If a site fails, the script continues with the others — no crash.

---

## Project structure

```
busca_chamba/
├── scraper.py            # Main entry point
├── filters.py            # Keyword + seniority filtering
├── export.py             # Excel export with formatting
├── empresa_urls.json     # Company career page URLs + sector metadata
├── requirements.txt
├── README.md
├── jobs.db               # Created on first run
├── jobs_today.xlsx       # Created on first run
└── scrapers/
    ├── __init__.py
    ├── base.py           # Base class: rotating user agents, retries
    ├── linkedin.py
    ├── bumeran.py        # Disabled (bot detection)
    ├── computrabajo.py
    ├── indeed.py         # Disabled (bot detection)
    └── empresas_peru.py  # Direct company career pages (20+ companies)
```
