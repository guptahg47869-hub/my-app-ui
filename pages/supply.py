# pages/supply.py  (Casting Metal In UI)
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

def safe_f(x: Any) -> float:
    try:
        return float(x or 0.0)
    except Exception:
        return 0.0

# ---------------- API ----------------
async def fetch_casting_metal_in_queue(params: Dict[str, Any]) -> List[Dict[str, Any]]:
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(f'{API_URL}/queue/casting_metal_in', params=params)
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

async def post_casting_metal_in(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Backend should now accept *total only*.

    If your backend key is NOT `casting_in_weight`, change it here to whatever your Pydantic schema expects.
    """
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.post(f'{API_URL}/supply', json=payload)
        try:
            r.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise RuntimeError(explain_http_error(e)) from e
        return r.json()

# Same label builder you already had (kept intact)
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
        c.setPageRotation(90)
    except AttributeError:
        c.saveState()
        c.translate(W, 0)
        c.rotate(90)
        W, H = H, W

    c.setLineWidth(0.6)
    c.rect(1, 1, W-2, H-2)

    y = H - M - 10
    c.setFont('Helvetica-Bold', 22)
    c.drawCentredString(W/2, y, f'{metal_name or "—"}')
    y -= 8
    c.setLineWidth(1)
    c.line(0, y, W, y); y -= 16

    c.setFont('Helvetica', 10)
    c.drawString(M, y, 'Metal Weight:'); c.drawRightString(W-M, y, f'{required:.2f}'); y -= 16

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

# ---------------- page ----------------
@ui.page('/casting-metal-in')
async def casting_metal_in_page(client: Client):

    def notify(msg: str, color='primary'):
        with client:
            ui.notify(msg, color=color)

    ui.page_title('Casting Metal In · Casting Tracker')
    ui.add_head_html("""
    <style>
      .fill-parent { width:100% !important; max-width:100% !important; }
      .btn-blue { background:#3B82F6; color:white; }
      .btn-white { background:white; color:#111827; }
      .muted { color:#6B7280; }
    </style>
    """)

    with ui.header().classes('items-center justify-between bg-gray-900 text-white'):
        ui.label('Casting Metal In').classes('text-lg font-semibold')
        with ui.row().classes('items-center gap-2'):
            ui.button('← Casting Dept', on_click=lambda: ui.navigate.to('/dept/casting')).props('flat').classes('text-white font-semibold')

    # preload metals (for filter)
    try:
        metals = await fetch_metals()
        metal_options = ['All'] + sorted([m['name'] for m in metals if 'name' in m])
    except Exception as e:
        notify(f'Failed to load metals: {e}', color='negative')
        metal_options = ['All']

    selected: Optional[Dict[str, Any]] = None

    # layout
    with ui.splitter(value=55).classes('px-6').style('width: 100%; height: calc(100vh - 140px);') as main_split:

        # LEFT: single queue + filters
        with main_split.before:
            with ui.column().classes('w-full h-full').style('display:flex; flex-direction:column;'):
                with ui.row().classes('items-end gap-3 p-4').style('flex:0 0 auto;'):
                    ui.label('Casting Metal In Queue').classes('text-base font-semibold mr-4')
                    search = ui.input('Search by Flask or Tree').props('clearable').classes('w-56')
                    date_from = ui.input('From').props('type=date').classes('w-36')
                    date_to   = ui.input('To').props('type=date').classes('w-36')
                    metal_pick = ui.select(options=metal_options, value='All', label='Metal').classes('w-48')
                    metal_pick.props('options-dense behavior=menu popup-content-style="z-index:4000"')

                    async def reset_filters():
                        search.value = ''
                        date_from.value = ''
                        date_to.value = ''
                        metal_pick.value = 'All'
                        await refresh_queue()
                    ui.button('RESET FILTERS', on_click=lambda: asyncio.create_task(reset_filters())).props('outline')

                with ui.element('div').classes('fill-parent').style('flex:1 1 auto; overflow:auto; padding:0 16px 16px 16px; width:100%;'):
                    columns = [
                        {'name': 'id',       'label': '',               'field': 'id', 'style': 'display:none', 'headerStyle': 'display:none'},
                        {'name': 'date',     'label': 'Date',           'field': 'date'},
                        {'name': 'flask_no', 'label': 'Flask No',       'field': 'flask_no'},
                        {'name': 'tree_no',  'label': 'Tree No',        'field': 'tree_no'},
                        {'name': 'metal',    'label': 'Metal',          'field': 'metal_name'},
                        {'name': 'supplied', 'label': 'Supplied Weight', 'field': 'metal_supplied_weight'},
                    ]
                    queue_table = ui.table(columns=columns, rows=[]) \
                        .props('dense flat bordered row-key="id" selection="single" hide-bottom') \
                        .classes('w-full text-sm')

        # RIGHT: editor (top) + reserves (bottom)
        with main_split.after:
            # right_split = ui.splitter(value=67).props('horizontal').style('width:100%; height:100%;')\\

            # TOP: editor
            # with right_split.before:
            with ui.card().props('flat').classes('w-full h-full p-4 overflow-auto'):
                with ui.row().classes('items-center justify-between'):
                    ui.label('Casting Metal In for Selected Flask').classes('text-base font-semibold')
                    btn_print = ui.button('PRINT LABEL').classes('btn-blue')

                with ui.grid(columns=2).classes('gap-2 mb-2'):
                    ui.label('Flask No:');    flask_no_lbl = ui.label('—')
                    ui.label('Tree No:');     tree_no_lbl  = ui.label('—')
                    ui.label('Metal:');       metal_lbl    = ui.label('—')
                    ui.label('Required Weight:'); req_lbl      = ui.label('—')
                    ui.label('Metal Supplied:');  supplied_lbl = ui.label('—').classes('font-semibold')  # bold
                    ui.label('Date:');        date_lbl     = ui.label('—')

                ui.separator()

                # show what came from Metal Prep plan (read-only)
                # prepped_lbl = ui.label('Metal Prep Planned Total: —').classes('text-sm muted')

                # the ONLY input now
                casting_in_in = ui.number('Casting In Weight (Total)', value=0.0).classes('w-full')

                transit_loss_lbl = ui.label('Transit Loss: —').classes('text-xs muted')


                # note_lbl = ui.label('Tip: This autofills from Metal Prep planned totals; edit if scale differs.').classes('text-xs muted')

                with ui.row().classes('gap-2 mt-3'):
                    btn_reset = ui.button('RESET TO SUPPLIED TOTAL').props('outline').classes('btn-white')
                    btn_post  = ui.button('POST TO CASTING').classes('btn-blue')

            # BOTTOM: reserves
            # with right_split.after:
            #     with ui.card().props('flat').classes('w-full h-full p-4 overflow-auto'):
            #         ui.label('Scrap Reserve').classes('text-base font-semibold mb-2')
            #         reserve_columns = [
            #             {'name': 'metal', 'label': 'Metal', 'field': 'metal_name'},
            #             {'name': 'qty',   'label': 'Scrap Available', 'field': 'qty_on_hand'},
            #         ]
            #         with ui.grid(columns=2).classes('gap-3 w-full'):
            #             reserve_left = ui.table(columns=reserve_columns, rows=[]) \
            #                 .props('dense flat bordered hide-bottom') \
            #                 .classes('w-full text-sm')
            #             reserve_right = ui.table(columns=reserve_columns, rows=[]) \
            #                 .props('dense flat bordered hide-bottom') \
            #                 .classes('w-full text-sm')

    # ---------------- behavior ----------------
    def update_transit_loss_display():
        if not selected:
            transit_loss_lbl.text = 'Transit Loss: —'
            return
        supplied = float(selected.get('planned_total') or compute_prep_total(selected) or 0.0)
        casting_in = safe_f(casting_in_in.value)
        loss = round(supplied - casting_in, 3)
        transit_loss_lbl.text = f"Transit Loss: {loss:.2f}g"



    def compute_prep_total(row: Dict[str, Any]) -> float:
        """
        Queue endpoint should include planned values from Metal Prep.
        Supports either:
          - top-level keys: scrap_planned, fine_24k_planned, alloy_planned, pure_planned
          - OR nested "prepped": {...}
        """
        prepped = row.get('prepped') or {}
        scrap = safe_f(prepped.get('scrap_planned', row.get('scrap_planned')))
        fine  = safe_f(prepped.get('fine_24k_planned', row.get('fine_24k_planned')))
        alloy = safe_f(prepped.get('alloy_planned', row.get('alloy_planned')))
        pure  = safe_f(prepped.get('pure_planned', row.get('pure_planned')))
        # If backend uses pure instead of fine for PT/AG, this sums correctly.
        return round(scrap + fine + alloy + pure, 3)

    async def refresh_queue():
        params: Dict[str, Any] = {}

        q = (search.value or '').strip()
        if q:
            params['q'] = q
        if date_from.value:
            params['date_from'] = date_from.value
        if date_to.value:
            params['date_to'] = date_to.value
        m = metal_pick.value
        if m and m != 'All':
            params['metal'] = m

        try:
            rows = await fetch_casting_metal_in_queue(params)
        except Exception as e:
            notify(f'Failed to fetch Casting Metal In queue: {e}', 'negative')
            rows = []

        # normalize display fields
        normalized = []
        for r in rows:
            d_iso = r.get('date') or r.get('date_iso') or ''
            item = dict(r)
            item['date_iso'] = d_iso
            item['date'] = to_ui_date(d_iso)
            # support both names from backend:
            if 'required_metal_weight' not in item:
                item['required_metal_weight'] = safe_f(item.get('metal_weight'))
            # Always compute metal supplied from Metal Prep planned totals
            item['metal_supplied_weight'] = float(item.get('planned_total') or compute_prep_total(item) or 0.0)

            normalized.append(item)

        with client:
            queue_table.rows = normalized
            queue_table.update()

    async def refresh_reserves():
        try:
            rows = await fetch_reserves()
        except Exception as e:
            notify(f'Failed to fetch reserves: {e}', 'negative')
            rows = []

        normalized = []
        for r in rows:
            name = r.get('metal_name') or r.get('metal') or r.get('name')
            qty  = r.get('qty_on_hand') or r.get('qty') or 0
            if name is None:
                continue
            normalized.append({'metal_name': name, 'qty_on_hand': safe_f(qty)})

        normalized.sort(key=lambda x: x['metal_name'])
        half = (len(normalized) + 1) // 2

        # with client:
        #     reserve_left.rows = normalized[:half]
        #     reserve_right.rows = normalized[half:]
        #     reserve_left.update()
        #     reserve_right.update()

    async def hydrate_right():
        nonlocal selected
        row = (queue_table.selected or [None])[0]
        selected = row

        with client:
            if not row:
                flask_no_lbl.text = tree_no_lbl.text = metal_lbl.text = req_lbl.text = date_lbl.text = '—'
                # prepped_lbl.text = 'Metal Prep Planned Total: —'
                supplied_lbl.text = '—'
                casting_in_in.value = 0.0
                update_transit_loss_display()
                return

            flask_no_lbl.text = f"{row.get('flask_no','—')}"
            tree_no_lbl.text  = f"{row.get('tree_no','—') or '—'}"
            metal_lbl.text    = f"{row.get('metal_name','—')}"
            req_lbl.text      = f"{safe_f(row.get('required_metal_weight')):.2f}"
            date_lbl.text     = to_ui_date(row.get('date_iso') or '')

            supplied = float(row.get('planned_total') or compute_prep_total(row) or 0.0)
            supplied_lbl.text = f"{supplied:.2f}"

            casting_in_in.value = supplied
            casting_in_in.on('change', lambda _e: update_transit_loss_display())
            update_transit_loss_display()

            # prep_total = compute_prep_total(row)
            # # prepped_lbl.text = f"Metal Prep Planned Total: {prep_total:.2f}g"
            # casting_in_in.value = prep_total

    def do_print_label():
        if not selected:
            notify('Select a flask first.', 'warning')
            return
        try:
            pdf_bytes = build_simple_label_pdf(
                flask_no=str(selected.get('flask_no') or ''),
                tree_no=str(selected.get('tree_no') or ''),
                metal_name=str(selected.get('metal_name') or ''),
                date_iso=str(selected.get('date_iso') or date.today().isoformat()),
                required=float(safe_f(selected.get('required_metal_weight'))),
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

    def reset_to_prep_total():
        if not selected:
            notify('Select a flask first.', 'warning')
            return
        casting_in_in.value = compute_prep_total(selected)

    async def submit():
        if not selected:
            notify('Select a flask first.', 'warning')
            return

        fid = selected.get('id') or selected.get('flask_id')
        if fid is None:
            notify('Missing flask id in selected row.', 'negative')
            return

        casting_in_wt = safe_f(casting_in_in.value)

        payload = {
            'flask_id': int(fid),
            'casting_in_weight': casting_in_wt,   # 🔴 change this key if your backend uses a different name
            'posted_by': 'casting_metal_in_ui',
        }

        try:
            await post_casting_metal_in(payload)
            notify(f"Flask {selected.get('flask_no')} posted to Casting", 'positive')
            with client:
                queue_table.selected = []
            await refresh_queue()
            await refresh_reserves()
            await hydrate_right()
        except Exception as ex:
            notify(str(ex), 'negative')

    # events
    btn_print.on('click', do_print_label)
    btn_reset.on('click', reset_to_prep_total)
    btn_post.on('click', lambda: asyncio.create_task(submit()))

    queue_table.on('selection', lambda _e: asyncio.create_task(hydrate_right()))

    for ctrl in (search, date_from, date_to):
        ctrl.on('change', lambda _e: asyncio.create_task(refresh_queue()))
    metal_pick.on('update:model-value', lambda _v: asyncio.create_task(refresh_queue()))

    # initial load
    await refresh_queue()
    await refresh_reserves()
    await hydrate_right()
