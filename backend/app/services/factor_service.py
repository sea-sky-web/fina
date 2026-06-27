from __future__ import annotations

from datetime import UTC, date, datetime
from math import ceil

import pandas as pd

from app.core.config import settings
from app.factors.base import Factor
from app.factors.processing import process_factor
from app.factors.registry import FACTOR_REGISTRY
from app.models import (
    FactorDiagnostics,
    FactorDistribution,
    FactorForwardReturn,
    FactorHistoryPoint,
    FactorScore,
    FactorStability,
)
from app.services.records import dataframe_records
from app.services.theme_classifier import infer_etf_theme
from app.storage.parquet_store import read_parquet, write_parquet


def _factor_path(processed: bool = False):
    filename = "factors_processed.parquet" if processed else "factors.parquet"
    return settings.clean_dir / filename


def _theme_groups_by_symbol() -> pd.Series | None:
    basic = read_parquet(settings.clean_dir / "etf_basic.parquet")
    if basic.empty or "symbol" not in basic.columns:
        return None

    rows = basic.copy()
    if "name" not in rows.columns:
        rows["name"] = rows["symbol"]
    if "index_name" not in rows.columns:
        rows["index_name"] = None

    themes = rows.apply(
        lambda row: infer_etf_theme(row.get("name"), row.get("index_name")),
        axis=1,
    )
    return pd.Series(themes.to_numpy(), index=rows["symbol"].astype(str), dtype="object")


def _rank_factor_frame(
    frame: pd.DataFrame,
    factor: Factor,
    *,
    processed: bool = False,
) -> pd.DataFrame:
    ranked = frame.copy()
    ascending = False if processed else factor.direction == "lower_better"
    ranked["rank"] = ranked.groupby("date")["factor_value"].rank(
        ascending=ascending,
        method="min",
    )
    ranked["percentile"] = ranked.groupby("date")["factor_value"].rank(
        ascending=not ascending,
        pct=True,
    )
    ranked["factor_name"] = factor.name
    ranked["lookback_days"] = factor.lookback_days
    return ranked


def rebuild_factors() -> dict[str, object]:
    daily = read_parquet(settings.clean_dir / "etf_daily.parquet")
    if daily.empty:
        raise RuntimeError("No clean ETF daily data found. Collect ETF daily data first.")

    required_columns = {"symbol", "date", "close"}
    missing = sorted(required_columns - set(daily.columns))
    if missing:
        raise ValueError(f"ETF daily data missing columns for factor calculation: {missing}")

    daily["date"] = pd.to_datetime(daily["date"]).dt.date
    daily["close"] = pd.to_numeric(daily["close"], errors="coerce")
    daily = daily.dropna(subset=["symbol", "date", "close"])
    daily = daily.sort_values(["symbol", "date"])

    frames: list[pd.DataFrame] = []
    processed_frames: list[pd.DataFrame] = []
    theme_groups = _theme_groups_by_symbol() if settings.factor_neutralize else None
    for factor in FACTOR_REGISTRY.values():
        factor_frame = daily[["symbol", "date"]].copy()
        factor_frame["factor_value"] = factor.compute(daily)
        factor_frame["factor_value"] = pd.to_numeric(factor_frame["factor_value"], errors="coerce")
        factor_frame = factor_frame.replace([float("inf"), -float("inf")], pd.NA)
        factor_frame = factor_frame.dropna(subset=["factor_value"])
        if factor_frame.empty:
            continue

        frames.append(_rank_factor_frame(factor_frame, factor))

        raw_series = factor_frame.set_index(["date", "symbol"])["factor_value"].sort_index()
        processed_series = process_factor(
            raw_series,
            direction=factor.direction,
            method=settings.factor_outlier_method,
            mad_n=settings.factor_outlier_mad_n,
            standardize=settings.factor_standardize,
            groupby=theme_groups,
            neutralize_method=settings.factor_neutralize_method,
            min_cross_section_size=settings.factor_min_cross_section_size,
        )
        processed_frame = (
            processed_series.rename("factor_value")
            .reset_index()
            .replace([float("inf"), -float("inf")], pd.NA)
            .dropna(subset=["factor_value"])
        )
        if not processed_frame.empty:
            processed_frames.append(
                _rank_factor_frame(processed_frame, factor, processed=True)
            )

    if not frames:
        raise RuntimeError("No factor data could be computed from the daily data.")

    output = pd.concat(frames, ignore_index=True)
    output["provider"] = "local"
    output["updated_at"] = datetime.now(UTC)
    output["rank"] = output["rank"].astype(int)

    write_parquet(output, _factor_path(processed=False))

    processed_output = (
        pd.concat(processed_frames, ignore_index=True)
        if processed_frames
        else output.head(0).copy()
    )
    processed_output["provider"] = "local"
    processed_output["updated_at"] = datetime.now(UTC)
    processed_output["rank"] = processed_output["rank"].astype(int)
    write_parquet(processed_output, _factor_path(processed=True))

    latest_date = output["date"].max().isoformat()
    factor_summaries = [
        {"factor_name": name, "rows": int(len(output[output["factor_name"] == name]))}
        for name in output["factor_name"].unique()
    ]
    return {
        "factors": factor_summaries,
        "total_rows": int(len(output)),
        "processed_rows": int(len(processed_output)),
        "symbols": int(output["symbol"].nunique()),
        "latest_date": latest_date,
    }


