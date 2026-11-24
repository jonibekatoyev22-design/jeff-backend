"""
File conversion endpoints — the 'heavy lifting' side of universal export/import.

Design principle: the frontend owns presentation (which columns, labels, what a
row means); this router owns binary-format generation and parsing, because that
needs real libraries (openpyxl / reportlab / pdfplumber), not browser JS hacks.

Export: frontend posts {title, columns, rows} (plain JSON it already has in
memory) → backend returns a real .xlsx or .pdf file as a stream.

Import: frontend posts a .xlsx or .pdf file → backend extracts tabular rows and
returns them as JSON so the frontend can show a review/mapping step before
saving anything into tenant data (nothing is written to the database here).
"""
import io
from datetime import datetime, date
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app import models, auth

router = APIRouter(prefix="/api/files", tags=["files"])

ColType = Literal["text", "number", "money", "percent", "date"]


class ExportColumn(BaseModel):
    key: str
    label: str
    type: ColType = "text"


class ExportRequest(BaseModel):
    title: str = "Export"
    columns: list[ExportColumn]
    rows: list[dict[str, Any]]


def _safe_filename(title: str) -> str:
    keep = "".join(c if c.isalnum() or c in " _-" else "" for c in title).strip()
    keep = keep.replace(" ", "_") or "export"
    return keep[:80]


def _fmt_text(value: Any, col_type: ColType) -> str:
    """Single source of truth for how a cell *looks* — used by the PDF path so
    PDF and Excel exports of the same data always agree on formatting."""
    if value is None or value == "":
        return ""
    if col_type == "money":
        try:
            return f"${float(value):,.2f}"
        except (TypeError, ValueError):
            return str(value)
    if col_type == "percent":
        try:
            n = float(value)
            return f"{n:g}%"
        except (TypeError, ValueError):
            return str(value)
    if col_type == "number":
        try:
            n = float(value)
            return f"{n:,.2f}" if not n.is_integer() else f"{int(n):,}"
        except (TypeError, ValueError):
            return str(value)
    if col_type == "date":
        return str(value)
    return str(value)


# ───────────────────────── EXPORT: XLSX ─────────────────────────

@router.post("/export/xlsx")
def export_xlsx(req: ExportRequest, user: models.User = Depends(auth.get_current_user)):
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment
        from openpyxl.utils import get_column_letter
    except ImportError:
        raise HTTPException(status_code=501, detail="Excel export is not available on the server yet.")

    wb = Workbook()
    ws = wb.active
    ws.title = _safe_filename(req.title)[:31] or "Sheet1"

    header_fill = PatternFill(start_color="1F2937", end_color="1F2937", fill_type="solid")
    header_font = Font(color="FFFFFF", bold=True)

    for ci, col in enumerate(req.columns, start=1):
        c = ws.cell(row=1, column=ci, value=col.label)
        c.font = header_font
        c.fill = header_fill
        c.alignment = Alignment(vertical="center")

    money_fmt = '"$"#,##0.00'
    number_fmt = "#,##0.00"
    percent_fmt = '0.##"%"'
    date_fmt = "yyyy-mm-dd"

    for ri, row in enumerate(req.rows, start=2):
        for ci, col in enumerate(req.columns, start=1):
            val = row.get(col.key)
            cell = ws.cell(row=ri, column=ci)
            if val is None or val == "":
                cell.value = ""
                continue
            if col.type in ("number", "money", "percent"):
                try:
                    cell.value = float(val)
                    cell.number_format = {"money": money_fmt, "percent": percent_fmt}.get(col.type, number_fmt)
                except (TypeError, ValueError):
                    cell.value = str(val)
            elif col.type == "date":
                parsed = None
                if isinstance(val, str):
                    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
                        try:
                            parsed = datetime.strptime(val[: len(fmt) + 5], fmt)
                            break
                        except ValueError:
                            continue
                if parsed:
                    cell.value = parsed
                    cell.number_format = date_fmt
                else:
                    cell.value = str(val)
            else:
                cell.value = str(val)

    for ci, col in enumerate(req.columns, start=1):
        width = max(10, min(40, len(col.label) + 4))
        ws.column_dimensions[get_column_letter(ci)].width = width
    ws.freeze_panes = "A2"
    if req.rows:
        ws.auto_filter.ref = f"A1:{get_column_letter(len(req.columns))}{len(req.rows) + 1}"

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    filename = f"{_safe_filename(req.title)}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ───────────────────────── EXPORT: PDF ─────────────────────────

