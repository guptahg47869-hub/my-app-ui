# pages/post_flask.py
from nicegui import ui, Client  # type: ignore
import httpx, os, asyncio, base64, json  # <- added base64, json for printing
from datetime import date, datetime
from typing import Any, Dict, List

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

def mm_dd_yyyy(iso: str) -> str:  # <- same as metal_prep
    try:
        return datetime.strptime(iso, '%Y-%m-%d').strftime('%m-%d-%Y')
    except Exception:
        return iso

def mm_dd(iso: str) -> str:
    try:
        return datetime.strptime(iso, '%Y-%m-%d').strftime('%m-%d')
    except Exception:
        return iso

def explain_http_error(e: httpx.HTTPStatusError) -> str:
    try:
        data = e.response.json()
        if isinstance(data, dict) and 'detail' in data:
            return str(data['detail'])
        return str(data)
    except Exception:
        return e.response.text or str(e)

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

# --- posts to Metal Prep (unchanged) ---
async def post_flask(payload: Dict[str, Any]):
    async with httpx.AsyncClient(timeout=15.0) as c:
        r = await c.post(f'{API_URL}/waxing/post_to_prep', json=payload)
        try:
            r.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise RuntimeError(explain_http_error(e)) from e
        return r.json()

def est_metal_weight(tree_weight: float, metal_name: str) -> float:
    name = (metal_name or '').upper()
    factor = 1.0
    if '10' in name: factor = 11
    elif '14' in name: factor = 13.25
    elif '18' in name: factor = 16.5
    elif 'PLATINUM' in name: factor = 21
    elif 'SILVER' in name: factor = 11
    return round((tree_weight or 0.0) * factor, 3)

# --- snapshot for Metal Prep queue (bottom-left) ---
async def fetch_metal_prep_queue(params: Dict[str, Any] | None = None):
    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.get(f'{API_URL}/queue/metal_prep', params=params or None)
        r.raise_for_status()
        return r.json()

async def check_flask_unique(date_iso: str, flask_no: str):
    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.get(f'{API_URL}/waxing/check_flask_unique',
                        params={'date': date_iso, 'flask_no': flask_no})
        try:
            r.raise_for_status()
        except httpx.HTTPStatusError as e:
            # re-use your existing explainer for a nice message
            raise RuntimeError(explain_http_error(e)) from e
        return r.json()

# ------------ SAME label generator as Metal Prep ------------
def build_simple_label_pdf(*, flask_no: str, tree_no: str, metal_name: str,
                           date_iso: str, required: float) -> bytes:
    """
    2x3in, skinny Code128 barcode, big DATE and 'FLASK: N' at bottom.
    """
    from io import BytesIO
    from reportlab.pdfgen import canvas
    from reportlab.lib.units import inch, mm
    from reportlab.graphics.barcode import code128

    W, H = (2 * inch, 3 * inch)
    M = 12
    disp_date = mm_dd(date_iso)

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=(H, W))

    try:
        # ReportLab 3.6+: sets PDF /Rotate on the page (no layout changes needed)
        c.setPageRotation(90)
    except AttributeError:
        # Fallback: rotate the drawing coordinate system
        # (do this BEFORE any drawing; then swap W/H so your existing code works)
        print("this")
        c.saveState()
        c.translate(W, 0)     # move origin to the right edge
        c.rotate(90)          # rotate CCW 90°
        W, H = H, W           # swap logical width/height so layout code below stays the same
    
    c.setLineWidth(0.6)
    c.rect(1, 1, W-2, H-2)

    y = H - M -10
    c.setFont('Helvetica-Bold', 22)
    # c.drawString(M, y, 'Metal:'); 
    # c.drawRightString(W-M, y, (metal_name or '—'))
    c.drawCentredString(W/2, y, f'{metal_name or "—"}')
    y -= 8
    c.setLineWidth(1)
    c.line(0, y, W, y); y -= 16

    c.setFont('Helvetica', 10)
    c.drawString(M, y, 'Metal Weight:'); c.drawRightString(W-M, y, f'{required:.1f}'); y -= 16

    c.drawString(M, y, 'Casting Weight:'); c.line(M+80, y-1, W-M, y-1); y -= 16
    c.drawString(M, y, 'Cutting Weight:'); c.line(M+80, y-1, W-M, y-1); y -= 20

    bar_width  = 0.8
    bar_height = 7 * mm
    b = code128.Code128(tree_no or '', barHeight=bar_height, barWidth=bar_width)
    bx = max(M, (W - b.width) / 2)
    by = y - b.height
    b.drawOn(c, bx, by)
    y = by - 12

    c.setFont('Helvetica', 10)
    c.drawString(M, y, 'Tree:'); c.drawRightString(W-M, y, (tree_no or '—')); y -= 8

    c.setLineWidth(1)
    c.line(0, y, W, y); y -= 8

    c.setFont('Helvetica-Bold', 20)
    c.drawCentredString(W/2, M+38, disp_date)

    c.setFont('Helvetica-Bold', 22)
    c.drawCentredString(W/2, M+18, f'FLASK: {flask_no}')

    c.showPage(); c.save()
    return buf.getvalue()