def _read_factors(*, processed: bool = False) -> pd.DataFrame:
    return read_parquet(_factor_path(processed=processed))


def _factor_definition(factor: Factor) -> dict[str, object]:
    return {
        "name": factor.name,
        "label": factor.label,
        "description": factor.description,
        "lookback_days": str(factor.lookback_days),
        "direction": factor.direction,
        "category": factor.category,
        "format": factor.value_format,
        "interpretation": factor.interpretation,
        "limitation": _factor_limitation(factor),
    }


def get_factor_definitions() -> list[dict[str, object]]:
    return [
        _factor_definition(f)
        for f in FACTOR_REGISTRY.values()
    ]


def _factor_limitation(factor: Factor) -> str:
    if factor.category == "return":
        return "趋势可能反转，历史动量不代表未来延续。"
    if factor.category == "risk":
        return "低风险指标不等于高收益，只说明该风险维度更温和。"
    if factor.category == "liquidity":
        return "成交额可能受短期放量影响，需要观察持续性。"
    if factor.category == "trend":
        return "均线类指标具有滞后性，对快速反转不敏感。"
    return "该因子仅用于历史研究，需要结合其他指标验证。"


def _factor_scores_from_frame(frame: pd.DataFrame) -> list[FactorScore]:
    basic = read_parquet(settings.clean_dir / "etf_basic.parquet")
    output = frame.copy()
    if not basic.empty:
        basic = basic[["symbol", "name", "index_name"]].copy()
        output = output.merge(basic, on="symbol", how="left")
    else:
        output["name"] = output["symbol"]
        output["index_name"] = None

    output["name"] = output["name"].fillna(output["symbol"])
    output["theme"] = output.apply(
        lambda row: infer_etf_theme(row.get("name"), row.get("index_name")),
        axis=1,
    )
    return [FactorScore(**record) for record in dataframe_records(output)]


def _total_symbol_count() -> int:
    basic = read_parquet(settings.clean_dir / "etf_basic.parquet")
    if not basic.empty and "symbol" in basic.columns:
        return int(basic["symbol"].nunique())
    daily = read_parquet(settings.clean_dir / "etf_daily.parquet")
    if not daily.empty and "symbol" in daily.columns:
        return int(daily["symbol"].nunique())
    return 0


def _distribution(frame: pd.DataFrame) -> FactorDistribution:
    values = pd.to_numeric(frame["factor_value"], errors="coerce").dropna()
    total_symbols = _total_symbol_count()
    if values.empty:
        return FactorDistribution(missing_count=total_symbols)
    return FactorDistribution(
        count=int(len(values)),
        missing_count=max(total_symbols - int(len(values)), 0),
        min=float(values.min()),
        p25=float(values.quantile(0.25)),
        median=float(values.median()),
        p75=float(values.quantile(0.75)),
        max=float(values.max()),
        mean=float(values.mean()),
    )


