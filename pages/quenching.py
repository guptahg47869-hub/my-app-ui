from nicegui import ui, Client  # type: ignore
import httpx, os, asyncio  # type: ignore
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

API_URL = os.getenv('API_URL', 'http://localhost:8000')
print('UI using API_URL =', API_URL)

# ---- timezone helpers (EST/EDT) ----
try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    try:
        TZ_NY = ZoneInfo('America/New_York')
    except ZoneInfoNotFoundError:
        TZ_NY = datetime.now().astimezone().tzinfo  # fallback if tzdata not installed
except Exception:
    TZ_NY = datetime.now().astimezone().tzinfo

def to_est_hm(dt_aware: Optional[datetime]) -> str:
    if not dt_aware:
        return ''
    return dt_aware.astimezone(TZ_NY).strftime('%H:%M')

def parse_iso_dt_utc(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace('Z', '+00:00'))
        if dt.tzinfo is None:          # naive -> actually UTC from the API
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt
    except Exception:
        return None

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
    



# ---------- API calls ----------
async def fetch_metals() -> List[Dict[str, Any]]:
    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.get(f'{API_URL}/metals')
        r.raise_for_status()
        return r.json()

async def fetch_quenching_queue(flask_no: str | None = None) -> List[Dict[str, Any]]:
    # params = {}
    # if flask_no:
    #     params['flask_no'] = flask_no
    async with httpx.AsyncClient(timeout=15.0) as c:
        # r = await c.get(f'{API_URL}/queue/quenching', params=params or None)  # includes minutes_left, ready_at
        r = await c.get(f'{API_URL}/queue/quenching')  # includes minutes_left, ready_at
        r.raise_for_status()
        return r.json()

async def post_to_cutting(flask_id: int) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=15.0) as c:
        r = await c.post(f'{API_URL}/quenching/{flask_id}/post', json={'posted_by': 'quenching_ui'})
        try:
            r.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise RuntimeError(explain_http_error(e)) from e
        return r.json()

