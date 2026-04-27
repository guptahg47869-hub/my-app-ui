# jewelry-casting-ui/pages/casting.py
from nicegui import ui, Client # type: ignore
import httpx, os, asyncio   # type: ignore
from datetime import date, datetime, timedelta
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
    elif "SILVER" in n: temp = 1000
    elif "18W" in n: temp = 1050
    elif "18Y" in n: temp = 1060
    elif "18R" in n: temp = 1100
    elif "PLATINUM" in n: temp = 1900
    return float(temp)

def oven_temp_for(metal_name: str) -> float:
    n = (metal_name or '').upper()
    temp = 1000
    if "10" in n: temp = 1100
    elif "14W" in n: temp = 1050
    elif "14Y" in n: temp = 1050
    elif "14R" in n: temp = 1050
    elif "SILVER" in n: temp = 1020
    elif "18W" in n: temp = 1050
    elif "18Y" in n: temp = 1050
    elif "18R" in n: temp = 1020
    elif "PLATINUM" in n: temp = 1400
    return float(temp)

# ---------- API ----------
async def fetch_metals() -> List[Dict[str, Any]]:
    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.get(f'{API_URL}/metals')
        r.raise_for_status()
        return r.json()

async def fetch_casting_queue(flask_no: str | None = None) -> List[Dict[str, Any]]:
    # params = {}
    # if flask_no:
    #     params['flask_no'] = flask_no
    async with httpx.AsyncClient(timeout=15.0) as c:
        # r = await c.get(f'{API_URL}/queue/casting', params=params or None)
        r = await c.get(f'{API_URL}/queue/casting')
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

