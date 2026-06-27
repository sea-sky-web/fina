from __future__ import annotations

from datetime import UTC, date, datetime
from math import sqrt

import pandas as pd

from app.core.config import settings
from app.factors.registry import FACTOR_REGISTRY
from app.models import (
    FactorClusterGroup,
    FactorCorrelationMatrix,
    FactorEvaluationReport,
    FactorICPoint,
    FactorICStats,
    FactorPoolEvaluationReport,
    FactorQuantilePoint,
    FactorQuantileReturns,
    FactorTurnoverStats,
    RedundantFactorPair,
)
from app.services.cache import FingerprintCache, clean_data_fingerprint
from app.services.factor_service import _read_factors
from app.storage.parquet_store import read_parquet

_REPORT_CACHE = FingerprintCache(max_items=128)
_POOL_REPORT_CACHE = FingerprintCache(max_items=32)


def default_horizons() -> list[int]:
    values: list[int] = []
    for item in settings.factor_evaluation_horizons.split(","):
        try:
            horizon = int(item.strip())
        except ValueError:
            continue
        if horizon > 0 and horizon not in values:
            values.append(horizon)
    return values or [1, 5, 10, 20]


def _data_fingerprint(processed: bool) -> tuple[object, ...]:
    factor_file = "factors_processed.parquet" if processed else "factors.parquet"
    return clean_data_fingerprint(["etf_daily.parquet", factor_file])


def _clean_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number in {float("inf"), float("-inf")}:
        return None
    return number


def _safe_corr(left: pd.Series, right: pd.Series) -> float | None:
    paired = pd.concat(
        [
            pd.to_numeric(left, errors="coerce").rename("left"),
            pd.to_numeric(right, errors="coerce").rename("right"),
        ],
        axis=1,
    ).dropna()
    if len(paired) < 2:
        return None
    if paired["left"].std(ddof=0) == 0 or paired["right"].std(ddof=0) == 0:
        return None
    return _clean_float(paired["left"].corr(paired["right"]))


def _date_filtered(frame: pd.DataFrame, start: date | None, end: date | None) -> pd.DataFrame:
    output = frame.copy()
    output["date"] = pd.to_datetime(output["date"]).dt.date
    if start is not None:
        output = output[output["date"] >= start]
    if end is not None:
        output = output[output["date"] <= end]
    return output


def _factor_rows(
    factor_name: str,
    start: date | None = None,
    end: date | None = None,
    *,
    processed: bool = True,
) -> pd.DataFrame:
    factors = _read_factors(processed=processed)
    if factors.empty or "factor_name" not in factors.columns:
        return pd.DataFrame()
    rows = factors[factors["factor_name"] == factor_name].copy()
    if rows.empty:
        return rows
    rows = _date_filtered(rows, start, end)
    rows["factor_value"] = pd.to_numeric(rows["factor_value"], errors="coerce")
    return rows.dropna(subset=["symbol", "date", "factor_value"])


def _daily_forward_returns(horizon: int) -> pd.DataFrame:
    daily = read_parquet(settings.clean_dir / "etf_daily.parquet")
    if daily.empty or not {"symbol", "date", "close"}.issubset(daily.columns):
        return pd.DataFrame()

    daily = daily[["symbol", "date", "close"]].copy()
    daily["date"] = pd.to_datetime(daily["date"]).dt.date
    daily["close"] = pd.to_numeric(daily["close"], errors="coerce")
    daily = daily.dropna(subset=["symbol", "date", "close"]).sort_values(["symbol", "date"])
    daily["future_close"] = daily.groupby("symbol")["close"].shift(-horizon)
    daily["forward_return"] = daily["future_close"] / daily["close"] - 1
    return daily[["symbol", "date", "forward_return"]].dropna(subset=["forward_return"])


