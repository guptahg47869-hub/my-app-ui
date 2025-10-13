# pages/trees.py
from nicegui import ui, Client  # type: ignore
import httpx, os, asyncio  # type: ignore
from datetime import date, datetime
from typing import Any, Dict, List
import base64, json

API_URL = os.getenv('API_URL', 'http://localhost:8000')
print('UI using API_URL =', API_URL)

# ---------- helpers ----------
def to_ui_date(iso: str) -> str:
    try:
        return datetime.strptime(iso, '%Y-%m-%d').strftime('%m-%d-%y')
    except Exception:
        return iso

def parse_iso_date(s: str):
    try:
        return datetime.strptime(s, '%Y-%m-%d').date()
    except Exception:
        return None

def explain_http_error(e: httpx.HTTPStatusError) -> str:
    try:
        data = e.response.json()
        if isinstance(data, dict) and 'detail' in data:
            return str(data['detail'])
        return str(data)
    except Exception:
        return e.response.text or str(e)

async def fetch_metals() -> List[Dict[str, Any]]:
    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.get(f'{API_URL}/metals')
        r.raise_for_status()
        return r.json()

async def fetch_transit(date_from: str | None = None, date_to: str | None = None,
                        tree_no: str | None = None, metal: str | None = None):
    params: Dict[str, Any] = {}
    if date_from: params['date_from'] = date_from
    if date_to:   params['date_to']   = date_to
    if tree_no:   params['tree_no']   = tree_no
    if metal and metal != 'All': params['metal'] = metal
    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.get(f'{API_URL}/queue/transit', params=params or None)
        r.raise_for_status()
        return r.json()

async def fetch_next_tree_no() -> str:
    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.get(f'{API_URL}/trees/next_number')
        r.raise_for_status()
        return r.json()['tree_no']

# client-side preview for est. metal
def est_metal_weight(tree_weight: float, metal_name: str) -> float:
    name = (metal_name or '').upper()
    factor = 1.0
    if '10' in name: factor = 11
    elif '14' in name: factor = 13.25
    elif '18' in name: factor = 16.5
    elif 'PLATINUM' in name: factor = 21
    elif 'SILVER' in name: factor = 11
    return round((tree_weight or 0.0) * factor, 3)

# # ---------- PDF: 1" x 2" tree label ----------
# def _build_tree_label_pdf_bytes(*, tree_no: str, metal_name: str, when_iso: str, est_metal: float) -> bytes:
#     """
#     Create a true 2in x 1in PDF label (landscape):
#       - Left column: Tree No (bold), Metal, Date (MM-DD-YYYY), Est. Metal
#       - Right column: auto-scaled Code128 barcode of tree_no
#     Everything is sized to avoid overlap on small media.
#     """
#     try:
#         from reportlab.pdfgen import canvas
#         from reportlab.lib.units import inch, mm
#         from reportlab.graphics.barcode import code128
#         from reportlab.pdfbase import pdfmetrics
#         from io import BytesIO
#     except ImportError:
#         raise RuntimeError("Missing dependency: reportlab. Install with: pip install reportlab")

#     # Format date
#     try:
#         from datetime import datetime
#         date_disp = datetime.strptime(when_iso, "%Y-%m-%d").strftime("%m-%d-%Y")
#     except Exception:
#         date_disp = when_iso

#     # Page: 2" wide x 1" tall
#     W, H = (2 * inch, 1 * inch)
#     M = 2.5 * mm  # margin

#     buf = BytesIO()
#     c = canvas.Canvas(buf, pagesize=(W, H))

#     # --- Layout: 2 columns ----------------------------------------------------
#     left_x  = M
#     left_w  = W * 0.60 - M  # ~60% for text
#     right_x = W * 0.60
#     right_w = W - right_x - M
#     top_y   = H - M

