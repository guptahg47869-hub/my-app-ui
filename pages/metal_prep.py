# pages/metal_prep.py
from nicegui import ui, Client
import httpx, os, asyncio, base64, json
from datetime import date, datetime
from typing import Any, Dict, List

API_URL = os.getenv('API_URL', 'http://localhost:8000')
print('UI using API_URL =', API_URL)


# ---------- helpers ----------
def to_ui_date(iso: str) -> str:
    try:
        return datetime.strptime(iso, '%Y-%m-%d').strftime('%m-%d-%Y')
    except Exception:
        return iso

def mm_dd_yyyy(iso: str) -> str:
    try:
        return datetime.strptime(iso, '%Y-%m-%d').strftime('%m-%d-%Y')
    except Exception:
        return iso

def mm_dd(iso: str) -> str:
    try:
        return datetime.strptime(iso, '%Y-%m-%d').strftime('%m-%d')
    except Exception:
        return iso

def is_gold(m: str) -> bool:
    m = (m or '').upper()
    return m.startswith('10') or m.startswith('14') or m.startswith('18')

def is_pure_only(m: str) -> bool:
    m = (m or '').upper()
    return ('PLATINUM' in m) or ('SILVER' in m)

def rule_for_metal(metal_name: str) -> dict:
    m = (metal_name or '').strip().lower()
    if m in ('platinum', 'silver'):
        return {'type': 'pure_only'}
    if m.startswith('10'):
        return {'type': 'gold_pct', 'pct': 0.417}
    if m.startswith('14'):
        return {'type': 'gold_pct', 'pct': 0.587}
    if m.startswith('18'):
        return {'type': 'gold_pct', 'pct': 0.752}
    return {'type': 'none'}

def split_with_ratio(total: float, fine_part: int, alloy_part: int):
    denom = fine_part + alloy_part
    if denom <= 0:
        return 0.0, 0.0
    fine = total * (fine_part / denom)
    alloy = total - fine
    return round(fine, 3), round(alloy, 3)

def explain_http_error(e: httpx.HTTPStatusError) -> str:
    try:
        data = e.response.json()
        if isinstance(data, dict) and 'detail' in data:
            return str(data['detail'])
        return str(data)
    except Exception:
        return e.response.text or str(e)

def _row_id(row: dict) -> int | None:
    return row.get('flask_id') or row.get('id')

def split_with_pct(total: float, pct: float):
    fine = total * pct
    alloy = total - fine
    return round(fine, 3), round(alloy, 3)

# ---------- API ----------
async def fetch_metals() -> List[Dict[str, Any]]:
    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.get(f'{API_URL}/metals'); r.raise_for_status(); return r.json()

async def fetch_metal_prep_queue(params: Dict[str, Any]) -> List[Dict[str, Any]]:
    async with httpx.AsyncClient(timeout=12.0) as c:
        r = await c.get(f'{API_URL}/queue/metal_prep', params=params)
        r.raise_for_status(); return r.json()

async def fetch_reserves() -> List[Dict[str, Any]]:
    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.get(f'{API_URL}/scrap/reserves'); r.raise_for_status(); return r.json()

async def get_preset(flask_id: int) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.get(f'{API_URL}/metal-prep/preset/{flask_id}')
        r.raise_for_status(); return r.json()

async def post_prep(payload: Dict[str, Any]) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=20.0) as c:
        r = await c.post(f'{API_URL}/metal-prep', json=payload)
        try:
            r.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise RuntimeError(explain_http_error(e)) from e
        return r.json()


