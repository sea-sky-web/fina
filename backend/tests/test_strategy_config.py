"""Tests for versioned strategy configuration and state persistence."""
from __future__ import annotations

import json

from app.services import strategy_state
from app.services.strategy_config import load_strategy_params, universe_path


def test_load_strategy_params_reads_version_from_config_file() -> None:
    params = load_strategy_params()
    assert params.version  # e.g. "v58", never empty
    assert params.k >= 1
    assert params.benchmark.endswith((".SH", ".SZ"))


def test_universe_path_points_to_existing_csv() -> None:
    path = universe_path()
    assert path.name == "strategy_universe.csv"
    assert path.exists()


def test_state_load_falls_back_to_legacy_file(tmp_path, monkeypatch) -> None:
    new_file = tmp_path / "strategy_state.json"
    legacy_file = tmp_path / "v58_state.json"
    monkeypatch.setattr(strategy_state, "STATE_FILE", new_file)
    monkeypatch.setattr(strategy_state, "_LEGACY_STATE_FILE", legacy_file)

    legacy_file.write_text(
        json.dumps({"current_holdings": ["159998.SZ"], "portfolio_equity": 1.2}),
        encoding="utf-8",
    )
    state = strategy_state.load_state()
    assert state.current_holdings == ["159998.SZ"]
    assert state.portfolio_equity == 1.2

    # saving writes the new file; subsequent loads prefer it
    state.current_holdings = ["510300.SH"]
    strategy_state.save_state(state)
    assert new_file.exists()
    assert strategy_state.load_state().current_holdings == ["510300.SH"]


def test_state_load_defaults_when_no_files(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(strategy_state, "STATE_FILE", tmp_path / "strategy_state.json")
    monkeypatch.setattr(strategy_state, "_LEGACY_STATE_FILE", tmp_path / "v58_state.json")
    state = strategy_state.load_state()
    assert state.current_holdings == []
    assert state.portfolio_equity == 1.0