#     # Utility: draw a line of text that auto-shrinks to fit the left column
#     def fit_text(font_name: str, base_size: float, text: str, x: float, y: float, max_w: float, min_size: float = 5.5):
#         size = base_size
#         while size >= min_size:
#             width = pdfmetrics.stringWidth(text, font_name, size)
#             if width <= max_w:
#                 c.setFont(font_name, size)
#                 c.drawString(x, y, text)
#                 return size
#             size -= 0.5
#         # If still too long, truncate with ellipsis
#         c.setFont(font_name, min_size)
#         ell = '…'
#         while pdfmetrics.stringWidth(text + ell, font_name, min_size) > max_w and len(text) > 1:
#             text = text[:-1]
#         c.drawString(x, y, text + ell)

#     # --- Left column text (stacked, with tight leading) -----------------------
#     y = top_y
#     # Tree No (bold)
#     used = fit_text("Helvetica-Bold", 10.0, f"{tree_no}", left_x, y - 9, left_w)
#     y -= (used + 3)

#     # Metal
#     used = fit_text("Helvetica", 7.5, f"Metal: {metal_name}", left_x, y - 7, left_w)
#     y -= (used + 2)

#     # Date
#     used = fit_text("Helvetica", 7.5, f"Date:  {date_disp}", left_x, y - 7, left_w)
#     y -= (used + 2)

#     # Est. Metal
#     used = fit_text("Helvetica-Bold", 8.0, f"Est. Metal: {est_metal:.1f}", left_x, y - 8, left_w)
#     y -= (used + 2)

#     # --- Right column barcode -------------------------------------------------
#     # Create with a conservative bar width; we'll scale to fit both width and height
#     b = code128.Code128(tree_no, barHeight=10 * mm, barWidth=0.38)  # initial values before scaling

#     # Available height for barcode is full height minus margins top/bottom
#     avail_h = H - 2 * M
#     avail_w = right_w

#     # Compute scale factor to fit in right column (preserve aspect ratio)
#     scale_x = avail_w / float(b.width)
#     scale_y = avail_h / float(b.height)
#     scale   = min(scale_x, scale_y, 1.0)  # never scale up beyond 1 (keeps bars crisp)

#     # Center the barcode inside the right column
#     bx = right_x + (avail_w - b.width * scale) / 2.0
#     by = M + (avail_h - b.height * scale) / 2.0

#     c.saveState()
#     c.translate(bx, by)
#     c.scale(scale, scale)
#     b.drawOn(c, 0, 0)
#     c.restoreState()

#     c.showPage()
#     c.save()
#     pdf = buf.getvalue()
#     buf.close()
#     return pdf

