# jewelry-casting-ui/pages/casting.py
from nicegui import ui, Client # type: ignore
import httpx, os, asyncio   # type: ignore
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

def explain_http_error(e: httpx.HTTPStatusError) -> str:
    try:
        data = e.response.json()
        if isinstance(data, dict) and 'detail' in data:
            return str(data['detail'])
        return str(data)
    except Exception:
        return e.response.text or str(e)

# Temperature logic (your exact rules)
def casting_temp_for(metal_name: str) -> float:
    n = (metal_name or '').upper()
    temp = 1000
    if "10" in n: temp = 1100
    elif "14W" in n: temp = 1050
    elif "14Y" in n: temp = 1030
    elif "14R" in n: temp = 1100
    elif "SILVER" in n: temp = 980
    elif "18W" in n: temp = 1050
    elif "18Y" in n: temp = 1060
    elif "18R" in n: temp = 1100
    elif "PLATINUM" in n: temp = 1000
    return float(temp)

def oven_temp_for(metal_name: str) -> float:
    n = (metal_name or '').upper()
    temp = 1000
    if "10" in n: temp = 1100
    elif "14W" in n: temp = 1150
    elif "14Y" in n: temp = 1050
    elif "14R" in n: temp = 1050
    elif "SILVER" in n: temp = 980
    elif "18W" in n: temp = 1050
    elif "18Y" in n: temp = 1050
    elif "18R" in n: temp = 1020
    elif "PLATINUM" in n: temp = 1000
    return float(temp)

# ---------- API ----------
async def fetch_metals() -> List[Dict[str, Any]]:
    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.get(f'{API_URL}/metals')
        r.raise_for_status()
        return r.json()

async def fetch_casting_queue(flask_no: str | None = None) -> List[Dict[str, Any]]:
    params = {}
    if flask_no:
        params['flask_no'] = flask_no
    async with httpx.AsyncClient(timeout=15.0) as c:
        r = await c.get(f'{API_URL}/queue/casting', params=params or None)
        r.raise_for_status()
        return r.json()

async def post_complete_casting(flask_id: int) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=15.0) as c:
        r = await c.post(f'{API_URL}/casting/{flask_id}/complete', json={'posted_by': 'casting_ui'})
        try:
            r.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise RuntimeError(explain_http_error(e)) from e
        return r.json()