def _factor_forward_frame(
    factor_name: str,
    horizon: int,
    start: date | None = None,
    end: date | None = None,
    *,
    processed: bool = True,
) -> pd.DataFrame:
    factors = _factor_rows(factor_name, start=start, end=end, processed=processed)
    forward = _daily_forward_returns(horizon)
    if factors.empty or forward.empty:
        return pd.DataFrame()
    return factors.merge(forward, on=["symbol", "date"], how="inner").dropna(
        subset=["factor_value", "forward_return"]
    )


def _rank_ic_series(merged: pd.DataFrame) -> list[FactorICPoint]:
    points: list[FactorICPoint] = []
    if merged.empty:
        return points

    for date_value, group in merged.groupby("date"):
        if group["symbol"].nunique() < 4:
            continue
        factor_rank = group["factor_value"].rank(method="average")
        return_rank = group["forward_return"].rank(method="average")
        ic_value = _safe_corr(factor_rank, return_rank)
        if ic_value is not None:
            points.append(FactorICPoint(date=date_value, ic_value=float(ic_value)))
    return points


def _ic_mean_for_horizon(
    factor_name: str,
    horizon: int,
    start: date | None,
    end: date | None,
    *,
    processed: bool = True,
) -> float | None:
    points = _rank_ic_series(
        _factor_forward_frame(
            factor_name,
            horizon,
            start=start,
            end=end,
            processed=processed,
        )
    )
    if not points:
        return None
    return float(pd.Series([point.ic_value for point in points]).mean())


def calculate_ic_stats(
    factor_name: str,
    *,
    start: date | None = None,
    end: date | None = None,
    horizon: int = 20,
    horizons: list[int] | None = None,
    processed: bool = True,
) -> FactorICStats:
    merged = _factor_forward_frame(
        factor_name,
        horizon,
        start=start,
        end=end,
        processed=processed,
    )
    points = _rank_ic_series(merged)
    values = pd.Series([point.ic_value for point in points], dtype="float64")
    rank_ic_mean = _clean_float(values.mean()) if not values.empty else None
    rank_ic_std = _clean_float(values.std(ddof=1)) if len(values) > 1 else None
    icir = (
        _clean_float(rank_ic_mean / rank_ic_std)
        if rank_ic_mean is not None and rank_ic_std not in (None, 0)
        else None
    )
    ic_t_stat = (
        _clean_float(rank_ic_mean / (rank_ic_std / sqrt(len(values))))
        if rank_ic_mean is not None and rank_ic_std not in (None, 0) and len(values) > 1
        else None
    )
    ic_pos_ratio = _clean_float((values > 0).mean()) if not values.empty else None
    requested_horizons = horizons or default_horizons()

    return FactorICStats(
        factor_name=factor_name,
        period_start=points[0].date if points else None,
        period_end=points[-1].date if points else None,
        num_periods=len(points),
        rank_ic_mean=rank_ic_mean,
        rank_ic_std=rank_ic_std,
        icir=icir,
        ic_pos_ratio=ic_pos_ratio,
        ic_t_stat=ic_t_stat,
        ic_series=points,
        ic_by_horizon={
            item: _clean_float(
                _ic_mean_for_horizon(
                    factor_name,
                    item,
                    start,
                    end,
                    processed=processed,
                )
            )
            for item in requested_horizons
        },
    )