@router.post("/export/pdf")
def export_pdf(req: ExportRequest, user: models.User = Depends(auth.get_current_user)):
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import letter, landscape
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    except ImportError:
        raise HTTPException(status_code=501, detail="PDF export is not available on the server yet.")

    buf = io.BytesIO()
    page_size = landscape(letter) if len(req.columns) > 5 else letter
    doc = SimpleDocTemplate(
        buf, pagesize=page_size,
        leftMargin=0.4 * inch, rightMargin=0.4 * inch, topMargin=0.5 * inch, bottomMargin=0.4 * inch,
    )
    styles = getSampleStyleSheet()
    cell_style = styles["BodyText"]
    cell_style.fontSize = 7.5
    cell_style.leading = 9

    header = [col.label for col in req.columns]
    data_rows = [header]
    for row in req.rows:
        data_rows.append([_fmt_text(row.get(col.key), col.type) for col in req.columns])

    avail_width = page_size[0] - 0.8 * inch
    col_width = avail_width / max(1, len(req.columns))
    table = Table(data_rows, colWidths=[col_width] * len(req.columns), repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F2937")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("FONTSIZE", (0, 1), (-1, -1), 7.5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F3F4F6")]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D1D5DB")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))

    elements = [
        Paragraph(f"<b>{req.title}</b>", styles["Title"]),
        Paragraph(f"Generated {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')} · {len(req.rows)} rows", styles["Normal"]),
        Spacer(1, 12),
        table,
    ]
    doc.build(elements)
    buf.seek(0)
    filename = f"{_safe_filename(req.title)}.pdf"
    return StreamingResponse(
        buf, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ───────────────────────── IMPORT: XLSX ─────────────────────────

@router.post("/import/xlsx")
async def import_xlsx(file: UploadFile = File(...), user: models.User = Depends(auth.get_current_user)):
    try:
        from openpyxl import load_workbook
    except ImportError:
        raise HTTPException(status_code=501, detail="Excel import is not available on the server yet.")

    content = await file.read()
    if len(content) > 15 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (max 15MB).")
    try:
        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception:
        raise HTTPException(status_code=400, detail="Could not read this file — is it a valid .xlsx workbook?")

    ws = wb.worksheets[0]
    all_rows = list(ws.iter_rows(values_only=True))

    # Real-world exports (payroll summaries, carrier reports, etc.) almost never
    # put the header on row 1 — there's usually a title/date preamble first.
    # Scan the first few rows and treat the first "dense" row (several filled
    # cells) as the header, instead of blindly trusting row 1.
    def _nonempty(row):
        return sum(1 for v in (row or []) if v is not None and str(v).strip() != "")

    header_idx = 0
    scan_window = min(20, len(all_rows))
    for i in range(scan_window):
        if _nonempty(all_rows[i]) >= 3:
            header_idx = i
            break

    if not all_rows:
        return {"headers": [], "rows": [], "sheet": ws.title, "sheets": wb.sheetnames}

    header_row = all_rows[header_idx]
    headers = [str(h).strip() if h is not None else f"col{i+1}" for i, h in enumerate(header_row)]
    out_rows = []
    for raw in all_rows[header_idx + 1:]:
        if raw is None or all(v is None or str(v).strip() == "" for v in raw):
            continue
        row = {}
        for i, h in enumerate(headers):
            v = raw[i] if i < len(raw) else None
            if isinstance(v, (datetime, date)):
                v = v.isoformat()
            row[h] = v
        out_rows.append(row)

    return {
        "headers": headers,
        "rows": out_rows,
        "sheet": ws.title,
        "sheets": wb.sheetnames,
        "header_row_index": header_idx,
    }


# ───────────────────────── IMPORT: PDF (multi-strategy, multi-page) ─────────────────────────

def _norm_header(cells: list) -> list[str]:
    return [str(h).strip().lower() if h else "" for h in cells]


def _clean_row(raw: list, headers: list[str]) -> dict | None:
    if not raw or all(v is None or str(v).strip() == "" for v in raw):
        return None
    return {
        headers[i] if i < len(headers) else f"col{i+1}": (v.strip() if isinstance(v, str) else v)
        for i, v in enumerate(raw)
    }


def _extract_tables_for_page(page, strategies: list[dict]) -> list[list[list]]:
    """Try several pdfplumber table strategies on one page, in order, and
    return the first one that finds real tables. Carrier/broker statements
    are inconsistent: some draw ruled grid lines (the default "lines"
    strategy works), many others are plain whitespace-aligned text with no
    visible borders at all (only the "text" strategy finds rows there)."""
    for settings in strategies:
        try:
            tables = page.extract_tables(table_settings=settings) if settings else page.extract_tables()
        except Exception:
            continue
        tables = [t for t in (tables or []) if t and len(t) > 1]
        if tables:
            return tables
    return []


@router.post("/import/pdf")
async def import_pdf(file: UploadFile = File(...), user: models.User = Depends(auth.get_current_user)):
    try:
        import pdfplumber
    except ImportError:
        raise HTTPException(status_code=501, detail="PDF import is not available on the server yet.")

    content = await file.read()
    if len(content) > 15 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (max 15MB).")

    # Three fallback strategies, tried in order per page: default (ruled
    # lines), then pure text-alignment (no lines at all — the common case
    # for statements exported as plain reports), then a looser text variant
    # with smaller tolerances for tightly-spaced columns.
    strategies = [
        None,
        {"vertical_strategy": "text", "horizontal_strategy": "text"},
        {"vertical_strategy": "text", "horizontal_strategy": "text", "text_x_tolerance": 2, "text_y_tolerance": 2},
    ]

    pages_tables: list[list[list[list]]] = []  # per-page list of tables
    text_preview_parts: list[str] = []
    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for page in pdf.pages:
                pages_tables.append(_extract_tables_for_page(page, strategies))
                text_preview_parts.append(page.extract_text() or "")
    except Exception:
        raise HTTPException(status_code=400, detail="Could not read this file — is it a valid PDF?")

    all_tables = [t for page_tables in pages_tables for t in page_tables]
    if not all_tables:
        return {
            "headers": [], "rows": [],
            "rawTextPreview": "\n".join(text_preview_parts)[:4000],
            "note": "No structured table detected in this PDF, even after trying both ruled-line and text-alignment extraction. Review the raw text preview and enter data manually, or try a cleaner export from the carrier portal.",
        }

    # Group tables by matching header row so a statement that spans several
    # pages (the normal case for a weekly report) gets all its rows merged
    # into one table, instead of only the single biggest page winning and
    # the rest being silently dropped.
    groups: list[dict] = []  # [{headers_norm, headers, rows: [...]}]
    for tbl in all_tables:
        raw_headers = tbl[0]
        headers_norm = _norm_header(raw_headers)
        group = next((g for g in groups if g["headers_norm"] == headers_norm), None)
        if group is None:
            headers = [str(h).strip() if h else f"col{i+1}" for i, h in enumerate(raw_headers)]
            group = {"headers_norm": headers_norm, "headers": headers, "rows_raw": []}
            groups.append(group)
        for raw in tbl[1:]:
            # Skip a repeated header row (common when a table restarts on
            # each new page with the same column titles).
            if _norm_header(raw) == headers_norm:
                continue
            group["rows_raw"].append(raw)

    best_group = max(groups, key=lambda g: len(g["rows_raw"]))
    out_rows = [r for r in (_clean_row(raw, best_group["headers"]) for raw in best_group["rows_raw"]) if r]

    extra_note = ""
    if len(groups) > 1:
        extra_note = f" {len(groups)-1} other, differently-shaped table(s) on this PDF were ignored — if this looks wrong, the statement may mix formats mid-document."

    return {
        "headers": best_group["headers"], "rows": out_rows,
        "rawTextPreview": "\n".join(text_preview_parts)[:4000],
        "note": f"Extracted {len(out_rows)} row(s) across {sum(1 for pt in pages_tables if pt)} page(s) with matching columns.{extra_note} Please review before saving.",
    }
