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

def split_bags(bag_nos_text: str | None) -> List[str]:
    if not bag_nos_text:
        return []
    # backend returns "B12, B18" etc.
    parts = [p.strip() for p in str(bag_nos_text).split(',')]
    return [p for p in parts if p]

# ---------- API ----------
async def fetch_metals() -> List[Dict[str, Any]]:
    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.get(f'{API_URL}/metals')
        r.raise_for_status()
        return r.json()

async def fetch_job_bag_supply_queue() -> List[Dict[str, Any]]:
    async with httpx.AsyncClient(timeout=15.0) as c:
        r = await c.get(f'{API_URL}/queue/job_bag_supply')
        r.raise_for_status()
        return r.json()

async def fetch_recon_detail(flask_id: int) -> Dict[str, Any]:
    """GET /reconciliation/{flask_id} returns after_cast_weight, etc."""
    async with httpx.AsyncClient(timeout=15.0) as c:
        r = await c.get(f'{API_URL}/reconciliation/{flask_id}')
        r.raise_for_status()
        return r.json()

async def post_job_bag_supply(payload: Dict[str, Any]) -> Dict[str, Any]:
    """POST /job_bag_supply expects flask_id, posted_by."""
    async with httpx.AsyncClient(timeout=20.0) as c:
        r = await c.post(f'{API_URL}/job_bag_supply', json=payload)
        try:
            r.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise RuntimeError(explain_http_error(e)) from e
        return r.json()