def _forward_return_diagnostic(
    factors: pd.DataFrame,
    factor_name: str,
    target_date: date,
    horizon: int,
) -> FactorForwardReturn:
    daily = read_parquet(settings.clean_dir / "etf_daily.parquet")
    if daily.empty or not {"symbol", "date", "close"}.issubset(daily.columns):
        return FactorForwardReturn(
            horizon=horizon,
            data_notes=["缺少可用于未来收益诊断的日线 close 数据。"],
        )

    daily = daily[["symbol", "date", "close"]].copy()
    daily["date"] = pd.to_datetime(daily["date"]).dt.date
    daily["close"] = pd.to_numeric(daily["close"], errors="coerce")
    daily = daily.dropna(subset=["symbol", "date", "close"]).sort_values(["symbol", "date"])
    daily["future_close"] = daily.groupby("symbol")["close"].shift(-horizon)
    daily["forward_return"] = daily["future_close"] / daily["close"] - 1

    factor_rows = factors[
        (factors["factor_name"] == factor_name)
        & (pd.to_datetime(factors["date"]).dt.date <= target_date)
    ].copy()
    factor_rows["date"] = pd.to_datetime(factor_rows["date"]).dt.date
    merged = factor_rows.merge(
        daily[["symbol", "date", "forward_return"]],
        on=["symbol", "date"],
        how="left",
    ).dropna(subset=["forward_return"])

    top_means: list[float] = []
    bottom_means: list[float] = []
    for _, group in merged.groupby("date"):
        group = group.sort_values("rank")
        if len(group) < 4:
            continue
        bucket_size = max(1, ceil(len(group) * 0.2))
        top_means.append(float(group.head(bucket_size)["forward_return"].mean()))
        bottom_means.append(float(group.tail(bucket_size)["forward_return"].mean()))

    if not top_means or not bottom_means:
        return FactorForwardReturn(
            horizon=horizon,
            data_notes=["当前样本不足，暂不解读有效性。"],
        )

    top_mean = float(pd.Series(top_means).mean())
    bottom_mean = float(pd.Series(bottom_means).mean())
    return FactorForwardReturn(
        horizon=horizon,
        sample_count=len(top_means),
        top_mean=top_mean,
        bottom_mean=bottom_mean,
        spread=top_mean - bottom_mean,
        data_notes=["Top/Bottom 仅为历史样本表现，不构成交易结论。"],
    )


def _stability_diagnostic(
    factors: pd.DataFrame,
    factor_name: str,
    target_date: date,
    lookback_dates: int = 20,
) -> FactorStability:
    history = factors[factors["factor_name"] == factor_name].copy()
    if history.empty:
        return FactorStability(data_notes=["缺少该因子的历史排名。"])
    history["date"] = pd.to_datetime(history["date"]).dt.date
    dates = sorted(
        date_value for date_value in history["date"].unique() if date_value <= target_date
    )
    dates = dates[-lookback_dates:]
    if len(dates) < 2:
        return FactorStability(
            lookback_dates=len(dates),
            data_notes=["可用历史日期不足，暂不判断稳定性。"],
        )

    window = history[history["date"].isin(dates)]
    pivot = window.pivot_table(index="date", columns="symbol", values="rank", aggfunc="first")
    changes = pivot.sort_index().diff().abs().stack().dropna()
    if changes.empty:
        return FactorStability(
            lookback_dates=len(dates),
            data_notes=["可比较排名变化样本不足。"],
        )
    average_change = float(changes.mean())
    if average_change <= 5:
        label = "较稳定"
    elif average_change <= 15:
        label = "中等波动"
    else:
        label = "跳动较大"
    return FactorStability(
        lookback_dates=len(dates),
        average_rank_change=average_change,
        label=label,
        data_notes=["排名稳定性用于观察因子噪声，不能单独判断因子有效。"],
    )