# ---------- label (2x3) like Supply / Metal Prep standard ----------
def build_simple_label_pdf(*, flask_no: str, tree_no: str, metal_name: str,
                           date_iso: str, required: float) -> bytes:
    """
    Skinny Code128; big date + 'FLASK: #'
    """
    try:
        from reportlab.pdfgen import canvas
        from reportlab.lib.units import inch, mm
        from reportlab.graphics.barcode import code128
        from io import BytesIO
    except ImportError:
        raise RuntimeError('Missing dependency: reportlab (pip install reportlab)')

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

    y = H - M
    c.setFont('Helvetica', 10)
    c.drawString(M, y, 'Metal:')
    c.drawRightString(W-M, y, (metal_name or '—')); y -= 14
    c.drawString(M, y, 'Metal Weight:')
    c.drawRightString(W-M, y, f'{required:.1f}'); y -= 16

    c.drawString(M, y, 'Casting Weight:')
    c.line(M+80, y-1, W-M, y-1); y -= 16
    c.drawString(M, y, 'Cutting Weight:')
    c.line(M+80, y-1, W-M, y-1); y -= 20

    bar_width  = 0.8
    bar_height = 7 * mm
    b = code128.Code128(tree_no or '', barHeight=bar_height, barWidth=bar_width)
    bx = max(M, (W - b.width) / 2)
    by = y - b.height
    b.drawOn(c, bx, by)
    y = by - 12

    c.setFont('Helvetica', 10)
    c.drawString(M, y, 'Tree:')
    c.drawRightString(W-M, y, (tree_no or '—')); y -= 8

    c.setFont('Helvetica-Bold', 16)
    c.drawCentredString(W/2, M+38, disp_date)
    c.setFont('Helvetica-Bold', 18)
    c.drawCentredString(W/2, M+18, f'FLASK: {flask_no}')

    c.showPage(); c.save()
    out = buf.getvalue(); buf.close()
    return out