# ---------- PDF: 12" x 0.5" long strip tree label ----------
def _build_tree_label_pdf_bytes(
    *,
    tree_no: str,
    metal_name: str,
    when_iso: str,
    est_metal: float,
    bag_nos: list[str] | None = None,    # <-- NEW
) -> bytes:
    """
    Create a horizontal strip PDF (your current 6in x 0.5in):
      LEFT: 2 lines of text
            Line 1: "  {MM-DD}  | {TREE_NO}  |  Metal: {metal}  |  Est: {grams}g"
            Line 2: "Bags: {bag1, bag2, ...}" (shrinks or ellipsizes to fit)
      RIGHT: Code128 barcode (tree_no), auto-scaled
    """
    try:
        from reportlab.pdfgen import canvas
        from reportlab.lib.units import inch, mm
        from reportlab.graphics.barcode import code128
        from reportlab.pdfbase import pdfmetrics
        from io import BytesIO
        from datetime import datetime
    except ImportError:
        raise RuntimeError("Missing dependency: reportlab. Install with: pip install reportlab")

    # Format date (MM-DD) to match your current code
    try:
        date_disp = datetime.strptime(when_iso, "%Y-%m-%d").strftime("%m-%d")
    except Exception:
        date_disp = when_iso

    # Page: using your current 6" x 0.5"
    W, H = (4 * inch, 0.5 * inch)
    M = 0.5 * mm          # margin
    GAP = 1 * mm          # gap between text and barcode block
    BAR_W_FRACTION = 0.33 # ~1/3 width reserved for barcode

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=(W, H))
    c.setLineWidth(0.6)
    c.rect(1, 1, W-2, H-2)

    # Compose the top info line (kept exactly as you wrote it)
    info = f"  {date_disp}  | {tree_no}  |  Metal: {metal_name}  |  Est: {est_metal:.1f}g"

    # Build the bags line
    bags_line = None
    if bag_nos:
        bags_line = "  Bags: " + ", ".join(bag_nos)

    # Layout: text block (left), barcode block (right)
    bar_w = max(W * BAR_W_FRACTION, 1.5 * inch)
    text_x = M
    text_w = W - (M + GAP + bar_w + M)
    # two-line layout with modest padding top/bottom
    top_pad = 0.8 * mm
    bottom_pad = 0.7 * mm

    # Helpers: fit, then (if still too long) ellipsize to width
    def _fit_size(text: str, max_w: float, base: float, minsz: float) -> float:
        size = base
        while size >= minsz:
            if pdfmetrics.stringWidth(text, "Helvetica", size) <= max_w:
                return size
            size -= 0.5
        return minsz

    def _draw_line(text: str, y: float, base: float, minsz: float):
        # try shrink first
        sz = _fit_size(text, text_w, base, minsz)
        if pdfmetrics.stringWidth(text, "Helvetica", sz) <= text_w:
            c.setFont("Helvetica", sz)
            c.drawString(text_x, y, text)
            return

        # ellipsize if still too long
        ell = "…"
        while text and pdfmetrics.stringWidth(text + ell, "Helvetica", sz) > text_w:
            text = text[:-1]
        c.setFont("Helvetica", sz)
        c.drawString(text_x, y, (text + ell) if text else ell)

    # Decide font sizes (slightly different bases for top/bottom)
    top_base, top_min = 10.0, 5.0
    bot_base, bot_min = 9.0, 5.0

    # Compute y positions: top line near top, bottom line near bottom
    # baselines, not centers (reportlab uses baseline y)
    top_y = H - M - top_pad - top_base * 0.9
    bot_y = M + bottom_pad

    # Draw top info line
    _draw_line(info, top_y, top_base, top_min)

    # Draw bag numbers if provided
    if bags_line:
        _draw_line(bags_line, bot_y, bot_base, bot_min)

    # Barcode block (right)
    bar_x = W - M - bar_w
    avail_h = H - 2 * M
    avail_w = bar_w

    # Your current barcode settings (kept unchanged)
    b = code128.Code128(tree_no, barHeight=avail_h, barWidth=1)

    # Uniform scaling so it fits
    scale_x = avail_w / float(b.width)
    scale_y = avail_h / float(b.height)
    scale = min(scale_x, scale_y, 1.0)

    # Center barcode in its block
    bx = bar_x + (avail_w - b.width * scale) / 2.0
    by = M + (avail_h - b.height * scale) / 2.0

    c.saveState()
    c.translate(bx, by)
    c.scale(scale, scale)
    b.drawOn(c, 0, 0)
    c.restoreState()

    c.showPage()
    c.save()
    pdf = buf.getvalue()
    buf.close()
    return pdf

