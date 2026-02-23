# blackroad-code-coverage

[![CI](https://github.com/BlackRoad-OS/blackroad-code-coverage/actions/workflows/ci.yml/badge.svg)](https://github.com/BlackRoad-OS/blackroad-code-coverage/actions/workflows/ci.yml)
![Coverage](https://img.shields.io/badge/coverage-dynamic-brightgreen)

> **BlackRoad Code Coverage Analyzer** — Parse, diff, trend, and report code coverage data from LCOV and Cobertura XML formats. Store history in SQLite, generate HTML reports, and produce shield.io-compatible badges.

---

## Features

- Parse **LCOV** (`.info`) and **Cobertura XML** coverage files
- Store history in a local **SQLite** database with branch/commit metadata
- **Diff** two reports to see which files improved or regressed
- Generate self-contained **HTML summary reports** with progress bars
- Generate **shield.io badge** URLs and Markdown snippets
- **Trend tracking** — query historical coverage over time
- Fully typed with `dataclasses`; zero external runtime dependencies

---

## Installation

```bash
git clone https://github.com/BlackRoad-OS/blackroad-code-coverage.git
cd blackroad-code-coverage
pip install -r requirements.txt   # pytest + flake8 for dev
```

Python 3.9+ required. No third-party runtime dependencies.

---

## CLI Usage

```bash
python -m src.coverage_analyzer [--db PATH] <command> [args]
```

### Parse an LCOV file

```bash
python -m src.coverage_analyzer lcov coverage.info --branch main --commit abc1234
# Parsed LCOV: cov-3f8a1b2c4d  coverage=82.4%  lines=412/500
```

### Parse a Cobertura XML file

```bash
python -m src.coverage_analyzer cobertura coverage.xml --branch main
# Parsed Cobertura: cov-9d2e1a7f8b  coverage=75.0%
```

### Generate a badge

```bash
python -m src.coverage_analyzer badge 87.5
```

```json
{
  "pct": 87.5,
  "color": "green",
  "label": "good",
  "pct_str": "87.5%",
  "badge_url": "https://img.shields.io/badge/coverage-87.5%25-green",
  "markdown": "![Coverage](https://img.shields.io/badge/coverage-87.5%25-green)"
}
```

### Diff two reports

```bash
python -m src.coverage_analyzer diff cov-abc123 cov-def456
# Coverage changed from 78.2% to 83.5% (+5.30%). 3 files improved, 0 regressed, 1 new, 0 removed.
```

### Generate HTML report

```bash
python -m src.coverage_analyzer html cov-abc123 --output report.html
# HTML report written to report.html
```

### Show coverage trend

```bash
python -m src.coverage_analyzer trend --branch main --limit 10
```

```json
[
  {"id": "cov-abc", "timestamp": "2024-01-01T10:00:00", "pct": 78.2, "branch": "main"},
  {"id": "cov-def", "timestamp": "2024-01-02T11:30:00", "pct": 83.5, "branch": "main"}
]
```

### Show database stats

```bash
python -m src.coverage_analyzer stats
```

```json
{
  "total_reports": 14,
  "latest_pct": 83.5,
  "latest_ts": "2024-01-02T11:30:00",
  "average_pct": 80.1
}
```

---

## Python API

```python
from src.coverage_analyzer import CoverageAnalyzer

analyzer = CoverageAnalyzer(db_path="coverage.db")

# Parse LCOV
report = analyzer.parse_lcov("coverage.info", branch="main", commit_sha="abc1234")
print(f"Coverage: {report.overall_pct:.1f}%")

# Parse Cobertura
report = analyzer.parse_cobertura("coverage.xml", branch="main")

# Generate badge
badge = analyzer.calculate_badge(report.overall_pct)
print(badge["markdown"])  # ![Coverage](https://img.shields.io/badge/...)

# Diff two reports
diff = analyzer.diff_coverage(old_report, new_report)
print(diff.summary)

# Generate HTML
html = analyzer.generate_html_summary(report)
open("report.html", "w").write(html)

# Trend data
trend = analyzer.trend_tracking(branch="main", limit=20)

# Stats
stats = analyzer.get_stats()
```

---

## Supported Formats

| Format | Extension | Parser |
|---|---|---|
| LCOV | `.info` | `parse_lcov()` |
| Cobertura XML | `.xml` | `parse_cobertura()` |

Most coverage tools can export these formats:
- **Python**: `coverage.py --format=lcov` or `pytest-cov --cov-report=xml`
- **JavaScript**: `nyc`, `c8`, `jest --coverage`
- **Go**: `go test -coverprofile=coverage.out` → convert with `gcov2lcov`
- **Java/Kotlin**: JaCoCo exports Cobertura-compatible XML
- **Rust**: `cargo-tarpaulin --out Lcov`

---

## Badge Color Thresholds

| Coverage | Color | Label |
|---|---|---|
| >= 90% | ![](https://img.shields.io/badge/-brightgreen-brightgreen) `brightgreen` | excellent |
| >= 75% | ![](https://img.shields.io/badge/-green-green) `green` | good |
| >= 60% | ![](https://img.shields.io/badge/-yellowgreen-yellowgreen) `yellowgreen` | acceptable |
| >= 40% | ![](https://img.shields.io/badge/-yellow-yellow) `yellow` | low |
| < 40%  | ![](https://img.shields.io/badge/-red-red) `red` | critical |

---

## SQLite Schema

```sql
-- One row per parsed coverage report
CREATE TABLE coverage_history (
    id TEXT PRIMARY KEY,          -- "cov-<sha10>"
    timestamp TEXT NOT NULL,      -- ISO-8601 UTC
    source TEXT NOT NULL,         -- "lcov" | "cobertura"
    overall_pct REAL NOT NULL,    -- 0.0 – 100.0
    total_lines INTEGER NOT NULL,
    covered_lines INTEGER NOT NULL,
    total_branches INTEGER DEFAULT 0,
    covered_branches INTEGER DEFAULT 0,
    commit_sha TEXT DEFAULT '',
    branch TEXT DEFAULT '',
    tag TEXT DEFAULT ''
);

-- Per-file coverage rows linked to a report
CREATE TABLE file_coverage (
    id TEXT PRIMARY KEY,
    report_id TEXT NOT NULL,
    filename TEXT NOT NULL,
    total_lines INTEGER NOT NULL,
    covered_lines INTEGER NOT NULL,
    total_branches INTEGER DEFAULT 0,
    covered_branches INTEGER DEFAULT 0,
    FOREIGN KEY (report_id) REFERENCES coverage_history(id)
);
```

---

## Development

```bash
# Run tests
pytest tests/ -v --tb=short

# Lint
flake8 src/ tests/ --max-line-length=120 --ignore=E501,W503
```

---

## License

Proprietary — © BlackRoad OS, Inc. All rights reserved.
