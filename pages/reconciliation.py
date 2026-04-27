from nicegui import ui, Client  # type: ignore
import httpx, os, asyncio  # type: ignore
from datetime import date, datetime
from typing import Any, Dict, List, Optional

API_URL = os.getenv('API_URL', 'http://localhost:8000')
print('UI using API_URL =', API_URL)

# ---------- helpers ----------
def to_ui_date(iso: str) -> str:
    try:
        return datetime.strptime(iso, '%Y-%m-%d').strftime('%m-%d-%y')
    except Exception:
        return iso

def parse_iso_date(s: str) -> Optional[date]:
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

# ---------- API ----------
async def fetch_metals() -> List[Dict[str, Any]]:
    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.get(f'{API_URL}/metals')
        r.raise_for_status()
        return r.json()

async def fetch_recon_queue(params: Dict[str, Any]) -> List[Dict[str, Any]]:
    # drop blank / None / "All" so FastAPI sees them as truly omitted
    clean = {k: v for k, v in params.items() if v not in (None, '', 'All')}
    async with httpx.AsyncClient(timeout=15.0) as c:
        r = await c.get(f'{API_URL}/queue/reconciliation', params=clean)
        r.raise_for_status()
        return r.json()

async def get_recon_detail(flask_id: int) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.get(f'{API_URL}/reconciliation/{flask_id}')
        r.raise_for_status()
        return r.json()

async def post_recon_confirm(payload: Dict[str, Any]) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=20.0) as c:
        r = await c.post(f'{API_URL}/reconciliation/confirm', json=payload)
        try:
            r.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise RuntimeError(explain_http_error(e)) from e
        return r.json()

