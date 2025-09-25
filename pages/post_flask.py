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

async def fetch_supply_queue():
    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.get(f'{API_URL}/queue/supply')
        r.raise_for_status()
        return r.json()

async def post_flask(payload: Dict[str, Any]):
    async with httpx.AsyncClient(timeout=15.0) as c:
        r = await c.post(f'{API_URL}/waxing/post_to_supply', json=payload)
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

@ui.page('/post-flask')
async def post_flask_page(client: Client):
    def notify(msg: str, color='primary'):
        with client:
            ui.notify(msg, color=color)

    ui.page_title('Post Flask to Supply · Casting Tracker')
    ui.add_head_html('<style>.fill-parent{width:100%!important;max-width:100%!important}</style>')

    with ui.header().classes('items-center justify-between bg-gray-900 text-white'):
        ui.label('Post Flask to Supply').classes('text-lg font-semibold')
        with ui.row().classes('items-center gap-2'):
            ui.button('CREATE TREE', on_click=lambda: ui.navigate.to('/trees')).props('flat').classes('text-white')
            ui.button('HOME', on_click=lambda: ui.navigate.to('/')).props('flat').classes('text-white')

    selected: Dict[str, Any] | None = None

    with ui.splitter(value=60).classes('px-6').style('width:100%; height: calc(100vh - 140px);') as main_split:

        # LEFT: top transit (filters + table), bottom supply snapshot
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
                            d_from = ui.input('From', value=today_iso).props('type=date').classes('w-36')
                            d_to   = ui.input('To',   value=today_iso).props('type=date').classes('w-36')

                            # metals for filter
                            try:
                                async with httpx.AsyncClient(timeout=10) as c:
                                    metals = (await c.get(f'{API_URL}/metals')).json()
                                metal_options = ['All'] + sorted([m['name'] for m in metals if 'name' in m])
                            except Exception:
                                metal_options = ['All']
                            metal_filter = ui.select(options=metal_options, value='All', label='Metal').classes('w-48')
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
                                              .props('dense flat bordered row-key="tree_id" selection="single" hide-bottom') \
                                              .classes('w-full text-sm')

                # BOTTOM: supply snapshot
                with inner.after:
                    with ui.column().classes('w-full h-full').style('display:flex; flex-direction:column;'):
                        with ui.row().classes('items-center justify-between p-4').style('flex:0 0 auto;'):
                            ui.label('Metal Supply Queue (snapshot)').classes('text-base font-semibold')
                            ui.button('Refresh', on_click=lambda: asyncio.create_task(refresh_supply_table())).props('outline')
                        with ui.element('div').classes('fill-parent').style(
                            'flex:1 1 auto; overflow:auto; padding:0 16px 16px 16px; width:100%; max-width:100%;'
                        ):
                            s_columns = [
                                {'name': 'date', 'label': 'Date', 'field': 'date'},
                                {'name': 'flask_no', 'label': 'Flask No', 'field': 'flask_no'},
                                {'name': 'metal_name', 'label': 'Metal', 'field': 'metal_name'},
                                {'name': 'metal_weight', 'label': 'Req. Metal', 'field': 'metal_weight'},
                            ]
                            supply_table = ui.table(columns=s_columns, rows=[]) \
                                             .props('dense flat bordered hide-bottom') \
                                             .classes('w-full text-sm')

        # RIGHT: posting form
        with main_split.after:
            with ui.card().classes('w-full h-full p-4'):
                ui.label('Post Flask to Supply').classes('text-base font-semibold mb-2')

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
                        tree_wt_lbl.text = f'Tree Weight (Total − Gasket): {tw:.3f}'
                        mname = metal_lbl.text or ''
                        final = est_metal_weight(tw, mname)
                        final_lbl.text = f'Final Metal (preview): {final:.3f}'
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
                            g_wt.value = 0.0; t_wt.value = 0.0
                            refresh_preview()

                transit_table.on('selection', lambda _e: asyncio.create_task(sync_selection()))

                def recompute_defaults():
                    refresh_preview()

                async def submit():
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
                        await post_flask(payload)
                        notify(f"Flask {payload['flask_no']} posted to Supply", 'positive')
                        # remove from transit, refresh supply
                        with client:
                            transit_table.rows = [r for r in transit_table.rows if r['tree_id'] != selected['tree_id']]
                            transit_table.selected = []
                            transit_table.update()
                        await refresh_supply_table()
                        await sync_selection()
                    except Exception as ex:
                        notify(str(ex), 'negative')

                with ui.row().classes('gap-2 mt-2'):
                    ui.button('Recalculate', on_click=recompute_defaults).props('outline')
                    ui.button('Post to Supply', on_click=lambda: asyncio.create_task(submit())) \
                      .classes('bg-emerald-600 text-white')

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

    def _format_and_sort_supply(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for r in rows:
            d_iso = r.get('date') or r.get('posted_at') or ''
            d = parse_iso_date(d_iso)
            if not d:
                continue
            rr = dict(r)
            rr['_sort_ord'] = -d.toordinal()                # date DESC
            rr['_sort_metal'] = rr.get('metal_name') or ''  # metal ASC
            rr['_sort_flask'] = str(rr.get('flask_no',''))  # flask ASC
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

    async def refresh_supply_table():
        try:
            raw = await fetch_supply_queue()
        except Exception as e:
            notify(f'Failed to fetch supply queue: {e}', 'negative')
            raw = []
        rows = _format_and_sort_supply(raw)
        supply_table.rows = rows
        supply_table.update()

    # events
    metal_filter.on('update:model-value', lambda _v: asyncio.create_task(refresh_transit_table()))
    t_search.on('change', lambda _e: asyncio.create_task(refresh_transit_table()))
    d_from.on('change',  lambda _e: asyncio.create_task(refresh_transit_table()))
    d_to.on('change',    lambda _e: asyncio.create_task(refresh_transit_table()))

    # initial
    await asyncio.create_task(refresh_transit_table())
    await asyncio.create_task(refresh_supply_table())
