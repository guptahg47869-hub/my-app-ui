from nicegui import ui, Client # type: ignore
import httpx, os, asyncio # type: ignore
from datetime import date, datetime
from typing import Any, Dict, List

API_URL = os.getenv('API_URL', 'http://localhost:8000')
print('UI using API_URL =', API_URL)

# ---------- helpers (copied style from /supply) ----------
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

# client-side preview
def est_metal_weight(tree_weight: float, metal_name: str) -> float:
    name = (metal_name or '').upper()
    factor = 1.0
    if '10' in name: factor = 11
    elif '14' in name: factor = 13.25
    elif '18' in name: factor = 16.5
    elif 'PLATINUM' in name: factor = 21
    elif 'SILVER' in name: factor = 11
    return round((tree_weight or 0.0) * factor, 3)

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
            ui.button('POST FLASK', on_click=lambda: ui.navigate.to('/post-flask')).props('flat').classes('text-white')
            ui.button('HOME', on_click=lambda: ui.navigate.to('/')).props('flat').classes('text-white')

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
                    t_no = ui.input('Tree No').classes('w-full')
                    metal_pick = ui.select(options=metal_options, label='Metal').classes('w-full')
                    t_wt = ui.number('Tree Weight', value=0.0).classes('w-full')
                    est_label = ui.label('Estimated Metal: —').classes('text-gray-600 mt-1')

                    def refresh_est():
                        if not metal_pick.value:
                            est_label.text = 'Estimated Metal: —'; return
                        try:
                            est = est_metal_weight(float(t_wt.value or 0), metal_pick.value)
                            est_label.text = f'Estimated Metal: {est:.3f}'
                        except Exception:
                            est_label.text = 'Estimated Metal: —'

                    metal_pick.on('update:model-value', lambda _v: refresh_est())
                    t_wt.on('change', lambda _e: refresh_est())

                    async def submit():
                        if not (d_in.value and t_no.value and metal_pick.value):
                            notify('Please fill Date, Tree No, and Metal.', 'warning'); return
                        if metal_pick.value not in name_to_id:
                            notify('Unknown metal selected.', 'negative'); return
                        try:
                            payload = {
                                'date': d_in.value,
                                'tree_no': t_no.value.strip(),
                                'metal_id': int(name_to_id[metal_pick.value]),
                                'tree_weight': float(t_wt.value or 0.0),
                                'posted_by': 'tree_ui',
                            }
                        except Exception:
                            notify('Invalid numbers.', 'negative'); return
                        try:
                            async with httpx.AsyncClient(timeout=10.0) as c:
                                r = await c.post(f'{API_URL}/trees', json=payload)
                                r.raise_for_status()
                                data = r.json()
                            est_label.text = f"Estimated Metal: {float(data['est_metal_weight']):.3f}"
                            notify('Tree created → Transit', 'positive')
                            t_no.value = ''; t_wt.value = 0.0; refresh_est()
                            await refresh_transit_table()
                        except httpx.HTTPStatusError as e:
                            notify(explain_http_error(e), 'negative')
                        except Exception as ex:
                            notify(str(ex), 'negative')

                    with ui.row().classes('gap-2 mt-2'):
                        ui.button('CREATE TREE', on_click=lambda: asyncio.create_task(submit())) \
                          .classes('bg-emerald-600 text-white')
                        ui.button('RECALCULATE', on_click=refresh_est).props('outline')

        # RIGHT: transit queue
        with split.after:
            with ui.card().classes('w-full h-full p-0'):
                with ui.column().classes('w-full h-full').style('display:flex; flex-direction:column;'):
                    today_iso = date.today().isoformat()
                    with ui.row().classes('items-end gap-3 p-4').style('flex:0 0 auto;'):
                        ui.label('Trees in Transit').classes('text-base font-semibold mr-4')
                        t_search = ui.input('Search by Tree No').props('clearable').classes('w-48')
                        d_from = ui.input('From', value=today_iso).props('type=date').classes('w-36')
                        d_to   = ui.input('To',   value=today_iso).props('type=date').classes('w-36')
                        metal_filter = ui.select(options=['All'] + metal_options, value='All', label='Metal').classes('w-48')
                        metal_filter.props('options-dense behavior=menu popup-content-style="z-index:4000"')

                        async def reset_filters():
                            d_from.value = today_iso; d_to.value = today_iso
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
                                          .props('dense flat bordered row-key="tree_id" hide-bottom') \
                                          .classes('w-full text-sm')

    # -------- filtering & refresh (same pattern as /supply) --------
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
            rr['_sort_ord'] = -d.toordinal()                 # date DESC
            rr['_sort_metal'] = rr.get('metal_name') or ''   # metal ASC
            rr['_sort_tree'] = str(rr.get('tree_no',''))     # tree ASC
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
