# pages/flask_search.py
from nicegui import ui, Client  # type: ignore
import httpx, os, asyncio
from typing import Any, Dict, List
from datetime import datetime
import csv
from io import StringIO

API_URL = os.getenv('API_URL', 'http://localhost:8000')
print('UI using API_URL =', API_URL)

def explain_http_error(e: httpx.HTTPStatusError) -> str:
    try:
        data = e.response.json()
        if isinstance(data, dict) and 'detail' in data:
            return str(data['detail'])
        return str(data)
    except Exception:
        return e.response.text or str(e)

def to_mmddyy(iso: str) -> str:
    try:
        return datetime.strptime(iso, '%Y-%m-%d').strftime('%m-%d-%y')
    except Exception:
        return iso
    
def rows_to_csv_bytes(rows, field_order):
    buf = StringIO()
    writer = csv.DictWriter(buf, fieldnames=field_order, extrasaction='ignore')
    writer.writeheader()
    for r in rows:
        writer.writerow(r)
    return buf.getvalue().encode('utf-8-sig')

# Display labels ↔ slugs
STAGE_LABELS = {
    'transit': 'Transit',
    'metal_prep': 'Metal Prep',
    'supply': 'Supply',
    'casting': 'Casting',
    'quenching': 'Quenching',
    'cutting': 'Cutting',
    'reconciliation': 'Reconciliation',
    'done': 'Done',
}
LABEL_TO_STAGE = {v: k for k, v in STAGE_LABELS.items()}
STAGE_ORDER = {
    'transit': 0, 'metal_prep': 1, 'supply': 2, 'casting': 3,
    'quenching': 4, 'cutting': 5, 'reconciliation': 6, 'done': 7,
}

async def fetch_metals() -> List[str]:
    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.get(f'{API_URL}/metals')
        r.raise_for_status()
        data = r.json()
        return [m['name'] for m in data if 'name' in m]