def calculate_quantile_returns(
    factor_name: str,
    *,
    horizon: int = 20,
    num_quantiles: int = 5,
    start: date | None = None,
    end: date | None = None,
    processed: bool = True,
) -> FactorQuantileReturns:
    merged = _factor_forward_frame(
        factor_name,
        horizon,
        start=start,
        end=end,
        processed=processed,
    )
    labels = [f"Q{index}" for index in range(1, num_quantiles + 1)]
    series_points: list[FactorQuantilePoint] = []
    if merged.empty or "date" not in merged.columns:
        return FactorQuantileReturns(
            factor_name=factor_name,
            horizon_days=horizon,
            num_quantiles=num_quantiles,
            quantile_returns={label: None for label in labels},
        )

    for date_value, group in merged.groupby("date"):
        if group["symbol"].nunique() < num_quantiles:
            continue
        ordered = group.sort_values(["factor_value", "symbol"], ascending=[False, True]).copy()
        ordered["bucket"] = [
            min(num_quantiles, int(position * num_quantiles / len(ordered)) + 1)
            for position in range(len(ordered))
        ]
        returns = {
            f"Q{bucket}": _clean_float(bucket_rows["forward_return"].mean())
            for bucket, bucket_rows in ordered.groupby("bucket")
        }
        series_points.append(
            FactorQuantilePoint(
                date=date_value,
                returns={label: returns.get(label) for label in labels},
            )
        )

    means: dict[str, float | None] = {}
    for label in labels:
        values = [
            point.returns[label]
            for point in series_points
            if point.returns[label] is not None
        ]
        means[label] = float(pd.Series(values).mean()) if values else None

    spread = (
        _clean_float(means["Q1"] - means[f"Q{num_quantiles}"])
        if means.get("Q1") is not None and means.get(f"Q{num_quantiles}") is not None
        else None
    )
    monotonic_values = [means[label] for label in labels]
    is_monotonic = all(
        left is not None and right is not None and left >= right
        for left, right in zip(monotonic_values, monotonic_values[1:], strict=False)
    )

    return FactorQuantileReturns(
        factor_name=factor_name,
        horizon_days=horizon,
        num_quantiles=num_quantiles,
        quantile_returns=means,
        spread=spread,
        is_monotonic=is_monotonic,
        quantile_series=series_points,
    )


def calculate_factor_correlation_matrix(
    *,
    target_date: date | None = None,
    end: date | None = None,
    processed: bool = True,
) -> FactorCorrelationMatrix:
    factors = _read_factors(processed=processed)
    if factors.empty:
        return FactorCorrelationMatrix()

    factors = factors.copy()
    factors["date"] = pd.to_datetime(factors["date"]).dt.date
    if end is not None:
        factors = factors[factors["date"] <= end]
    if factors.empty:
        return FactorCorrelationMatrix()

    date_value = target_date or factors["date"].max()
    current = factors[factors["date"] == date_value].copy()
    if current.empty:
        return FactorCorrelationMatrix(date=date_value)

    factor_names = [name for name in FACTOR_REGISTRY if name in set(current["factor_name"])]
    pivot = current.pivot_table(
        index="symbol",
        columns="factor_name",
        values="factor_value",
        aggfunc="first",
    ).reindex(columns=factor_names)
    matrix: list[list[float | None]] = []
    redundant_pairs: list[RedundantFactorPair] = []

    for row_name in factor_names:
        row: list[float | None] = []
        for column_name in factor_names:
            value = _safe_corr(pivot[row_name], pivot[column_name])
            if row_name == column_name and value is None:
                value = 1.0
            row.append(value)
        matrix.append(row)

    for left_index, left_name in enumerate(factor_names):
        for right_name in factor_names[left_index + 1 :]:
            value = _safe_corr(pivot[left_name], pivot[right_name])
            if value is not None and abs(value) > 0.6:
                redundant_pairs.append(
                    RedundantFactorPair(
                        factor_a=left_name,
                        factor_b=right_name,
                        correlation=value,
                    )
                )

    return FactorCorrelationMatrix(
        date=date_value,
        factor_names=factor_names,
        matrix=matrix,
        redundant_pairs=redundant_pairs,
    )


def _quantile_table(rows: pd.DataFrame, num_quantiles: int = 5) -> pd.DataFrame:
    records: list[pd.DataFrame] = []
    for date_value, group in rows.groupby("date"):
        if group["symbol"].nunique() < num_quantiles:
            continue
        ordered = group.sort_values(["rank", "symbol"]).copy()
        ordered["quantile"] = [
            min(num_quantiles, int(position * num_quantiles / len(ordered)) + 1)
            for position in range(len(ordered))
        ]
        ordered["date"] = date_value
        records.append(ordered[["date", "symbol", "quantile"]])
    return pd.concat(records, ignore_index=True) if records else pd.DataFrame()