# ---------- PAGE ----------
@ui.page('/quenching')
async def quenching_page(client: Client):
    def notify(msg: str, color='primary'):
        with client:
            ui.notify(msg, color=color)

    ui.page_title('Quenching · Casting Tracker')
    ui.add_head_html('''
    <style>
      .fill-parent{width:100%!important;max-width:100%!important}
      .num-shadow{text-shadow:0 2px 8px rgba(0,0,0,.15)}
    </style>
    ''')

    with ui.header().classes('items-center justify-between bg-gray-900 text-white'):
        ui.label('Quenching Queue').classes('text-lg font-semibold')
        with ui.row().classes('items-center gap-2'):
            ui.button(icon='home', on_click=lambda: ui.navigate.to('/')).props('flat round').classes('text-white')

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
                        ui.label('Flasks in Quenching').classes('text-base font-semibold mr-4')
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
                            {'name': 'metal_weight', 'label': 'Req. Metal', 'field': 'metal_weight'},
                            {'name': 'ready_at_est', 'label': 'Ready At', 'field': 'ready_at_est'},
                            {'name': 'time_left', 'label': 'Time Left', 'field': 'time_left_display'},
                        ]
                        quench_table = ui.table(columns=columns, rows=[]) \
                                          .props('dense flat bordered row-key="id" selection="single" hide-bottom') \
                                          .classes('w-full text-sm')

                        # colorize the "Time Left" cell (red if DONE, yellow if <=2)
                        quench_table.add_slot('body-cell-time_left', '''
                        <q-td :props="props">
                          <span :class="props.row.minutes_left === 0 ? 'text-negative' : (props.row.minutes_left <= 2 ? 'text-warning' : '')">
                            {{ props.row.time_left_display }}
                          </span>
                        </q-td>
                        ''')

        # RIGHT: big-panel details + post
        with main_split.after:
            with ui.card().classes('w-full h-full p-6 flex flex-col items-start justify-start'):
                ui.label('Quenching Details').classes('text-2xl font-semibold mb-4')

                flask_no_lbl = ui.label('Flask: —').classes('text-4xl font-extrabold')
                metal_lbl    = ui.label('Metal: —').classes('text-3xl font-bold text-gray-700')

                ui.separator().classes('my-4 w-full')

                # === NEW: two tiles in a row: Ready At (left) + Time Left (right) ===
                with ui.grid(columns=2).classes('gap-6 w-full'):
                    with ui.card().classes('w-full flex flex-col items-center p-6'):
                        ui.label('Ready At (EST)').classes('text-lg text-gray-500')
                        ready_tile_lbl = ui.label('—').classes('text-7xl font-extrabold num-shadow')

                    with ui.card().classes('w-full flex flex-col items-center p-6'):
                        ui.label('Time Left (min)').classes('text-lg text-gray-500')
                        left_lbl = ui.label('—').classes('text-7xl font-extrabold num-shadow')

                def _set_time_color(ml: int | None):
                    # clear previous state
                    left_lbl.classes(remove='text-warning')
                    left_lbl.classes(remove='text-negative')
                    # apply new
                    if ml is None:
                        return
                    if ml == 0:
                        left_lbl.classes(add='text-negative')   # red
                    elif ml <= 2:
                        left_lbl.classes(add='text-warning')    # yellow


                async def sync_selection():
                    """Refresh the right panel using the *latest* row data after table updates."""
                    nonlocal selected
                    row_list = quench_table.selected or []
                    if row_list:
                        # Re-bind selection to the freshly-updated row with the same id
                        sel_id = row_list[0].get('id')
                        current = next((r for r in quench_table.rows if r.get('id') == sel_id), row_list[0])
                        selected = current
                    else:
                        selected = None

                    with client:
                        if not selected:
                            flask_no_lbl.text = 'Flask: —'
                            metal_lbl.text = 'Metal: —'
                            left_lbl.text = '—'
                            ready_tile_lbl.text = '—'
                            _set_time_color(None)

                        else:
                            flask_no_lbl.text = f"Flask: {selected.get('flask_no','—')}"
                            mname = selected.get('metal_name','—')
                            metal_lbl.text = f"Metal: {mname}"

                            ml = int(selected.get('minutes_left', 0) or 0)
                            left_lbl.text = 'DONE' if ml == 0 else f'{ml}'
                            _set_time_color(ml)

                            # prefer precomputed 'ready_at_est'; fall back to raw 'ready_at'
                            ra_est = (selected.get('ready_at_est') or '').strip()
                            if ra_est:
                                ready_tile_lbl.text = ra_est
                            else:
                                ra_raw = selected.get('ready_at', '')
                                dt_utc = parse_iso_dt_utc(ra_raw) if ra_raw else None
                                ready_tile_lbl.text = to_est_hm(dt_utc) if dt_utc else '—'

                quench_table.on('selection', lambda _e: asyncio.create_task(sync_selection()))

                async def advance_to_cutting():
                    if not selected:
                        notify('Select a flask first.', 'warning'); return
                    try:
                        await post_to_cutting(int(selected['id']))
                        notify('Moved to Cutting', 'positive')
                        # remove from table and clear
                        with client:
                            quench_table.rows = [r for r in quench_table.rows if r['id'] != selected['id']]
                            quench_table.selected = []
                            quench_table.update()
                        await sync_selection()
                    except Exception as ex:
                        notify(str(ex), 'negative')

                ui.button('POST TO CUTTING', on_click=lambda: asyncio.create_task(advance_to_cutting())) \
                  .classes('bg-emerald-600 text-white mt-6 text-2xl py-4 px-6 rounded-xl shadow-lg')

    # -------- filters & refresh --------
    def _apply_filters(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        fdate = parse_iso_date(d_from.value)
        tdate = parse_iso_date(d_to.value)
        pick  = metal_filter.value or 'All'
        needle = (f_search.value or '').strip().lower()

        out: List[Dict[str, Any]] = []
        now = datetime.now(timezone.utc)

        for r in rows:
            # date filtering
            d_iso = r.get('date') or ''
            d = parse_iso_date(d_iso)
            if not d:
                continue
            if fdate and d < fdate:
                continue
            if tdate and d > tdate:
                continue
            # metal filter
            if pick != 'All' and (r.get('metal_name') != pick):
                continue

            # search by flask or tree no
            hay = f"{r.get('flask_no','')} {r.get('tree_no','')}".lower()
            if needle and needle not in hay:
                continue

            # if needle and needle not in str(r.get('flask_no','')).lower():
            #     continue

            # compute time left and 'Ready At (EST)'
            ml = r.get('minutes_left')
            ra = r.get('ready_at')
            dt_ready_utc = parse_iso_dt_utc(ra) if ra else None
            if ml is None:
                if dt_ready_utc:
                    secs = (dt_ready_utc - now).total_seconds()
                    ml = int(max(0, secs // 60))
                else:
                    ml = 0

            rr = dict(r)
            rr['minutes_left'] = int(ml)
            rr['time_left_display'] = 'DONE' if rr['minutes_left'] == 0 else f"{rr['minutes_left']}"
            rr['ready_at_est'] = to_est_hm(dt_ready_utc) if dt_ready_utc else ''

            # sorting keys: minutes_left ASC, then date DESC, metal ASC, flask ASC
            rr['_sort_ml'] = rr['minutes_left']
            rr['_sort_ord'] = -d.toordinal()
            rr['_sort_metal'] = rr.get('metal_name') or ''
            rr['_sort_flask'] = str(rr.get('flask_no',''))
            rr['date'] = to_ui_date(d_iso)
            out.append(rr)

        out.sort(key=lambda x: (x['_sort_ml'], x['_sort_ord'], x['_sort_metal'], x['_sort_flask']))
        for rr in out:
            for k in ('_sort_ml','_sort_ord','_sort_metal','_sort_flask'):
                rr.pop(k, None)
        return out

    async def refresh_table():
        """Refresh table rows; keep the same selection (by id) and update right panel."""
        try:
            # raw = await fetch_quenching_queue(flask_no=(f_search.value or '').strip() or None)
            raw = await fetch_quenching_queue()
        except Exception as e:
            notify(f'Failed to fetch quenching queue: {e}', 'negative')
            raw = []

        rows = _apply_filters(raw)

        # --- preserve current selection by id and re-select in new rows ---
        selected_id = None
        try:
            if quench_table.selected:
                selected_id = quench_table.selected[0].get('id')
        except Exception:
            selected_id = None

        quench_table.rows = rows
        if selected_id is not None:
            re_row = next((r for r in rows if r.get('id') == selected_id), None)
            quench_table.selected = [re_row] if re_row else []
        quench_table.update()

        await sync_selection()

    # events
    metal_filter.on('update:model-value', lambda _v: asyncio.create_task(refresh_table()))
    f_search.on('change', lambda _e: asyncio.create_task(refresh_table()))
    d_from.on('change',  lambda _e: asyncio.create_task(refresh_table()))
    d_to.on('change',    lambda _e: asyncio.create_task(refresh_table()))

    # auto-refresh every 30s so countdown stays fresh
    ui.timer(30.0, lambda: asyncio.create_task(refresh_table()))

    # initial
    await asyncio.create_task(refresh_table())
