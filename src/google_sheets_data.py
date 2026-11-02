"""Google-Sheets Datenoperationen für den PoE Loot Tracker."""
from __future__ import annotations

import re
import time
import uuid
import webbrowser
from datetime import UTC, datetime
from typing import Any

from google_sheets_setup import (
    RUN_HEADERS,
    get_or_create_spreadsheet,
    get_service,
)


def _runs_sheet_id(service: Any, spreadsheet_id: str) -> int | None:
    """Gibt die sheetId des Tabellenblatts 'Runs' zurück."""
    spreadsheet = (
        service.spreadsheets()
        .get(spreadsheetId=spreadsheet_id, fields="sheets.properties")
        .execute()
    )
    for sheet in spreadsheet.get("sheets", []):
        if sheet["properties"]["title"] == "Runs":
            return sheet["properties"]["sheetId"]
    return None


def _row_background_color(
    service: Any, spreadsheet_id: str, row_number: int
) -> dict[str, Any] | None:
    """Gibt die Hintergrundfarbe der Zeile ``row_number`` (1-basiert) zurück."""
    if row_number < 1:
        return None
    resp = (
        service.spreadsheets()
        .get(
            spreadsheetId=spreadsheet_id,
            ranges=[f"Runs!A{row_number}:F{row_number}"],
            fields="sheets/data/rowData/values/userEnteredFormat/backgroundColor",
            includeGridData=True,
        )
        .execute()
    )
    for sheet in resp.get("sheets", []):
        for data in sheet.get("data", []):
            for row_data in data.get("rowData", []):
                for cell in row_data.get("values", []):
                    color = cell.get("userEnteredFormat", {}).get("backgroundColor")
                    if color:
                        return color
    return None


def _baseline_background_color(
    service: Any, spreadsheet_id: str, from_row: int
) -> dict[str, Any] | None:
    """Sucht rückwärts die Farbe der letzten nicht-roten Zeile.

    Angehängte Zeilen übernehmen die Farbe der vorherigen Zeile. Um zu
    verhindern, dass ein roter Fehler-Row in nachfolgende normale Zeilen
    "hinunterfliegt", suchen wir die letzte Zeile, die nicht rot ist, und
    verwenden deren Farbe als Basis.
    """
    for row in range(from_row, 1, -1):
        color = _row_background_color(service, spreadsheet_id, row)
        if not color:
            continue
        is_red = (
            color.get("red", 0) > 0.8
            and color.get("green", 0) < 0.4
            and color.get("blue", 0) < 0.4
        )
        if not is_red:
            return color
    return None


def _find_row_by_run_id(
    service: Any,
    spreadsheet_id: str,
    run_id: str,
    attempts: int = 25,
    delay: float = 0.2,
) -> int | None:
    """Find the 1-based row number containing run_id in column A."""
    for _ in range(attempts):
        rows = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=spreadsheet_id, range="Runs!A:A")
            .execute()
            .get("values", [])
        )
        for idx, row in enumerate(rows, start=1):
            if row and row[0] == run_id:
                return idx
        time.sleep(delay)
    return None


def append_run(
    player: str, boss: str, loot: str, time_to_complete: str, error: bool = False
) -> str:
    """Fügt einen Run und seine Drops an und gibt die run_id zurück."""
    service = get_service()
    config = get_or_create_spreadsheet(service)
    spreadsheet_id = config["spreadsheet_id"]
    timestamp = datetime.now(UTC).isoformat(timespec="seconds")

    run_id = str(uuid.uuid4())
    result = (
        service.spreadsheets()
        .values()
        .append(
            spreadsheetId=spreadsheet_id,
            range="Runs!A:F",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={
                "values": [[run_id, timestamp, player, boss, loot, time_to_complete]]
            },
        )
        .execute()
    )

    # Zeile anhand der eindeutigen run_id nachschlagen (robust gegen
    # überlappende updatedRange bei gleichzeitigen Aufrufen).
    row_number = _find_row_by_run_id(service, spreadsheet_id, run_id)

    updated_range = result.get("updates", {}).get("updatedRange") or result.get(
        "updatedRange", ""
    )
    if row_number is None:
        match = re.search(r"!A(\d+)", updated_range)
        if match:
            row_number = int(match.group(1))

    sheet_id = _runs_sheet_id(service, spreadsheet_id)
    if sheet_id is None or row_number is None:
        return run_id

    # Hintergrundfarbe der neuen Zeile setzen.
    if error:
        red, green, blue = (0.9, 0.3, 0.3)
    else:
        red, green, blue = (0.12, 0.27, 0.45)

    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={
            "requests": [
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": row_number - 1,
                            "endRowIndex": row_number,
                            "startColumnIndex": 0,
                            "endColumnIndex": len(RUN_HEADERS),
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "backgroundColor": {
                                    "red": red,
                                    "green": green,
                                    "blue": blue,
                                }
                            }
                        },
                        "fields": "userEnteredFormat.backgroundColor",
                    }
                }
            ]
        },
    ).execute()
    return run_id


def read_rows(tab_name: str) -> list[list[str]]:
    """Liest alle befüllten Zeilen eines Tabellenblatts."""
    if tab_name not in {"Runs", "Drops"}:
        raise ValueError("tab_name muss 'Runs' oder 'Drops' sein.")

    service = get_service()
    config = get_or_create_spreadsheet(service)

    result = (
        service.spreadsheets()
        .values()
        .get(
            spreadsheetId=config["spreadsheet_id"],
            range=f"{tab_name}!A:Z",
        )
        .execute()
    )

    return result.get("values", [])


def open_spreadsheet() -> str:
    """Öffnet das Sheet im Standardbrowser und gibt die URL zurück."""
    config = get_or_create_spreadsheet()
    webbrowser.open(config["url"])
    return config["url"]


def append_row(tab_name: str, values: list[Any]) -> None:
    if tab_name not in {"Runs", "Drops"}:
        raise ValueError("tab_name muss 'Runs' oder 'Drops' sein.")
    service = get_service()
    config = get_or_create_spreadsheet(service)
    service.spreadsheets().values().append(
        spreadsheetId=config["spreadsheet_id"],
        range=f"{tab_name}!A:Z",
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": [values]},
    ).execute()
