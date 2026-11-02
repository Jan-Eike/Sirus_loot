"""Google-Sheets Setup/Auth/Connection für den PoE Loot Tracker."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

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


def get_service() -> Any:
    """Gibt einen authentifizierten Google-Sheets-Service zurück."""
    return build(
        "sheets",
        "v4",
        credentials=_authenticate(),
        cache_discovery=False,
    )


def _load_config() -> dict[str, Any] | None:
    if not CONFIG_FILE.exists():
        return None

    return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))


def _save_config(spreadsheet_id: str) -> dict[str, Any]:
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


def connect_spreadsheet(spreadsheet_id_or_url: str) -> dict[str, Any]:
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
            "In der Tabelle fehlen diese Tabellenblätter: "
            + ", ".join(sorted(missing_sheets))
        )

    return _save_config(spreadsheet_id)


def _format_new_spreadsheet(service: Any, spreadsheet: dict[str, Any]) -> None:
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


def create_spreadsheet(service: Any = None) -> dict[str, Any]:
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


def get_or_create_spreadsheet(service: Any = None) -> dict[str, Any]:
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
                f"Lösche {CONFIG_FILE.name}, um eine neue anzulegen."
            ) from error

    return create_spreadsheet(service)