def list_factor_scores(
    factor_name: str = "momentum_60d",
    factor_date: date | None = None,
    limit: int = 100,
    processed: bool = False,
) -> list[FactorScore]:
    factors = _read_factors(processed=processed)
    if factors.empty:
        return []

    factors = factors[factors["factor_name"] == factor_name].copy()
    if factors.empty:
        return []

    factors["date"] = pd.to_datetime(factors["date"]).dt.date
    target_date = factor_date or factors["date"].max()
    factors = factors[factors["date"] == target_date].copy()
    factors = factors.sort_values(["rank", "symbol"]).head(limit)

    basic = read_parquet(settings.clean_dir / "etf_basic.parquet")
    if not basic.empty:
        basic = basic[["symbol", "name", "index_name"]].copy()
        factors = factors.merge(basic, on="symbol", how="left")
    else:
        factors["name"] = factors["symbol"]
        factors["index_name"] = None

    factors["name"] = factors["name"].fillna(factors["symbol"])
    factors["theme"] = factors.apply(
        lambda row: infer_etf_theme(row.get("name"), row.get("index_name")),
        axis=1,
    )

    return [FactorScore(**record) for record in dataframe_records(factors)]


def get_factor_history(
    symbol: str,
    factor_name: str,
    processed: bool = False,
) -> list[FactorHistoryPoint]:
    factors = _read_factors(processed=processed)
    if factors.empty:
        return []

    mask = (factors["symbol"] == symbol) & (factors["factor_name"] == factor_name)
    history = factors[mask].copy()
    if history.empty:
        return []

    history["date"] = pd.to_datetime(history["date"]).dt.date
    history = history.sort_values("date")
    return [FactorHistoryPoint(**record) for record in dataframe_records(history)]


def get_factor_diagnostics(
    factor_name: str = "momentum_60d",
    factor_date: date | None = None,
    horizon: int = 20,
    limit: int = 10,
    processed: bool = False,
) -> FactorDiagnostics | None:
    factor = FACTOR_REGISTRY.get(factor_name)
    if factor is None:
        return None

    factors = _read_factors(processed=processed)
    if factors.empty:
        return FactorDiagnostics(
            factor_name=factor_name,
            definition=_factor_definition(factor),
            distribution=FactorDistribution(),
            forward_return=FactorForwardReturn(
                horizon=horizon,
                data_notes=["缺少因子数据，暂不解读有效性。"],
            ),
            stability=FactorStability(data_notes=["缺少因子数据，暂不判断稳定性。"]),
            data_notes=["缺少因子数据，请先重建因子。"],
        )

    factors = factors.copy()
    factors["date"] = pd.to_datetime(factors["date"]).dt.date
    factor_rows = factors[factors["factor_name"] == factor_name].copy()
    if factor_rows.empty:
        return None

    target_date = factor_date or factor_rows["date"].max()
    current = factor_rows[factor_rows["date"] == target_date].copy()
    if current.empty:
        return FactorDiagnostics(
            factor_name=factor_name,
            date=target_date,
            definition=_factor_definition(factor),
            distribution=FactorDistribution(missing_count=_total_symbol_count()),
            forward_return=FactorForwardReturn(
                horizon=horizon,
                data_notes=["指定日期没有该因子的横截面数据。"],
            ),
            stability=FactorStability(data_notes=["指定日期没有该因子的历史排名。"]),
            data_notes=["指定日期没有该因子的横截面数据。"],
        )

    top = current.sort_values(["rank", "symbol"]).head(limit)
    bottom = current.sort_values(["rank", "symbol"], ascending=[False, True]).head(limit)
    return FactorDiagnostics(
        factor_name=factor_name,
        date=target_date,
        definition=_factor_definition(factor),
        distribution=_distribution(current),
        top=_factor_scores_from_frame(top),
        bottom=_factor_scores_from_frame(bottom),
        forward_return=_forward_return_diagnostic(
            factors=factors,
            factor_name=factor_name,
            target_date=target_date,
            horizon=horizon,
        ),
        stability=_stability_diagnostic(
            factors=factors,
            factor_name=factor_name,
            target_date=target_date,
        ),
        data_notes=[
            "诊断结果基于本地清洗数据和历史因子结果。",
            "本页面只用于学习和研究，不构成投资建议。",
        ],
    )
