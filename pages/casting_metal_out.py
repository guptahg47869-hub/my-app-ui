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

async def fetch_casting_metal_out_queue() -> List[Dict[str, Any]]:
    """/queue/casting_metal_out returns flasks in casting_metal_out stage; includes casting_in_weight."""
    async with httpx.AsyncClient(timeout=15.0) as c:
        r = await c.get(f'{API_URL}/queue/casting_metal_out')
        r.raise_for_status()
        return r.json()

async def post_casting_metal_out(payload: Dict[str, Any]) -> Dict[str, Any]:
    """POST /casting_metal_out expects flask_id, casting_out_weight, posted_by."""
    async with httpx.AsyncClient(timeout=20.0) as c:
        r = await c.post(f'{API_URL}/casting_metal_out', json=payload)
        try:
            r.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise RuntimeError(explain_http_error(e)) from e
        return r.json()

# ---------- PAGE ----------
@ui.page('/casting-metal-out')  # kebab-case UI route
async def casting_metal_out_page(client: Client):
    def notify(msg: str, color='primary'):
        with client:
            ui.notify(msg, color=color)

    ui.page_title('Casting Metal Out · Casting Tracker')
    ui.add_head_html('''
    <style>
      .fill-parent{width:100%!important;max-width:100%!important}
      .num-shadow{text-shadow:0 2px 8px rgba(0,0,0,.15)}
    </style>
    ''')

    with ui.header().classes('items-center justify-between bg-gray-900 text-white'):
        ui.label('Casting Metal Out Queue').classes('text-lg font-semibold')
        with ui.row().classes('items-center gap-2'):
            # ui.button(icon='home', on_click=lambda: ui.navigate.to('/')).props('flat round').classes('text-white')
            ui.button('← Casting Dept', on_click=lambda: ui.navigate.to('/dept/casting')).props('flat').classes('text-white font-semibold')

    # preload metals for filter
    try:
        metals = await fetch_metals()
        metal_options = ['All'] + sorted([m['name'] for m in metals if 'name' in m])
    except Exception:
        metal_options = ['All']

    selected: Dict[str, Any] | None = None
    current_casting_in: float = 0.0  # <- used in preview

    # per-session drafts: remember last values per flask id (matches cutting page behavior)
    drafts: Dict[int, Dict[str, float]] = {}

    with ui.splitter(value=60).classes('px-6').style('width:100%; height: calc(100vh - 140px);') as main_split:

        # LEFT: queue + filters (same layout/props as cutting.py)
        with main_split.before:
            with ui.card().classes('w-full h-full p-0'):
                with ui.column().classes('w-full h-full').style('display:flex; flex-direction:column;'):

                    with ui.row().classes('items-end gap-3 p-4').style('flex:0 0 auto;'):
                        ui.label('Flasks in Casting Metal Out').classes('text-base font-semibold mr-4')
                        f_search = ui.input('Search by Flask or Tree').props('clearable').classes('w-48')
                        d_from = ui.input('From').props('type=date').classes('w-36')
                        d_to   = ui.input('To').props('type=date').classes('w-36')
                        metal_filter = ui.select(options=metal_options, value='All', label='Metal').classes('w-48')
                        metal_filter.props('options-dense behavior=menu popup-content-style="z-index:4000"')

                        async def reset_filters():
                            d_from.value = ''; d_to.value = ''
                            f_search.value = ''; metal_filter.value = 'All'
                            await refresh_table()
                            notify('Filters reset.', 'positive')

                        ui.button('RESET FILTERS', on_click=lambda: asyncio.create_task(reset_filters())).props('outline')

                    # table
                    with ui.element('div').classes('fill-parent').style(
                        'flex:1 1 auto; overflow:auto; padding:0 16px 16px 16px; width:100%; max-width:100%;'
                    ):
                        columns = [
                            {'name': 'date', 'label': 'Date', 'field': 'date'},
                            {'name': 'flask_no', 'label': 'Flask No', 'field': 'flask_no'},
                            {'name': 'tree_no',  'label': 'Tree No',  'field': 'tree_no'},
                            {'name': 'metal_name', 'label': 'Metal', 'field': 'metal_name'},
                            {'name': 'casting_in_weight', 'label': 'Casting In Weight', 'field': 'casting_in_weight'},
                        ]
                        out_table = ui.table(columns=columns, rows=[]) \
                                      .props('dense flat bordered row-key="flask_id" selection="single" hide-bottom') \
                                      .classes('w-full text-sm')

        # RIGHT: details + form + post (same aesthetic as cutting.py)
        with main_split.after:
            with ui.card().classes('w-full h-full p-6'):
                ui.label('Casting Metal Out Details').classes('text-base font-semibold mb-2')

                with ui.grid(columns=2).classes('gap-2 mb-2'):
                    ui.label('Flask No:'); flask_lbl = ui.label('—')
                    ui.label('Metal:');    metal_lbl = ui.label('—')
                    ui.label('Casting In Weight:'); in_wt_lbl = ui.label('—')

                # Form inputs (single input, as requested)
                after_casting = ui.number('After Casting weight', value=0.0).props('step=0.001').classes('w-full')

                # Preview
                preview_loss = ui.label('Casting Loss: —').classes('text-gray-800 font-semibold')

                def update_preview_and_draft():
                    try:
                        out_wt = float(after_casting.value or 0.0)
                        cin = float(current_casting_in or 0.0)
                        loss = cin - out_wt

                        preview_loss.text = f'Casting Loss: {loss:.2f}'

                        preview_loss.classes(remove='text-negative')
                        if loss < 0:
                            preview_loss.classes(add='text-negative')

                        # store draft
                        if selected and isinstance(selected.get('flask_id'), int):
                            drafts[int(selected['flask_id'])] = {'after_casting': out_wt}
                    except Exception:
                        preview_loss.text = 'Casting Loss: —'
                        preview_loss.classes(remove='text-negative')

                after_casting.on('change', lambda _: update_preview_and_draft())

                async def sync_selection():
                    """Refresh right panel to match current selection (after table updates too)."""
                    nonlocal selected, current_casting_in
                    row_list = out_table.selected or []
                    if row_list:
                        sel_id = row_list[0].get('flask_id')
                        current = next((r for r in out_table.rows if r.get('flask_id') == sel_id), row_list[0])
                        selected = current
                    else:
                        selected = None

                    with client:
                        if not selected:
                            flask_lbl.text = '—'
                            metal_lbl.text = '—'
                            in_wt_lbl.text = '—'
                            current_casting_in = 0.0
                            after_casting.value = 0.0
                            update_preview_and_draft()
                            return

                        flask_lbl.text = f"{selected.get('flask_no','—')}"
                        metal_lbl.text = f"{selected.get('metal_name','—')}"

                        cin_raw = selected.get('casting_in_weight')
                        try:
                            cin = float(cin_raw or 0.0)
                        except Exception:
                            cin = 0.0

                        current_casting_in = cin
                        in_wt_lbl.text = f"{cin:.2f}" if cin_raw is not None else '—'

                        sel_id = int(selected.get('flask_id'))
                        if sel_id in drafts:
                            d = drafts[sel_id]
                            after_casting.value = float(d.get('after_casting', cin))
                        else:
                            # consistent “prefill” behavior like cutting: default to the reference weight
                            after_casting.value = cin

                        update_preview_and_draft()

                out_table.on('selection', lambda _e: asyncio.create_task(sync_selection()))

                async def submit_casting_metal_out():
                    if not selected:
                        notify('Select a flask first.', 'warning')
                        return
                    try:
                        out_wt = float(after_casting.value or 0.0)
                        if out_wt < 0:
                            notify('After Casting weight must be >= 0.', 'negative')
                            return

                        payload = {
                            'flask_id': int(selected['flask_id']),
                            'casting_out_weight': out_wt,
                            'posted_by': 'casting_metal_out_ui',
                        }
                    except Exception:
                        notify('Invalid inputs.', 'negative')
                        return

                    try:
                        await post_casting_metal_out(payload)
                        notify('Moved to Cutting', 'positive')
                        # remove from table and clear selection
                        with client:
                            out_table.rows = [r for r in out_table.rows if r['flask_id'] != selected['flask_id']]
                            out_table.selected = []
                            out_table.update()
                        await sync_selection()
                    except Exception as ex:
                        notify(str(ex), 'negative')

                with ui.row().classes('gap-2 mt-2'):
                    ui.button('RECALCULATE', on_click=update_preview_and_draft).props('outline')
                    ui.button('POST TO CUTTING', on_click=lambda: asyncio.create_task(submit_casting_metal_out())) \
                      .classes('bg-emerald-600 text-white')

    # -------- filtering & refresh (MATCHES cutting.py behavior) --------
    def _apply_filters(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        fdate = parse_iso_date(d_from.value)
        tdate = parse_iso_date(d_to.value)
        pick  = metal_filter.value or 'All'
        needle = (f_search.value or '').strip().lower()

        out: List[Dict[str, Any]] = []

        for r in rows:
            d_iso = r.get('date') or ''
            d = parse_iso_date(d_iso)
            if not d:
                continue
            if fdate and d < fdate:
                continue
            if tdate and d > tdate:
                continue
            if pick != 'All' and (r.get('metal_name') != pick):
                continue

            hay = f"{r.get('flask_no','')} {r.get('tree_no','')}".lower()
            if needle and needle not in hay:
                continue

            rr = dict(r)
            rr['_sort_ord'] = -d.toordinal()
            rr['_sort_metal'] = rr.get('metal_name') or ''
            rr['_sort_flask'] = str(rr.get('flask_no',''))
            rr['date'] = to_ui_date(d_iso)

            # normalize number
            if 'casting_in_weight' in rr and rr['casting_in_weight'] is not None:
                try:
                    rr['casting_in_weight'] = float(rr['casting_in_weight'])
                except Exception:
                    pass

            out.append(rr)

        out.sort(key=lambda x: (x['_sort_ord'], x['_sort_metal'], x['_sort_flask']))
        for rr in out:
            for k in ('_sort_ord','_sort_metal','_sort_flask'):
                rr.pop(k, None)
        return out

    async def refresh_table():
        """Refresh table; keep selection by flask_id; update right panel."""
        try:
            raw = await fetch_casting_metal_out_queue()
        except Exception as e:
            notify(f'Failed to fetch casting metal out queue: {e}', 'negative')
            raw = []

        rows = _apply_filters(raw)

        # preserve selection
        selected_id = None
        try:
            if out_table.selected:
                selected_id = out_table.selected[0].get('flask_id')
        except Exception:
            selected_id = None

        out_table.rows = rows
        if selected_id is not None:
            re_row = next((r for r in rows if r.get('flask_id') == selected_id), None)
            out_table.selected = [re_row] if re_row else []
        out_table.update()

        await sync_selection()

    # events
    metal_filter.on('update:model-value', lambda _v: asyncio.create_task(refresh_table()))
    f_search.on('change', lambda _e: asyncio.create_task(refresh_table()))
    d_from.on('change',  lambda _e: asyncio.create_task(refresh_table()))
    d_to.on('change',    lambda _e: asyncio.create_task(refresh_table()))

    # auto-refresh
    ui.timer(30.0, lambda: asyncio.create_task(refresh_table()))

    # initial
    await asyncio.create_task(refresh_table())
