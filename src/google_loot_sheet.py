"""Google-Sheets-Anbindung fuer den PoE Loot Tracker.

Installation:
    python -m pip install --upgrade \
        google-api-python-client google-auth-httplib2 google-auth-oauthlib

Lege die aus Google Cloud heruntergeladene ``credentials.json`` neben dieses
Skript. Beim ersten Aufruf wird die Anmeldung im Browser gestartet. Danach
werden ``token.json`` und ``sheet_config.json`` ebenfalls neben dem Skript
gespeichert.

Beispiele:
    python google_loot_sheet.py setup
    python google_loot_sheet.py connect \
        "https://docs.google.com/spreadsheets/d/TABELLEN_ID/edit"
    python google_loot_sheet.py open
    python google_loot_sheet.py add-run --player "Jan" --boss "Maven" \
        --loot "Dying Sun" --loot "Orb of Conflict"
    python google_loot_sheet.py list-runs
"""

from __future__ import annotations

import argparse
import json
import os
import re
import uuid
import webbrowser
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

APP_DIR = Path(__file__).resolve().parent
CREDENTIALS_FILE = Path(
    os.environ.get(
        "GOOGLE_CREDENTIALS_FILE", APP_DIR.parent / "config" / "credentials.json"
    )
)
TOKEN_FILE = Path(
    os.environ.get("GOOGLE_TOKEN_FILE", APP_DIR.parent / "config" / "token.json")
)
CONFIG_FILE = Path(
    os.environ.get(
        "GOOGLE_SHEET_CONFIG_FILE", APP_DIR.parent / "config" / "sheet_config.json"
    )
)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SPREADSHEET_TITLE = "PoE Loot Tracker"

RUN_HEADERS = ["run_id", "timestamp_utc", "player", "boss", "loot", "time"]


def _authenticate() -> Credentials:
    credentials = None

    if TOKEN_FILE.exists():
        credentials = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if credentials and set(credentials.scopes or []) != set(SCOPES):
        credentials = None

    if credentials and credentials.expired and credentials.refresh_token:
        try:
            credentials.refresh(Request())
        except RefreshError:
            credentials = None

    if not credentials or not credentials.valid:
        if not CREDENTIALS_FILE.exists():
            raise FileNotFoundError(
                f"{CREDENTIALS_FILE.name} fehlt. Lege die OAuth-Datei neben "
                "das Skript oder setze GOOGLE_CREDENTIALS_FILE."
            )

        flow = InstalledAppFlow.from_client_secrets_file(
            CREDENTIALS_FILE,
            SCOPES,
        )
        credentials = flow.run_local_server(port=0)

    TOKEN_FILE.write_text(credentials.to_json(), encoding="utf-8")
    return credentials


def get_service():
    """Gibt einen authentifizierten Google-Sheets-Service zurueck."""
    return build(
        "sheets",
        "v4",
        credentials=_authenticate(),
        cache_discovery=False,
    )


def _load_config() -> dict | None:
    if not CONFIG_FILE.exists():
        return None

    return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))


def _save_config(spreadsheet_id: str) -> dict:
    config = {
        "spreadsheet_id": spreadsheet_id,
        "url": f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit",
    }
    CONFIG_FILE.write_text(
        json.dumps(config, indent=2),
        encoding="utf-8",
    )
    return config


def _extract_spreadsheet_id(value: str) -> str:
    value = value.strip()

    if "/spreadsheets/d/" in value:
        return value.split("/spreadsheets/d/", 1)[1].split("/", 1)[0]

    return value


def connect_spreadsheet(spreadsheet_id_or_url: str) -> dict:
    """Verbindet diesen Rechner mit einem bereits vorhandenen zentralen Sheet."""
    spreadsheet_id = _extract_spreadsheet_id(spreadsheet_id_or_url)
    service = get_service()

    spreadsheet = (
        service.spreadsheets()
        .get(
            spreadsheetId=spreadsheet_id,
            fields="spreadsheetId,sheets.properties.title",
        )
        .execute()
    )

    sheet_titles = {
        sheet["properties"]["title"] for sheet in spreadsheet.get("sheets", [])
    }
    missing_sheets = {"Runs"} - sheet_titles

    if missing_sheets:
        raise RuntimeError(
            "In der Tabelle fehlen diese Tabellenblaetter: "
            + ", ".join(sorted(missing_sheets))
        )

    return _save_config(spreadsheet_id)