def calculate_turnover_stats(
    factor_name: str,
    *,
    start: date | None = None,
    end: date | None = None,
    processed: bool = True,
) -> FactorTurnoverStats:
    rows = _factor_rows(factor_name, start=start, end=end, processed=processed)
    if rows.empty:
        return FactorTurnoverStats(factor_name=factor_name)

    pivot = rows.pivot_table(index="date", columns="symbol", values="rank", aggfunc="first")
    rank_autocorr: dict[int, float | None] = {}
    for lag in [1, 5, 20]:
        prior = pivot.shift(lag).stack()
        current = pivot.stack()
        common = prior.index.intersection(current.index)
        rank_autocorr[lag] = (
            _safe_corr(prior.loc[common], current.loc[common])
            if len(common) > 2
            else None
        )

    quantiles = _quantile_table(rows)
    matrix_counts = [[0 for _ in range(5)] for _ in range(5)]
    total_transitions = 0
    same_quantile = 0
    if not quantiles.empty:
        table = quantiles.pivot_table(
            index="date",
            columns="symbol",
            values="quantile",
            aggfunc="first",
        ).sort_index()
        dates = list(table.index)
        for previous_date, current_date in zip(dates, dates[1:], strict=False):
            previous = table.loc[previous_date].dropna()
            current = table.loc[current_date].dropna()
            common_symbols = previous.index.intersection(current.index)
            for symbol in common_symbols:
                previous_quantile = int(previous.loc[symbol])
                current_quantile = int(current.loc[symbol])
                matrix_counts[previous_quantile - 1][current_quantile - 1] += 1
                total_transitions += 1
                same_quantile += int(previous_quantile == current_quantile)

    migration_matrix: list[list[float | None]] = []
    for row in matrix_counts:
        row_total = sum(row)
        migration_matrix.append(
            [round(value / row_total, 4) if row_total else None for value in row]
        )

    avg_turnover = (
        _clean_float(1 - same_quantile / total_transitions)
        if total_transitions
        else None
    )
    return FactorTurnoverStats(
        factor_name=factor_name,
        rank_autocorr=rank_autocorr,
        avg_turnover=avg_turnover,
        migration_matrix=migration_matrix,
    )


def _report_warnings(
    factor_name: str,
    ic: FactorICStats,
    primary_quantile: FactorQuantileReturns | None,
    correlations: FactorCorrelationMatrix,
) -> list[str]:
    warnings: list[str] = []
    if ic.num_periods < 10:
        warnings.append("IC 样本期数不足 10，统计结论需要继续观察。")
    if ic.icir is None:
        warnings.append("ICIR 暂不可计算，可能是 IC 样本不足或波动为 0。")
    elif ic.icir < 0.2:
        warnings.append("ICIR 低于 0.2，暂不适合单独作为稳定因子使用。")
    if ic.ic_pos_ratio is not None and ic.ic_pos_ratio < 0.55:
        warnings.append("IC 为正比例低于 55%，方向稳定性不足。")
    if primary_quantile is not None and not primary_quantile.is_monotonic:
        warnings.append("分位数收益暂未呈现单调结构。")
    for pair in correlations.redundant_pairs:
        if pair.factor_a == factor_name or pair.factor_b == factor_name:
            other = pair.factor_b if pair.factor_a == factor_name else pair.factor_a
            warnings.append(f"与 {other} 的相关性较高，合成信号时需要降权或择一。")
    return warnings


def _overall_verdict(ic: FactorICStats, warnings: list[str]) -> str:
    if ic.num_periods < 5:
        return "待观察"
    if ic.icir is not None and ic.ic_pos_ratio is not None:
        if ic.icir >= 0.3 and ic.ic_pos_ratio >= 0.55:
            return "可用"
        if ic.icir < 0.05 or ic.ic_pos_ratio < 0.45:
            return "不推荐单独使用"
    if len(warnings) >= 3:
        return "不推荐单独使用"
    return "待观察"


