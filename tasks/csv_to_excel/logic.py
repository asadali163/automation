"""Pure logic for the CSV to Excel task — no Streamlit here."""
from io import BytesIO

import pandas as pd


def dataframe_to_excel_bytes(df: pd.DataFrame, sheet_name: str = "Sheet1") -> bytes:
    """Serialize a DataFrame to .xlsx bytes, ready for a download button."""
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name)
    return buffer.getvalue()
