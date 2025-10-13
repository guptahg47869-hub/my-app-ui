# jewelry-casting-ui/pages/supply.py
from nicegui import ui, Client  # type: ignore
import httpx, os, asyncio, base64, json  # type: ignore
from datetime import datetime, date
from typing import Any, Dict, List, Optional

API_URL = os.getenv('API_URL', 'http://localhost:8000')
print('UI using API_URL =', API_URL)

# ---------------- helpers ----------------
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

# ---- API calls (merge two sources) ------------------------------------------
async def fetch_supply_queue_preparedness(q: str = '') -> List[Dict[str, Any]]:
    """New endpoint that tells us prepared vs not-prepared + prepped values."""
    params = {'q': q} if q else None
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(f'{API_URL}/supply/queue', params=params)  # prepared flag + prepped plan
        r.raise_for_status()
        return r.json()

async def fetch_supply_queue_required(q: str = '') -> List[Dict[str, Any]]:
    """Generic stage list; includes required metal (from Waxing)."""
    params = {'flask_no': q} if q else None
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(f'{API_URL}/queue/supply', params=params)  # includes metal_weight
        r.raise_for_status()
        return r.json()

async def fetch_reserves() -> List[Dict[str, Any]]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(f'{API_URL}/scrap/reserves')
        r.raise_for_status()
        return r.json()

async def fetch_metals() -> List[Dict[str, Any]]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(f'{API_URL}/metals')
        r.raise_for_status()
        return r.json()

async def post_supply(payload: Dict[str, Any]) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.post(f'{API_URL}/supply', json=payload)
        try:
            r.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise RuntimeError(explain_http_error(e)) from e
        return r.json()

# --- composition rules mirrored from backend ---
def rule_for_metal(metal_name: str) -> Dict[str, Any]:
    if not metal_name:
        return {"type": "none"}
    m = metal_name.strip().lower()
    if m in ("platinum", "silver"):
        return {"type": "pure_only"}  # alloy must be 0
    if m.startswith('10'):
        return {'type': 'gold_pct', 'pct': 0.417}
    if m.startswith('14'):
        return {'type': 'gold_pct', 'pct': 0.587}
    if m.startswith('18'):
        return {'type': 'gold_pct', 'pct': 0.752}
    return {"type": "none"}

def split_with_ratio(total: float, fine_part: int, alloy_part: int):
    denom = fine_part + alloy_part
    if denom <= 0:
        return 0.0, 0.0
    fine = total * (fine_part / denom)
    alloy = total - fine
    return round(fine, 3), round(alloy, 3)

def split_with_pct(total: float, pct: float):
    fine = total * pct
    alloy = total - fine
    return round(fine, 3), round(alloy, 3)

# Same builder used on Metal Prep: 2" x 3" portrait, skinny barcode, big date + flask
def build_simple_label_pdf(*, flask_no: str, tree_no: str, metal_name: str,
                           date_iso: str, required: float) -> bytes:
    from reportlab.pdfgen import canvas
    from reportlab.lib.units import inch, mm
    from reportlab.graphics.barcode import code128
    from io import BytesIO
    from datetime import datetime

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

    # skinny + short barcode
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