# ---------- PAGE ----------
@ui.page('/casting')
async def casting_page(client: Client):
    def notify(msg: str, color='primary'):
        with client:
            ui.notify(msg, color=color)

    ui.page_title('Casting · Casting Tracker')
    ui.add_head_html('''
    <style>
      .fill-parent{width:100%!important;max-width:100%!important}
      .num-shadow{text-shadow:0 2px 8px rgba(0,0,0,.15)}
    </style>
    ''')

    with ui.header().classes('items-center justify-between bg-gray-900 text-white'):
        ui.label('Casting Queue').classes('text-lg font-semibold')
        with ui.row().classes('items-center gap-2'):
            ui.button('Home', on_click=lambda: ui.navigate.to('/')).props('flat').classes('text-white')

    # preload metals for filter
    try:
        metals = await fetch_metals()
        metal_options = ['All'] + sorted([m['name'] for m in metals if 'name' in m])
    except Exception:
        metal_options = ['All']

    selected: Dict[str, Any] | None = None

    with ui.splitter(value=60).classes('px-6').style('width:100%; height: calc(100vh - 140px);') as main_split:

        # LEFT: queue + filters
        with main_split.before:
            with ui.card().classes('w-full h-full p-0'):
                with ui.column().classes('w-full h-full').style('display:flex; flex-direction:column;'):

                    today_iso = date.today().isoformat()

                    with ui.row().classes('items-end gap-3 p-4').style('flex:0 0 auto;'):
                        ui.label('Flasks in Casting').classes('text-base font-semibold mr-4')
                        f_search = ui.input('Search by Flask No').props('clearable').classes('w-48')
                        d_from = ui.input('From', value=today_iso).props('type=date').classes('w-36')
                        d_to   = ui.input('To',   value=today_iso).props('type=date').classes('w-36')
                        metal_filter = ui.select(options=metal_options, value='All', label='Metal').classes('w-48')
                        metal_filter.props('options-dense behavior=menu popup-content-style="z-index:4000"')

                        async def reset_filters():
                            d_from.value = today_iso; d_to.value = today_iso
                            f_search.value = ''; metal_filter.value = 'All'
                            await refresh_table()
                            notify('Filters reset.', 'positive')

                        ui.button('RESET FILTERS', on_click=lambda: asyncio.create_task(reset_filters())).props('outline')

                    with ui.element('div').classes('fill-parent').style(
                        'flex:1 1 auto; overflow:auto; padding:0 16px 16px 16px; width:100%; max-width:100%;'
                    ):
                        columns = [
                            {'name': 'date', 'label': 'Date', 'field': 'date'},
                            {'name': 'flask_no', 'label': 'Flask No', 'field': 'flask_no'},
                            {'name': 'metal_name', 'label': 'Metal', 'field': 'metal_name'},
                            {'name': 'metal_weight', 'label': 'Req. Metal', 'field': 'metal_weight'},
                        ]
                        casting_table = ui.table(columns=columns, rows=[]) \
                                          .props('dense flat bordered row-key="id" selection="single" hide-bottom') \
                                          .classes('w-full text-sm')

        # RIGHT: GIANT details + post button
        with main_split.after:
            with ui.card().classes('w-full h-full p-6 flex flex-col items-start justify-start'):
                ui.label('Casting Details').classes('text-2xl font-semibold mb-4')

                # Big identifiers
                flask_no_lbl = ui.label('Flask: —').classes('text-4xl font-extrabold')
                metal_lbl    = ui.label('Metal: —').classes('text-3xl font-bold text-gray-700')

                ui.separator().classes('my-4 w-full')

                # Huge temps (side-by-side on wide screens)
                with ui.grid(columns=2).classes('gap-6 w-full'):
                    with ui.card().classes('w-full flex flex-col items-center p-6'):
                        ui.label('Casting Temp').classes('text-lg text-gray-500')
                        cast_lbl = ui.label('—').classes('text-7xl font-extrabold num-shadow')
                    with ui.card().classes('w-full flex flex-col items-center p-6'):
                        ui.label('Oven Temp').classes('text-lg text-gray-500')
                        oven_lbl = ui.label('—').classes('text-7xl font-extrabold num-shadow')

                time_lbl = ui.label('').classes('text-gray-600 mt-4 text-lg')

                async def sync_selection():
                    nonlocal selected
                    row_list = casting_table.selected or []
                    selected = row_list[0] if row_list else None
                    with client:
                        if not selected:
                            flask_no_lbl.text = 'Flask: —'
                            metal_lbl.text = 'Metal: —'
                            cast_lbl.text = '—'
                            oven_lbl.text = '—'
                            time_lbl.text = ''
                        else:
                            flask_no_lbl.text = f"Flask: {selected.get('flask_no','—')}"
                            mname = selected.get('metal_name','—')
                            metal_lbl.text = f"Metal: {mname}"
                            cast_lbl.text = f"{casting_temp_for(mname):.0f}"
                            oven_lbl.text = f"{oven_temp_for(mname):.0f}"
                            time_lbl.text = ''

                casting_table.on('selection', lambda _e: asyncio.create_task(sync_selection()))

                async def post_to_quenching():
                    if not selected:
                        notify('Select a flask first.', 'warning'); return
                    try:
                        resp = await post_complete_casting(int(selected['id']))
                        notify('Moved to Quenching', 'positive')
                        completed = resp.get('completed_at', '')
                        if completed:
                            try:
                                dt = datetime.fromisoformat(completed.replace('Z', '+00:00'))
                                time_lbl.text = f"Completed at: {dt.strftime('%m-%d-%y %H:%M:%S')}"
                            except Exception:
                                time_lbl.text = f"Completed at: {completed}"
                        # remove from table and clear
                        with client:
                            casting_table.rows = [r for r in casting_table.rows if r['id'] != selected['id']]
                            casting_table.selected = []
                            casting_table.update()
                        await sync_selection()
                    except Exception as ex:
                        notify(str(ex), 'negative')

                ui.button('POST TO QUENCHING', on_click=lambda: asyncio.create_task(post_to_quenching())) \
                  .classes('bg-emerald-600 text-white mt-6 text-2xl py-4 px-6 rounded-xl shadow-lg')

    # -------- filters & refresh --------
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
            if needle and needle not in str(r.get('flask_no','')).lower():
                continue

            rr = dict(r)
            rr['_sort_ord'] = -d.toordinal()                 # date DESC
            rr['_sort_metal'] = rr.get('metal_name') or ''   # metal ASC
            rr['_sort_flask'] = str(rr.get('flask_no',''))   # flask ASC
            rr['_display_date'] = to_ui_date(d_iso)
            out.append(rr)

        out.sort(key=lambda x: (x['_sort_ord'], x['_sort_metal'], x['_sort_flask']))
        for rr in out:
            rr['date'] = rr['_display_date']
            for k in ('_sort_ord','_sort_metal','_sort_flask','_display_date'):
                rr.pop(k, None)
        return out

    async def refresh_table():
        try:
            raw = await fetch_casting_queue(flask_no=(f_search.value or '').strip() or None)
        except Exception as e:
            notify(f'Failed to fetch casting queue: {e}', 'negative')
            raw = []
        rows = _apply_filters(raw)
        casting_table.rows = rows
        casting_table.update()

    # events
    metal_filter.on('update:model-value', lambda _v: asyncio.create_task(refresh_table()))
    f_search.on('change', lambda _e: asyncio.create_task(refresh_table()))
    d_from.on('change',  lambda _e: asyncio.create_task(refresh_table()))
    d_to.on('change',    lambda _e: asyncio.create_task(refresh_table()))

    # initial
    await asyncio.create_task(refresh_table())