def generate_factor_evaluation_report(
    factor_name: str,
    *,
    start: date | None = None,
    end: date | None = None,
    horizons: list[int] | None = None,
    processed: bool = True,
) -> FactorEvaluationReport | None:
    if factor_name not in FACTOR_REGISTRY:
        return None

    requested_horizons = horizons or default_horizons()
    cache_key = (
        "factor",
        factor_name,
        start,
        end,
        tuple(requested_horizons),
        processed,
        _data_fingerprint(processed),
    )
    cached = _REPORT_CACHE.get(cache_key)
    if cached is not None:
        return cached

    primary_horizon = requested_horizons[-1]
    rows = _factor_rows(factor_name, start=start, end=end, processed=processed)
    correlations = calculate_factor_correlation_matrix(end=end, processed=processed)
    ic = calculate_ic_stats(
        factor_name,
        start=start,
        end=end,
        horizon=primary_horizon,
        horizons=requested_horizons,
        processed=processed,
    )
    quantile_returns = {
        horizon: calculate_quantile_returns(
            factor_name,
            horizon=horizon,
            start=start,
            end=end,
            processed=processed,
        )
        for horizon in requested_horizons
    }
    turnover = calculate_turnover_stats(
        factor_name,
        start=start,
        end=end,
        processed=processed,
    )
    primary_quantile = quantile_returns.get(primary_horizon)
    warnings = _report_warnings(factor_name, ic, primary_quantile, correlations)

    num_assets_avg = (
        float(rows.groupby("date")["symbol"].nunique().mean())
        if not rows.empty
        else 0.0
    )

    report = FactorEvaluationReport(
        factor_name=factor_name,
        generated_at=datetime.now(UTC),
        period_start=rows["date"].min() if not rows.empty else None,
        period_end=rows["date"].max() if not rows.empty else None,
        num_assets_avg=num_assets_avg,
        ic=ic,
        quantile_returns=quantile_returns,
        correlations=correlations,
        turnover=turnover,
        warnings=warnings,
        overall_verdict=_overall_verdict(ic, warnings),
    )
    _REPORT_CACHE.set(cache_key, report)
    return report


def generate_factor_pool_report(
    *,
    start: date | None = None,
    end: date | None = None,
    horizons: list[int] | None = None,
    processed: bool = True,
) -> FactorPoolEvaluationReport:
    requested_horizons = horizons or default_horizons()
    cache_key = (
        "pool",
        start,
        end,
        tuple(requested_horizons),
        processed,
        _data_fingerprint(processed),
    )
    cached = _POOL_REPORT_CACHE.get(cache_key)
    if cached is not None:
        return cached

    reports = [
        report
        for name in FACTOR_REGISTRY
        if (
            report := generate_factor_evaluation_report(
                name,
                start=start,
                end=end,
                horizons=requested_horizons,
                processed=processed,
            )
        )
        is not None
    ]
    correlation_matrix = calculate_factor_correlation_matrix(end=end, processed=processed)
    cluster_map: dict[str, list[str]] = {}
    for name, factor in FACTOR_REGISTRY.items():
        cluster_map.setdefault(factor.category, []).append(name)
    recommendations = [
        (
            f"{pair.factor_a} 与 {pair.factor_b} 相关性 {pair.correlation:.2f}，"
            "合成时应避免重复加权。"
        )
        for pair in correlation_matrix.redundant_pairs
    ]
    if not recommendations:
        recommendations.append("当前因子池未发现 |相关性| > 0.6 的高冗余因子对。")

    if len(correlation_matrix.factor_names) < 2:
        pool_health = "因子不足"
    elif correlation_matrix.redundant_pairs:
        pool_health = "冗余"
    else:
        pool_health = "健康"

    report = FactorPoolEvaluationReport(
        generated_at=datetime.now(UTC),
        individual_reports=reports,
        correlation_matrix=correlation_matrix,
        cluster_groups=[
            FactorClusterGroup(group=category, factors=factors)
            for category, factors in cluster_map.items()
        ],
        pool_health=pool_health,
        recommendations=recommendations,
    )
    _POOL_REPORT_CACHE.set(cache_key, report)
    return report
