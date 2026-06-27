from __future__ import annotations

import pandas as pd


def dataframe_records(frame: pd.DataFrame) -> list[dict]:
    normalized = frame.astype("object").where(pd.notna(frame), None)
    records = normalized.to_dict(orient="records")
    for record in records:
        for key, value in list(record.items()):
            if isinstance(value, pd.Timestamp):
                record[key] = value.to_pydatetime()
    return records