def _format_new_spreadsheet(service, spreadsheet: dict) -> None:
    sheet_ids = {
        sheet["properties"]["title"]: sheet["properties"]["sheetId"]
        for sheet in spreadsheet["sheets"]
    }

    requests = []
    for title, column_count in (("Runs", len(RUN_HEADERS)),):
        sheet_id = sheet_ids[title]

        requests.extend(
            [
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": 0,
                            "endRowIndex": 1,
                            "startColumnIndex": 0,
                            "endColumnIndex": column_count,
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "backgroundColor": {
                                    "red": 0.12,
                                    "green": 0.27,
                                    "blue": 0.45,
                                },
                                "textFormat": {
                                    "foregroundColor": {
                                        "red": 1.0,
                                        "green": 1.0,
                                        "blue": 1.0,
                                    },
                                    "bold": True,
                                },
                                "horizontalAlignment": "CENTER",
                            }
                        },
                        "fields": "userEnteredFormat",
                    }
                },
                {
                    "updateSheetProperties": {
                        "properties": {
                            "sheetId": sheet_id,
                            "gridProperties": {"frozenRowCount": 1},
                        },
                        "fields": "gridProperties.frozenRowCount",
                    }
                },
                {
                    "autoResizeDimensions": {
                        "dimensions": {
                            "sheetId": sheet_id,
                            "dimension": "COLUMNS",
                            "startIndex": 0,
                            "endIndex": column_count,
                        }
                    }
                },
                {
                    "setBasicFilter": {
                        "filter": {
                            "range": {
                                "sheetId": sheet_id,
                                "startRowIndex": 0,
                                "startColumnIndex": 0,
                                "endColumnIndex": column_count,
                            }
                        }
                    }
                },
            ]
        )

    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet["spreadsheetId"],
        body={"requests": requests},
    ).execute()


def create_spreadsheet(service=None) -> dict:
    """Erstellt das zentrale Sheet im Drive des angemeldeten Kontos."""
    service = service or get_service()

    spreadsheet = (
        service.spreadsheets()
        .create(
            body={
                "properties": {"title": SPREADSHEET_TITLE},
                "sheets": [
                    {"properties": {"title": "Runs"}},
                ],
            },
            fields="spreadsheetId,spreadsheetUrl,sheets.properties",
        )
        .execute()
    )

    spreadsheet_id = spreadsheet["spreadsheetId"]

    service.spreadsheets().values().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={
            "valueInputOption": "RAW",
            "data": [
                {"range": "Runs!A1:F1", "values": [RUN_HEADERS]},
            ],
        },
    ).execute()

    _format_new_spreadsheet(service, spreadsheet)
    return _save_config(spreadsheet_id)


def get_or_create_spreadsheet(service=None) -> dict:
    """Verwendet das vorhandene Sheet oder erstellt es beim ersten Start."""
    service = service or get_service()
    config = _load_config()

    if config:
        try:
            service.spreadsheets().get(
                spreadsheetId=config["spreadsheet_id"],
                fields="spreadsheetId",
            ).execute()
            return config
        except HttpError as error:
            if error.resp.status not in (403, 404):
                raise
            raise RuntimeError(
                "Die gespeicherte Tabelle ist nicht mehr erreichbar. "
                f"Loesche {CONFIG_FILE.name}, um eine neue anzulegen."
            ) from error

    return create_spreadsheet(service)


def _runs_sheet_id(service, spreadsheet_id) -> int | None:
    """Gibt die sheetId des Tabellenblatts 'Runs' zurueck."""
    spreadsheet = (
        service.spreadsheets()
        .get(spreadsheetId=spreadsheet_id, fields="sheets.properties")
        .execute()
    )
    for sheet in spreadsheet.get("sheets", []):
        if sheet["properties"]["title"] == "Runs":
            return sheet["properties"]["sheetId"]
    return None


def _row_background_color(service, spreadsheet_id, row_number: int) -> dict | None:
    """Gibt die Hintergrundfarbe der Zeile ``row_number`` (1-basiert) zurueck."""
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


