import re
import unicodedata

# Keywords used to search each job site
SEARCH_KEYWORDS = [
    "Planeamiento Financiero",
    "FP&A",
    "Finanzas Corporativas",
    "Gerente de Finanzas",
    "Director Financiero",
    "CFO",
    "Desarrollo de Negocios",
    "Business Development",
    "Estrategia Corporativa",
    "Gerente de Estrategia",
    "Planeamiento Estratégico",
    "Gerente Comercial",
    "Director Comercial",
    "Controller",
    "Gerencia de Finanzas",
]

# Title tokens that indicate senior seniority (checked after exclusions)
_SENIORITY_C_LEVEL = [
    "director", "directora", "cfo", "chief financial", "vp ", "vice president",
    "vicepresidente", "vicepresidenta", "chief", "c-level",
]
_SENIORITY_GERENTE = [
    "gerente", "gerenta", "manager", "country manager",
]
_SENIORITY_JEFE = [
    "jefe", "jefa", "head of", "head ", "controller", "superintendente",
    "coordinador senior", "coordinadora senior",
]
_SENIORITY_SENIOR = [
    "senior", "sr.", "sr ", "lead ", "líder", "lider",
]

# All seniority markers combined (any match keeps the job)
SENIORITY_ALL = (
    _SENIORITY_C_LEVEL
    + _SENIORITY_GERENTE
    + _SENIORITY_JEFE
    + _SENIORITY_SENIOR
)

# Keywords that immediately disqualify a job (junior / entry-level)
SENIORITY_EXCLUDE = [
    "practicante", "practicas", "practicas",
    "asistente", "auxiliar",
    "trainee", "intern", "internship",
    "egresado", "egresada",
    "tecnico",  # normalised from técnico
    "bachiller",
    "recien egresado",
    "entry level",
    "junior",
    "jr.",
]

# Title must touch at least one of these domains to be kept
DOMAIN_KEYWORDS = [
    "finan", "fp&a", "planeamiento", "estrateg", "business development",
    "desarrollo de negocio", "comercial", "controller", "tesorería", "tesoreria",
    "presupuesto", "cfo", "corporate", "corporativ",
]


def _normalize(text: str) -> str:
    """Lowercase + strip accents for robust matching."""
    if not text:
        return ""
    nfkd = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def detect_seniority(title: str):
    """Return seniority label string, or None if the job should be excluded."""
    t = _normalize(title)

    # Hard exclusions (applied to ALL sources)
    for excl in SENIORITY_EXCLUDE:
        if excl in t:
            return None

    # Reject standalone "jr" / "jr." even without a period (word boundary)
    if re.search(r'\bjr\.?\b', t):
        return None

    # Reject "analista" UNLESS immediately qualified by "senior" or "sr"
    if "analista" in t:
        if not re.search(r'(senior\s+analista|analista\s+senior|sr\.?\s+analista|analista\s+sr\.?)', t):
            return None

    # Classify by seniority tier
    for kw in _SENIORITY_C_LEVEL:
        if _normalize(kw) in t:
            return "Director / C-Level"

    for kw in _SENIORITY_GERENTE:
        if _normalize(kw) in t:
            return "Gerente"

    for kw in _SENIORITY_JEFE:
        if _normalize(kw) in t:
            return "Jefe / Especialista Senior"

    for kw in _SENIORITY_SENIOR:
        if _normalize(kw) in t:
            return "Senior"

    return None  # No seniority marker found → skip


def is_relevant_domain(title: str) -> bool:
    t = _normalize(title)
    return any(_normalize(kw) in t for kw in DOMAIN_KEYWORDS)


def filter_jobs(jobs: list) -> list:
    """
    Filter raw jobs:
      1. Must be in a relevant domain (finance / strategy / bizdev).
      2. Must pass seniority check (senior+ only, no junior roles).
      3. Deduplicate by URL within this batch.
    Returns jobs with 'seniority' key populated.
    """
    results = []
    seen_keys: set = set()

    for job in jobs:
        title = job.get("title", "")
        url = job.get("url", "")

        # Dedup within this scrape session
        key = url.strip().lower() if url else _normalize(f"{job.get('company','')} {title}")
        if not key or key in seen_keys:
            continue
        seen_keys.add(key)

        if not is_relevant_domain(title):
            continue

        seniority = detect_seniority(title)
        if seniority is None:
            continue

        job = dict(job)  # don't mutate original
        job["seniority"] = seniority
        results.append(job)

    return results
