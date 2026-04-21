import os
import json
import requests
import pandas as pd
from datetime import datetime, timezone


COINGECKO_URL = "https://api.coingecko.com/api/v3/coins/markets"
PARAMS = {
    "vs_currency": "usd",
    "order": "market_cap_desc",
    "per_page": 50,
    "page": 1,
    "sparkline": False,
}

RAW_TO_PROCESS = "raw_data/to_process"
RAW_PROCESSED = "raw_data/processed"
TRANSFORMED_COIN = "transformed_data/coin_data"
TRANSFORMED_MARKET = "transformed_data/market_data"
TRANSFORMED_PRICE = "transformed_data/price_data"


def create_folders():
    for folder in [
        RAW_TO_PROCESS, RAW_PROCESSED,
        TRANSFORMED_COIN, TRANSFORMED_MARKET, TRANSFORMED_PRICE,
    ]:
        os.makedirs(folder, exist_ok=True)


def extract_crypto_data() -> list[dict]:
    """Pull top 50 cryptocurrencies by market cap from CoinGecko."""
    response = requests.get(COINGECKO_URL, params=PARAMS, timeout=30)
    response.raise_for_status()
    return response.json()


def save_raw_data(raw_data: list[dict]) -> str:
    """Save raw JSON to the to_process folder."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    filename = os.path.join(RAW_TO_PROCESS, f"crypto_raw_{ts}.json")
    with open(filename, "w") as f:
        json.dump(raw_data, f, indent=2)
    return filename


def move_raw_to_processed(raw_file: str):
    """Move raw file from to_process to processed after transformation."""
    dest = os.path.join(RAW_PROCESSED, os.path.basename(raw_file))
    os.rename(raw_file, dest)
    return dest


def transform_crypto_data(raw_data: list[dict]) -> dict[str, pd.DataFrame]:
    """Clean, enrich, and split into coin_data, market_data, price_data."""
    df = pd.DataFrame(raw_data)

    columns_to_keep = [
        "id", "symbol", "name", "current_price", "market_cap",
        "total_volume", "high_24h", "low_24h",
        "price_change_percentage_24h", "circulating_supply",
        "ath", "ath_date", "last_updated",
    ]
    df = df[columns_to_keep]

    df["ath_date"] = pd.to_datetime(df["ath_date"], utc=True)
    df["last_updated"] = pd.to_datetime(df["last_updated"], utc=True)

    df["symbol"] = df["symbol"].str.upper()
    df["name"] = df["name"].str.strip().str.title()

    df["price_to_ath_ratio"] = (df["current_price"] / df["ath"]).round(4)
    df["daily_price_range"] = (df["high_24h"] - df["low_24h"]).round(2)
    df["volume_to_mcap_ratio"] = (df["total_volume"] / df["market_cap"]).round(6)

    df["market_cap_tier"] = pd.cut(
        df["market_cap"],
        bins=[0, 1e9, 10e9, 100e9, float("inf")],
        labels=["Small", "Mid", "Large", "Mega"],
    )

    df["days_since_ath"] = (
        pd.Timestamp.now(tz=timezone.utc) - df["ath_date"]
    ).dt.days

    df["extracted_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    df = df.sort_values("market_cap", ascending=False).reset_index(drop=True)
    df.index += 1
    df.index.name = "rank"

    coin_df = df[["id", "symbol", "name", "market_cap_tier", "extracted_at"]].copy()

    market_df = df[[
        "id", "market_cap", "total_volume", "circulating_supply",
        "volume_to_mcap_ratio", "extracted_at",
    ]].copy()

    price_df = df[[
        "id", "current_price", "high_24h", "low_24h", "ath", "ath_date",
        "price_change_percentage_24h", "price_to_ath_ratio",
        "daily_price_range", "days_since_ath", "last_updated", "extracted_at",
    ]].copy()

    return {"coin_data": coin_df, "market_data": market_df, "price_data": price_df}


def load_transformed(datasets: dict[str, pd.DataFrame]) -> list[str]:
    """Write each transformed DataFrame to its subfolder as CSV."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    folder_map = {
        "coin_data": TRANSFORMED_COIN,
        "market_data": TRANSFORMED_MARKET,
        "price_data": TRANSFORMED_PRICE,
    }
    output_files = []
    for name, df in datasets.items():
        filepath = os.path.join(folder_map[name], f"{name}_{ts}.csv")
        df.to_csv(filepath)
        output_files.append(filepath)
    return output_files


def run_etl():
    create_folders()

    print("Extracting data from CoinGecko API...")
    raw = extract_crypto_data()
    print(f"  -> Pulled {len(raw)} records")

    raw_file = save_raw_data(raw)
    print(f"  -> Saved raw JSON to '{raw_file}'")

    print("Transforming data...")
    datasets = transform_crypto_data(raw)
    for name, df in datasets.items():
        print(f"  -> {name}: {len(df)} rows, {len(df.columns)} columns")

    print("Loading transformed data...")
    output_files = load_transformed(datasets)
    for f in output_files:
        print(f"  -> {f}")

    processed = move_raw_to_processed(raw_file)
    print(f"  -> Moved raw file to '{processed}'")

    print("\nETL complete.")


if __name__ == "__main__":
    run_etl()
