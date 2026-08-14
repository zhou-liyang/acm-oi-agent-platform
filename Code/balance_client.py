import json
import os
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv


@dataclass
class BalanceInfo:
    currency: str
    total: str
    granted: str
    topped_up: str


@dataclass
class BalanceResult:
    ok: bool
    available: bool
    balances: list[BalanceInfo]
    error: str = ""


def get_balance() -> BalanceResult:
    load_dotenv()

    api_key = os.getenv("DEEPSEEK_API_KEY")

    if not api_key:
        return BalanceResult(
            ok=False,
            available=False,
            balances=[],
            error="DEEPSEEK_API_KEY is not set.",
        )

    base_url = os.getenv(
        "DEEPSEEK_BASE_URL",
        "https://api.deepseek.com",
    ).rstrip("/")

    request = Request(
        f"{base_url}/user/balance",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
        },
        method="GET",
    )

    try:
        with urlopen(request, timeout=15) as response:
            data = json.loads(
                response.read().decode("utf-8")
            )

    except HTTPError as error:
        return BalanceResult(
            ok=False,
            available=False,
            balances=[],
            error=f"HTTP {error.code}: {error.reason}",
        )

    except URLError as error:
        return BalanceResult(
            ok=False,
            available=False,
            balances=[],
            error=f"Connection error: {error.reason}",
        )

    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        return BalanceResult(
            ok=False,
            available=False,
            balances=[],
            error=str(error),
        )

    balances = []

    for item in data.get("balance_infos", []):
        balances.append(
            BalanceInfo(
                currency=str(item.get("currency", "")),
                total=str(item.get("total_balance", "0")),
                granted=str(item.get("granted_balance", "0")),
                topped_up=str(
                    item.get("topped_up_balance", "0")
                ),
            )
        )

    return BalanceResult(
        ok=True,
        available=bool(data.get("is_available")),
        balances=balances,
    )


def main() -> int:
    result = get_balance()

    if not result.ok:
        print(f"ERROR: {result.error}")
        return 1

    print(
        "API available: "
        f"{'yes' if result.available else 'no'}"
    )

    for balance in result.balances:
        print()
        print(f"Currency: {balance.currency}")
        print(f"Total: {balance.total}")
        print(f"Granted: {balance.granted}")
        print(f"Topped up: {balance.topped_up}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())