def _baseline_background_color(service, spreadsheet_id, from_row: int) -> dict | None:
    """Sucht rueckwaerts die Farbe der letzten nicht-roten Zeile.

    Angehaengte Zeilen uebernehmen die Farbe der vorherigen Zeile. Um zu
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


def append_run(player: str, boss: str, loot: str, time: str, error: bool = False):
    """Fuegt einen Run und seine Drops an und gibt die run_id zurueck."""
    service = get_service()
    config = get_or_create_spreadsheet(service)
    spreadsheet_id = config["spreadsheet_id"]
    timestamp = datetime.now(UTC).isoformat(timespec="seconds")

    # Die Zeilennummer (und damit die run_id) vergibt das Sheet selbst
    # atomisch beim Anhaengen. Zwei gleichzeitige Aufrufe erhalten so immer
    # verschiedene Zeilen. Die Formel =ROW()-1 wird nach dem Anhaengen
    # automatisch berechnet und zeigt auf die gerade angelegte Zeile.
    result = (
        service.spreadsheets()
        .values()
        .append(
            spreadsheetId=spreadsheet_id,
            range="Runs!A:F",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": [["=ROW()-1", timestamp, player, boss, loot, time]]},
        )
        .execute()
    )

    updated_range = result.get("updates", {}).get("updatedRange") or result.get(
        "updatedRange", ""
    )
    match = re.search(r"!A(\d+)", updated_range)
    if not match:
        raise RuntimeError(
            f"append-Antwort enthaelt keine Zeilennummer: {updated_range!r} (raw: {result!r})"
        )
    row_number = int(match.group(1))  # 1-basiert; Zeile 1 ist die Kopfzeile
    run_id = str(row_number - 1)

    sheet_id = _runs_sheet_id(service, spreadsheet_id)
    if sheet_id is None:
        return run_id

    # Hintergrundfarbe der neuen Zeile setzen. Da angehaengte Zeilen die Farbe
    # der vorherigen uebernehmen, setzen wir sie explizit: rot bei Fehler,
    # sonst die Farbe der letzten nicht-roten Zeile (oder Weiss).
    if error:
        red, green, blue = (0.9, 0.3, 0.3)
    else:
        prev_color = _baseline_background_color(service, spreadsheet_id, row_number - 1)
        if prev_color:
            red, green, blue = (
                prev_color.get("red", 0.12),
                prev_color.get("green", 0.27),
                prev_color.get("blue", 0.45),
            )
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
    """Liest alle befuellten Zeilen eines Tabellenblatts."""
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
    """Oeffnet das Sheet im Standardbrowser und gibt die URL zurueck."""
    config = get_or_create_spreadsheet()
    webbrowser.open(config["url"])
    return config["url"]


def _print_table(rows: list[list[str]]) -> None:
    for row in rows:
        print("\t".join(str(value) for value in row))


def append_row(tab_name: str, values: list) -> None:
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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Zugriff auf das zentrale Google Sheet des PoE Loot Trackers."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("setup", help="Anmelden und Tabelle anlegen")
    subparsers.add_parser("open", help="Tabelle im Browser oeffnen")
    subparsers.add_parser("list-runs", help="Gespeicherte Runs anzeigen")
    subparsers.add_parser("list-drops", help="Gespeicherte Drops anzeigen")

    connect_parser = subparsers.add_parser(
        "connect",
        help="Mit einer bereits vorhandenen zentralen Tabelle verbinden",
    )
    connect_parser.add_argument(
        "spreadsheet",
        help="Google-Sheets-URL oder Tabellen-ID",
    )

    add_run_parser = subparsers.add_parser(
        "add-run",
        help="Run und erkannte Drops anhaengen",
    )
    add_run_parser.add_argument("--player", required=True)
    add_run_parser.add_argument("--boss", required=True)
    add_run_parser.add_argument(
        "--loot",
        action="append",
        default=[],
        help="Erkannter Itemtext; fuer mehrere Items wiederholen",
    )
    add_run_parser.add_argument("--notes", default="")

    append_parser = subparsers.add_parser(
        "append-row",
        help="Beliebige Zeile als JSON-Array anhaengen",
    )
    append_parser.add_argument("--tab", required=True, choices=["Runs", "Drops"])
    append_parser.add_argument(
        "--json", required=True, help="JSON-Array der Zeilenwerte"
    )

    arguments = parser.parse_args()

    if arguments.command == "setup":
        config = get_or_create_spreadsheet()
        print(config["url"])
    elif arguments.command == "connect":
        config = connect_spreadsheet(arguments.spreadsheet)
        print(config["url"])
    elif arguments.command == "open":
        print(open_spreadsheet())
    elif arguments.command == "list-runs":
        _print_table(read_rows("Runs"))
    elif arguments.command == "list-drops":
        _print_table(read_rows("Drops"))
    elif arguments.command == "append-row":
        import json as _json

        append_row(arguments.tab, _json.loads(arguments.json))
        print("ok")


if __name__ == "__main__":
    main()