async def fetch_search(params: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Backend expects: date_from, date_to, stage, metal, flask_no, tree_no, bag_no."""
    # Debug: see exactly what is being sent
    print('SEARCH params =>', params)
    async with httpx.AsyncClient(timeout=20.0) as c:
        r = await c.get(f'{API_URL}/search/flasks', params=params)
        r.raise_for_status()
        return r.json()

@ui.page('/flask-search')
async def flask_search(client: Client):
    def notify(msg: str, color='primary'):
        with client:
            ui.notify(msg, color=color)

    ui.page_title('Flask Search · Casting Tracker')

    ui.add_head_html('''
    <style>
      .fill-parent{width:100%!important;max-width:100%!important}
      .fixed-table .q-table__container table{table-layout:fixed}
      .chip-row{display:flex;gap:6px; overflow-x:auto; width:100%; padding:2px 0}
    </style>
    ''')

    # header like Trees
    with ui.header().classes('items-center justify-between bg-gray-900 text-white'):
        ui.label('Flask Search').classes('text-lg font-semibold')
        ui.button(icon='home', on_click=lambda: ui.navigate.to('/')).props('flat round').classes('text-white')

    # preload metals
    try:
        metal_options = ['All'] + sorted(await fetch_metals())
    except Exception as e:
        metal_options = ['All']
        notify(f'Failed to load metals: {e}', 'negative')

    stage_options = ['All'] + [STAGE_LABELS[s] for s in STAGE_ORDER.keys()]

    with ui.element('div').classes('w-full').style('height: calc(100vh - 120px);'):
        with ui.card().classes('w-full h-full p-0').props('flat'):
            # --- filters ---
            with ui.row().classes('items-end gap-3 p-4').style('flex:0 0 auto;'):
                ui.label('Filters').classes('text-base font-semibold mr-2')

                # three separate searches
                flask_input = ui.input('Flask No').props('clearable dense').classes('w-36')
                tree_input  = ui.input('Tree No').props('clearable dense').classes('w-40')
                bag_input   = ui.input('Bag No').props('clearable dense').classes('w-48')

                date_from = ui.input('From').props('type=date dense clearable').classes('w-38')
                date_to   = ui.input('To').props('type=date dense clearable').classes('w-38')

                metal_pick = ui.select(options=metal_options, value='All', label='Metal') \
                               .classes('w-44').props('dense options-dense behavior=menu')
                stage_pick = ui.select(options=stage_options, value='All', label='Stage') \
                               .classes('w-44').props('dense options-dense behavior=menu')

                async def reset_filters():
                    flask_input.value = ''
                    tree_input.value  = ''
                    bag_input.value   = ''
                    date_from.value   = ''
                    date_to.value     = ''
                    metal_pick.value  = 'All'
                    stage_pick.value  = 'All'
                    await refresh_table()
                    notify('Filters reset.', 'positive')

                ui.button('RESET FILTERS', on_click=lambda: asyncio.create_task(reset_filters())) \
                  .props('outline').classes('q-ml-md')
                
                def export_csv():
                    # choose the same columns you show in the table
                    # NOTE: 'bag_nos_text' is a CSV-friendly version of the chips column
                    field_order = ['date', 'stage_label', 'metal_name', 'flask_no', 'tree_no', 'metal_weight', 'bag_nos_text']

                    rows = table.rows or []     # <-- your table variable
                    csv_bytes = rows_to_csv_bytes(rows, field_order)

                    # nice, safe filename even if filters are blank
                    df = (date_from.value or '').replace('/', '-') or 'all'
                    dt = (date_to.value or '').replace('/', '-') or 'all'
                    ui.download(csv_bytes, filename=f'flask_search_{df}_{dt}.csv')

                # export_btn.on('click', export_csv)

                ui.button('EXPORT (CSV)', on_click=export_csv)\
                .props('color=primary').classes('q-ml-sm')

            # --- table ---
            with ui.element('div').classes('fill-parent').style('flex:1 1 auto; overflow:auto; padding:0 16px 16px 16px;'):
                columns = [
                    {'name':'date','label':'Date','field':'date','headerStyle':'width:130px','style':'width:130px'},
                    {'name':'stage_label','label':'Stage','field':'stage_label','headerStyle':'width:200px','style':'width:200px'},
                    {'name':'metal_name','label':'Metal','field':'metal_name','headerStyle':'width:180px','style':'width:180px'},
                    {'name':'flask_no','label':'Flask No','field':'flask_no','headerStyle':'width:120px','style':'width:120px'},
                    {'name':'tree_no','label':'Tree No','field':'tree_no','headerStyle':'width:200px','style':'width:200px'},
                    {'name':'metal_weight','label':'Metal Wt','field':'metal_weight','headerStyle':'width:130px','style':'width:130px'},
                    # {'name':'bag_nos','label':'Bags','field':'bag_nos','headerStyle':'width:280px','style':'width:280px; overflow:hidden;'},
                    {'name':'bag_nos','label':'Bags','field':'bag_nos','headerStyle':'width:calc(100% - 830px)','style':'width:calc(100% - 830px);overflow:hidden;'}
                ]
                table = ui.table(columns=columns, rows=[]) \
                          .props('dense flat bordered row-key="id" hide-bottom table-class="fixed-table" table-style="table-layout: fixed"') \
                          .classes('w-full text-sm')

                table.add_slot('body-cell-bag_nos', '''
                <q-td :props="props">
                  <div class="chip-row" style="width:100%">
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

    # ---------- data plumbing ----------
    def massage(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for r in rows:
            rr = dict(r)
            st = rr.get('stage') or ''
            rr['stage_label'] = STAGE_LABELS.get(st, st or '')
            rr['date'] = to_mmddyy(rr.get('date') or '')
            # sort helpers
            d_iso = r.get('date') or ''
            try:
                ord_date = datetime.strptime(d_iso, '%Y-%m-%d').date().toordinal()
            except Exception:
                ord_date = 0
            rr['_s_stage']  = STAGE_ORDER.get(st, 99)
            rr['_s_date']   = ord_date
            rr['_s_metal']  = rr.get('metal_name') or ''
            rr['_s_flask']  = rr.get('flask_no') or ''
            out.append(rr)
        out.sort(key=lambda x: (x['_s_stage'], x['_s_date'], x['_s_metal'], x['_s_flask']))
        for rr in out:
            rr.pop('_s_stage', None); rr.pop('_s_date', None); rr.pop('_s_metal', None); rr.pop('_s_flask', None)
        return out

    def _row_matches_local_filters(row: dict, flask_no: str, tree_no: str, bag_no: str) -> bool:
        """Front-end filter fallback (case-insensitive contains)."""
        f = (flask_no or '').strip().lower()
        t = (tree_no  or '').strip().lower()
        b = (bag_no   or '').strip().lower()

        if f:
            if not str(row.get('flask_no') or '').lower().__contains__(f):
                return False
        if t:
            if not str(row.get('tree_no') or '').lower().__contains__(t):
                return False
        if b:
            # match either the pre-joined text or the list of bags
            text = str(row.get('bag_nos_text') or '').lower()
            bags = [str(x).lower() for x in (row.get('bag_nos') or [])]
            if b not in text and all(b not in one for one in bags):
                return False
        return True


    async def refresh_table():
        # --- build query params exactly once ---
        params: Dict[str, Any] = {}

        # normalize dates
        df = (date_from.value or '').strip()
        dt = (date_to.value or '').strip()

        # optional guard: if both set and From > To, just swap or warn
        if df and dt and df > dt:
            notify('From date cannot be after To date', 'warning')
            # either swap or early-return; swapping shown here
            df, dt = dt, df
            date_from.value, date_to.value = df, dt

        if df: params['date_from'] = df
        if dt: params['date_to']   = dt

        # if date_from.value: params['date_from'] = date_from.value
        # if date_to.value:   params['date_to']   = date_to.value

        stage_label = stage_pick.value or 'All'
        if stage_label != 'All':
            params['stage'] = LABEL_TO_STAGE.get(stage_label, stage_label)

        metal_val = metal_pick.value or 'All'
        if metal_val != 'All':
            params['metal'] = metal_val

        fi = (flask_input.value or '').strip()
        ti = (tree_input.value  or '').strip()
        bi = (bag_input.value   or '').strip()
        if fi: params['flask_no'] = fi
        if ti: params['tree_no']  = ti
        if bi: params['bag_no']   = bi

        try:
            rows = await fetch_search(params)
            # helpful debug so you can see what the backend returned
            print('RESULT rows =>', len(rows))
        except httpx.HTTPStatusError as e:
            notify(explain_http_error(e), 'negative')
            rows = []
        except Exception as e:
            notify(str(e), 'negative')
            rows = []

        # --- front-end fallback filter (only narrows the set, never expands) ---
        if any([fi, ti, bi]):
            rows = [r for r in rows if _row_matches_local_filters(r, fi, ti, bi)]

        # massage + render
        table.rows = massage(rows)
        table.update()

    # async def refresh_table():
    #     # build params explicitly; only include keys when they have values
    #     params: Dict[str, Any] = {}
    #     if date_from.value: params['date_from'] = date_from.value
    #     if date_to.value:   params['date_to']   = date_to.value

    #     stage_label = stage_pick.value or 'All'
    #     if stage_label != 'All':
    #         params['stage'] = LABEL_TO_STAGE.get(stage_label, stage_label)

    #     metal_val = metal_pick.value or 'All'
    #     if metal_val != 'All':
    #         params['metal'] = metal_val

    #     fi = (flask_input.value or '').strip()
    #     ti = (tree_input.value or '').strip()
    #     bi = (bag_input.value or '').strip()
    #     if fi: params['flask_no'] = fi
    #     if ti: params['tree_no']  = ti
    #     if bi: params['bag_no']   = bi

    #     try:
    #         rows = await fetch_search(params)
    #     except httpx.HTTPStatusError as e:
    #         notify(explain_http_error(e), 'negative')
    #         rows = []
    #     except Exception as e:
    #         notify(str(e), 'negative')
    #         rows = []
    #     table.rows = massage(rows)
    #     table.update()

    # debounce + handlers
    debounce = {'task': None}
    def schedule_refresh(delay: float = 0.25):
        async def _do():
            await asyncio.sleep(delay)
            await refresh_table()
        if debounce['task']:
            try: debounce['task'].cancel()
            except: pass
        debounce['task'] = asyncio.create_task(_do())

    for el in (flask_input, tree_input, bag_input):
        el.on('update:model-value', lambda _v: schedule_refresh())
        el.on('keydown.enter', lambda _e: asyncio.create_task(refresh_table()))

    # for el in (date_from, date_to):
    #     el.on('update:model-value', lambda _v: asyncio.create_task(refresh_table()))

    # --- replace your current date handlers with this helper ---
    def bind_date_input(inp):
        # fired when value changes as you type or by picker
        inp.on('update:model-value', lambda _v: asyncio.create_task(refresh_table()))
        # fired on blur / browser-native date change
        inp.on('change',              lambda _v: asyncio.create_task(refresh_table()))
        # fired when the clearable 'x' is clicked
        inp.on('clear',               lambda _v: asyncio.create_task(refresh_table()))

    bind_date_input(date_from)
    bind_date_input(date_to)

    metal_pick.on('update:model-value', lambda _v: asyncio.create_task(refresh_table()))
    stage_pick.on('update:model-value',  lambda _v: asyncio.create_task(refresh_table()))

    await refresh_table()