# ---------- PAGE ----------
@ui.page('/job-bag-supply')  # kebab-case UI route (matches your newer pages)
async def job_bag_supply_page(client: Client):
    def notify(msg: str, color='primary'):
        with client:
            ui.notify(msg, color=color)

    ui.page_title('Job Bag Supply · Casting Tracker')
    ui.add_head_html('''
    <style>
      .fill-parent{width:100%!important;max-width:100%!important}
      .chip-row{display:flex;gap:6px; flex-wrap:wrap; width:100%; padding:2px 0}
      .num-shadow{text-shadow:0 2px 8px rgba(0,0,0,.15)}
    </style>
    ''')

    with ui.header().classes('items-center justify-between bg-gray-900 text-white'):
        ui.label('Job Bag Supply Queue').classes('text-lg font-semibold')
        with ui.row().classes('items-center gap-2'):
            # ui.button(icon='home', on_click=lambda: ui.navigate.to('/')).props('flat round').classes('text-white')
            ui.button('← Job Bag Supply', on_click=lambda: ui.navigate.to('/dept/job-bag')).props('flat').classes('text-white font-semibold')

    # preload metals for filter
    try:
        metals = await fetch_metals()
        metal_options = ['All'] + sorted([m['name'] for m in metals if 'name' in m])
    except Exception:
        metal_options = ['All']

    selected: Dict[str, Any] | None = None

    # right-panel state
    current_after_cast: float = 0.0
    current_bags: List[str] = []

    with ui.splitter(value=60).classes('px-6').style('width:100%; height: calc(100vh - 140px);') as main_split:

        # LEFT: queue + filters (identical structure to casting_metal_out) :contentReference[oaicite:4]{index=4}
        with main_split.before:
            with ui.card().classes('w-full h-full p-0'):
                with ui.column().classes('w-full h-full').style('display:flex; flex-direction:column;'):

                    with ui.row().classes('items-end gap-3 p-4').style('flex:0 0 auto;'):
                        ui.label('Flasks in Job Bag Supply').classes('text-base font-semibold mr-4')
                        f_search = ui.input('Search by Flask, Tree, or Bag').props('clearable').classes('w-48')
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
                            {'name': 'bag_nos', 'label': 'Bags', 'field': 'bag_nos'},
                        ]
                        bag_table = ui.table(columns=columns, rows=[]) \
                                      .props('dense flat bordered row-key="flask_id" selection="single" hide-bottom') \
                                      .classes('w-full text-sm')

                        # Chips in the Bags column (same concept as flask_search) 
                        bag_table.add_slot('body-cell-bag_nos', '''
                        <q-td :props="props">
                          <div class="chip-row">
                            <q-chip v-for="b in (props.row.bag_nos || [])"
                                    :key="b"
                                    dense
                                    color="primary"
                                    text-color="white"
                                    class="q-mr-xs q-mb-xs"
                                    clickable="false">{{ b }}</q-chip>
                          </div>
                        </q-td>
                        ''')

        # RIGHT: details + bags + post (matches the “details” card style) :contentReference[oaicite:6]{index=6}
        with main_split.after:
            with ui.card().classes('w-full h-full p-6'):
                ui.label('Job Bag Supply Details').classes('text-base font-semibold mb-2')

                with ui.grid(columns=2).classes('gap-2 mb-2'):
                    ui.label('Flask No:'); flask_lbl = ui.label('—')
                    ui.label('Metal:');    metal_lbl = ui.label('—')
                    ui.label('After Cut: Consumable Weight:'); after_cast_lbl = ui.label('—')

                ui.label('Bags:').classes('text-sm font-semibold mt-2')

                # container for chips on the right panel
                chips_container = ui.element('div').classes('chip-row')

                def render_right_chips(bags: List[str]):
                    chips_container.clear()
                    with chips_container:
                        if not bags:
                            ui.label('—').classes('text-gray-500')
                            return
                        for b in bags:
                            ui.chip(b).props('dense color=primary text-color=white').classes('q-mr-xs q-mb-xs')

                async def sync_selection():
                    """Refresh right panel to match current selection (after table updates too)."""
                    nonlocal selected, current_after_cast, current_bags

                    row_list = bag_table.selected or []
                    if row_list:
                        sel_id = row_list[0].get('flask_id')
                        current = next((r for r in bag_table.rows if r.get('flask_id') == sel_id), row_list[0])
                        selected = current
                    else:
                        selected = None

                    with client:
                        if not selected:
                            flask_lbl.text = '—'
                            metal_lbl.text = '—'
                            after_cast_lbl.text = '—'
                            current_after_cast = 0.0
                            current_bags = []
                            render_right_chips([])
                            return

                        flask_lbl.text = f"{selected.get('flask_no','—')}"
                        metal_lbl.text = f"{selected.get('metal_name','—')}"

                        # bags already computed in queue rows
                        current_bags = list(selected.get('bag_nos') or [])
                        render_right_chips(current_bags)

                        # fetch recon detail for after_cast_weight
                        try:
                            detail = await fetch_recon_detail(int(selected['flask_id']))
                            val = float(detail.get('after_cast_weight') or 0.0)
                            current_after_cast = val
                            after_cast_lbl.text = f"{val:.2f}"
                        except Exception:
                            current_after_cast = 0.0
                            after_cast_lbl.text = '—'

                bag_table.on('selection', lambda _e: asyncio.create_task(sync_selection()))

                async def submit_job_bag_supply():
                    if not selected:
                        notify('Select a flask first.', 'warning')
                        return
                    try:
                        payload = {
                            'flask_id': int(selected['flask_id']),
                            'posted_by': 'job_bag_supply_ui',
                        }
                    except Exception:
                        notify('Invalid selection.', 'negative')
                        return

                    try:
                        await post_job_bag_supply(payload)
                        notify('Moved to Done', 'positive')
                        # remove from table and clear selection
                        with client:
                            bag_table.rows = [r for r in bag_table.rows if r['flask_id'] != selected['flask_id']]
                            bag_table.selected = []
                            bag_table.update()
                        await sync_selection()
                    except Exception as ex:
                        notify(str(ex), 'negative')

                async def recalc_right_panel():
                    # for symmetry with casting_metal_out page: recalc just re-syncs selection
                    await sync_selection()
                    notify('Refreshed.', 'positive')

                with ui.row().classes('gap-2 mt-4'):
                    ui.button('RECALCULATE', on_click=lambda: asyncio.create_task(recalc_right_panel())).props('outline')
                    ui.button('POST TO DONE', on_click=lambda: asyncio.create_task(submit_job_bag_supply())) \
                      .classes('bg-emerald-600 text-white')

    # -------- filtering & refresh (same pattern as casting_metal_out) :contentReference[oaicite:7]{index=7} --------
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

            # Build bags list from bag_nos_text so we can display chips consistently
            rr = dict(r)
            rr['bag_nos'] = rr.get('bag_nos') or split_bags(rr.get('bag_nos_text'))

            hay = f"{rr.get('flask_no','')} {rr.get('tree_no','')} {rr.get('bag_nos_text','')}".lower()
            # also search individual chips
            if rr.get('bag_nos'):
                hay += " " + " ".join([str(x).lower() for x in rr.get('bag_nos') or []])

            if needle and needle not in hay:
                continue

            rr['_sort_ord'] = -d.toordinal()
            rr['_sort_metal'] = rr.get('metal_name') or ''
            rr['_sort_flask'] = str(rr.get('flask_no',''))
            rr['date'] = to_ui_date(d_iso)

            out.append(rr)

        out.sort(key=lambda x: (x['_sort_ord'], x['_sort_metal'], x['_sort_flask']))
        for rr in out:
            for k in ('_sort_ord','_sort_metal','_sort_flask'):
                rr.pop(k, None)
        return out

    async def refresh_table():
        """Refresh table; keep selection by flask_id; update right panel."""
        try:
            raw = await fetch_job_bag_supply_queue()
        except Exception as e:
            notify(f'Failed to fetch job bag supply queue: {e}', 'negative')
            raw = []

        rows = _apply_filters(raw)

        # preserve selection
        selected_id = None
        try:
            if bag_table.selected:
                selected_id = bag_table.selected[0].get('flask_id')
        except Exception:
            selected_id = None

        bag_table.rows = rows
        if selected_id is not None:
            re_row = next((r for r in rows if r.get('flask_id') == selected_id), None)
            bag_table.selected = [re_row] if re_row else []
        bag_table.update()

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