# ------------------------------------------------------------

@ui.page('/post-flask')
async def post_flask_page(client: Client):
    def notify(msg: str, color='primary'):
        with client:
            ui.notify(msg, color=color)

    ui.page_title('Post Flask to Metal Prep · Casting Tracker')
    ui.add_head_html('<style>.fill-parent{width:100%!important;max-width:100%!important}</style>')

    with ui.header().classes('items-center justify-between bg-gray-900 text-white'):
        ui.label('Post Flask to Metal Prep').classes('text-lg font-semibold')
        with ui.row().classes('items-center gap-2'):
            # ui.button('CREATE TREE', on_click=lambda: ui.navigate.to('/trees')).props('flat').classes('text-white')
            ui.button(icon='home', on_click=lambda: ui.navigate.to('/')).props('flat round').classes('text-white')

    selected: Dict[str, Any] | None = None

    with ui.splitter(value=60).classes('px-6').style('width:100%; height: calc(100vh - 140px);') as main_split:

        # LEFT: top transit, bottom metal prep snapshot (unchanged)
        with main_split.before:
            with ui.card().classes('w-full h-full p-0'):
                inner = ui.splitter(value=60).props('horizontal').style('width:100%; height:100%')

                # TOP: transit
                with inner.before:
                    with ui.column().classes('w-full h-full').style('display:flex; flex-direction:column;'):
                        today_iso = date.today().isoformat()
                        with ui.row().classes('items-end gap-3 p-4').style('flex:0 0 auto;'):
                            ui.label('Transit Queue').classes('text-base font-semibold mr-4')
                            t_search = ui.input('Search by Tree No').props('clearable').classes('w-48')
                            d_from = ui.input('From').props('type=date').classes('w-36')
                            d_to   = ui.input('To').props('type=date').classes('w-36')

                            try:
                                async with httpx.AsyncClient(timeout=10) as c:
                                    metals = (await c.get(f'{API_URL}/metals')).json()
                                metal_options = ['All'] + sorted([m['name'] for m in metals if 'name' in m])
                            except Exception:
                                metal_options = ['All']
                            metal_filter = ui.select(options=metal_options, value='All', label='Metal').classes('w-48')
                            metal_filter.props('options-dense behavior=menu popup-content-style="z-index:4000"')

                            async def reset_filters():
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
                                {'name': 'tree_weight', 'label': 'Tree Wt', 'field': 'tree_weight'},
                                {'name': 'est_metal_weight', 'label': 'Est. Metal', 'field': 'est_metal_weight'},
                            ]
                            transit_table = ui.table(columns=columns, rows=[]) \
                                              .props('dense flat bordered row-key="tree_id" selection="single" hide-bottom') \
                                              .classes('w-full text-sm')

                # BOTTOM: Metal Prep snapshot
                with inner.after:
                    with ui.column().classes('w-full h-full').style('display:flex; flex-direction:column;'):
                        with ui.row().classes('items-center justify-between p-4').style('flex:0 0 auto;'):
                            ui.label('Metal Prep Queue (snapshot)').classes('text-base font-semibold')
                            ui.button('Refresh', on_click=lambda: asyncio.create_task(refresh_prep_table())).props('outline')
                        with ui.element('div').classes('fill-parent').style(
                            'flex:1 1 auto; overflow:auto; padding:0 16px 16px 16px; width:100%; max-width:100%;'
                        ):
                            prep_columns = [
                                {'name': 'date', 'label': 'Date', 'field': 'date'},
                                {'name': 'flask_no', 'label': 'Flask No', 'field': 'flask_no'},
                                {'name': 'tree_no', 'label': 'Tree No', 'field': 'tree_no'},
                                {'name': 'metal_name', 'label': 'Metal', 'field': 'metal_name'},
                                {'name': 'required_metal_weight', 'label': 'Req. Metal', 'field': 'required_metal_weight'},
                            ]
                            prep_table = ui.table(columns=prep_columns, rows=[]) \
                                           .props('dense flat bordered hide-bottom') \
                                           .classes('w-full text-sm')

        # RIGHT: posting + PRINT LABEL (button moved to top-right)
        with main_split.after:
            with ui.card().classes('w-full h-full p-4'):
                with ui.row().classes('items-center justify-between mb-2'):
                    ui.label('Post Flask to Metal Prep').classes('text-base font-semibold')
                    btn_print = ui.button('PRINT LABEL').classes('bg-indigo-600 text-white')

                with ui.grid(columns=2).classes('gap-2 mb-2'):
                    ui.label('Tree No:');   tree_no_lbl = ui.label('—')
                    ui.label('Metal:');     metal_lbl   = ui.label('—')
                    ui.label('Transit Est:'); est_lbl   = ui.label('—')

                f_date = ui.input('Flask Date', value=date.today().isoformat()).props('type=date').classes('w-full')
                f_no   = ui.input('Flask No').classes('w-full')
                g_wt   = ui.number('Gasket Weight', value=0.0).classes('w-full')
                t_wt   = ui.number('Total Weight',  value=0.0).classes('w-full')
                tree_wt_lbl = ui.label('Tree Weight (Total − Gasket): —').classes('text-gray-600')
                final_lbl   = ui.label('Final Metal (preview): —').classes('text-gray-600')

                def refresh_preview():
                    try:
                        tw = float(t_wt.value or 0) - float(g_wt.value or 0)
                        tree_wt_lbl.text = f'Tree Weight (Total − Gasket): {tw:.1f}'
                        mname = metal_lbl.text or ''
                        final = est_metal_weight(tw, mname)
                        final_lbl.text = f'Final Metal (preview): {final:.1f}'
                    except Exception:
                        tree_wt_lbl.text = 'Tree Weight (Total − Gasket): —'
                        final_lbl.text = 'Final Metal (preview): —'

                g_wt.on('change', lambda _e: refresh_preview())
                t_wt.on('change', lambda _e: refresh_preview())

                async def sync_selection():
                    nonlocal selected
                    row_list = transit_table.selected or []
                    selected = row_list[0] if row_list else None
                    with client:
                        if not selected:
                            tree_no_lbl.text = '—'; metal_lbl.text = '—'; est_lbl.text = '—'
                            f_no.value = ''; g_wt.value = 0.0; t_wt.value = 0.0
                            tree_wt_lbl.text = 'Tree Weight (Total − Gasket): —'
                            final_lbl.text   = 'Final Metal (preview): —'
                        else:
                            tree_no_lbl.text = selected.get('tree_no','—')
                            metal_lbl.text   = selected.get('metal_name','—')
                            est_lbl.text     = f"{selected.get('est_metal_weight','—')}"
                            g = selected.get('gasket_weight')
                            t = selected.get('total_weight')
                            tw = float(selected.get('tree_weight') or 0.0)
                            if g is None and t is None:
                                g = 0.0; t = tw
                            g_wt.value = float(g or 0.0)
                            t_wt.value = float(t or 0.0)
                            refresh_preview()

                transit_table.on('selection', lambda _e: asyncio.create_task(sync_selection()))

                # PRINT LABEL (same logic & layout as metal_prep)
                async def do_print_label():
                    nonlocal selected
                    if not selected:
                        notify('Select a tree first.', 'warning'); return
                    flask_no = (f_no.value or '').strip()
                    if not flask_no:
                        notify('Enter a Flask No before printing.', 'warning'); return
                    # 1) VALIDATE without posting
                    try:
                        await check_flask_unique(str(f_date.value or date.today().isoformat()), flask_no)
                    except Exception as ex:
                        # same message as posting endpoint (e.g. "Flask #N is already used on MM-DD-YYYY")
                        notify(str(ex), 'negative'); return

                    try:
                        tw = float(t_wt.value or 0) - float(g_wt.value or 0)
                        required = est_metal_weight(tw, metal_lbl.text or '')
                        pdf_bytes = build_simple_label_pdf(
                            flask_no=str((f_no.value or '').strip()),
                            tree_no=str(selected.get('tree_no') or ''),
                            metal_name=str(metal_lbl.text or ''),
                            date_iso=str(f_date.value or date.today().isoformat()),
                            required=float(required or 0.0),
                        )
                        b64 = base64.b64encode(pdf_bytes).decode('ascii')
                        b64_json = json.dumps(b64)
                        with client:
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

                # btn_print.on('click', do_print_label)
                btn_print.on('click', lambda: asyncio.create_task(do_print_label()))


                # POST to Metal Prep (unchanged)
                async def do_post():
                    nonlocal selected
                    if not selected:
                        notify('Select a tree in transit first.', 'warning'); return
                    try:
                        payload = {
                            'tree_id': int(selected['tree_id']),
                            'flask_no': (f_no.value or '').strip(),
                            'date': f_date.value,
                            'gasket_weight': float(g_wt.value or 0.0),
                            'total_weight': float(t_wt.value or 0.0),
                            'posted_by': 'waxing_ui',
                        }
                    except Exception:
                        notify('Invalid inputs.', 'negative'); return
                    if not payload['flask_no']:
                        notify('Flask No is required.', 'warning'); return

                    try:
                        _ = await post_flask(payload)
                        notify(f"Flask {payload['flask_no']} posted to Metal Prep.", 'positive')
                        with client:
                            transit_table.rows = [r for r in transit_table.rows if r['tree_id'] != selected['tree_id']]
                            transit_table.selected = []; transit_table.update()
                        await refresh_prep_table()

                        f_no.value = ''; g_wt.value = 0.0; t_wt.value = 0.0
                        refresh_preview()
                        await sync_selection()
                    except Exception as ex:
                        notify(str(ex), 'negative')

                with ui.row().classes('gap-2 mt-2'):
                    ui.button('Recalculate', on_click=refresh_preview).props('outline')
                    ui.button('Post to Metal Prep', on_click=lambda: asyncio.create_task(do_post())) \
                        .classes('bg-emerald-600 text-white')

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
            if not d:
                continue
            if f_date and d < f_date:
                continue
            if t_date and d > t_date:
                continue
            if pick != 'All' and (r.get('metal_name') != pick):
                continue
            if needle and needle not in str(r.get('tree_no','')).lower():
                continue
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

    def _format_and_sort_prep(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for r in rows:
            d_iso = r.get('date') or ''
            d = parse_iso_date(d_iso)
            if not d:
                continue
            rr = dict(r)
            rr['_sort_ord'] = -d.toordinal()
            rr['_sort_metal'] = rr.get('metal_name') or ''
            rr['_sort_flask'] = str(rr.get('flask_no',''))
            rr['_display_date'] = to_ui_date(d_iso)
            out.append(rr)
        out.sort(key=lambda x: (x['_sort_ord'], x['_sort_metal'], x['_sort_flask']))
        for rr in out:
            rr['date'] = rr['_display_date']
            for k in ('_sort_ord','_sort_metal','_sort_flask','_display_date'):
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

    async def refresh_prep_table():
        try:
            raw = await fetch_metal_prep_queue({})
        except Exception as e:
            notify(f'Failed to fetch metal prep queue: {e}', 'negative')
            raw = []
        rows = _format_and_sort_prep(raw)
        prep_table.rows = rows
        prep_table.update()

    metal_filter.on('update:model-value', lambda _v: asyncio.create_task(refresh_transit_table()))
    t_search.on('change', lambda _e: asyncio.create_task(refresh_transit_table()))
    d_from.on('change',  lambda _e: asyncio.create_task(refresh_transit_table()))
    d_to.on('change',    lambda _e: asyncio.create_task(refresh_transit_table()))

    await asyncio.create_task(refresh_transit_table())
    await asyncio.create_task(refresh_prep_table())