# ---------- PAGE ----------
@ui.page('/reconciliation')
async def reconciliation_page(client: Client):
    def notify(msg: str, color='primary'):
        with client:
            ui.notify(msg, color=color)

    # ---------------- Weight History Dialog (like Flask Search) ----------------
    with ui.dialog() as history_dialog:
        with ui.card().classes('w-[720px] max-w-[92vw] p-6 relative'):
            with ui.row().classes('w-full items-center justify-between'):
                history_title = ui.label('').classes('text-xl font-semibold')
                ui.button('✕', on_click=history_dialog.close).props('flat').classes('text-gray-600 text-lg')
            ui.separator().classes('my-4')
            history_kv = ui.column().classes('gap-2')

    def _fmt_num(v):
        if v is None:
            return '—'
        try:
            return f'{float(v):.2f}'
        except Exception:
            return str(v)

    def _kv(label: str, value: str, *, red: bool = False, bold: bool = False):
        left_cls = 'text-gray-600'
        right_cls = 'font-semibold' if bold else ''
        if red:
            left_cls += ' text-red-600'
            right_cls += ' text-red-600'
        with ui.row().classes('w-full justify-between'):
            ui.label(label).classes(left_cls)
            ui.label(value).classes(right_cls)


    ui.page_title('Reconciliation · Casting Tracker')
    ui.add_head_html('''
    <style>
    .fill-parent{width:100%!important;max-width:100%!important}
    .num-shadow{text-shadow:0 2px 8px rgba(0,0,0,.15)}

    /* compact “tabbed” rows */
    .kv-grid{row-gap:.25rem; column-gap:.75rem}
    .tri{display:grid; grid-template-columns:repeat(3,minmax(0,2fr)); gap:.5rem}

    /* each cell: equal width, centered, a little padding */
    .tri-cell{
        padding:.25rem .35rem;
        border-radius:.375rem;
        text-align:center;
        white-space:nowrap;
    }
    </style>
    ''')

    with ui.header().classes('items-center justify-between bg-gray-900 text-white'):
        ui.label('Reconciliation Queue').classes('text-lg font-semibold')
        with ui.row().classes('items-center gap-2'):
            # ui.button('METAL PREP', on_click=lambda: ui.navigate.to('/metal-prep')).props('flat').classes('text-white')
            # ui.button('METAL SUPPLY', on_click=lambda: ui.navigate.to('/supply')).props('flat').classes('text-white')
            # ui.button(icon='home', on_click=lambda: ui.navigate.to('/')).props('flat round').classes('text-white')
            ui.button('← Inventory', on_click=lambda: ui.navigate.to('/dept/inventory')).props('flat').classes('text-white font-semibold')

    # preload metals for filter
    try:
        metals = await fetch_metals()
        metal_options = ['All'] + sorted([m['name'] for m in metals if 'name' in m])
    except Exception:
        metal_options = ['All']

    selected: Dict[str, Any] | None = None
    # current_supplied: float = 0.0

    current_supplied_mp: float = 0.0
    current_casting_in: float = 0.0
    current_casting_out: float = 0.0


    with ui.splitter(value=60).classes('px-6').style('width:100%; height: calc(100vh - 140px);') as main_split:

        # LEFT: queue + filters
        with main_split.before:
            with ui.card().classes('w-full h-full p-0'):
                with ui.column().classes('w-full h-full').style('display:flex; flex-direction:column;'):

                    today_iso = date.today().isoformat()

                    with ui.row().classes('items-end gap-3 p-4').style('flex:0 0 auto;'):
                        ui.label('Flasks in Reconciliation').classes('text-base font-semibold mr-4')
                        q_search = ui.input('Search Flask or Tree').props('clearable').classes('w-56')
                        d_from = ui.input('From').props('type=date').classes('w-36')
                        d_to   = ui.input('To').props('type=date').classes('w-36')
                        metal_filter = ui.select(options=metal_options, value='All', label='Metal').classes('w-48')
                        metal_filter.props('options-dense behavior=menu popup-content-style="z-index:4000"')

                        async def reset_filters():
                            d_from.value = ''; d_to.value = ''
                            q_search.value = ''; metal_filter.value = 'All'
                            await refresh_table()
                            notify('Filters reset.', 'positive')

                        ui.button('RESET FILTERS', on_click=lambda: asyncio.create_task(reset_filters())).props('outline')

                    with ui.element('div').classes('fill-parent').style(
                        'flex:1 1 auto; overflow:auto; padding:0 16px 16px 16px; width:100%; max-width:100%;'
                    ):
                        columns = [
                            {'name': 'date', 'label': 'Date', 'field': 'date'},
                            {'name': 'flask_no', 'label': 'Flask No', 'field': 'flask_no'},
                            {'name': 'tree_no', 'label': 'Tree No', 'field': 'tree_no'},
                            {'name': 'metal_name', 'label': 'Metal', 'field': 'metal_name'},
                            # {'name': 'supplied', 'label': 'Supplied', 'field': 'supplied_weight'},
                            # {'name': 'before', 'label': 'Before', 'field': 'before_cut_weight'},
                            # {'name': 'cast', 'label': 'After Cast', 'field': 'after_cast_weight'},
                            # {'name': 'scrap', 'label': 'After Scrap', 'field': 'after_scrap_weight'},
                            # {'name': 'loss', 'label': 'Loss', 'field': 'loss_total'},
                            {'name': 'supplied_mp', 'label': 'Supplied Weight', 'field': 'metal_supplied_weight'},
                            {'name': 'casting_out', 'label': 'Casting Out Weight', 'field': 'casting_out_weight'},
                            {'name': 'cut_in', 'label': 'Cutting In Weight', 'field': 'before_cut_weight'},
                            {'name': 'cut_usable', 'label': 'Cutting Out - Consumable', 'field': 'after_cast_weight'},
                            {'name': 'cut_scrap', 'label': 'Cutting Out - Scrap', 'field': 'after_scrap_weight'},
                            {'name': 'loss_total', 'label': 'Total Loss So Far', 'field': 'loss_total'},
                        ]
                        recon_table = ui.table(columns=columns, rows=[]) \
                                      .props('dense flat bordered row-key="flask_id" selection="single" hide-bottom') \
                                      .classes('w-full text-sm')

        # RIGHT: details + confirm
        with main_split.after:
            # with ui.card().classes('w-full h-full p-6'):
            with ui.card().props('flat').classes('w-full h-full p-4 overflow-auto'):
                ui.label('Reconciliation Details').classes('text-base font-semibold mb-2')

                # with ui.grid(columns=2).classes('gap-1 mb-1'):
                with ui.grid(columns=2).classes('kv-grid mb-1'):

                    ui.label('Flask No:').classes('text-sm font-semibold'); flask_lbl = ui.label('—')
                    ui.label('Tree No:').classes('text-sm font-semibold');  tree_lbl = ui.label('—')
                    ui.label('Metal:').classes('text-sm font-semibold');    metal_lbl = ui.label('—')
                    ui.label('Date:').classes('text-sm font-semibold');     date_lbl = ui.label('—')

                ui.separator().classes('my-2')

                ui.button('[ See weight & loss details ]', on_click=lambda: open_weight_history_dialog()) \
                    .props('flat dense') \
                    .classes('mt-1 mb-3 text-xs text-gray-500 hover:text-gray-700')

                ui.separator().classes('my-2')

                # ui.label('Supplied:'); supplied_lbl = ui.label('—')
                # supplied_lbl = ui.label('Supplied: —')
                # supplied_lbl = ui.html('<b>Supplied</b>: —')

                # with ui.grid(columns=2).classes('kv-grid mb-1'):
                #     ui.label('Supplied:').classes('text-sm font-semibold'); supplied_lbl = ui.label('—')

                # ui.separator().classes('my-2')

                # ui.label('Casting').classes('text-sm font-semibold')

                # with ui.grid(columns=2).classes('kv-grid mb-1'):
                #     ui.label('Casting In:').classes('text-sm font-semibold'); casting_in_lbl = ui.label('—')
                    
                # with ui.grid(columns=2).classes('kv-grid mb-1'):
                #     ui.label('Casting Out:').classes('text-sm font-semibold'); casting_out_lbl = ui.label('—')

                # with ui.grid(columns=2).classes('kv-grid mb-1'):
                #     ui.label('Casting Loss:').classes('text-sm font-semibold text-negative'); casting_loss_lbl = ui.label('—').classes('text-negative')


                # with ui.grid(columns=3).classes('tri mb-2'):
                #     casting_in_lbl   = ui.html('<b>In</b>: —').classes('tri-cell')
                #     casting_out_lbl  = ui.html('<b>Out</b>: —').classes('tri-cell')
                #     casting_loss_lbl = ui.html('<b>Loss</b>: —').classes('tri-cell text-negative')

                # ui.separator()
                ui.label('Cutting').classes('text-sm font-semibold')

                before_cut = ui.number('Before Cutting Weight', value=0.0).props('step=0.001').classes('w-full')
                after_cast = ui.number('After Cut: Consumable Weight', value=0.0).props('step=0.001').classes('w-full')
                after_scrap = ui.number('After Cut: Scrap Weight', value=0.0).props('step=0.001').classes('w-full')

                # preview_i    = ui.label('(i) Metal Loss in Casting: —').classes('text-gray-600')
                # preview_ii   = ui.label('(ii) Metal Loss in Cutting: —').classes('text-gray-600')
                # preview_total= ui.label('Total Scrap Loss: —').classes('text-gray-800 font-semibold')

                cutting_loss_lbl = ui.label('Cutting Loss: —').classes('text-negative')

                # ui.label('Transit Loss').classes('text-sm font-semibold')

                # with ui.grid(columns=3).classes('gap-1 mt-1 mb-1'):
                #     transit_mc_lbl    = ui.label('Metal Prep → Casting: —').classes('text-negative')
                #     transit_cc_lbl    = ui.label('Casting → Cutting: —').classes('text-negative')
                #     transit_total_lbl = ui.label('Total: —').classes('text-negative')

                total_loss_lbl   = ui.label('Total Loss: —').classes('text-negative font-bold')
                # total_loss_btn = ui.button('Total Loss: —', on_click=lambda: open_weight_history_dialog()) \
                #     .props('flat dense') \
                #     .classes('text-negative font-bold justify-start p-0')

                def open_weight_history_dialog():
                    # only open if a row is selected
                    sel = (recon_table.selected or [None])[0]
                    if not sel:
                        notify('Select a flask first.', 'warning')
                        return

                    # read current values (final edits included)
                    A = float(before_cut.value or 0.0)   # cutting in
                    C = float(after_cast.value or 0.0)   # usable
                    B = float(after_scrap.value or 0.0)  # scrap

                    supplied = float(current_supplied_mp or 0.0)
                    cin = float(current_casting_in or 0.0)
                    cout = float(current_casting_out or 0.0)

                    casting_loss = cin - cout
                    cutting_loss = A - (B + C)

                    transit_mc = supplied - cin
                    transit_cc = cout - A
                    transit_total = transit_mc + transit_cc

                    total_loss = casting_loss + cutting_loss + transit_total

                    # title (match flask_search style: date • flask • metal)
                    # dt = date_lbl.text or '—'
                    dt_full = date_lbl.text or '—'
                    dt_mmdd = dt_full[:5] if isinstance(dt_full, str) and len(dt_full) >= 5 else dt_full
                    history_title.text = f"{dt_mmdd} • Flask {flask_lbl.text} • {metal_lbl.text}"

                    history_kv.clear()
                    with history_kv:
                        # 1) Supplied weight
                        _kv('Supplied weight', _fmt_num(supplied), bold=True)
                        ui.separator().classes('my-3')

                        # 3-6) Casting in/out/loss
                        _kv('Casting in weight', _fmt_num(cin))
                        _kv('Casting out weight', _fmt_num(cout))
                        _kv('Casting loss', _fmt_num(casting_loss), red=True, bold=True)
                        ui.separator().classes('my-3')

                        # 7-11) Cutting in/out/loss
                        _kv('Cutting in weight', _fmt_num(A))
                        _kv('Cutting out weight (consumable)', _fmt_num(C))
                        _kv('Cutting out weight (scrap)', _fmt_num(B))
                        _kv('Cutting loss', _fmt_num(cutting_loss), red=True, bold=True)
                        ui.separator().classes('my-3')

                        # 12-15) Transit legs + total transit
                        _kv('Transit loss (Metal Prep → Casting)', _fmt_num(transit_mc))
                        _kv('Transit loss (Casting → Cutting)', _fmt_num(transit_cc))
                        _kv('Total transit loss', _fmt_num(transit_total), red=True, bold=True)
                        ui.separator().classes('my-3')

                        # 16) Total loss
                        _kv('Total loss', _fmt_num(total_loss), red=True, bold=True)

                    history_dialog.open()



                def update_preview():
                    try:
                        # A = float(before_cut.value or 0.0)
                        # C = float(after_cast.value or 0.0)
                        # B = float(after_scrap.value or 0.0)
                        # supplied = float(current_supplied or 0.0)

                        # part_i  = supplied - A
                        # part_ii = A - (B + C)
                        # total   = supplied - (B + C)

                        # preview_i.text     = f'(i) Metal Loss in Casting: {part_i:.2f}'
                        # preview_ii.text    = f'(ii) Metal Loss in Cutting: {part_ii:.2f}'
                        # preview_total.text = f'Total Scrap Loss: {total:.2f}'

                        # preview_total.classes(remove='text-negative')
                        # if total < 0:
                        #     preview_total.classes(add='text-negative')
                        A = float(before_cut.value or 0.0)      # cutting in
                        C = float(after_cast.value or 0.0)      # usable
                        B = float(after_scrap.value or 0.0)     # scrap

                        casting_loss = current_casting_in - current_casting_out

                        transit_mc = current_supplied_mp - current_casting_in        # metal prep → casting in
                        transit_cc = current_casting_out - A                         # casting out → cutting in
                        transit_total = transit_mc + transit_cc

                        cutting_loss = A - (B + C)
                        total_loss = casting_loss + transit_total + cutting_loss

                        # casting_loss_lbl.text = f'{casting_loss:.2f}'
                        cutting_loss_lbl.text = f'Cutting Loss: {cutting_loss:.2f}'

                        # transit_mc_lbl.text    = f'Metal Prep → Casting: {transit_mc:.2f}'
                        # transit_cc_lbl.text    = f'Casting → Cutting: {transit_cc:.2f}'
                        # transit_total_lbl.text = f'Total Transit Loss: {transit_total:.2f}'

                        total_loss_lbl.text   = f'Total Loss: {total_loss:.2f}'

                    # except Exception:
                    #     preview_i.text = '(i) Metal Loss in Casting: —'
                    #     preview_ii.text = '(ii) Metal Loss in Cutting: —'
                    #     preview_total.text = 'Total Scrap Loss: —'

                    except Exception:
                        # casting_loss_lbl.text = '—'
                        cutting_loss_lbl.text = 'Cutting Loss: —'
                        # transit_mc_lbl.text   = 'Metal Prep → Casting: —'
                        # transit_cc_lbl.text   = 'Casting → Cutting: —'
                        # transit_total_lbl.text= 'Total Transit Loss: —'
                        total_loss_lbl.text   = 'Total Loss: —'


                def validate_rules() -> str | None:
                    """Return an error string if a rule is violated, else None."""
                    try:
                        supplied = float(current_casting_out or 0.0)
                        A = float(before_cut.value or 0.0)        # before-cut
                        C = float(after_cast.value or 0.0)
                        B = float(after_scrap.value or 0.0)
                        tol = 0.05

                        # Rule A: before within ±5% of supplied
                        if supplied > 0:
                            if abs(A - supplied) > supplied * tol:
                                return f"Before-cut ({A:.2f}) must be within 5% of supplied ({supplied:.2f})."

                        # Rule B: (after-cast + after-scrap) within ±5% of before
                        if A > 0:
                            if abs((C + B) - A) > A * tol:
                                return "(After Cast + After Scrap) must be within 5% of Before-cut."

                        return None
                    except Exception:
                        return "Invalid numbers."

                def clear_right_panel():
                    nonlocal current_supplied_mp, current_casting_in, current_casting_out
                    current_supplied_mp = 0.0
                    current_casting_in = 0.0
                    current_casting_out = 0.0

                    flask_lbl.text = tree_lbl.text = metal_lbl.text = date_lbl.text = '—'

                    # supplied_lbl.text = '—'
                    # casting_in_lbl.text = '—'
                    # casting_out_lbl.text = '—'
                    # casting_loss_lbl.text = '—'
                    cutting_loss_lbl.text = 'Cutting Loss: —'
                    # transit_mc_lbl.text   = 'Metal Prep → Casting: —'
                    # transit_cc_lbl.text   = 'Casting → Cutting: —'
                    # transit_total_lbl.text= 'Total Transit Loss: —'                    
                    total_loss_lbl.text   = 'Total Loss: —'

                    before_cut.value = after_cast.value = after_scrap.value = 0.0


                before_cut.on('change', lambda _: update_preview())
                after_cast.on('change', lambda _: update_preview())
                after_scrap.on('change', lambda _: update_preview())

                async def hydrate_right():
                    sel = (recon_table.selected or [None])[0]
                    if not sel:
                        with client:
                            # flask_lbl.text = tree_lbl.text = metal_lbl.text = supplied_lbl.text = date_lbl.text = '—'
                            # before_cut.value = after_cast.value = after_scrap.value = 0.0
                            # update_preview()
                            clear_right_panel()
                        return

                    # fetch detail to be safe / consistent
                    try:
                        detail = await get_recon_detail(int(sel['flask_id']))
                    except Exception:
                        detail = {}

                    with client:
                        flask_lbl.text = f"{detail.get('flask_no') or sel.get('flask_no') or '—'}"
                        tree_lbl.text  = f"{detail.get('tree_no') or sel.get('tree_no') or '—'}"
                        metal_lbl.text = f"{detail.get('metal_name') or sel.get('metal_name') or '—'}"
                        date_lbl.text  = to_ui_date(detail.get('date') or sel.get('date') or date.today().isoformat())

                        nonlocal current_supplied_mp, current_casting_in, current_casting_out

                        current_supplied_mp = float(sel.get('metal_supplied_weight', 0.0) or 0.0)
                        current_casting_in  = float(sel.get('casting_in_weight', 0.0) or 0.0)
                        current_casting_out = float(sel.get('casting_out_weight', 0.0) or 0.0)

                        # supplied_lbl.text = f'{current_supplied_mp:.2f}'
                        # casting_in_lbl.text = f'{current_casting_in:.2f}'
                        # casting_out_lbl.text = f'{current_casting_out:.2f}'

                        # supplied for preview
                        # try:
                        #     sup = float(detail.get('supplied_weight', sel.get('supplied_weight', 0.0)) or 0.0)
                        # except Exception:
                        #     sup = 0.0
                        # supplied_lbl.text = f'{sup:.2f}'
                        # nonlocal current_supplied
                        # current_supplied = sup

                        # inputs (prefill from detail or sel)
                        before_cut.value = float(detail.get('before_cut_weight', sel.get('before_cut_weight', 0.0)) or 0.0)
                        after_cast.value = float(detail.get('after_cast_weight', sel.get('after_cast_weight', 0.0)) or 0.0)
                        after_scrap.value= float(detail.get('after_scrap_weight', sel.get('after_scrap_weight', 0.0)) or 0.0)

                        update_preview()

                recon_table.on('selection', lambda _e: asyncio.create_task(hydrate_right()))

                async def confirm_and_post():
                    sel = (recon_table.selected or [None])[0]
                    if not sel:
                        notify('Select a flask first.', 'warning'); return

                    fid = int(sel['flask_id'])
                    payload = {
                        'flask_id': fid,
                        'supplied_weight': float(current_casting_out or 0.0),
                        'before_cut_weight': float(before_cut.value or 0.0),
                        'after_cast_weight': float(after_cast.value or 0.0),
                        'after_scrap_weight': float(after_scrap.value or 0.0),
                        'posted_by': 'recon_ui',
                    }
                    try:
                        # client-side validation (same as cutting)
                        err = validate_rules()
                        if err:
                            notify(err, 'negative')
                            return

                        await post_recon_confirm(payload)
                        notify('Reconciliation confirmed • Moved to Job Bag Supply', 'positive')
                        # remove from queue and clear panel
                        with client:
                            recon_table.rows = [r for r in recon_table.rows if r.get('flask_id') != fid]
                            recon_table.selected = []
                            recon_table.update()
                        await hydrate_right()
                    except Exception as ex:
                        notify(str(ex), 'negative')

                with ui.row().classes('gap-2 mt-2'):
                    ui.button('RECALCULATE', on_click=update_preview).props('outline')
                    ui.button('POST TO JOB BAG SUPPLY', on_click=lambda: asyncio.create_task(confirm_and_post())) \
                      .classes('bg-emerald-600 text-white')

    # -------- filtering & refresh --------
    def _apply_filters(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        fdate = parse_iso_date(d_from.value)
        tdate = parse_iso_date(d_to.value)
        pick  = metal_filter.value or 'All'
        needle = (q_search.value or '').strip().lower()

        out: List[Dict[str, Any]] = []

        for r in rows:
            d_iso = r.get('date') or ''
            d = parse_iso_date(d_iso)
            if not d:
                continue
            if fdate and d < fdate: continue
            if tdate and d > tdate: continue
            if pick != 'All' and (r.get('metal_name') != pick): continue
            # search by flask or tree
            key = (str(r.get('flask_no','')) + ' ' + str(r.get('tree_no',''))).lower()
            if needle and needle not in key: continue

            rr = dict(r)
            rr['_sort_ord'] = -d.toordinal()
            rr['_sort_metal'] = rr.get('metal_name') or ''
            rr['_sort_flask'] = str(rr.get('flask_no',''))
            rr['date'] = to_ui_date(d_iso)

            # normalize numeric fields
            # for k in ('supplied_weight','before_cut_weight','after_cast_weight','after_scrap_weight','loss_total'):
            for k in (
                'metal_supplied_weight',
                'casting_in_weight',
                'casting_out_weight',
                'supplied_weight',
                'before_cut_weight',
                'after_cast_weight',
                'after_scrap_weight',
                'loss_total',
            ):
                if k in rr and rr[k] is not None:
                    try: rr[k] = float(rr[k])
                    except Exception: pass

            # --- compute Total Loss So Far (casting + cutting + BOTH transit legs) ---
            try:
                supplied_mp = float(rr.get('metal_supplied_weight') or 0.0)
                cin        = float(rr.get('casting_in_weight') or 0.0)
                cout       = float(rr.get('casting_out_weight') or 0.0)
                A          = float(rr.get('before_cut_weight') or 0.0)
                C          = float(rr.get('after_cast_weight') or 0.0)
                B          = float(rr.get('after_scrap_weight') or 0.0)

                casting_loss = cin - cout
                transit_mc   = supplied_mp - cin
                transit_cc   = cout - A
                cutting_loss = A - (B + C)

                total_loss = casting_loss + transit_mc + transit_cc + cutting_loss
                rr['loss_total'] = round(total_loss, 1)
            except Exception:
                rr['loss_total'] = rr.get('loss_total')


            out.append(rr)

        out.sort(key=lambda x: (x['_sort_ord'], x['_sort_metal'], x['_sort_flask']))
        for rr in out:
            for k in ('_sort_ord','_sort_metal','_sort_flask'):
                rr.pop(k, None)
        return out

    async def refresh_table():
        """Refresh queue with filters."""
        params = {
            'date_from': d_from.value or None,
            'date_to':   d_to.value or None,
            'metal': None if metal_filter.value == 'All' else metal_filter.value,
            'q': (q_search.value or '').strip(),
        }
        try:
            raw = await fetch_recon_queue(params)
        except Exception as e:
            notify(f'Failed to fetch reconciliation queue: {e}', 'negative'); raw = []

        rows = _apply_filters(raw)
        # keep selection
        selected_id = None
        try:
            if recon_table.selected:
                selected_id = recon_table.selected[0].get('flask_id')
        except Exception:
            selected_id = None

        recon_table.rows = rows
        if selected_id is not None:
            re_row = next((r for r in rows if r.get('flask_id') == selected_id), None)
            recon_table.selected = [re_row] if re_row else []
        recon_table.update()

        await hydrate_right()

    # events
    metal_filter.on('update:model-value', lambda _v: asyncio.create_task(refresh_table()))
    q_search.on('change', lambda _e: asyncio.create_task(refresh_table()))
    d_from.on('change',  lambda _e: asyncio.create_task(refresh_table()))
    d_to.on('change',    lambda _e: asyncio.create_task(refresh_table()))

    # auto-refresh
    ui.timer(30.0, lambda: asyncio.create_task(refresh_table()))

    # initial
    await asyncio.create_task(refresh_table())
