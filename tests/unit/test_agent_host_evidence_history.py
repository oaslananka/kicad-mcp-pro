"""Historical real-host evidence is not conflated with current static catalog checks."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_historical_host_evidence_points_to_real_maintained_source() -> None:
    index = ROOT / "docs/evidence/agent-host-smoke-history.md"
    evidence = ROOT / "docs/evidence/kicad-pcm/2026-08-29/linux-kicad-10.0.5.md"
    assert index.is_file()
    assert evidence.is_file()
    original = evidence.read_text(encoding="utf-8")
    current = index.read_text(encoding="utf-8")
    for marker in ("2.1.238", "0.150.1", "546227bcb13eb851913eaf6d6d8d95c9a5ae367c"):
        assert marker in current
        assert marker in original
    assert "not-run" in current
    assert "current" in current
    assert "does not" in current.lower()


def test_discovery_and_public_listing_link_to_real_documents() -> None:
    status = (ROOT / "docs/status/distribution-readiness.md").read_text(encoding="utf-8")
    listing = (ROOT / "docs/public-listing.md").read_text(encoding="utf-8")
    assert "../evidence/agent-host-smoke-history.md" in status
    assert (ROOT / "docs/release-readiness-2026-07-03.md").is_file()
    assert "(release-readiness-2026-07-03.md)" in listing
    assert "latest dated [`release-readiness-*.md`](.)" not in listing
