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
    
def to_mmdd(iso: str) -> str:
    try:
        return datetime.strptime(iso, '%Y-%m-%d').strftime('%m/%d')
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
    'casting_metal_in': 'Casting Metal In',
    'casting': 'Casting',
    'casting_metal_out': 'Casting Metal Out',
    'quenching': 'Quenching',
    'cutting': 'Cutting',
    'reconciliation': 'Reconciliation',
    'job_bag_supply': 'Job Bag Supply',
    'done': 'Done',
}
LABEL_TO_STAGE = {v: k for k, v in STAGE_LABELS.items()}
STAGE_ORDER = {
    'transit': 0, 'metal_prep': 1, 'casting_metal_in': 2, 'casting': 3, 'casting_metal_out': 4,
    'quenching': 5, 'cutting': 6, 'reconciliation': 7, 'job_bag_supply': 8, 'done': 9,
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
    
async def fetch_weight_history(flask_id: int) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=15.0) as c:
        r = await c.get(f'{API_URL}/search/flasks/{flask_id}/weight_history')
        r.raise_for_status()
        return r.json()

async def fetch_tree_weight_history(tree_id: int) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=15.0) as c:
        r = await c.get(f'{API_URL}/search/trees/{tree_id}/weight_history')
        r.raise_for_status()
        return r.json()

async def update_flask_bags(flask_id: int, bag_nos: List[str]) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=15.0) as c:
        r = await c.put(f'{API_URL}/search/flasks/{flask_id}/bags', json={'bag_nos': bag_nos})
        r.raise_for_status()
        return r.json()

async def update_tree_bags(tree_id: int, bag_nos: List[str]) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=15.0) as c:
        r = await c.put(f'{API_URL}/search/trees/{tree_id}/bags', json={'bag_nos': bag_nos})
        r.raise_for_status()
        return r.json()


