#!/usr/bin/env python3
"""BlackRoad Code Coverage Analyzer - Parse, diff, trend, and report coverage data."""

from __future__ import annotations
import argparse, hashlib, json, math, re, sqlite3, sys, xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

BADGE_THRESHOLDS = [
    (90, "brightgreen", "excellent"),
    (75, "green", "good"),
    (60, "yellowgreen", "acceptable"),
    (40, "yellow", "low"),
    (0,  "red", "critical"),
]

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Coverage Report</title>
<style>
body{{font-family:sans-serif;margin:2em;background:#f5f5f5}}
.summary{{background:#fff;padding:1.5em;border-radius:8px;box-shadow:0 2px 4px rgba(0,0,0,.1)}}
.badge{{display:inline-block;padding:.25em .6em;border-radius:4px;color:#fff;font-weight:bold;font-size:1.2em;background:{color}}}
table{{width:100%;border-collapse:collapse;margin-top:1em;background:#fff}}
th,td{{padding:.6em 1em;border:1px solid #ddd;text-align:left}}
th{{background:#333;color:#fff}}
tr:nth-child(even){{background:#f9f9f9}}
.bar{{height:14px;background:#eee;border-radius:3px}}
.bar-fill{{height:14px;border-radius:3px;background:{color}}}
.delta-pos{{color:green}}.delta-neg{{color:red}}.delta-zero{{color:gray}}
</style></head>
<body>
<h1>Coverage Report</h1>
<div class="summary">
<span class="badge" style="background:{color}">{pct:.1f}%</span>
&nbsp;&nbsp;<strong>Overall Coverage</strong>
<br><br>
<table>
<tr><th>File</th><th>Lines</th><th>Covered</th><th>Coverage</th><th>Bar</th></tr>
{rows}
</table>
</div>
<p><em>Generated: {ts}</em></p>
</body></html>"""


@dataclass
class FileCoverage:
    filename: str
    total_lines: int
    covered_lines: int
    total_branches: int = 0
    covered_branches: int = 0

    @property
    def line_rate(self) -> float:
        if self.total_lines == 0:
            return 1.0
        return round(self.covered_lines / self.total_lines, 4)

    @property
    def branch_rate(self) -> float:
        if self.total_branches == 0:
            return 1.0
        return round(self.covered_branches / self.total_branches, 4)

    @property
    def line_pct(self) -> float:
        return round(self.line_rate * 100, 2)


@dataclass
class CoverageReport:
    report_id: str
    timestamp: str
    source: str
    overall_pct: float
    total_lines: int
    covered_lines: int
    total_branches: int = 0
    covered_branches: int = 0
    files: List[FileCoverage] = field(default_factory=list)
    commit_sha: str = ""
    branch: str = ""
    tag: str = ""

    def to_dict(self) -> Dict:
        d = asdict(self)
        d["files"] = [asdict(f) for f in self.files]
        return d


@dataclass
class CoverageDiff:
    old_pct: float
    new_pct: float
    delta: float
    improved_files: List[str]
    regressed_files: List[str]
    new_files: List[str]
    removed_files: List[str]
    summary: str


class CoverageAnalyzer:
    """Parse, store, diff, and report code coverage data."""

    def __init__(self, db_path: str = "coverage.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS coverage_history (
                    id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    source TEXT NOT NULL,
                    overall_pct REAL NOT NULL,
                    total_lines INTEGER NOT NULL,
                    covered_lines INTEGER NOT NULL,
                    total_branches INTEGER DEFAULT 0,
                    covered_branches INTEGER DEFAULT 0,
                    commit_sha TEXT DEFAULT '',
                    branch TEXT DEFAULT '',
                    tag TEXT DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS file_coverage (
                    id TEXT PRIMARY KEY,
                    report_id TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    total_lines INTEGER NOT NULL,
                    covered_lines INTEGER NOT NULL,
                    total_branches INTEGER DEFAULT 0,
                    covered_branches INTEGER DEFAULT 0,
                    FOREIGN KEY (report_id) REFERENCES coverage_history(id)
                );
                CREATE INDEX IF NOT EXISTS idx_history_ts ON coverage_history(timestamp);
                CREATE INDEX IF NOT EXISTS idx_history_branch ON coverage_history(branch);
                CREATE INDEX IF NOT EXISTS idx_file_report ON file_coverage(report_id);
            """)

    def _gen_id(self) -> str:
        ts = datetime.utcnow().isoformat()
        return "cov-" + hashlib.sha256(ts.encode()).hexdigest()[:10]

    def parse_lcov(self, path: str, commit_sha: str = "", branch: str = "") -> CoverageReport:
        """Parse an LCOV .info file and return a CoverageReport."""
        lcov_path = Path(path)
        if not lcov_path.exists():
            raise FileNotFoundError(f"LCOV file not found: {path}")

        files: Dict[str, Dict] = {}
        current_file = None

        with open(lcov_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("SF:"):
                    current_file = line[3:]
                    files[current_file] = {
                        "lines_found": 0, "lines_hit": 0,
                        "branches_found": 0, "branches_hit": 0, "hit_lines": set()
                    }
                elif line.startswith("DA:") and current_file:
                    parts = line[3:].split(",")
                    if len(parts) >= 2:
                        lineno = int(parts[0])
                        hits = int(parts[1]) if parts[1].strip().lstrip("-").isdigit() else 0
                        files[current_file]["lines_found"] += 1
                        if hits > 0:
                            files[current_file]["lines_hit"] += 1
                            files[current_file]["hit_lines"].add(lineno)
                elif line.startswith("BRH:") and current_file:
                    files[current_file]["branches_hit"] = int(line[4:])
                elif line.startswith("BRF:") and current_file:
                    files[current_file]["branches_found"] = int(line[4:])
                elif line.startswith("LF:") and current_file:
                    files[current_file]["lines_found"] = int(line[3:])
                elif line.startswith("LH:") and current_file:
                    files[current_file]["lines_hit"] = int(line[3:])
                elif line == "end_of_record":
                    current_file = None

        file_coverages = []
        total_lines = total_covered = total_branches = covered_branches = 0

        for fname, data in files.items():
            lf = data["lines_found"]
            lh = data["lines_hit"] if isinstance(data["lines_hit"], int) else len(data["lines_hit"])
            bf = data["branches_found"]
            bh = data["branches_hit"]
            total_lines += lf
            total_covered += lh
            total_branches += bf
            covered_branches += bh
            file_coverages.append(FileCoverage(
                filename=fname, total_lines=lf, covered_lines=lh,
                total_branches=bf, covered_branches=bh,
            ))

        overall = round((total_covered / total_lines * 100) if total_lines > 0 else 0.0, 2)
        report = CoverageReport(
            report_id=self._gen_id(), timestamp=datetime.utcnow().isoformat(),
            source="lcov", overall_pct=overall,
            total_lines=total_lines, covered_lines=total_covered,
            total_branches=total_branches, covered_branches=covered_branches,
            files=file_coverages, commit_sha=commit_sha, branch=branch,
        )
        self._save_report(report)
        return report

    def parse_cobertura(self, xml_path: str, commit_sha: str = "", branch: str = "") -> CoverageReport:
        """Parse a Cobertura XML coverage file."""
        path = Path(xml_path)
        if not path.exists():
            raise FileNotFoundError(f"Cobertura XML not found: {xml_path}")

        tree = ET.parse(str(path))
        root = tree.getroot()

        overall_line_rate = float(root.get("line-rate", "0"))
        lines_valid = int(root.get("lines-valid", "0"))
        lines_covered = int(root.get("lines-covered", "0"))
        branches_valid = int(root.get("branches-valid", "0"))
        branches_covered = int(root.get("branches-covered", "0"))

        file_coverages = []
        for cls in root.iter("class"):
            fname = cls.get("filename", "unknown")
            f_lines = list(cls.iter("line"))
            f_total = len(f_lines)
            f_covered = sum(1 for ln in f_lines if int(ln.get("hits", "0")) > 0)
            file_coverages.append(FileCoverage(
                filename=fname, total_lines=f_total, covered_lines=f_covered,
            ))

        overall_pct = round(overall_line_rate * 100, 2)
        report = CoverageReport(
            report_id=self._gen_id(), timestamp=datetime.utcnow().isoformat(),
            source="cobertura", overall_pct=overall_pct,
            total_lines=lines_valid, covered_lines=lines_covered,
            total_branches=branches_valid, covered_branches=branches_covered,
            files=file_coverages, commit_sha=commit_sha, branch=branch,
        )
        self._save_report(report)
        return report

    def calculate_badge(self, coverage_pct: float) -> Dict:
        """Return badge color, label, and SVG URL for a coverage percentage."""
        for threshold, color, label in BADGE_THRESHOLDS:
            if coverage_pct >= threshold:
                pct_str = f"{coverage_pct:.1f}%"
                svg_url = f"https://img.shields.io/badge/coverage-{pct_str.replace('%', '%25')}-{color}"
                return {
                    "pct": coverage_pct,
                    "color": color,
                    "label": label,
                    "pct_str": pct_str,
                    "badge_url": svg_url,
                    "markdown": f"![Coverage]({svg_url})",
                }
        return {"pct": 0, "color": "red", "label": "critical", "pct_str": "0%", "badge_url": "", "markdown": ""}

    def diff_coverage(self, old_report: CoverageReport, new_report: CoverageReport) -> CoverageDiff:
        """Compare two coverage reports and return a CoverageDiff."""
        old_files = {f.filename: f for f in old_report.files}
        new_files = {f.filename: f for f in new_report.files}

        improved = []
        regressed = []
        for fname, new_fc in new_files.items():
            if fname in old_files:
                old_pct = old_files[fname].line_pct
                new_pct = new_fc.line_pct
                if new_pct > old_pct + 0.1:
                    improved.append(f"{fname}: {old_pct:.1f}% -> {new_pct:.1f}%")
                elif new_pct < old_pct - 0.1:
                    regressed.append(f"{fname}: {old_pct:.1f}% -> {new_pct:.1f}%")

        new_file_names = [f for f in new_files if f not in old_files]
        removed_file_names = [f for f in old_files if f not in new_files]

        delta = round(new_report.overall_pct - old_report.overall_pct, 2)
        sign = "+" if delta >= 0 else ""
        summary = (
            f"Coverage changed from {old_report.overall_pct:.1f}% to {new_report.overall_pct:.1f}% "
            f"({sign}{delta:.2f}%). "
            f"{len(improved)} files improved, {len(regressed)} regressed, "
            f"{len(new_file_names)} new, {len(removed_file_names)} removed."
        )

        return CoverageDiff(
            old_pct=old_report.overall_pct, new_pct=new_report.overall_pct,
            delta=delta, improved_files=improved, regressed_files=regressed,
            new_files=new_file_names, removed_files=removed_file_names,
            summary=summary,
        )

    def generate_html_summary(self, report: CoverageReport) -> str:
        """Generate an HTML summary page for a coverage report."""
        badge = self.calculate_badge(report.overall_pct)
        color = badge["color"]
        color_map = {
            "brightgreen": "#4c1", "green": "#97ca00", "yellowgreen": "#a4a61d",
            "yellow": "#dfb317", "red": "#e05d44"
        }
        hex_color = color_map.get(color, "#999")

        rows = []
        for fc in sorted(report.files, key=lambda f: f.line_pct):
            bar_width = int(fc.line_pct)
            rows.append(
                f"<tr><td>{fc.filename}</td><td>{fc.total_lines}</td>"
                f"<td>{fc.covered_lines}</td><td>{fc.line_pct:.1f}%</td>"
                f'<td><div class="bar"><div class="bar-fill" style="width:{bar_width}%;background:{hex_color}"></div></div></td></tr>'
            )

        html = HTML_TEMPLATE.format(
            color=hex_color, pct=report.overall_pct,
            rows="\n".join(rows), ts=report.timestamp,
        )
        return html

    def trend_tracking(self, reports: Optional[List[CoverageReport]] = None,
                       branch: Optional[str] = None, limit: int = 30) -> List[Dict]:
        """Get coverage trend data. Returns list of {timestamp, pct, branch} dicts."""
        if reports:
            return [{"timestamp": r.timestamp, "pct": r.overall_pct,
                     "branch": r.branch, "id": r.report_id} for r in reports]

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            if branch:
                rows = conn.execute(
                    "SELECT id, timestamp, overall_pct, branch FROM coverage_history "
                    "WHERE branch=? ORDER BY timestamp DESC LIMIT ?", (branch, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, timestamp, overall_pct, branch FROM coverage_history "
                    "ORDER BY timestamp DESC LIMIT ?", (limit,)
                ).fetchall()

        trend = [{"id": r["id"], "timestamp": r["timestamp"],
                  "pct": r["overall_pct"], "branch": r["branch"]} for r in rows]
        return list(reversed(trend))

    def get_report(self, report_id: str) -> Optional[CoverageReport]:
        """Fetch a full report from the database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM coverage_history WHERE id=?", (report_id,)).fetchone()
            if not row:
                return None
            file_rows = conn.execute("SELECT * FROM file_coverage WHERE report_id=?", (report_id,)).fetchall()
            files = [FileCoverage(
                filename=r["filename"], total_lines=r["total_lines"], covered_lines=r["covered_lines"],
                total_branches=r["total_branches"], covered_branches=r["covered_branches"],
            ) for r in file_rows]
            return CoverageReport(
                report_id=row["id"], timestamp=row["timestamp"], source=row["source"],
                overall_pct=row["overall_pct"], total_lines=row["total_lines"],
                covered_lines=row["covered_lines"], total_branches=row["total_branches"],
                covered_branches=row["covered_branches"], files=files,
                commit_sha=row["commit_sha"], branch=row["branch"], tag=row["tag"],
            )

    def _save_report(self, report: CoverageReport):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO coverage_history VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (report.report_id, report.timestamp, report.source, report.overall_pct,
                 report.total_lines, report.covered_lines, report.total_branches,
                 report.covered_branches, report.commit_sha, report.branch, report.tag)
            )
            for fc in report.files:
                fid = "fc-" + hashlib.sha256(f"{report.report_id}{fc.filename}".encode()).hexdigest()[:10]
                conn.execute(
                    "INSERT OR REPLACE INTO file_coverage VALUES (?,?,?,?,?,?,?)",
                    (fid, report.report_id, fc.filename, fc.total_lines,
                     fc.covered_lines, fc.total_branches, fc.covered_branches)
                )

    def get_stats(self) -> Dict:
        """Return aggregate statistics from the coverage history database."""
        with sqlite3.connect(self.db_path) as conn:
            total = conn.execute("SELECT COUNT(*) FROM coverage_history").fetchone()[0]
            latest = conn.execute(
                "SELECT overall_pct, timestamp FROM coverage_history ORDER BY timestamp DESC LIMIT 1"
            ).fetchone()
            avg = conn.execute("SELECT AVG(overall_pct) FROM coverage_history").fetchone()[0]
        return {
            "total_reports": total,
            "latest_pct": latest[0] if latest else None,
            "latest_ts": latest[1] if latest else None,
            "average_pct": round(avg, 2) if avg else None,
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="coverage-analyzer", description="BlackRoad Coverage Analyzer")
    parser.add_argument("--db", default="coverage.db")
    sub = parser.add_subparsers(dest="command")

    lcov = sub.add_parser("lcov", help="Parse LCOV file")
    lcov.add_argument("file")
    lcov.add_argument("--commit", default="")
    lcov.add_argument("--branch", default="")

    cob = sub.add_parser("cobertura", help="Parse Cobertura XML")
    cob.add_argument("file")
    cob.add_argument("--commit", default="")
    cob.add_argument("--branch", default="")

    badge = sub.add_parser("badge", help="Generate badge info")
    badge.add_argument("pct", type=float)

    diff_cmd = sub.add_parser("diff", help="Diff two reports")
    diff_cmd.add_argument("old_id")
    diff_cmd.add_argument("new_id")

    html_cmd = sub.add_parser("html", help="Generate HTML report")
    html_cmd.add_argument("report_id")
    html_cmd.add_argument("--output", default="coverage.html")

    trend = sub.add_parser("trend", help="Show trend data")
    trend.add_argument("--branch", default="")
    trend.add_argument("--limit", type=int, default=20)

    sub.add_parser("stats", help="Show database stats")
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(0)
    analyzer = CoverageAnalyzer(db_path=args.db)
    if args.command == "lcov":
        r = analyzer.parse_lcov(args.file, commit_sha=args.commit, branch=args.branch)
        print(f"Parsed LCOV: {r.report_id}  coverage={r.overall_pct:.1f}%  lines={r.covered_lines}/{r.total_lines}")
    elif args.command == "cobertura":
        r = analyzer.parse_cobertura(args.file, commit_sha=args.commit, branch=args.branch)
        print(f"Parsed Cobertura: {r.report_id}  coverage={r.overall_pct:.1f}%")
    elif args.command == "badge":
        print(json.dumps(analyzer.calculate_badge(args.pct), indent=2))
    elif args.command == "diff":
        old = analyzer.get_report(args.old_id)
        new = analyzer.get_report(args.new_id)
        if not old or not new:
            print("ERROR: one or both report IDs not found", file=sys.stderr)
            sys.exit(1)
        diff = analyzer.diff_coverage(old, new)
        print(diff.summary)
    elif args.command == "html":
        r = analyzer.get_report(args.report_id)
        if not r:
            print("ERROR: report not found", file=sys.stderr)
            sys.exit(1)
        html = analyzer.generate_html_summary(r)
        Path(args.output).write_text(html)
        print(f"HTML report written to {args.output}")
    elif args.command == "trend":
        trend = analyzer.trend_tracking(branch=args.branch or None, limit=args.limit)
        print(json.dumps(trend, indent=2))
    elif args.command == "stats":
        print(json.dumps(analyzer.get_stats(), indent=2))


if __name__ == "__main__":
    main()
