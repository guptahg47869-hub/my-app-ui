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

    ui.page_title('Reconciliation · Casting Tracker')
    ui.add_head_html('''
    <style>
      .fill-parent{width:100%!important;max-width:100%!important}
      .num-shadow{text-shadow:0 2px 8px rgba(0,0,0,.15)}
    </style>
    ''')

    with ui.header().classes('items-center justify-between bg-gray-900 text-white'):
        ui.label('Reconciliation Queue').classes('text-lg font-semibold')
        with ui.row().classes('items-center gap-2'):
            ui.button('METAL PREP', on_click=lambda: ui.navigate.to('/metal-prep')).props('flat').classes('text-white')
            ui.button('METAL SUPPLY', on_click=lambda: ui.navigate.to('/supply')).props('flat').classes('text-white')
            ui.button(icon='home', on_click=lambda: ui.navigate.to('/')).props('flat round').classes('text-white')

    # preload metals for filter
    try:
        metals = await fetch_metals()
        metal_options = ['All'] + sorted([m['name'] for m in metals if 'name' in m])
    except Exception:
        metal_options = ['All']

    selected: Dict[str, Any] | None = None
    current_supplied: float = 0.0

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
                            {'name': 'supplied', 'label': 'Supplied', 'field': 'supplied_weight'},
                            {'name': 'before', 'label': 'Before', 'field': 'before_cut_weight'},
                            {'name': 'cast', 'label': 'After Cast', 'field': 'after_cast_weight'},
                            {'name': 'scrap', 'label': 'After Scrap', 'field': 'after_scrap_weight'},
                            {'name': 'loss', 'label': 'Loss', 'field': 'loss_total'},
                        ]
                        recon_table = ui.table(columns=columns, rows=[]) \
                                      .props('dense flat bordered row-key="flask_id" selection="single" hide-bottom') \
                                      .classes('w-full text-sm')

        # RIGHT: details + confirm
        with main_split.after:
            with ui.card().classes('w-full h-full p-6'):
                ui.label('Reconciliation Details').classes('text-base font-semibold mb-2')

                with ui.grid(columns=2).classes('gap-2 mb-2'):
                    ui.label('Flask No:'); flask_lbl = ui.label('—')
                    ui.label('Tree No:');  tree_lbl = ui.label('—')
                    ui.label('Metal:');    metal_lbl = ui.label('—')
                    ui.label('Supplied Wt:'); supplied_lbl = ui.label('—')
                    ui.label('Date:');     date_lbl = ui.label('—')

                before_cut = ui.number('Before Cutting Weight', value=0.0).props('step=0.001').classes('w-full')
                after_cast = ui.number('After Cut: Casting Weight', value=0.0).props('step=0.001').classes('w-full')
                after_scrap = ui.number('After Cut: Scrap Weight', value=0.0).props('step=0.001').classes('w-full')

                preview_i    = ui.label('(i) Metal Loss in Casting: —').classes('text-gray-600')
                preview_ii   = ui.label('(ii) Metal Loss in Cutting: —').classes('text-gray-600')
                preview_total= ui.label('Total Scrap Loss: —').classes('text-gray-800 font-semibold')

                def update_preview():
                    try:
                        A = float(before_cut.value or 0.0)
                        C = float(after_cast.value or 0.0)
                        B = float(after_scrap.value or 0.0)
                        supplied = float(current_supplied or 0.0)

                        part_i  = supplied - A
                        part_ii = A - (B + C)
                        total   = supplied - (B + C)

                        preview_i.text     = f'(i) Metal Loss in Casting: {part_i:.1f}'
                        preview_ii.text    = f'(ii) Metal Loss in Cutting: {part_ii:.1f}'
                        preview_total.text = f'Total Scrap Loss: {total:.1f}'

                        preview_total.classes(remove='text-negative')
                        if total < 0:
                            preview_total.classes(add='text-negative')
                    except Exception:
                        preview_i.text = '(i) Metal Loss in Casting: —'
                        preview_ii.text = '(ii) Metal Loss in Cutting: —'
                        preview_total.text = 'Total Scrap Loss: —'

                def validate_rules() -> str | None:
                    """Return an error string if a rule is violated, else None."""
                    try:
                        supplied = float(current_supplied or 0.0)
                        A = float(before_cut.value or 0.0)        # before-cut
                        C = float(after_cast.value or 0.0)
                        B = float(after_scrap.value or 0.0)
                        tol = 0.05

                        # Rule A: before within ±5% of supplied
                        if supplied > 0:
                            if abs(A - supplied) > supplied * tol:
                                return f"Before-cut ({A:.1f}) must be within 5% of supplied ({supplied:.1f})."

                        # Rule B: (after-cast + after-scrap) within ±5% of before
                        if A > 0:
                            if abs((C + B) - A) > A * tol:
                                return "(After Cast + After Scrap) must be within 5% of Before-cut."

                        return None
                    except Exception:
                        return "Invalid numbers."


                before_cut.on('change', lambda _: update_preview())
                after_cast.on('change', lambda _: update_preview())
                after_scrap.on('change', lambda _: update_preview())

                async def hydrate_right():
                    sel = (recon_table.selected or [None])[0]
                    if not sel:
                        with client:
                            flask_lbl.text = tree_lbl.text = metal_lbl.text = supplied_lbl.text = date_lbl.text = '—'
                            before_cut.value = after_cast.value = after_scrap.value = 0.0
                            update_preview()
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

                        # supplied for preview
                        try:
                            sup = float(detail.get('supplied_weight', sel.get('supplied_weight', 0.0)) or 0.0)
                        except Exception:
                            sup = 0.0
                        supplied_lbl.text = f'{sup:.1f}'
                        nonlocal current_supplied
                        current_supplied = sup

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
                        'supplied_weight': current_supplied,
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
                        notify('Reconciliation confirmed • Moved to Done', 'positive')
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
                    ui.button('CONFIRM & POST TO DONE', on_click=lambda: asyncio.create_task(confirm_and_post())) \
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
            for k in ('supplied_weight','before_cut_weight','after_cast_weight','after_scrap_weight','loss_total'):
                if k in rr and rr[k] is not None:
                    try: rr[k] = float(rr[k])
                    except Exception: pass

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
