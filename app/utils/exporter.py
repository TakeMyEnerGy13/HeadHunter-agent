from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


def export_to_excel(data: list[dict[str, Any]], filename: str) -> None:
    output_path = Path(filename)
    df = pd.DataFrame(data)

    preferred_order = [
        "Название",
        "Компания",
        "Ссылка",
        "Score",
        "Reason",
        "Текст письма",
    ]
    existing = [c for c in preferred_order if c in df.columns]
    remaining = [c for c in df.columns if c not in existing]
    df = df[existing + remaining]

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        sheet_name = "Results"
        df.to_excel(writer, index=False, sheet_name=sheet_name)

        ws = writer.book[sheet_name]
        ws.freeze_panes = "A2"

        for col_cells in ws.columns:
            max_len = 0
            col_letter = col_cells[0].column_letter
            for cell in col_cells:
                value = "" if cell.value is None else str(cell.value)
                max_len = max(max_len, len(value))
                cell.alignment = cell.alignment.copy(wrap_text=True, vertical="top")

            width = min(max(12, max_len + 2), 60)
            ws.column_dimensions[col_letter].width = width

