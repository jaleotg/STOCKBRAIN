import html
import io
from datetime import datetime, timedelta
from zipfile import ZipFile, ZIP_DEFLATED

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

from .models import WorkLogDocument


DOCX_XML_DECL = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'


def _w_p(text, bold=False):
    """Return a simple paragraph XML snippet."""
    safe = html.escape(text or "")
    if bold:
        return (
            f"<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>{safe}</w:t></w:r></w:p>"
        )
    return f"<w:p><w:r><w:t>{safe}</w:t></w:r></w:p>"


def _w_tbl(rows):
    """Build a very small table; rows is list of list of cell strings."""
    out = ["<w:tbl>"]
    for row in rows:
        out.append("<w:tr>")
        for cell in row:
            safe = html.escape(cell or "")
            out.append(
                "<w:tc><w:p><w:r><w:t>{}</w:t></w:r></w:p></w:tc>".format(safe)
            )
        out.append("</w:tr>")
    out.append("</w:tbl>")
    return "".join(out)


def render_worklog_docx(worklog):
    """
    Produce a minimal DOCX (as bytes) for the given worklog without external deps.
    """
    author_first = (worklog.author.first_name or "").strip()
    author_last = (worklog.author.last_name or "").strip()
    author_username = worklog.author.username
    name_display = author_first or author_username
    surname_display = author_last or ""

    entries = list(worklog.entries.select_related("vehicle_location", "state", "part", "unit"))

    total_hours = ""
    if worklog.start_time and worklog.end_time:
        # compute difference in hours
        dt_start = datetime.combine(datetime.today().date(), worklog.start_time)
        dt_end = datetime.combine(datetime.today().date(), worklog.end_time)
        if dt_end < dt_start:
            dt_end += timedelta(days=1)
        total_hours = (dt_end - dt_start).total_seconds() / 3600.0
        total_hours = f"{total_hours:.2f}".rstrip("0").rstrip(".")

    start_time = worklog.start_time.strftime("%H:%M") if worklog.start_time else ""
    end_time = worklog.end_time.strftime("%H:%M") if worklog.end_time else ""
    due_str = worklog.due_date.strftime("%d.%m.%Y") if worklog.due_date else ""
    created_str = worklog.created_at.strftime("%d.%m.%Y, %H:%M") if worklog.created_at else ""

    # Header mini-table (4 cols, 3 rows)
    header_rows = [
        ["Name", name_display, "Total Time", total_hours],
        ["Surname", surname_display, "Start Time", start_time],
        ["Date", due_str, "End Time", end_time],
    ]

    # Build rows for the main table (ensure at least 8 rows)
    table_rows = [
        ["Vehicle", "Job description", "Parts Utilize", "Time"],
    ]
    max_rows = max(len(entries), 8)
    for idx in range(max_rows):
        if idx < len(entries):
            en = entries[idx]
            parts_text = en.part.name if en.part else en.part_description
            time_str = (
                f"{float(en.time_hours):.2f}".rstrip("0").rstrip(".")
                if en.time_hours is not None
                else ""
            )
            veh_name = en.vehicle_location.name if en.vehicle_location else ""
            job_text = en.job_description or ""
        else:
            veh_name = ""
            job_text = ""
            parts_text = ""
            time_str = ""
        table_rows.append([
            veh_name,
            job_text,
            parts_text or "",
            time_str,
        ])

    # Notes section (show first note line if present)
    notes_lines = []
    # entry notes with vehicle context
    for en in entries:
        if en.notes:
            veh_name = en.vehicle_location.name if en.vehicle_location else "Vehicle"
            for line in en.notes.splitlines():
                notes_lines.append(f"{veh_name}: {line}")
    # general notes
    notes_content = (worklog.notes or "").strip()
    if notes_content:
        for line in notes_content.splitlines():
            notes_lines.append(f"General: {line}")
    if not notes_lines:
        notes_lines = ["No notes in this worklog"]

    body_parts = [
        _w_p("ADVS DESERT CHAMELEON", bold=True),
        _w_tbl(header_rows),
        _w_p(""),
        _w_tbl(table_rows),
        _w_p(""),
        _w_tbl([["Notes / Problems"]]),
    ]
    body_parts.extend(_w_p(line) for line in notes_lines)

    document_xml = (
        DOCX_XML_DECL
        + '<w:document xmlns:wpc="http://schemas.microsoft.com/office/word/2010/wordprocessingCanvas" '
        + 'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
        + 'xmlns:o="urn:schemas-microsoft-com:office:office" '
        + 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        + 'xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math" '
        + 'xmlns:v="urn:schemas-microsoft-com:vml" '
        + 'xmlns:wp14="http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing" '
        + 'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
        + 'xmlns:w10="urn:schemas-microsoft-com:office:word" '
        + 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        + 'xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml" '
        + 'xmlns:wpg="http://schemas.microsoft.com/office/word/2010/wordprocessingGroup" '
        + 'xmlns:wpi="http://schemas.microsoft.com/office/word/2010/wordprocessingInk" '
        + 'xmlns:wne="http://schemas.microsoft.com/office/word/2006/wordml" '
        + 'xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape" '
        + 'mc:Ignorable="w14 wp14">'
        + "<w:body>"
        + "".join(body_parts)
        + "<w:sectPr><w:pgSz w:w=\"11900\" w:h=\"16840\"/>"
        + "<w:pgMar w:top=\"1440\" w:right=\"1440\" w:bottom=\"1440\" w:left=\"1440\" "
        + "w:header=\"720\" w:footer=\"720\" w:gutter=\"0\"/>"
        + "</w:sectPr></w:body></w:document>"
    )

    styles_xml = (
        DOCX_XML_DECL
        + '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        + '<w:style w:type="paragraph" w:default="1" w:styleId="Normal">'
        + '<w:name w:val="Normal"/>'
        + "</w:style>"
        + "</w:styles>"
    )

    rels_xml = (
        DOCX_XML_DECL
        + '<Relationships xmlns="http://schemas.openxmlformats.org/officeDocument/2006/relationships"/>'
    )

    root_rels = (
        DOCX_XML_DECL
        + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + '<Relationship Id="rId1" '
        + 'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        + 'Target="word/document.xml"/>'
        + '<Relationship Id="rId2" '
        + 'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
        + 'Target="word/styles.xml"/>'
        + "</Relationships>"
    )

    content_types = (
        DOCX_XML_DECL
        + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        + '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        + '<Default Extension="xml" ContentType="application/xml"/>'
        + '<Override PartName="/word/document.xml" '
        + 'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        + '<Override PartName="/word/styles.xml" '
        + 'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
        + "</Types>"
    )

    core_props = (
        DOCX_XML_DECL
        + '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        + 'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        + 'xmlns:dcterms="http://purl.org/dc/terms/" '
        + 'xmlns:dcmitype="http://purl.org/dc/dcmitype/" '
        + 'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        + f"<dc:title>{html.escape(worklog.wl_number)}</dc:title>"
        + f"<dc:creator>{html.escape(worklog.author.username)}</dc:creator>"
        + f"<dcterms:created xsi:type=\"dcterms:W3CDTF\">{datetime.utcnow().isoformat()}Z</dcterms:created>"
        + "</cp:coreProperties>"
    )

    app_props = (
        DOCX_XML_DECL
        + '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" '
        + 'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
        + "<Application>DesertBrain</Application>"
        + "</Properties>"
    )

    buffer = io.BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", root_rels)
        z.writestr("docProps/core.xml", core_props)
        z.writestr("docProps/app.xml", app_props)
        z.writestr("word/document.xml", document_xml)
        z.writestr("word/styles.xml", styles_xml)
        z.writestr("word/_rels/document.xml.rels", rels_xml)

    return buffer.getvalue()


def generate_and_store_docx(worklog):
    """
    Build DOCX bytes and persist to WorkLogDocument (FileField).
    Returns WorkLogDocument instance.
    """
    content = render_worklog_docx(worklog)
    filename = f"worklogs/docx/{worklog.wl_number}.docx".replace(" ", "_")

    doc_obj, _ = WorkLogDocument.objects.get_or_create(worklog=worklog)
    # remove old file if exists
    if doc_obj.docx_file:
        try:
            default_storage.delete(doc_obj.docx_file.name)
        except Exception:
            pass

    doc_obj.docx_file.save(filename, ContentFile(content), save=True)
    return doc_obj
