import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd

import google_loot_sheet as g  # ty: ignore[unresolved-import]


def analyse_loot_data(loot_table: pd.DataFrame) -> pd.DataFrame:
    item_counts: pd.Series = loot_table["loot"].str.split(", ").explode().value_counts()
    run_number = loot_table.shape[0]
    drop_chances = item_counts / run_number
    return drop_chances.reset_index(name="count")


def main():
    # 1. Load current table from Google Sheets
    rows = g.read_rows("Runs")
    df = pd.DataFrame(rows[1:], columns=rows[0])

    # 2. Analyse (placeholder)
    result_df = analyse_loot_data(df)

    # 3. Add a new worksheet tab in the same spreadsheet
    service = g.get_service()
    config = g.get_or_create_spreadsheet(service)
    spreadsheet_id = config["spreadsheet_id"]

    sheet_title = "Analysis"
    spreadsheet = (
        service.spreadsheets()
        .get(spreadsheetId=spreadsheet_id, fields="sheets.properties.title")
        .execute()
    )
    existing = {s["properties"]["title"] for s in spreadsheet.get("sheets", [])}
    if sheet_title not in existing:
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{"addSheet": {"properties": {"title": sheet_title}}}]},
        ).execute()

    values = [result_df.columns.tolist()] + result_df.astype(str).values.tolist()
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"{sheet_title}!A1",
        valueInputOption="RAW",
        body={"values": values},
    ).execute()
    print(config["url"])


if __name__ == "__main__":
    main()
