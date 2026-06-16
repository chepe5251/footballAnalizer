from datetime import datetime
from pathlib import Path

import pandas as pd

from logger import log


def export_to_csv(
    df: pd.DataFrame,
    calibration: pd.DataFrame,
    strategy_metrics: pd.DataFrame,
    output_prefix: str,
):
    """
    Exports three CSV files into backtest_output/:
      {prefix}_{timestamp}_matches.csv     — one row per match
      {prefix}_{timestamp}_calibration.csv — calibration by probability bin
      {prefix}_{timestamp}_summary.csv     — strategy performance metrics
    """
    output_dir = Path("backtest_output")
    output_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = f"{output_prefix}_{timestamp}"

    matches_path = output_dir / f"{base}_matches.csv"
    df.to_csv(matches_path, index=False, float_format="%.4f")
    log.info(f"Matches CSV saved: {matches_path}")

    cal_path = output_dir / f"{base}_calibration.csv"
    calibration.to_csv(cal_path, index=False)
    log.info(f"Calibration CSV saved: {cal_path}")

    summary_path = output_dir / f"{base}_summary.csv"
    strategy_metrics.to_csv(summary_path, index=False)
    log.info(f"Summary CSV saved: {summary_path}")

    _print_summary(df, calibration, strategy_metrics, output_dir)


def _print_summary(df, calibration, strategy_metrics, output_dir):
    sep = "=" * 60
    print(f"\n{sep}")
    print("BACKTEST RESULTS SUMMARY")
    print(sep)
    print(f"Total matches analyzed : {len(df)}")
    print(f"Leagues                : {df['league'].unique().tolist()}")
    print(f"Seasons                : {df['season'].unique().tolist()}")

    print("\n--- STRATEGY PERFORMANCE ---")
    print(strategy_metrics.to_string(index=False))

    visible_cal = calibration[calibration["n_predictions"] > 10]
    if not visible_cal.empty:
        print("\n--- CALIBRATION (bins with >10 predictions) ---")
        print(visible_cal.to_string(index=False))

    print(sep)
    print(f"\nFiles saved to: {output_dir.absolute()}")