# ---------------- page ----------------
@ui.page('/supply')
async def supply_page(client: Client):
    def notify(msg: str, color='primary'):
        with client:
            ui.notify(msg, color=color)

    ui.page_title('Metal Supply · Casting Tracker')
    ui.add_head_html("""
    <style>
      .fill-parent { width:100% !important; max-width:100% !important; }
      .btn-blue { background:#3B82F6; color:white; }
      .btn-white { background:white; color:#111827; }
      .tiny-green { color:#10B981; font-size:10px; margin-left:6px; }
    </style>
    """)

    with ui.header().classes('items-center justify-between bg-gray-900 text-white'):
        ui.label('Metal Supply').classes('text-lg font-semibold')
        with ui.row().classes('items-center gap-2'):
            ui.button('METAL PREP', on_click=lambda: ui.navigate.to('/metal-prep')).props('flat').classes('text-white')
            ui.button('RECONCILIATION', on_click=lambda: ui.navigate.to('/reconciliation')).props('flat').classes('text-white')
            ui.button(icon='home', on_click=lambda: ui.navigate.to('/')).props('flat round').classes('text-white')

    # preload metals
    try:
        metals = await fetch_metals()
        metal_options = ['All'] + sorted([m['name'] for m in metals if 'name' in m])
    except Exception as e:
        notify(f'Failed to load metals: {e}', color='negative')
        metal_options = ['All']

    # ----------- page state -----------
    selected: Dict[str, Any] | None = None
    required_by_flask: Dict[int, float] = {}

    fine_overridden = False
    alloy_overridden = False
    pure_overridden = False

    # ---- layout ----
    with ui.splitter(value=55).classes('px-6').style('width: 100%; height: calc(100vh - 140px);') as main_split:

        # LEFT: two queues (not prepared / prepared)
        with main_split.before:
            with ui.card().classes('w-full h-full p-0'):
                left_split = ui.splitter(value=50).props('horizontal').style('width:100%; height:100%')

                # =============== TOP: NOT PREPARED ======================
                with left_split.before:
                    with ui.column().classes('w-full h-full').style('display:flex; flex-direction:column;'):
                        today_iso = date.today().isoformat()
                        with ui.row().classes('items-end gap-3 p-4').style('flex:0 0 auto;'):
                            ui.label('Metal Supply (Not Prepared)').classes('text-base font-semibold mr-4')
                            np_search = ui.input('Search by Flask or Tree').props('clearable').classes('w-56')
                            np_date_from = ui.input('From').props('type=date').classes('w-36')
                            np_date_to   = ui.input('To').props('type=date').classes('w-36')
                            np_metal_pick = ui.select(options=metal_options, value='All', label='Metal').classes('w-48')
                            np_metal_pick.props('options-dense behavior=menu popup-content-style="z-index:4000"')

                            async def np_reset():
                                np_search.value = ''
                                np_date_from.value = ''
                                np_date_to.value = ''
                                np_metal_pick.value = 'All'
                                await refresh_left_tables()
                            ui.button('RESET FILTERS', on_click=lambda: asyncio.create_task(np_reset())).props('outline')

                        with ui.element('div').classes('fill-parent').style('flex:1 1 auto; overflow:auto; padding:0 16px 8px 16px; width:100%;'):
                            np_columns = [
                                {'name': 'date',       'label': 'Date',      'field': 'date'},
                                {'name': 'flask_no',   'label': 'Flask No',  'field': 'flask_no'},
                                {'name': 'tree_no',    'label': 'Tree No',   'field': 'tree_no'},
                                {'name': 'metal_name', 'label': 'Metal',     'field': 'metal_name'},
                                {'name': 'req',        'label': 'Req. Metal','field': 'metal_weight'},
                            ]
                            np_table = ui.table(columns=np_columns, rows=[]) \
                                       .props('dense flat bordered row-key="id" selection="single" hide-bottom') \
                                       .classes('w-full text-sm')

                # =============== BOTTOM: PREPARED ========================
                with left_split.after:
                    with ui.column().classes('w-full h-full').style('display:flex; flex-direction:column;'):
                        with ui.row().classes('items-end gap-3 p-4').style('flex:0 0 auto;'):
                            ui.label('Metal Supply (Prepared)').classes('text-base font-semibold mr-4')
                            p_search = ui.input('Search by Flask or Tree').props('clearable').classes('w-56')
                            p_date_from = ui.input('From').props('type=date').classes('w-36')
                            p_date_to   = ui.input('To').props('type=date').classes('w-36')
                            p_metal_pick = ui.select(options=metal_options, value='All', label='Metal').classes('w-48')
                            p_metal_pick.props('options-dense behavior=menu popup-content-style="z-index:4000"')

                            async def p_reset():
                                p_search.value = ''
                                p_date_from.value = ''
                                p_date_to.value = ''
                                p_metal_pick.value = 'All'
                                await refresh_left_tables()
                            ui.button('RESET FILTERS', on_click=lambda: asyncio.create_task(p_reset())).props('outline')

                        with ui.element('div').classes('fill-parent').style('flex:1 1 auto; overflow:auto; padding:0 16px 16px 16px; width:100%;'):
                            p_columns = [
                                {'name': 'date',       'label': 'Date',      'field': 'date'},
                                {'name': 'flask_no',   'label': 'Flask No',  'field': 'flask_no'},
                                {'name': 'tree_no',    'label': 'Tree No',   'field': 'tree_no'},
                                {'name': 'metal_name', 'label': 'Metal',     'field': 'metal_name'},
                                {'name': 'req',        'label': 'Req. Metal','field': 'metal_weight'},
                            ]
                            p_table = ui.table(columns=p_columns, rows=[]) \
                                       .props('dense flat bordered row-key="id" selection="single" hide-bottom') \
                                       .classes('w-full text-sm')

        # RIGHT: editor (top) + reserves (bottom)
        with main_split.after:
            right_split = ui.splitter(value=67).props('horizontal').style('width:100%; height:100%;')

            # --------- TOP: Editor ---------
            with right_split.before:
                with ui.card().props('flat').classes('w-full h-full p-4 overflow-auto'):
                    # title row with print button (top-right)
                    with ui.row().classes('items-center justify-between'):
                        title_lbl = ui.label('Supply for Selected Flask').classes('text-base font-semibold')
                        def do_print():
                            if not selected:
                                notify('Select a flask first.', 'warning'); return

                            fid = int(selected.get('id'))
                            req = float(required_by_flask.get(fid, 0.0))
                            metal_name = selected.get('metal_name') or ''
                            tree_no = selected.get('tree_no') or ''
                            flask_no = selected.get('flask_no') or ''
                            date_iso = selected.get('date_iso') or ''

                            try:
                                # Build the same label used on Metal Prep
                                pdf_bytes = build_simple_label_pdf(
                                    flask_no=flask_no,
                                    tree_no=tree_no,
                                    metal_name=metal_name,
                                    date_iso=date_iso,
                                    required=req,
                                )
                                b64 = base64.b64encode(pdf_bytes).decode('ascii')
                                b64_json = json.dumps(b64)

                                # Open via Blob + anchor click (same de-dupe guard as Metal Prep)
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
                        ui.button('PRINT LABEL', on_click=do_print).classes('btn-blue')

                    with ui.grid(columns=2).classes('gap-2 mb-2'):
                        ui.label('Flask No:');      flask_no_lbl = ui.label('—')
                        ui.label('Tree No:');       tree_no_lbl  = ui.label('—')
                        ui.label('Metal:');         metal_lbl    = ui.label('—')
                        ui.label('Required Wt:');   req_lbl      = ui.label('—')
                        ui.label('Date:');          date_lbl     = ui.label('—')

                    scrap_in = ui.number('Scrap', value=0.0).classes('w-full')

                    gold_box = ui.column().classes('w-full')
                    with gold_box:
                        with ui.row().classes('items-end gap-2 w-full'):
                            fine_in  = ui.number('24K (fine)', value=0.0).classes('w-full').style('flex:1')
                            fine_badge = ui.label('✔ prepped').classes('tiny-green'); fine_badge.visible = False
                        with ui.row().classes('items-end gap-2 w-full'):
                            alloy_in = ui.number('Alloy', value=0.0).classes('w-full').style('flex:1')
                            alloy_badge = ui.label('✔ prepped').classes('tiny-green'); alloy_badge.visible = False

                    pure_box = ui.column().classes('w-full')
                    with pure_box:
                        with ui.row().classes('items-end gap-2 w-full'):
                            pure_in = ui.number('Pure Metal', value=0.0).classes('w-full').style('flex:1')
                            pure_badge = ui.label('✔ prepped').classes('tiny-green'); pure_badge.visible = False
                    pure_box.visible = False

                    def show_gold():
                        gold_box.visible = True
                        pure_box.visible = False
                        gold_box.update(); pure_box.update()

                    def show_pure():
                        gold_box.visible = False
                        pure_box.visible = True
                        gold_box.update(); pure_box.update()

                    def reset_overrides():
                        nonlocal fine_overridden, alloy_overridden, pure_overridden
                        fine_overridden = False
                        alloy_overridden = False
                        pure_overridden = False

                    def current_required_and_rule():
                        if not selected:
                            return 0.0, {"type": "none"}
                        fid = int(selected.get('id'))
                        required_wt = float(required_by_flask.get(fid, 0.0))
                        rule = rule_for_metal(selected.get('metal_name') or '')
                        return required_wt, rule
                    
                    def update_total_preview():
                        if not selected:
                            with client:
                                preview_lbl.text = '—'
                            return

                        required_wt, rule = current_required_and_rule()
                        scrap = float(scrap_in.value or 0.0)

                        if rule['type'] == 'pure_only':
                            total = scrap + float(pure_in.value or 0.0)
                        elif rule['type'] == 'gold_pct':
                            total = scrap + float(fine_in.value or 0.0) + float(alloy_in.value or 0.0)
                        else:
                            total = scrap

                        label = 'Prepared Wt' if bool(selected.get('prepared')) else 'Supplied Wt'
                        with client:
                            preview_lbl.text = f'{label}: {total:.1f} (Req: {required_wt:.1f})'


                    def auto_fill_from_required(initial: bool = False):
                        required_wt, rule = current_required_and_rule()
                        scrap_val = float(scrap_in.value or 0.0)
                        remain = max(required_wt - scrap_val, 0.0)

                            # If we are hydrating a prepared flask selection, do NOT overwrite the prepped values.
                        if initial and selected and selected.get('prepared'):
                            update_total_preview()
                            return

                        # if selected and selected.get('prepared'):
                        #     return

                        if rule["type"] == "pure_only":
                            if not pure_overridden:
                                pure_in.value = round(remain, 3)
                        elif rule["type"] == "gold_pct":
                            if not (fine_overridden or alloy_overridden):
                                # f, a = rule["fine"], rule["alloy"]
                                fval, aval = split_with_pct(remain, rule["pct"])
                                fine_in.value = fval
                                alloy_in.value = aval
                        else:
                            if not pure_overridden and pure_box.visible:
                                pure_in.value = round(remain, 3)
                            if gold_box.visible and not (fine_overridden or alloy_overridden):
                                fine_in.value = 0.0
                                alloy_in.value = 0.0

                        update_total_preview()

                    async def sync_selection_from_table():
                        nonlocal selected
                        row = (np_table.selected or [None])[0] or (p_table.selected or [None])[0]
                        selected = row

                        reset_overrides()
                        fine_badge.visible = alloy_badge.visible = pure_badge.visible = False

                        with client:
                            if not row:
                                flask_no_lbl.text = tree_no_lbl.text = metal_lbl.text = req_lbl.text = date_lbl.text = '—'
                                scrap_in.value = 0.0
                                fine_in.value = alloy_in.value = pure_in.value = 0.0
                                show_gold()
                                # update header/button too
                                _sync_header_and_button()
                                return

                            flask_no_lbl.text = f"{row.get('flask_no','—')}"
                            tree_no_lbl.text  = f"{row.get('tree_no','—') or '—'}"
                            metal_lbl.text    = f"{row.get('metal_name','—')}"
                            fid = int(row['id'])
                            req = float(required_by_flask.get(fid, 0.0))
                            req_lbl.text      = f"{req:.1f}" if req else '—'
                            date_lbl.text     = to_ui_date(row.get('date_iso') or '')

                            rule = rule_for_metal(row.get('metal_name') or '')
                            scrap_in.value = 0.0

                            if row.get('prepared'):
                                prepped = row.get('prepped') or {}
                                if rule["type"] == "pure_only":
                                    show_pure()
                                    pure_in.value = float(prepped.get('pure_planned') or 0.0)
                                    pure_badge.visible = True
                                else:
                                    show_gold()
                                    fine_in.value  = float(prepped.get('fine_24k_planned') or 0.0)
                                    alloy_in.value = float(prepped.get('alloy_planned') or 0.0)
                                    fine_badge.visible = alloy_badge.visible = True
                                scrap_in.value = float(prepped.get('scrap_planned') or 0.0)
                            else:
                                if rule["type"] == "pure_only":
                                    show_pure()
                                    pure_in.value = 0.0
                                else:
                                    show_gold()
                                    fine_in.value = alloy_in.value = 0.0

                        auto_fill_from_required(initial=True)
                        _sync_header_and_button()   # <-- keep header & button in sync

                    def on_scrap_change(_e):
                        auto_fill_from_required(initial=False)  # recalc for both prepared & not-prepared

                    def on_fine_change(_e):
                        nonlocal fine_overridden
                        fine_overridden = True
                        update_total_preview()

                    def on_alloy_change(_e):
                        nonlocal alloy_overridden
                        alloy_overridden = True
                        update_total_preview()

                    def on_pure_change(_e):
                        nonlocal pure_overridden
                        pure_overridden = True
                        update_total_preview()

                    scrap_in.on('change', on_scrap_change)
                    fine_in.on('change',  on_fine_change)
                    alloy_in.on('change', on_alloy_change)
                    pure_in.on('change',  on_pure_change)

                    # (Optional: live typing feedback)
                    # scrap_in.on('input', on_scrap_change)
                    # fine_in.on('input',  on_fine_change)
                    # alloy_in.on('input', on_alloy_change)
                    # pure_in.on('input',  on_pure_change)

                    def recompute_defaults():
                        reset_overrides()
                        auto_fill_from_required(initial=False)

                    async def submit():
                        if not selected:
                            notify('Select a flask first.', 'warning'); return
                        fid = int(selected['id'])
                        rule = rule_for_metal(selected.get('metal_name') or '')
                        scrap = float(scrap_in.value or 0.0)
                        if rule["type"] == "pure_only":
                            payload = {
                                'flask_id': fid,
                                'scrap_supplied': scrap,
                                'fine_24k_supplied': float(pure_in.value or 0.0),
                                'alloy_supplied': 0.0,
                                'posted_by': 'supply_ui',
                            }
                        else:
                            payload = {
                                'flask_id': fid,
                                'scrap_supplied': scrap,
                                'fine_24k_supplied': float(fine_in.value or 0.0),
                                'alloy_supplied': float(alloy_in.value or 0.0),
                                'posted_by': 'supply_ui',
                            }
                        try:
                            await post_supply(payload)
                            await refresh_reserve()
                            notify(f"Flask {selected.get('flask_no')} posted to Casting", 'positive')
                            await refresh_left_tables()
                        except Exception as ex:
                            notify(str(ex), 'negative')

                    preview_lbl = ui.label('—').classes('text-sm text-gray-700 mt-1')

                    with ui.row().classes('gap-2 mt-2'):
                        ui.button('Recalculate', on_click=recompute_defaults).classes('btn-white').props('outline')
                        submit_btn = ui.button('Supply', on_click=lambda: asyncio.create_task(submit())).classes('btn-blue')

                    # ---- NEW: keep title + button label in sync with 'prepared' ----
                    def _sync_header_and_button():
                        prepared = bool(selected and selected.get('prepared'))
                        title_lbl.text = 'Confirm for Selected Flask' if prepared else 'Supply for Selected Flask'
                        submit_btn.text = 'Confirm' if prepared else 'Supply'
                        with client:
                            title_lbl.update(); submit_btn.update()

                        update_total_preview()

            # --------- BOTTOM: Reserves ---------
            with right_split.after:
                with ui.card().props('flat').classes('w-full h-full p-4 overflow-auto'):
                    ui.label('Scrap Reserve').classes('text-base font-semibold mb-2')
                    reserve_columns = [
                        {'name': 'metal', 'label': 'Metal', 'field': 'metal_name'},
                        {'name': 'qty',   'label': 'Scrap Available', 'field': 'qty_on_hand'},
                    ]
                    # two tables side-by-side
                    with ui.grid(columns=2).classes('gap-3 w-full'):
                        reserve_table_left = ui.table(columns=reserve_columns, rows=[]) \
                            .props('dense flat bordered hide-bottom') \
                            .classes('w-full text-sm')
                        reserve_table_right = ui.table(columns=reserve_columns, rows=[]) \
                            .props('dense flat bordered hide-bottom') \
                            .classes('w-full text-sm')

    # ---------- data plumbing ----------
    def _apply_filters(rows: List[Dict[str, Any]],
                       date_from_in: ui.input, date_to_in: ui.input,
                       metal_pick_in: ui.select, search_in: ui.input) -> List[Dict[str, Any]]:
        f_date = parse_iso_date(date_from_in.value)
        t_date = parse_iso_date(date_to_in.value)
        pick   = (metal_pick_in.value or 'All')
        q = (search_in.value or '').strip().lower()

        out: List[Dict[str, Any]] = []
        for r in rows:
            d_iso = r.get('date_iso') or r.get('date') or ''
            d = parse_iso_date(d_iso)
            if not d:
                continue
            if f_date and d < f_date: continue
            if t_date and d > t_date: continue
            if pick != 'All' and r.get('metal_name') != pick: continue
            if q:
                hay = f"{r.get('flask_no','')} {r.get('tree_no','')}".lower()
                if q not in hay: continue
            rr = dict(r)
            rr['_sort_ord'] = -d.toordinal()
            rr['_sort_metal'] = rr.get('metal_name') or ''
            rr['date'] = to_ui_date(d_iso)
            out.append(rr)

        out.sort(key=lambda x: (x['_sort_ord'], x['_sort_metal'], x.get('flask_no','')))
        for rr in out:
            rr.pop('_sort_ord', None); rr.pop('_sort_metal', None)
        return out

    async def refresh_left_tables():
        try:
            rows_preparedness = await fetch_supply_queue_preparedness()
            rows_required     = await fetch_supply_queue_required()
        except Exception as e:
            notify(f'Failed to fetch supply queues: {e}', 'negative')
            rows_preparedness, rows_required = [], []

        required_by_flask.clear()
        req_map: Dict[int, float] = {}
        for r in rows_required:
            fid = r.get('id')
            if fid is None: continue
            try:
                req_map[int(fid)] = float(r.get('metal_weight') or 0.0)
            except Exception:
                req_map[int(fid)] = 0.0

        merged: List[Dict[str, Any]] = []
        for r in rows_preparedness:
            fid = int(r.get('id'))
            d_iso = r.get('date') or ''
            item = dict(r)
            item['date_iso'] = d_iso
            item['metal_weight'] = float(req_map.get(fid, 0.0))
            required_by_flask[fid] = item['metal_weight']
            item['date'] = to_ui_date(d_iso)
            merged.append(item)

        not_prepped = [m for m in merged if not m.get('prepared')]
        prepped     = [m for m in merged if     m.get('prepared')]

        with client:
            np_table.rows = _apply_filters(not_prepped, np_date_from, np_date_to, np_metal_pick, np_search)
            p_table.rows  = _apply_filters(prepped,     p_date_from,  p_date_to,  p_metal_pick,  p_search)

            new_sel = None
            if np_table.rows:
                new_sel = np_table.rows[0]
                np_table.selected = [new_sel]; p_table.selected = []
            elif p_table.rows:
                new_sel = p_table.rows[0]
                p_table.selected = [new_sel]; np_table.selected = []
            else:
                np_table.selected = []; p_table.selected = []

            np_table.update(); p_table.update()
        await asyncio.create_task(sync_selection_from_table())

    async def refresh_reserve():
        try:
            rows = await fetch_reserves()
        except Exception as e:
            notify(f'Failed to fetch reserves: {e}', 'negative')
            rows = []
        normalized = []
        for r in rows:
            name = r.get('metal_name') or r.get('metal') or r.get('name')
            qty  = r.get('qty_on_hand') or r.get('qty') or 0
            if name is None: continue
            try: qty = float(qty)
            except Exception: qty = 0.0
            normalized.append({'metal_name': name, 'qty_on_hand': qty})
        normalized.sort(key=lambda x: x['metal_name'])
        with client:
            # split evenly into two columns
            half = (len(normalized) + 1) // 2
            reserve_table_left.rows = normalized[:half]
            reserve_table_right.rows = normalized[half:]
            reserve_table_left.update()
            reserve_table_right.update()

    # hook up events
    for w in (np_search, np_date_from, np_date_to):
        w.on('change', lambda _e: asyncio.create_task(refresh_left_tables()))
    np_metal_pick.on('update:model-value', lambda _v: asyncio.create_task(refresh_left_tables()))

    for w in (p_search, p_date_from, p_date_to):
        w.on('change', lambda _e: asyncio.create_task(refresh_left_tables()))
    p_metal_pick.on('update:model-value', lambda _v: asyncio.create_task(refresh_left_tables()))

    def _on_np_selection(_e=None):
        if np_table.selected:
            with client:
                p_table.selected = []
                p_table.update()
        asyncio.create_task(sync_selection_from_table())

    def _on_p_selection(_e=None):
        if p_table.selected:
            with client:
                np_table.selected = []
                np_table.update()
        asyncio.create_task(sync_selection_from_table())

    np_table.on('selection', _on_np_selection)
    p_table.on('selection',  _on_p_selection)

    # initial load
    await asyncio.create_task(refresh_left_tables())
    await asyncio.create_task(refresh_reserve())
