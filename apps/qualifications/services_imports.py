"""
apps/qualifications/services_imports.py
CSV import helpers for the qualifications app.

`parse_enrollment_csv` returns (rows, errors):
    rows   = list[dict] ready for services.bulk_upsert_enrollments
    errors = list[dict] of {row, field, message} for the response

This is a minimal scaffold — extend with strict header validation,
date parsing, and learner/qualification existence checks.
"""
from __future__ import annotations

import csv
import io
from typing import IO

REQUIRED_FIELDS = ("learner_id", "qualification_id", "cohort", "enrolled_at")
OPTIONAL_FIELDS = ("employer", "status", "expected_end_date", "notes")


def parse_enrollment_csv(file: IO[bytes]) -> tuple[list[dict], list[dict]]:
    rows: list[dict] = []
    errors: list[dict] = []

    try:
        text = io.TextIOWrapper(file, encoding="utf-8-sig", newline="")
        reader = csv.DictReader(text)
    except Exception as e:
        return [], [{"row": 0, "field": "file", "message": f"Could not read CSV: {e}"}]

    missing_headers = [f for f in REQUIRED_FIELDS if f not in (reader.fieldnames or [])]
    if missing_headers:
        return [], [{"row": 0, "field": ",".join(missing_headers), "message": "Missing required column(s)."}]

    for i, raw in enumerate(reader, start=2):  # +1 header, +1 humans count from 1
        row: dict = {}
        ok = True
        for field in REQUIRED_FIELDS:
            value = (raw.get(field) or "").strip()
            if not value:
                errors.append({"row": i, "field": field, "message": "Required value is empty."})
                ok = False
            else:
                row[field] = value
        for field in OPTIONAL_FIELDS:
            value = (raw.get(field) or "").strip()
            if value:
                row[field] = value
        if ok:
            rows.append(row)

    return rows, errors