@ui.page('/trees')
async def create_tree_page(client: Client):
    def notify(msg: str, color='primary'):
        with client:
            ui.notify(msg, color=color)

    ui.page_title('Create Tree · Casting Tracker')
    ui.add_head_html('<style>.fill-parent{width:100%!important;max-width:100%!important}</style>')

    # header
    with ui.header().classes('items-center justify-between bg-gray-900 text-white'):
        ui.label('Create Tree').classes('text-lg font-semibold')
        with ui.row().classes('items-center gap-2'):
            # ui.button('POST FLASK', on_click=lambda: ui.navigate.to('/post-flask')).props('flat').classes('text-white')
            ui.button(icon='home', on_click=lambda: ui.navigate.to('/')).props('flat round').classes('text-white')

    # preload metals
    try:
        metals = await fetch_metals()
        metal_options = sorted([m['name'] for m in metals if 'name' in m])
        name_to_id = {m['name']: m['id'] for m in metals}
    except Exception as e:
        notify(f'Failed to load metals: {e}', 'negative')
        metal_options, name_to_id = [], {}

    # layout: left form (full), right transit table
    with ui.splitter(value=50).classes('px-6').style('width:100%; height: calc(100vh - 140px);') as split:

        # LEFT: full-width form
        with split.before:
            with ui.element('div').classes('w-full h-full').style('width:100%; height:100%;'):
                with ui.card().classes('w-full h-full m-0 p-4'):
                    d_in = ui.input('Date', value=date.today().isoformat()).props('type=date').classes('w-full')
                    t_no = ui.input('Tree No').classes('w-full')  # auto-filled
                    metal_pick = ui.select(options=metal_options, label='Metal').classes('w-full')

                    # pages/trees.py  (inside the LEFT form card, near your other inputs)

                    # --- NEW: collect multiple bag numbers ---
                    bag_vals: List[str] = []  # local UI state

                    ui.label('Scan Bags').classes('mt-2')
                    bag_in = ui.input().props('autofocus clearable').classes('w-full')

                    chips_row = ui.row().classes('gap-2 flex-wrap mt-2')

                    def render_bag_chips():
                        chips_row.clear()
                        for b in bag_vals:
                            with chips_row:
                                ui.chip(b).props('removable').on('remove', lambda _=None, bb=b: remove_bag(bb))
                        chips_row.update()

                    def add_bag(raw: str):
                        s = (raw or '').strip().upper()
                        if not s:
                            return
                        if s not in bag_vals:
                            bag_vals.append(s)
                            render_bag_chips()
                        bag_in.value = ''  # clear for the next scan

                    def remove_bag(b: str):
                        try:
                            bag_vals.remove(b)
                            render_bag_chips()
                        except ValueError:
                            pass

                    # Enter to add; also add on blur/change so scanner + manual both work
                    bag_in.on('keydown.enter', lambda e: add_bag(bag_in.value))
                    bag_in.on('change',        lambda e: add_bag(bag_in.value))

                    # (call once so the container exists)
                    render_bag_chips()


                    # capture gasket & total here
                    g_in = ui.number('Gasket Weight', value=0.0).classes('w-full')
                    tot_in = ui.number('Total Weight', value=0.0).classes('w-full')

                    # derived preview
                    tw_label = ui.label('Tree Wt: —').classes('text-gray-600 mt-1')
                    est_label = ui.label('Estimated Metal: —').classes('text-gray-600 mt-1')

                    def refresh_est():
                        try:
                            g = float(g_in.value or 0.0)
                            t = float(tot_in.value or 0.0)
                            tw = max(0.0, t - g)
                            tw_label.text = f'Tree Wt: {tw:.1f}'
                            if not metal_pick.value:
                                est_label.text = 'Estimated Metal: —'; return
                            est = est_metal_weight(tw, metal_pick.value)
                            est_label.text = f'Estimated Metal: {est:.1f}'
                        except Exception:
                            tw_label.text = 'Tree Wt: —'
                            est_label.text = 'Estimated Metal: —'

                    metal_pick.on('update:model-value', lambda _v: refresh_est())
                    g_in.on('change', lambda _e: refresh_est())
                    tot_in.on('change', lambda _e: refresh_est())

                    async def fill_next_no():
                        """Fetch and fill the next tree number for current date."""
                        try:
                            t_no.value = await fetch_next_tree_no()
                        except Exception as ex:
                            notify(f'Failed to auto-assign Tree No: {ex}', 'warning')

                    # Fetch on load and whenever date changes
                    async def _date_changed():
                        await fill_next_no()
                    d_in.on('change', lambda _e: asyncio.create_task(_date_changed()))

                    async def submit(do_print: bool):
                        if not (d_in.value and t_no.value and metal_pick.value):
                            notify('Please fill Date, Tree No, and Metal.', 'warning'); return
                        if metal_pick.value not in name_to_id:
                            notify('Unknown metal selected.', 'negative'); return
                        try:
                            payload = {
                                'date': d_in.value,
                                'tree_no': t_no.value.strip(),
                                'metal_id': int(name_to_id[metal_pick.value]),
                                'gasket_weight': float(g_in.value or 0.0),
                                'total_weight': float(tot_in.value or 0.0),
                                'posted_by': 'tree_ui',
                                'bag_nos': bag_vals,
                            }
                        except Exception:
                            notify('Invalid numbers.', 'negative'); return

                        # estimate for label preview
                        g = float(payload['gasket_weight'])
                        t = float(payload['total_weight'])
                        tw = max(0.0, t - g)
                        est = est_metal_weight(tw, metal_pick.value)

                        try:
                            async with httpx.AsyncClient(timeout=10.0) as c:
                                r = await c.post(f'{API_URL}/trees', json=payload)
                                r.raise_for_status()
                                data = r.json()
                            est_label.text = f"Estimated Metal: {float(data['est_metal_weight']):.1f}"
                            notify('Tree created → Transit', 'positive')

                            if do_print:
                                try:
                                    pdf_bytes = _build_tree_label_pdf_bytes(
                                        tree_no=payload['tree_no'],
                                        metal_name=metal_pick.value or '',
                                        when_iso=payload['date'],
                                        est_metal=est,
                                        bag_nos=bag_vals,
                                    )
                                    b64 = base64.b64encode(pdf_bytes).decode('ascii')
                                    b64_json = json.dumps(b64)
                                    with client:
                                        # Open PDF in a new tab (same pattern as Post-Flask)
                                        ui.run_javascript(f"""
                                        (()=>{{
                                          if (window.__labelOpening) return;
                                          window.__labelOpening = true;
                                          const b64 = {b64_json};
                                          const bytes = atob(b64);
                                          const arr = new Uint8Array(bytes.length);
                                          for (let i=0;i<bytes.length;i++) arr[i] = bytes.charCodeAt(i);
                                          const blob = new Blob([arr], {{type:'application/pdf'}});
                                          const url = URL.createObjectURL(blob);
                                          const a = document.createElement('a');
                                          a.href = url; a.target = '_blank'; a.rel = 'noopener';
                                          document.body.appendChild(a); a.click(); a.remove();
                                          setTimeout(()=>{{ URL.revokeObjectURL(url); window.__labelOpening=false; }}, 30000);
                                        }})();
                                        """)
                                except Exception as ex:
                                    notify(f'Label error: {ex}', 'warning')

                            # reset inputs & prefill next number
                            g_in.value = 0.0
                            tot_in.value = 0.0

                            bag_vals.clear()
                            render_bag_chips()
                            bag_in.value = ''

                            refresh_est()
                            await fill_next_no()
                            await refresh_transit_table()
                        except httpx.HTTPStatusError as e:
                            notify(explain_http_error(e), 'negative')
                        except Exception as ex:
                            notify(str(ex), 'negative')

                    with ui.row().classes('gap-2 mt-2'):
                        ui.button('CREATE TREE', on_click=lambda: asyncio.create_task(submit(False))) \
                          .classes('bg-emerald-600 text-white')
                        ui.button('CREATE & PRINT BARCODE', on_click=lambda: asyncio.create_task(submit(True))) \
                          .classes('bg-indigo-600 text-white')
                        ui.button('RECALCULATE', on_click=refresh_est).props('outline')

                    # initial auto-assign
                    await fill_next_no()

        # RIGHT: transit queue (unchanged aside from columns/filters)
        with split.after:
            with ui.card().classes('w-full h-full p-0'):
                with ui.column().classes('w-full h-full').style('display:flex; flex-direction:column;'):
                    today_iso = date.today().isoformat()
                    with ui.row().classes('items-end gap-3 p-4').style('flex:0 0 auto;'):
                        ui.label('Trees in Transit').classes('text-base font-semibold mr-4')
                        t_search = ui.input('Search by Tree No').props('clearable').classes('w-48')
                        d_from = ui.input('From').props('type=date').classes('w-36')
                        d_to   = ui.input('To').props('type=date').classes('w-36')
                        metal_filter = ui.select(options=['All'] + metal_options, value='All', label='Metal').classes('w-48')
                        metal_filter.props('options-dense behavior=menu popup-content-style="z-index:4000"')

                        async def reset_filters():
                            # d_from.value = today_iso; d_to.value = today_iso
                            d_from.value = ''; d_to.value = ''
                            t_search.value = ''; metal_filter.value = 'All'
                            await refresh_transit_table()
                            notify('Filters reset.', 'positive')

                        ui.button('RESET FILTERS', on_click=lambda: asyncio.create_task(reset_filters())).props('outline')

                    with ui.element('div').classes('fill-parent').style(
                        'flex:1 1 auto; overflow:auto; padding:0 16px 16px 16px; width:100%; max-width:100%;'
                    ):
                        columns = [
                            {'name': 'date', 'label': 'Date', 'field': 'date'},
                            {'name': 'tree_no', 'label': 'Tree No', 'field': 'tree_no'},
                            {'name': 'metal_name', 'label': 'Metal', 'field': 'metal_name'},
                            {'name': 'gasket_weight', 'label': 'Gasket', 'field': 'gasket_weight'},
                            {'name': 'total_weight', 'label': 'Total', 'field': 'total_weight'},
                            {'name': 'tree_weight', 'label': 'Tree Wt', 'field': 'tree_weight'},
                            {'name': 'est_metal_weight', 'label': 'Est. Metal', 'field': 'est_metal_weight'},
                        ]
                        transit_table = ui.table(columns=columns, rows=[]) \
                                          .props('dense flat bordered row-key="tree_id" hide-bottom') \
                                          .classes('w-full text-sm')

    # -------- filtering & refresh --------
    def _apply_filters_transit(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        f_date = parse_iso_date(d_from.value)
        t_date = parse_iso_date(d_to.value)
        pick   = metal_filter.value or 'All'
        needle = (t_search.value or '').strip().lower()

        out: List[Dict[str, Any]] = []
        for r in rows:
            d_iso = r.get('date') or ''
            d = parse_iso_date(d_iso)
            if not d: continue
            if f_date and d < f_date: continue
            if t_date and d > t_date: continue
            if pick != 'All' and (r.get('metal_name') != pick): continue
            if needle and needle not in str(r.get('tree_no','')).lower(): continue

            rr = dict(r)
            rr['_sort_ord'] = -d.toordinal()
            rr['_sort_metal'] = rr.get('metal_name') or ''
            rr['_sort_tree'] = str(rr.get('tree_no',''))
            rr['_display_date'] = to_ui_date(d_iso)
            out.append(rr)

        out.sort(key=lambda x: (x['_sort_ord'], x['_sort_metal'], x['_sort_tree']))
        for rr in out:
            rr['date'] = rr['_display_date']
            for k in ('_sort_ord','_sort_metal','_sort_tree','_display_date'):
                rr.pop(k, None)
        return out

    async def refresh_transit_table():
        try:
            raw = await fetch_transit(
                date_from=d_from.value, date_to=d_to.value,
                tree_no=(t_search.value or '').strip(),
                metal=metal_filter.value,
            )
        except Exception as e:
            notify(f'Failed to fetch transit: {e}', 'negative')
            raw = []
        rows = _apply_filters_transit(raw)
        transit_table.rows = rows
        transit_table.update()

    # events
    metal_filter.on('update:model-value', lambda _v: asyncio.create_task(refresh_transit_table()))
    t_search.on('change', lambda _e: asyncio.create_task(refresh_transit_table()))
    d_from.on('change',  lambda _e: asyncio.create_task(refresh_transit_table()))
    d_to.on('change',    lambda _e: asyncio.create_task(refresh_transit_table()))

    # initial
    await asyncio.create_task(refresh_transit_table())