# ---------- page ----------
@ui.page('/metal-prep')
async def metal_prep_page(client: Client):

    def notify(msg: str, color='primary'):
        with client:
            ui.notify(msg, color=color)

    ui.page_title('Metal Prep · Casting Tracker')

    with ui.header().classes('items-center justify-between bg-gray-900 text-white'):
        ui.label('Metal Prep').classes('text-lg font-semibold')
        with ui.row().classes('items-center gap-2'):
            ui.button('METAL SUPPLY', on_click=lambda: ui.navigate.to('/supply')).props('flat').classes('text-white')
            ui.button('RECONCILIATION', on_click=lambda: ui.navigate.to('/reconciliation')).props('flat').classes('text-white')
            ui.button(icon='home', on_click=lambda: ui.navigate.to('/')).props('flat round').classes('text-white')

    # preload metal list (for filter dropdown)
    try:
        metals = await fetch_metals()
        metal_options = ['All'] + sorted([m['name'] for m in metals if 'name' in m])
    except Exception as e:
        notify(f'Failed to load metals: {e}', 'negative')
        metal_options = ['All']

    today_iso = date.today().isoformat()

    # --- layout ---
    with ui.splitter(value=55).classes('px-6').style('width:100%; height: calc(100vh - 140px);') as main_split:

        # LEFT: queue (top) + reserves (bottom)
        with main_split.before:
            left_split = ui.splitter(value=60).props('horizontal').style('width:100%; height:100%')

            # TOP LEFT: queue
            with left_split.before:
                with ui.column().classes('w-full h-full').style('display:flex; flex-direction:column;'):
                    with ui.row().classes('items-end gap-3 p-4').style('flex:0 0 auto;'):
                        ui.label('Metal Prep Queue').classes('text-base font-semibold mr-4')
                        search = ui.input('Search by Flask or Tree').props('clearable').classes('w-56')
                        date_from = ui.input('From').props('type=date').classes('w-36')
                        date_to   = ui.input('To').props('type=date').classes('w-36')
                        metal_pick = ui.select(options=metal_options, value='All', label='Metal').classes('w-48')
                        metal_pick.props('options-dense behavior=menu popup-content-style="z-index:4000"')

                        metal_pick.on('update:model-value', lambda _v: asyncio.create_task(refresh_queue()))
                        for ctrl in (search, date_from, date_to):
                            ctrl.on('change', lambda _e: asyncio.create_task(refresh_queue()))

                        async def reset_filters():
                            search.value = ''
                            date_from.value = ''
                            date_to.value   = ''
                            metal_pick.value = 'All'
                            await refresh_queue()

                        ui.button('RESET FILTERS', on_click=lambda: asyncio.create_task(reset_filters())).props('outline')

                    with ui.element('div').classes('fill-parent').style(
                        'flex:1 1 auto; overflow:auto; padding:0 16px 16px 16px; width:100%; max-width:100%;'
                    ):
                        columns = [
                            {'name': 'flask_id', 'label': '', 'field': 'flask_id',
                             'style': 'display:none', 'headerStyle': 'display:none'},
                            {'name': 'date', 'label': 'Date', 'field': 'date'},
                            {'name': 'flask_no', 'label': 'Flask No', 'field': 'flask_no'},
                            {'name': 'tree_no', 'label': 'Tree No', 'field': 'tree_no'},
                            {'name': 'metal_name', 'label': 'Metal', 'field': 'metal_name'},
                            {'name': 'required_metal_weight', 'label': 'Req. Metal', 'field': 'required_metal_weight'},
                        ]
                        queue_table = ui.table(columns=columns, rows=[]) \
                            .props('dense flat bordered row-key="flask_id" selection="single" hide-bottom') \
                            .classes('w-full text-sm')

            # BOTTOM LEFT: reserves
            with left_split.after:
                with ui.card().props('flat').classes('w-full h-full p-4 overflow-auto'):
                    ui.label('Scrap Reserve').classes('text-base font-semibold mb-2')
                    reserve_columns = [
                        {'name': 'metal', 'label': 'Metal', 'field': 'metal_name'},
                        {'name': 'qty',   'label': 'Scrap Available', 'field': 'qty_on_hand'},
                    ]
                    reserve_table = ui.table(columns=reserve_columns, rows=[]) \
                                      .props('dense flat bordered hide-bottom') \
                                      .classes('w-full text-sm')

        # RIGHT: editor (with Recalculate + print + two posts)
        with main_split.after:
            with ui.card().props('flat').classes('w-full h-full p-4 overflow-auto'):
                with ui.row().classes('items-center justify-between'):
                    ui.label('Prepare Selected Flask').classes('text-base font-semibold')
                    btn_print = ui.button('PRINT LABEL').classes('bg-indigo-600 text-white')

                with ui.grid(columns=2).classes('gap-2 mb-2'):
                    ui.label('Flask No:');  flask_no_lbl = ui.label('—')
                    ui.label('Tree No:');   tree_no_lbl  = ui.label('—')
                    ui.label('Metal:');     metal_lbl    = ui.label('—')
                    ui.label('Required Wt:'); req_lbl    = ui.label('—')
                    ui.label('Date:');      date_lbl     = ui.label('—')

                scrap_in = ui.number('Scrap', value=0.0).classes('w-full')

                gold_box = ui.column().classes('w-full')
                with gold_box:
                    fine_in  = ui.number('24K (fine)', value=0.0).classes('w-full')
                    alloy_in = ui.number('Alloy', value=0.0).classes('w-full')

                pure_box = ui.column().classes('w-full')
                with pure_box:
                    pure_in = ui.number('Pure Metal', value=0.0).classes('w-full')
                pure_box.visible = False

                preview = ui.label('Total: —').classes('text-sm text-gray-600')

                with ui.row().classes('gap-3 mt-2'):
                    btn_recalc    = ui.button('RECALCULATE').props('outline').classes('bg-white text-gray-800')
                    btn_prepared  = ui.button('PREPARED • POST').props('unelevated color=primary').classes('text-white')
                    btn_unprepared= ui.button('NOT PREPARED • POST').props('unelevated color=primary').classes('text-white')

    # ---------- state & behaviors ----------
    def _required(row: dict) -> float:
        return float(row.get('required_metal_weight') or row.get('metal_weight') or 0.0)

    def show_gold():
        gold_box.visible = True; pure_box.visible = False
        gold_box.update(); pure_box.update()

    def show_pure():
        gold_box.visible = False; pure_box.visible = True
        gold_box.update(); pure_box.update()

    def update_preview():
        sel = (queue_table.selected or [None])[0]
        req = _required(sel) if sel else 0.0
        rule = rule_for_metal((sel or {}).get('metal_name') or '')
        s = float(scrap_in.value or 0.0)

        if rule['type'] == 'pure_only':
            tot = s + float(pure_in.value or 0.0)
        elif rule['type'] == 'gold_ratio':
            tot = s + float(fine_in.value or 0.0) + float(alloy_in.value or 0.0)
        else:
            tot = s

        with client:
            preview.text = f'Total: {tot:.1f} (Req: {req:.1f})'


    # override flags (match Supply behavior)
    fine_overridden = False
    alloy_overridden = False
    pure_overridden = False

    def reset_overrides():
        nonlocal fine_overridden, alloy_overridden, pure_overridden
        fine_overridden = alloy_overridden = pure_overridden = False

    def auto_fill_from_required():
        sel = (queue_table.selected or [None])[0]
        if not sel:
            return
        req = _required(sel)
        scrap_val = float(scrap_in.value or 0.0)
        remain = max(req - scrap_val, 0.0)
        rule = rule_for_metal(sel.get('metal_name') or '')

        if rule['type'] == 'pure_only':
            if not pure_overridden:
                pure_in.value = round(remain, 3)
        elif rule['type'] == 'gold_pct':
            if not (fine_overridden or alloy_overridden):
                # f, a = rule['fine'], rule['alloy']
                fval, aval = split_with_pct(remain, rule['pct'])
                fine_in.value, alloy_in.value = fval, aval
        else:
            if not pure_overridden and pure_box.visible:
                pure_in.value = round(remain, 3)

        update_preview()

        # update preview
        total = 0.0
        if rule['type'] == 'pure_only':
            total = (float(scrap_in.value or 0.0) + float(pure_in.value or 0.0))
        elif rule['type'] == 'gold_ratio':
            total = (float(scrap_in.value or 0.0) + float(fine_in.value or 0.0) + float(alloy_in.value or 0.0))
        else:
            total = float(scrap_in.value or 0.0)
        preview.text = f'Total: {total:.1f} (Req: {req:.1f})'

    def on_scrap_change(_e):
        auto_fill_from_required()

    def on_fine_change(_e):
        nonlocal fine_overridden
        fine_overridden = True
        update_preview()

    def on_alloy_change(_e):
        nonlocal alloy_overridden
        alloy_overridden = True
        update_preview()

    def on_pure_change(_e):
        nonlocal pure_overridden
        pure_overridden = True
        update_preview()

    scrap_in.on('change', on_scrap_change)
    fine_in.on('change', on_fine_change)
    alloy_in.on('change', on_alloy_change)
    pure_in.on('change', on_pure_change)

    def recalc_click():
        reset_overrides()
        auto_fill_from_required()
        update_preview()

    btn_recalc.on('click', recalc_click)

    # pages/metal_prep.py
    async def refresh_queue():
        try:
            params = {}

            q = (search.value or '').strip()
            if q:
                params['q'] = q

            if date_from.value:          # only include if set
                params['date_from'] = date_from.value
            if date_to.value:            # only include if set
                params['date_to'] = date_to.value

            m = metal_pick.value
            if m and m != 'All':         # don't send empty/All
                params['metal'] = m

            async with httpx.AsyncClient(timeout=15.0) as c:
                r = await c.get(f'{API_URL}/queue/metal_prep', params=params)
                r.raise_for_status()
                rows = r.json()
                for r in rows:
                    r['date'] = mm_dd_yyyy(r.get('date'))
                queue_table.rows = rows
                queue_table.update()
        except httpx.HTTPStatusError as e:
            notify(f'Failed to load Metal Prep queue: {e}', 'negative')
        except Exception as ex:
            notify(f'Failed to load Metal Prep queue: {ex}', 'negative')

    async def load_reserves():
        try:
            rows = await fetch_reserves()
            for r in rows:
                r['qty_on_hand'] = round(float(r.get('qty_on_hand') or 0.0), 3)
            rows.sort(key=lambda r: (r.get('metal_name') or '').lower())
            with client:
                reserve_table.rows = rows; reserve_table.update()
        except Exception as e:
            notify(f'Failed to load reserves: {e}', 'negative')

    async def hydrate_right():
        sel = (queue_table.selected or [None])[0]
        if not sel:
            with client:
                flask_no_lbl.text = tree_no_lbl.text = metal_lbl.text = req_lbl.text = date_lbl.text = '—'
                scrap_in.value = fine_in.value = alloy_in.value = pure_in.value = 0.0
                preview.text = 'Total: —'
            show_gold()
            return

        req = _required(sel)
        with client:
            flask_no_lbl.text = f"{sel.get('flask_no')}"
            tree_no_lbl.text  = f"{sel.get('tree_no') or '—'}"
            metal_lbl.text    = f"{sel.get('metal_name')}"
            req_lbl.text      = f"{req:.1f}"
            date_lbl.text     = to_ui_date(sel.get('date_iso') or sel.get('date') or date.today().isoformat())

        # decide visible box
        if is_pure_only(sel.get('metal_name') or ''): show_pure()
        else:                                         show_gold()

        # prefill from preset if exists
        try:
            preset = await get_preset(int(_row_id(sel)))
        except Exception:
            preset = {}
        if preset.get('prepared'):
            with client:
                scrap_in.value = float(preset.get('scrap_planned') or 0.0)
                fine_in.value  = float(preset.get('fine_24k_planned') or 0.0)
                alloy_in.value = float(preset.get('alloy_planned') or 0.0)
                pure_in.value  = float(preset.get('pure_planned') or 0.0)
        else:
            with client:
                scrap_in.value = fine_in.value = alloy_in.value = pure_in.value = 0.0

        # compute preview on load
        recalc_click()

    # printing (open in new tab via Blob)
    def do_print_label():
        sel = (queue_table.selected or [None])[0]
        if not sel:
            notify('Select a flask from the queue', 'warning'); return
        try:
            pdf_bytes = build_simple_label_pdf(
                flask_no=str(sel.get('flask_no') or ''),
                tree_no=str(sel.get('tree_no') or ''),
                metal_name=str(sel.get('metal_name') or ''),
                date_iso=str(sel.get('date_iso') or date.today().isoformat()),
                required=float(_required(sel)),
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

    async def do_post(prepared: bool):
        sel = (queue_table.selected or [None])[0]
        if not sel:
            notify('Select a flask from the queue', 'warning'); return
        fid = _row_id(sel)
        if not fid:
            notify('Flask id missing', 'negative'); return

        payload = {
            'flask_id': int(fid),
            'prepared': bool(prepared),
            'scrap_planned': float(scrap_in.value or 0.0),
            'fine_24k_planned': float(fine_in.value or 0.0),
            'alloy_planned': float(alloy_in.value or 0.0),
            'pure_planned': float(pure_in.value or 0.0),
            'posted_by': 'metal_prep_ui',
        }
        try:
            await post_prep(payload)
            with client:
                ui.notify('Moved to Supply', color='positive')
                queue_table.selected = []
            await refresh_queue()
            await load_reserves()
            with client:
                flask_no_lbl.text = tree_no_lbl.text = metal_lbl.text = req_lbl.text = date_lbl.text = '—'
                scrap_in.value = fine_in.value = alloy_in.value = pure_in.value = 0.0
                preview.text = 'Total: —'
        except Exception as ex:
            notify(str(ex), 'negative')

    # wire up
    btn_print.on('click', do_print_label)
    btn_prepared.on('click',   lambda: asyncio.create_task(do_post(True)))
    btn_unprepared.on('click', lambda: asyncio.create_task(do_post(False)))
    queue_table.on('selection', lambda _e: asyncio.create_task(hydrate_right()))

    # initial load
    await refresh_queue()
    await load_reserves()
