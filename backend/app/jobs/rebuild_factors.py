import argparse
import json

from app.services.factor_service import rebuild_factors


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild ETF factor data from clean daily data.")
    parser.parse_args()
    result = rebuild_factors()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
