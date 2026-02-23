import pytest
import os
import json
from src.coverage_analyzer import CoverageAnalyzer, CoverageReport, FileCoverage


def make_analyzer(tmp_path):
    return CoverageAnalyzer(db_path=str(tmp_path / "cov.db"))


def make_lcov_content():
    return """SF:src/foo.py
DA:1,1
DA:2,1
DA:3,0
DA:4,1
LF:4
LH:3
end_of_record
SF:src/bar.py
DA:1,0
DA:2,0
LF:2
LH:0
end_of_record
"""


def make_cobertura_content():
    return """<?xml version="1.0" ?>
<coverage line-rate="0.75" branch-rate="0.5" lines-valid="100" lines-covered="75" branches-valid="20" branches-covered="10">
  <packages>
    <package name="src">
      <classes>
        <class filename="src/foo.py" line-rate="0.8" branch-rate="0.6">
          <lines>
            <line number="1" hits="1"/>
            <line number="2" hits="1"/>
            <line number="3" hits="1"/>
            <line number="4" hits="1"/>
            <line number="5" hits="0"/>
          </lines>
        </class>
      </classes>
    </package>
  </packages>
</coverage>"""


def test_parse_lcov(tmp_path):
    lcov_file = tmp_path / "cov.info"
    lcov_file.write_text(make_lcov_content())
    analyzer = make_analyzer(tmp_path)
    report = analyzer.parse_lcov(str(lcov_file))
    assert isinstance(report, CoverageReport)
    assert report.total_lines == 6
    assert report.covered_lines == 3
    assert len(report.files) == 2


def test_parse_cobertura(tmp_path):
    xml_file = tmp_path / "coverage.xml"
    xml_file.write_text(make_cobertura_content())
    analyzer = make_analyzer(tmp_path)
    report = analyzer.parse_cobertura(str(xml_file))
    assert isinstance(report, CoverageReport)
    assert report.overall_pct == pytest.approx(75.0)


def test_calculate_badge(tmp_path):
    analyzer = make_analyzer(tmp_path)
    badge = analyzer.calculate_badge(95.0)
    assert badge["color"] == "brightgreen"
    badge_low = analyzer.calculate_badge(30.0)
    assert badge_low["color"] == "red"


def test_calculate_badge_thresholds(tmp_path):
    analyzer = make_analyzer(tmp_path)
    assert analyzer.calculate_badge(90.0)["color"] == "brightgreen"
    assert analyzer.calculate_badge(75.0)["color"] == "green"
    assert analyzer.calculate_badge(60.0)["color"] == "yellowgreen"
    assert analyzer.calculate_badge(40.0)["color"] == "yellow"
    assert analyzer.calculate_badge(0.0)["color"] == "red"


def test_diff_coverage(tmp_path):
    lcov_file = tmp_path / "cov.info"
    lcov_file.write_text(make_lcov_content())
    analyzer = make_analyzer(tmp_path)
    r1 = analyzer.parse_lcov(str(lcov_file), branch="main")
    r2 = analyzer.parse_lcov(str(lcov_file), branch="main")
    diff = analyzer.diff_coverage(r1, r2)
    assert diff.delta == pytest.approx(0.0, abs=0.1)
    assert "Coverage changed" in diff.summary


def test_generate_html(tmp_path):
    lcov_file = tmp_path / "cov.info"
    lcov_file.write_text(make_lcov_content())
    analyzer = make_analyzer(tmp_path)
    report = analyzer.parse_lcov(str(lcov_file))
    html = analyzer.generate_html_summary(report)
    assert "<html" in html
    assert "Coverage Report" in html
    assert "src/foo.py" in html


def test_trend_tracking(tmp_path):
    lcov_file = tmp_path / "cov.info"
    lcov_file.write_text(make_lcov_content())
    analyzer = make_analyzer(tmp_path)
    analyzer.parse_lcov(str(lcov_file), branch="main")
    analyzer.parse_lcov(str(lcov_file), branch="main")
    trend = analyzer.trend_tracking(branch="main")
    assert len(trend) == 2
    assert "pct" in trend[0]


def test_get_stats(tmp_path):
    analyzer = make_analyzer(tmp_path)
    stats = analyzer.get_stats()
    assert "total_reports" in stats
    assert stats["total_reports"] == 0


def test_get_stats_after_ingestion(tmp_path):
    lcov_file = tmp_path / "cov.info"
    lcov_file.write_text(make_lcov_content())
    analyzer = make_analyzer(tmp_path)
    analyzer.parse_lcov(str(lcov_file), branch="main")
    stats = analyzer.get_stats()
    assert stats["total_reports"] == 1
    assert stats["latest_pct"] is not None


def test_get_report_roundtrip(tmp_path):
    lcov_file = tmp_path / "cov.info"
    lcov_file.write_text(make_lcov_content())
    analyzer = make_analyzer(tmp_path)
    original = analyzer.parse_lcov(str(lcov_file), commit_sha="abc123", branch="feature")
    fetched = analyzer.get_report(original.report_id)
    assert fetched is not None
    assert fetched.report_id == original.report_id
    assert fetched.overall_pct == original.overall_pct
    assert fetched.commit_sha == "abc123"
    assert fetched.branch == "feature"
    assert len(fetched.files) == len(original.files)


def test_get_report_missing(tmp_path):
    analyzer = make_analyzer(tmp_path)
    result = analyzer.get_report("nonexistent-id")
    assert result is None


def test_file_coverage_properties():
    fc = FileCoverage(filename="test.py", total_lines=10, covered_lines=8)
    assert fc.line_rate == pytest.approx(0.8)
    assert fc.line_pct == pytest.approx(80.0)
    assert fc.branch_rate == pytest.approx(1.0)


def test_file_coverage_zero_lines():
    fc = FileCoverage(filename="empty.py", total_lines=0, covered_lines=0)
    assert fc.line_rate == 1.0
    assert fc.line_pct == 100.0


def test_lcov_missing_file(tmp_path):
    analyzer = make_analyzer(tmp_path)
    with pytest.raises(FileNotFoundError):
        analyzer.parse_lcov("/nonexistent/path/cov.info")


def test_cobertura_missing_file(tmp_path):
    analyzer = make_analyzer(tmp_path)
    with pytest.raises(FileNotFoundError):
        analyzer.parse_cobertura("/nonexistent/path/coverage.xml")


def test_badge_markdown_format(tmp_path):
    analyzer = make_analyzer(tmp_path)
    badge = analyzer.calculate_badge(85.0)
    assert badge["markdown"].startswith("![Coverage]")
    assert "shields.io" in badge["markdown"]
    assert "pct_str" in badge
    assert "%" in badge["pct_str"]


def test_diff_new_and_removed_files(tmp_path):
    analyzer = make_analyzer(tmp_path)
    r1 = CoverageReport(
        report_id="r1", timestamp="2024-01-01T00:00:00", source="lcov",
        overall_pct=70.0, total_lines=100, covered_lines=70,
        files=[FileCoverage("old_file.py", 100, 70)],
    )
    r2 = CoverageReport(
        report_id="r2", timestamp="2024-01-02T00:00:00", source="lcov",
        overall_pct=80.0, total_lines=100, covered_lines=80,
        files=[FileCoverage("new_file.py", 100, 80)],
    )
    diff = analyzer.diff_coverage(r1, r2)
    assert "old_file.py" in diff.removed_files
    assert "new_file.py" in diff.new_files
    assert diff.delta == pytest.approx(10.0)