@ui.page('/flask-search')
async def flask_search(client: Client):

    # # ---------------- Weight History Dialog ----------------
    # history_dialog = ui.dialog()
    # history_title = ui.label('')
    # history_kv = ui.column().classes('gap-2')

    # ---------------- Weight History Dialog ----------------
    with ui.dialog() as history_dialog:
        with ui.card().classes('w-[720px] max-w-[92vw] p-6 relative'):
            with ui.row().classes('w-full items-center justify-between'):
                history_title = ui.label('').classes('text-xl font-semibold')
                ui.button('✕', on_click=history_dialog.close).props('flat').classes('text-gray-600 text-lg')
            ui.separator().classes('my-4')
            history_kv = ui.column().classes('gap-2')

    # ---------------- Edit Bags Dialog ----------------
    with ui.dialog() as edit_bags_dialog:
        with ui.card().classes('w-[720px] max-w-[92vw] p-6 relative'):
            with ui.row().classes('w-full items-center justify-between'):
                edit_bags_title = ui.label('Edit Bags').classes('text-xl font-semibold')
                ui.button('✕', on_click=edit_bags_dialog.close).props('flat').classes('text-gray-600 text-lg')

            ui.separator().classes('my-4')

            edit_bags_help = ui.label('').classes('text-sm text-gray-500 mb-2')
            chips_wrap = ui.row().classes('w-full flex-wrap gap-2')

            with ui.row().classes('w-full items-end gap-2 mt-3'):
                new_bag_inp = ui.input('Add bag').props('dense clearable').classes('w-64')
                # ui.button('ADD', on_click=lambda: None).props('outline dense')  # we’ll bind below
                # ui.button('ADD', on_click=_add_bag).props('outline dense')
                add_btn = ui.button('ADD').props('outline dense')



            ui.separator().classes('my-4')

            with ui.row().classes('w-full justify-end gap-2'):
                ui.button('CANCEL', on_click=edit_bags_dialog.close).props('outline')
                # save_bags_btn = ui.button('SAVE', on_click=lambda: None).props('color=primary')
                save_bags_btn = ui.button('SAVE', on_click=lambda: asyncio.create_task(_save_bags())).props('color=primary')



    def notify(msg: str, color='primary'):
        with client:
            ui.notify(msg, color=color)

    ui.page_title('Flask Search · Casting Tracker')

    ui.add_head_html('''
    <style>
      .fill-parent{width:100%!important;max-width:100%!important}
      .fixed-table .q-table__container table{table-layout:fixed}
      .chip-row{
                     display:flex;
                     flex-wrap: wrap;
                     gap:6px; 
                     overflow:visible; 
                     width:100%; 
                     padding:2px 0
                }
    </style>
    ''')

    ui.add_head_html("""
    <style>
        .sticky-headers .q-table__container thead th {
        position: sticky;
        top: 0;
        z-index: 5;               /* keep above rows */
        background: #fff;         /* match table background */
        }
    </style>
    """)


    # header like Trees
    with ui.header().classes('items-center justify-between bg-gray-900 text-white'):
        ui.label('Flask Search').classes('text-lg font-semibold')
        # ui.button(icon='home', on_click=lambda: ui.navigate.to('/')).props('flat round').classes('text-white')
        with ui.row().classes('items-center gap-2'):
            ui.button('← Inventory', on_click=lambda: ui.navigate.to('/dept/inventory')).props('flat').classes('text-white font-semibold')
            ui.button('← Job Bag Supply', on_click=lambda: ui.navigate.to('/dept/job-bag')).props('flat').classes('text-white font-semibold')
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
                    {'name':'metal_weight','label':'Req. Metal Weight','field':'metal_weight','headerStyle':'width:130px','style':'width:130px'},
                    # {'name':'bag_nos','label':'Bags','field':'bag_nos','headerStyle':'width:280px','style':'width:280px; overflow:hidden;'},
                    {'name':'bag_nos','label':'Bags','field':'bag_nos','headerStyle':'text-align:left;width:calc(100% - 830px)','style':'width:calc(100% - 830px);overflow:hidden;'},
                    {'name':'photo','label':'Photo','field':'photo_url','headerStyle':'width:90px','style':'width:90px'},
                ]
                table = ui.table(columns=columns, rows=[]) \
                          .props('dense flat bordered row-key="id" hide-bottom table-class="fixed-table" table-style="table-layout: fixed" table-header-style="text-align:left"') \
                          .classes('w-full text-sm sticky-headers')
                

                # table = ui.table(columns=columns, rows=[]) \
                #     .props('dense flat bordered row-key="id" hide-bottom sticky-header') \
                #     .style('max-height: 80vh;') \
                #     .classes('w-full text-sm')
                # table = ui.table(columns=columns, rows=[]) \
                #     .props('dense flat bordered row-key="id" hide-bottom sticky-header '
                #         'virtual-scroll virtual-scroll-item-size=44') \
                #     .style('height: 80vh;') \
                #     .classes('w-full text-sm')

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

                # table.add_slot('body-cell-photo', '''
                # <q-td :props="props">
                # <div v-if="props.row.photo_url" style="width:64px;height:64px;display:flex;align-items:center;justify-content:center;">
                #     <img :src="props.row.photo_url"
                #         alt="tree photo"
                #         style="width:64px;height:64px;object-fit:cover;border-radius:6px;border:1px solid #e5e7eb;"
                #         @click="window.open(props.row.photo_url, '_blank')">
                # </div>
                # </q-td>
                # ''')

                table.add_slot('body-cell-photo', f'''
                <q-td :props="props">
                <div v-if="props.row.photo_url" style="width:64px;height:64px;display:flex;align-items:center;justify-content:center;">
                    <a :href="(props.row.photo_url && props.row.photo_url[0]=='/' ? '{API_URL}'+props.row.photo_url : props.row.photo_url)"
                    target="_blank" rel="noopener">
                    <img
                        :src="(props.row.photo_url && props.row.photo_url[0]=='/' ? '{API_URL}'+props.row.photo_url : props.row.photo_url)"
                        alt="tree photo"
                        style="width:64px;height:64px;object-fit:cover;border-radius:6px;border:1px solid #e5e7eb;"
                    >
                    </a>
                </div>
                </q-td>
                ''')

                def on_row_click(e):
                    # Quasar q-table emits row-click with args: (evt, row, index)
                    # NiceGUI forwards those in e.args
                    print("ROW CLICK raw args:", e.args)

                    row = None
                    if isinstance(e.args, list):
                        # often: [evt, row, idx]
                        for item in e.args:
                            if isinstance(item, dict) and ('id' in item or 'kind' in item):
                                row = item
                                break

                    if not row:
                        notify('Could not read row from click event (see console).', 'negative')
                        return

                    asyncio.create_task(open_weight_history(row))

                table.on('row-click', on_row_click)



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

    def _fmt_num(v):
        if v is None:
            return '—'
        try:
            return f'{float(v):.2f}'
        except Exception:
            return str(v)

    # def _kv(label: str, value: str):
    #     with ui.row().classes('w-full justify-between'):
    #         ui.label(label).classes('text-gray-600')
    #         ui.label(value).classes('font-semibold')

    def _kv(label: str, value: str, *, red: bool = False, bold: bool = False):
        left_cls = 'text-gray-600'
        right_cls = 'font-semibold' if bold else ''
        if red:
            left_cls += ' text-red-600'
            right_cls += ' text-red-600'
        with ui.row().classes('w-full justify-between'):
            ui.label(label).classes(left_cls)
            ui.label(value).classes(right_cls)



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
    
    edit_state = {
        'kind': None,          # 'flask' | 'tree'
        'rid': None,           # int flask_id OR int tree_id
        'row': None,           # original table row dict
        'bags': [],            # editable list
    }

    def _render_edit_chips():
        chips_wrap.clear()
        with chips_wrap:
            if not edit_state['bags']:
                ui.label('No bags').classes('text-gray-400')
                return
            for b in edit_state['bags']:
                with ui.row().classes('items-center gap-1'):
                    ui.chip(b, color='primary', text_color='white').props('dense')
                    ui.button('✕', on_click=lambda b=b: _remove_bag(b)) \
                        .props('flat dense').classes('text-red-600')

    def _remove_bag(b: str):
        edit_state['bags'] = [x for x in edit_state['bags'] if x != b]
        _render_edit_chips()

    def _add_bag():
        b = (new_bag_inp.value or '').strip()
        if not b:
            return
        b = b.upper()
        if b not in edit_state['bags']:
            edit_state['bags'].append(b)
        new_bag_inp.value = ''
        _render_edit_chips()

    add_btn.on('click', lambda e: _add_bag())


    async def _save_bags():
        try:
            kind = edit_state['kind']
            rid = edit_state['rid']
            bags = edit_state['bags']

            # print("SAVE BAGS kind=", kind, "rid=", rid, "bags=", bags)


            if kind == 'tree':
                await update_tree_bags(int(rid), bags)
            else:
                await update_flask_bags(int(rid), bags)

            notify('Bags updated.', 'positive')
            edit_bags_dialog.close()

            # Refresh table + reopen history with updated bags
            await refresh_table()
            if edit_state['row']:
                await open_weight_history(edit_state['row'])

        except httpx.HTTPStatusError as e:
            notify(explain_http_error(e), 'negative')
        except Exception as e:
            notify(f'Failed to save bags: {e}', 'negative')

    # bind buttons
    # replace the placeholder handlers above:
    # - ADD button
    # - SAVE button
    # (NiceGUI lets us reassign on_click by creating new buttons, but simplest is use .on)
    new_bag_inp.on('keydown.enter', lambda _e: _add_bag())
    # Find the ADD button created above and bind it by recreating it if needed; easiest approach:



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

    # async def open_weight_history(row: Dict[str, Any]):
    #     kind = row.get('kind')  # backend sends this (tree/flask)
    #     rid = row.get('id')

    #     try:
    #         if kind == 'tree':
    #             # id looks like "tree-12"
    #             if isinstance(rid, str) and rid.startswith('tree-'):
    #                 tree_id = int(rid.split('-', 1)[1])
    #             else:
    #                 notify('Invalid tree id', 'negative')
    #                 return
    #             data = await fetch_tree_weight_history(tree_id)
    #             title_left = data.get('tree_no', 'Tree')
    #         else:
    #             # flask kind
    #             flask_id = int(rid)
    #             data = await fetch_weight_history(flask_id)
    #             title_left = f"Flask {data.get('flask_no','—')}"

    #     except httpx.HTTPStatusError as e:
    #         notify(explain_http_error(e), 'negative')
    #         return
    #     except Exception as e:
    #         notify(f'Failed to load history: {e}', 'negative')
    #         return

    #     # Title
    #     history_title.text = f"{title_left} • {data.get('metal_name','—')}"

    #     # Fill dialog
    #     history_kv.clear()
    #     with history_kv:

    #         if data.get('est_metal_weight') is not None:
    #             ui.separator().classes('my-2')
    #             _kv('Estimated metal (Transit)', _fmt_num(data.get('est_metal_weight')))

    #         _kv('Gasket weight', _fmt_num(data.get('gasket_weight')))
    #         _kv('Total weight', _fmt_num(data.get('total_weight')))
    #         _kv('Tree weight (Total − Gasket)', _fmt_num(data.get('tree_weight')))

    #         ui.separator().classes('my-2')

    #         _kv('Required / calculated metal weight', _fmt_num(data.get('required_metal_weight')))
    #         _kv('Supplied weight', _fmt_num(data.get('supplied_weight')))
    #         _kv('Casting in wt', _fmt_num(data.get('casting_in_weight')))
    #         _kv('Casting out wt', _fmt_num(data.get('casting_out_weight')))

    #         ui.separator().classes('my-2')

    #         _kv('Cutting before wt', _fmt_num(data.get('cutting_before_weight')))
    #         _kv('Cutting after usable wt', _fmt_num(data.get('cutting_after_usable_weight')))
    #         _kv('Cutting after scrap wt', _fmt_num(data.get('cutting_after_scrap_weight')))

    #         ui.separator().classes('my-2')

    #         _kv('Loss in casting', _fmt_num(data.get('loss_in_casting')))
    #         _kv('Loss in cutting', _fmt_num(data.get('loss_in_cutting')))
    #         _kv('Total loss', _fmt_num(data.get('total_loss')))

    #     history_dialog.open()

    async def open_weight_history(row: Dict[str, Any]):
        kind = row.get('kind')  # backend sends this (tree/flask)
        rid = row.get('id')

        try:
            if kind == 'tree':
                if isinstance(rid, str) and rid.startswith('tree-'):
                    tree_id = int(rid.split('-', 1)[1])
                else:
                    notify('Invalid tree id', 'negative')
                    return
                data = await fetch_tree_weight_history(tree_id)
                # title_mid = data.get('tree_no', 'Tree')
                title_mid = f"Flask {data.get('flask_no', '—')}"
            else:
                flask_id = int(rid)
                data = await fetch_weight_history(flask_id)
                title_mid = f"Flask {data.get('flask_no','—')}"
        except httpx.HTTPStatusError as e:
            notify(explain_http_error(e), 'negative')
            return
        except Exception as e:
            notify(f'Failed to load history: {e}', 'negative')
            return

        date_mmdd = to_mmdd(data.get('date') or '')
        metal_name = data.get('metal_name') or '—'
        stage_label = data.get('stage_label') or (data.get('stage') or '—')

        # Title: date • flask/tree • metal
        history_title.text = f"{date_mmdd} • {title_mid} • {metal_name}"

        history_kv.clear()
        with history_kv:
            # stage line (small grey)
            ui.label(stage_label).classes('text-sm text-gray-500')

            # bag chips line
            # bags = data.get('bag_nos') or []
            # if bags:
            #     with ui.row().classes('w-full flex-wrap gap-2 mt-2'):
            #         for b in bags:
            #             ui.chip(str(b), color='primary', text_color='white').props('dense')
            # bag chips + edit button

            bags = data.get('bag_nos') or []
            with ui.row().classes('w-full items-start justify-between mt-2'):
                with ui.row().classes('flex-wrap gap-2'):
                    for b in bags:
                        ui.chip(str(b), color='primary', text_color='white').props('dense')

                # edit icon
                ui.button(icon='edit', on_click=lambda: _open_edit_bags(kind, rid, row, bags)) \
                    .props('flat round dense').classes('text-gray-600')

            ui.separator().classes('my-4')

            stage = data.get('stage') or ''
            stage_idx = STAGE_ORDER.get(stage, 99)

            # Transit trees: do not show any weight rows yet
            if kind == 'tree' and stage == 'transit':
                history_dialog.open()
                return

            def at_or_past(stage_slug: str) -> bool:
                return stage_idx >= STAGE_ORDER.get(stage_slug, 99)

            def has(v) -> bool:
                return v is not None

            # --- Transit tree special: show est metal if present ---
            # if kind == 'tree' and has(data.get('est_metal_weight')):
            #     _kv('Estimated metal (Transit)', _fmt_num(data.get('est_metal_weight')), bold=True)
            #     return

            # --- top weights (only show if recorded so far) ---
            if has(data.get('gasket_weight')): _kv('Gasket weight', _fmt_num(data.get('gasket_weight')))
            if has(data.get('total_weight')):  _kv('Total weight', _fmt_num(data.get('total_weight')))
            if has(data.get('tree_weight')):   _kv('Tree weight (Total − Gasket)', _fmt_num(data.get('tree_weight')))

            # required/supplied
            if has(data.get('required_metal_weight')) or has(data.get('supplied_weight')):
                ui.separator().classes('my-3')
                if has(data.get('required_metal_weight')):
                    _kv('Required / calculated metal weight', _fmt_num(data.get('required_metal_weight')), bold=True)
                # if has(data.get('supplied_weight')):
                #     _kv('Supplied weight', _fmt_num(data.get('supplied_weight')))
                supplied_val = data.get('metal_supplied_weight', data.get('supplied_weight'))
                if has(supplied_val):
                    _kv('Supplied weight', _fmt_num(supplied_val))


            # casting in/out + casting loss
            if has(data.get('casting_in_weight')) or has(data.get('casting_out_weight')):
                ui.separator().classes('my-3')
                # if has(data.get('casting_in_weight')):
                #     _kv('Casting in wt', _fmt_num(data.get('casting_in_weight')))
                casting_in_val = data.get('casting_in_weight', data.get('casting_in'))
                if has(casting_in_val):
                    _kv('Casting in weight', _fmt_num(casting_in_val))

                if has(data.get('casting_out_weight')):
                    _kv('Casting out weight', _fmt_num(data.get('casting_out_weight')))
                if has(data.get('loss_in_casting')):
                    _kv('Casting loss', _fmt_num(data.get('loss_in_casting')), red=True, bold=True)

            # cutting in/out + cutting loss
            if has(data.get('cutting_before_weight')) or has(data.get('cutting_after_usable_weight')) or has(data.get('cutting_after_scrap_weight')):
                ui.separator().classes('my-3')
                if has(data.get('cutting_before_weight')):
                    _kv('Cutting in weight', _fmt_num(data.get('cutting_before_weight')))
                if has(data.get('cutting_after_usable_weight')):
                    _kv('Cutting out weight (consumable)', _fmt_num(data.get('cutting_after_usable_weight')))
                if has(data.get('cutting_after_scrap_weight')):
                    _kv('Cutting out weight (scrap)', _fmt_num(data.get('cutting_after_scrap_weight')))
                if has(data.get('loss_in_cutting')):
                    _kv('Cutting loss', _fmt_num(data.get('loss_in_cutting')), red=True, bold=True)

            # --- Transit loss (two legs + total) ---
            # if has(data.get('transit_loss_mp_casting')) or has(data.get('transit_loss_casting_cutting')) or has(data.get('total_transit_loss')):
            #     ui.separator().classes('my-3')
            #     _kv('Transit loss (Metal Prep → Casting)', _fmt_num(data.get('transit_loss_mp_casting')))
            #     _kv('Transit loss (Casting → Cutting)', _fmt_num(data.get('transit_loss_casting_cutting')))
            #     _kv('Total transit loss', _fmt_num(data.get('total_transit_loss')), red=True, bold=True)

            tl_mc = data.get('transit_loss_mp_casting')
            tl_cc = data.get('transit_loss_casting_cutting')
            tl_total = data.get('total_transit_loss')


            show_tl_mc = at_or_past('casting_metal_in') and has(tl_mc)          # after casting metal in
            show_tl_cc = at_or_past('cutting') and has(tl_cc)                  # after cutting
            show_tl_total = show_tl_mc and has(tl_total)                       # show when first leg exists (as requested)

            if show_tl_mc or show_tl_cc or show_tl_total:
                ui.separator().classes('my-3')
                if show_tl_mc:
                    _kv('Transit loss (Metal Prep → Casting)', _fmt_num(tl_mc))
                if show_tl_cc:
                    _kv('Transit loss (Casting → Cutting)', _fmt_num(tl_cc))
                if show_tl_total:
                    _kv('Total transit loss', _fmt_num(tl_total), red=True, bold=True)

            # total loss (bold red)
            # if has(data.get('total_loss')):
            #     ui.separator().classes('my-3')
            #     _kv('Total loss', _fmt_num(data.get('total_loss')), red=True, bold=True)
            ui.separator().classes('my-3')
            _kv('Total loss', _fmt_num(data.get('total_loss')), red=True, bold=True)

        history_dialog.open()

    def _open_edit_bags(kind: str, rid: Any, row: Dict[str, Any], bags: List[str]):
        edit_state['kind'] = kind
        edit_state['row'] = row

        if kind == 'tree':
            # rid is like "tree-12"
            if isinstance(rid, str) and rid.startswith('tree-'):
                edit_state['rid'] = int(rid.split('-', 1)[1])
            else:
                notify('Invalid tree id', 'negative')
                return
            edit_bags_help.text = 'Editing bags for this TRANSIT TREE'
        else:
            edit_state['rid'] = int(rid)
            edit_bags_help.text = 'Editing bags for this FLASK'

        # copy list
        edit_state['bags'] = list(bags or [])
        _render_edit_chips()
        edit_bags_dialog.open()

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
