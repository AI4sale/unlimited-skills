from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from verify_v064_money_saved_tier_smoke import main


if __name__ == "__main__":
    raise SystemExit(main())
