"""Corpus readiness must report missing evidence without claiming a board success."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from kicad_mcp.evals import ReferenceCorpusError
from scripts import validate_reference_board_bundle as cli


def _result(*, successes: int = 0) -> SimpleNamespace:
    return SimpleNamespace(
        manifest=SimpleNamespace(board_id="board-a", benchmark_version="v1"),
        summary=SimpleNamespace(
            attempts_total=3,
            successful_attempts=successes,
            failed_attempts=3 - successes,
            infrastructure_invalid_attempts=0,
        ),
    )


def test_corpus_readiness_preserves_all_board_versions(monkeypatch, tmp_path: Path, capsys) -> None:
    (tmp_path / "board-a" / "v1").mkdir(parents=True)
    (tmp_path / "board-b" / "v1").mkdir(parents=True)

    def validate(path: Path) -> SimpleNamespace:
        if path.parent.name == "board-b":
            raise ReferenceCorpusError("missing attempt-manifest.json")
        return _result()

    monkeypatch.setattr(cli, "validate_reference_board_bundle", validate)
    assert cli.main(["--corpus-root", str(tmp_path)]) == 2
    output = capsys.readouterr().out
    assert "board=board-a version=v1 status=validated attempts=3 successful=0" in output
    assert "board=board-b version=v1 status=incomplete" in output
    assert "corpus boards=2 validated_versions=1 incomplete_versions=1" in output
    assert str(tmp_path) not in output


def test_corpus_readiness_succeeds_only_when_all_versions_validate(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    (tmp_path / "board-a" / "v1").mkdir(parents=True)
    (tmp_path / "board-a" / "v2").mkdir()

    def validate(path: Path) -> SimpleNamespace:
        result = _result()
        result.manifest.benchmark_version = path.name
        return result

    monkeypatch.setattr(cli, "validate_reference_board_bundle", validate)
    assert cli.main(["--corpus-root", str(tmp_path)]) == 0
    output = capsys.readouterr().out
    assert output.count("status=validated attempts=3") == 2
    assert "corpus boards=1 validated_versions=2 incomplete_versions=0" in output


def test_corpus_readiness_requires_canonical_board_and_version_identity(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    (tmp_path / "board-a" / "v1").mkdir(parents=True)
    monkeypatch.setattr(
        cli,
        "validate_reference_board_bundle",
        lambda _: SimpleNamespace(
            manifest=SimpleNamespace(board_id="another-board", benchmark_version="v1"),
            summary=_result().summary,
        ),
    )
    assert cli.main(["--corpus-root", str(tmp_path)]) == 2
    assert "board=board-a version=v1 status=incomplete" in capsys.readouterr().out


def test_corpus_readiness_rejects_empty_and_symlink_roots(tmp_path: Path, capsys) -> None:
    assert cli.main(["--corpus-root", str(tmp_path)]) == 2
    assert "corpus boards=0" in capsys.readouterr().out
    link = tmp_path.parent / "redirect-to-corpus"
    link.symlink_to(tmp_path, target_is_directory=True)
    assert cli.main(["--corpus-root", str(link)]) == 2
    assert "real directory" in capsys.readouterr().err


def test_corpus_readiness_fails_for_missing_attempt_versions(tmp_path: Path, capsys) -> None:
    (tmp_path / "board-a").mkdir()
    assert cli.main(["--corpus-root", str(tmp_path)]) == 2
    assert "status=incomplete reason=no benchmark versions" in capsys.readouterr().out


def test_corpus_readiness_rejects_unsafe_entries(tmp_path: Path, capsys) -> None:
    (tmp_path / "board-a").mkdir()
    (tmp_path / "board-a" / "v1").symlink_to(tmp_path)
    assert cli.main(["--corpus-root", str(tmp_path)]) == 2
    assert "unsupported version entry" in capsys.readouterr().err


def test_corpus_readiness_does_not_echo_unsafe_board_names(tmp_path: Path, capsys) -> None:
    (tmp_path / "user@private").mkdir()
    assert cli.main(["--corpus-root", str(tmp_path)]) == 2
    output = capsys.readouterr()
    assert "unsupported board entry" in output.err
    assert "user@private" not in output.err + output.out


def test_single_bundle_option_preserves_legacy_output(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(cli, "validate_reference_board_bundle", lambda _: _result(successes=1))
    assert cli.main(["--bundle", str(tmp_path)]) == 0
    assert "reference corpus valid board=board-a attempts=3 successful=1" in capsys.readouterr().out
