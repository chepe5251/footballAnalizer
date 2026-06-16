"""
Football Agent — Backtest
Usage:
  python run_backtest.py --leagues "ENG-Premier League" "ESP-La Liga" --seasons 3
  python run_backtest.py --leagues all --seasons 2
  python run_backtest.py --leagues "ENG-Premier League" --seasons 1 --threshold 0.55
"""
import argparse
from backtest.runner import run_backtest

AVAILABLE_LEAGUES = {
    "ENG-Premier League",
    "ESP-La Liga",
    "ITA-Serie A",
    "GER-Bundesliga",
    "FRA-Ligue 1",
    "UEFA-Champions League",
    "UEFA-Europa League",
    "USA-Major League Soccer",
    "MEX-Liga MX",
    "NED-Eredivisie",
    "POR-Primeira Liga",
}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Football Agent Backtest")
    parser.add_argument(
        "--leagues", nargs="+", default=["ENG-Premier League"],
        help="League IDs to backtest, or 'all'",
    )
    parser.add_argument(
        "--seasons", type=int, default=2,
        help="Number of past completed seasons to backtest (1-3)",
    )
    parser.add_argument(
        "--threshold", type=float, default=0.55,
        help="Minimum model probability to place a bet (threshold strategy)",
    )
    parser.add_argument(
        "--stake", type=float, default=10.0,
        help="Fixed stake per bet in $ (default: 10)",
    )
    parser.add_argument(
        "--bankroll", type=float, default=1000.0,
        help="Starting bankroll for Kelly strategies (default: 1000)",
    )
    parser.add_argument(
        "--kelly-fraction", type=float, default=0.25,
        help="Kelly fraction — 0.25 = quarter Kelly (safer default)",
    )
    parser.add_argument(
        "--output", type=str, default="backtest_results",
        help="Output filename prefix (without .csv)",
    )
    args = parser.parse_args()

    leagues = (
        AVAILABLE_LEAGUES
        if args.leagues == ["all"]
        else set(args.leagues)
    )

    invalid = leagues - AVAILABLE_LEAGUES
    if invalid:
        print(f"Warning: unknown league IDs will be skipped: {invalid}")
        print(f"Valid options: {sorted(AVAILABLE_LEAGUES)}")

    run_backtest(
        leagues=leagues,
        num_seasons=args.seasons,
        threshold=args.threshold,
        fixed_stake=args.stake,
        initial_bankroll=args.bankroll,
        kelly_fraction=args.kelly_fraction,
        output_prefix=args.output,
    )