async def patch_metal_temps(metal_id: int, casting_temp: float | None, oven_temp: float | None) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=15.0) as c:
        r = await c.patch(
            f'{API_URL}/metals/{metal_id}/temps',
            json={
                "casting_temp": casting_temp,
                "oven_temp": oven_temp,
                "updated_by": "casting_ui",
            },
        )
        r.raise_for_status()
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
            # ui.button(icon='home', on_click=lambda: ui.navigate.to('/')).props('flat round').classes('text-white')
            ui.button('← Casting Dept', on_click=lambda: ui.navigate.to('/dept/casting')).props('flat').classes('text-white font-semibold')

    # preload metals for filter
    try:
        metals = await fetch_metals()
        metal_options = ['All'] + sorted([m['name'] for m in metals if 'name' in m])
        metal_by_name = {m['name']: m for m in metals if 'name' in m}

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

                    with ui.element('div').classes('fill-parent').style(
                        'flex:1 1 auto; overflow:auto; padding:0 16px 16px 16px; width:100%; max-width:100%;'
                    ):
                        columns = [
                            {'name': 'date', 'label': 'Date', 'field': 'date'},
                            {'name': 'flask_no', 'label': 'Flask No', 'field': 'flask_no'},
                            {'name': 'tree_no',  'label': 'Tree No',  'field': 'tree_no'},
                            {'name': 'metal_name', 'label': 'Metal', 'field': 'metal_name'},
                            {'name': 'metal_weight', 'label': 'Casting In Weight', 'field': 'metal_weight'},
                        ]
                        casting_table = ui.table(columns=columns, rows=[]) \
                                          .props('dense flat bordered row-key="id" selection="single" hide-bottom') \
                                          .classes('w-full text-sm')
                        
                        # make entire row red (text-negative) when props.row._is_old == True,
                        # using the same slot pattern as quenching's colored "Time Left" cell
                        casting_table.add_slot('body-cell-date', '''
                        <q-td :props="props">
                        <span :class="props.row._is_old ? 'text-negative' : ''">{{ props.row.date }}</span>
                        </q-td>
                        ''')

                        casting_table.add_slot('body-cell-flask_no', '''
                        <q-td :props="props">
                        <span :class="props.row._is_old ? 'text-negative' : ''">{{ props.row.flask_no }}</span>
                        </q-td>
                        ''')

                        casting_table.add_slot('body-cell-tree_no', '''
                        <q-td :props="props">
                        <span :class="props.row._is_old ? 'text-negative' : ''">{{ props.row.tree_no }}</span>
                        </q-td>
                        ''')

                        casting_table.add_slot('body-cell-metal_name', '''
                        <q-td :props="props">
                        <span :class="props.row._is_old ? 'text-negative' : ''">{{ props.row.metal_name }}</span>
                        </q-td>
                        ''')

                        casting_table.add_slot('body-cell-metal_weight', '''
                        <q-td :props="props">
                        <span :class="props.row._is_old ? 'text-negative' : ''">{{ props.row.metal_weight }}</span>
                        </q-td>
                        ''')


        # RIGHT: GIANT details + post button
        with main_split.after:
            # with ui.card().classes('w-full h-full p-6 flex flex-col items-start justify-start'):
            with ui.card().props('flat').classes('w-full h-full p-4 overflow-auto'):

                ui.label('Casting Details').classes('text-2xl font-semibold mb-4')

                # Big identifiers
                flask_no_lbl = ui.label('Flask: —').classes('text-4xl font-extrabold')
                metal_lbl    = ui.label('Metal: —').classes('text-3xl font-bold text-gray-700')

                ui.separator().classes('my-4 w-full')

                # Huge temps (side-by-side on wide screens)
                with ui.grid(columns=2).classes('gap-6 w-full'):

                    with ui.card().classes('w-full flex flex-col items-center p-6'):
                        ui.label('Casting Temp').classes('text-lg text-gray-500')
                        cast_lbl = ui.label('—').classes('text-6xl font-extrabold num-shadow')
                        suggest_cast_lbl = ui.label('Suggested temperature: —').classes('text-sm text-gray-500')
                        cast_edit = ui.number('Edit Casting Temp', value=0).props('step=1').classes('w-full')

                    with ui.card().classes('w-full flex flex-col items-center p-6'):
                        ui.label('Oven Temp').classes('text-lg text-gray-500')
                        oven_lbl = ui.label('—').classes('text-6xl font-extrabold num-shadow')
                        suggest_oven_lbl = ui.label('Suggested temperature: —').classes('text-sm text-gray-500')
                        oven_edit = ui.number('Edit Oven Temp', value=0).props('step=1').classes('w-full')

                    # with ui.row().classes('gap-2 mt-2'):
                    #     ui.button('SAVE TEMPS FOR METAL', on_click=lambda: asyncio.create_task(save_temps())).classes('bg-emerald-600 text-white')
                    #     ui.button('RESET TO SUGGESTED', on_click=lambda: asyncio.create_task(reset_to_suggested())).props('outline')
                    # buttons row: centered, smaller, both white
                with ui.row().classes('w-full justify-center gap-3 mt-2'):
                    ui.button('SAVE TEMPS', on_click=lambda: asyncio.create_task(save_temps())) \
                    .props('outline') \
                    .classes('bg-white text-gray-800 font-semibold text-sm px-4 py-2')

                    ui.button('RESET TO SUGGESTED', on_click=lambda: asyncio.create_task(reset_to_suggested())) \
                    .props('outline') \
                    .classes('bg-white text-gray-800 font-semibold text-sm px-4 py-2')


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

                            # NEW: suggested labels + edit fields reset
                            suggest_cast_lbl.text = 'Suggested temperature: —'
                            suggest_oven_lbl.text = 'Suggested temperature: —'
                            cast_edit.value = None
                            oven_edit.value = None
                            return

                        flask_no_lbl.text = f"Flask: {selected.get('flask_no','—')}"
                        mname = selected.get('metal_name', '—')
                        metal_lbl.text = f"Metal: {mname}"
                        time_lbl.text = ''

                        # Suggested temps (hardcoded logic)
                        try:
                            suggested_cast = float(casting_temp_for(mname))
                        except Exception:
                            suggested_cast = 0.0
                        try:
                            suggested_oven = float(oven_temp_for(mname))
                        except Exception:
                            suggested_oven = 0.0

                        suggest_cast_lbl.text = f"Suggested temperature: {suggested_cast:.0f}"
                        suggest_oven_lbl.text = f"Suggested temperature: {suggested_oven:.0f}"

                        # Override temps (from DB via GET /metals -> metal_by_name)
                        mrec = metal_by_name.get(mname, {}) if 'metal_by_name' in locals() else {}
                        override_cast = mrec.get('casting_temp_override', None)
                        override_oven = mrec.get('oven_temp_override', None)

                        # Display temps: override if present else suggested
                        try:
                            display_cast = float(override_cast) if override_cast is not None else suggested_cast
                        except Exception:
                            display_cast = suggested_cast

                        try:
                            display_oven = float(override_oven) if override_oven is not None else suggested_oven
                        except Exception:
                            display_oven = suggested_oven

                        cast_lbl.text = f"{display_cast:.0f}"
                        oven_lbl.text = f"{display_oven:.0f}"

                        # Prefill edit inputs to the current display
                        cast_edit.value = display_cast
                        oven_edit.value = display_oven

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

                # ui.button('POST TO QUENCHING', on_click=lambda: asyncio.create_task(post_to_quenching())) \
                #   .classes('bg-emerald-600 text-white mt-6 text-2xl py-4 px-6 rounded-xl shadow-lg')
                with ui.row().classes('w-full justify-center mt-8'):
                    ui.button('POST TO QUENCHING', on_click=lambda: asyncio.create_task(post_to_quenching())) \
                    .classes('bg-emerald-600 text-white text-lg py-3 px-6 rounded-xl shadow-lg')

    # -------- filters & refresh --------
    def _apply_filters(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        fdate = parse_iso_date(d_from.value)
        tdate = parse_iso_date(d_to.value)
        pick  = metal_filter.value or 'All'
        needle = (f_search.value or '').strip().lower()

        out: List[Dict[str, Any]] = []
        # yesterday cutoff (anything earlier than yesterday should be red)
        yday = date.today() - timedelta(days=1)

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
            rr['_is_old'] = bool(d < yday)          # <-- used by the slots above
            rr['_sort_ord'] = d.toordinal()         # <-- ASC (oldest first)
            rr['_sort_metal'] = rr.get('metal_name') or ''
            rr['_sort_flask'] = str(rr.get('flask_no',''))
            rr['_display_date'] = to_ui_date(d_iso)
            out.append(rr)

        # ASC by date now (then metal, then flask)
        out.sort(key=lambda x: (x['_sort_ord'], x['_sort_metal'], x['_sort_flask']))

        for rr in out:
            rr['date'] = rr['_display_date']
            for k in ('_sort_ord','_sort_metal','_sort_flask','_display_date'):
                rr.pop(k, None)
        return out

    async def refresh_table():
        nonlocal metals, metal_options, metal_by_name

        # 1) refresh metals so overrides reflect latest saved values
        try:
            metals = await fetch_metals()
            metal_by_name = {m['name']: m for m in metals if 'name' in m}

            # only rebuild options if you want it always fresh
            metal_options = ['All'] + sorted([m['name'] for m in metals if 'name' in m])
            # keep current selection if possible
            cur = metal_filter.value if hasattr(metal_filter, 'value') else 'All'
            metal_filter.options = metal_options
            if cur in metal_options:
                metal_filter.value = cur
            else:
                metal_filter.value = 'All'
        except Exception:
            # don’t hard-fail table refresh if metals refresh fails
            pass

        # 2) fetch queue rows
        try:
            raw = await fetch_casting_queue()
        except Exception as e:
            notify(f'Failed to fetch casting queue: {e}', 'negative')
            raw = []

        rows = _apply_filters(raw)

        # 3) preserve selection by flask_id (same pattern as other pages)
        selected_id = None
        try:
            if casting_table.selected:
                selected_id = casting_table.selected[0].get('flask_id')
        except Exception:
            selected_id = None

        with client:
            casting_table.rows = rows
            if selected_id is not None:
                re_row = next((r for r in rows if r.get('flask_id') == selected_id), None)
                casting_table.selected = [re_row] if re_row else []
            casting_table.update()

        # 4) refresh right panel values (so new metal overrides apply immediately)
        await sync_selection()

    async def save_temps():
        if not selected:
            notify('Select a flask first.', 'warning')
            return

        mname = selected.get('metal_name')
        if not mname or mname not in metal_by_name:
            notify('Metal not found for this flask.', 'negative')
            return

        metal_id = int(metal_by_name[mname]['id'])

        try:
            new_cast = float(cast_edit.value) if cast_edit.value is not None else None
            new_oven = float(oven_edit.value) if oven_edit.value is not None else None
        except Exception:
            notify('Invalid temperature values.', 'negative')
            return

        try:
            await patch_metal_temps(metal_id, new_cast, new_oven)
            # update local cache so UI immediately reflects saved values
            metal_by_name[mname]['casting_temp_override'] = new_cast
            metal_by_name[mname]['oven_temp_override'] = new_oven
            notify('Saved temps for metal.', 'positive')
            await sync_selection()
        except Exception as e:
            notify(f'Failed to save temps: {e}', 'negative')


    async def reset_to_suggested():
        if not selected:
            notify('Select a flask first.', 'warning')
            return

        mname = selected.get('metal_name')
        if not mname or mname not in metal_by_name:
            notify('Metal not found for this flask.', 'negative')
            return

        metal_id = int(metal_by_name[mname]['id'])

        # clearing override -> send nulls
        try:
            await patch_metal_temps(metal_id, None, None)
            metal_by_name[mname]['casting_temp_override'] = None
            metal_by_name[mname]['oven_temp_override'] = None
            notify('Reset to suggested temps.', 'positive')
            await sync_selection()
        except Exception as e:
            notify(f'Failed to reset temps: {e}', 'negative')


    # events
    metal_filter.on('update:model-value', lambda _v: asyncio.create_task(refresh_table()))
    f_search.on('change', lambda _e: asyncio.create_task(refresh_table()))
    d_from.on('change',  lambda _e: asyncio.create_task(refresh_table()))
    d_to.on('change',    lambda _e: asyncio.create_task(refresh_table()))

    # initial
    await asyncio.create_task(refresh_table())

