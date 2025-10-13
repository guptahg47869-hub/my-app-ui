from nicegui import ui, Client  # type: ignore
import httpx, os, asyncio  # type: ignore
from datetime import date, datetime
from typing import Any, Dict, List, Optional
import csv
from io import StringIO

API_URL = os.getenv('API_URL', 'http://localhost:8000')
print('UI using API_URL =', API_URL)

# ---------- helpers ----------
def to_ui_date(iso: str) -> str:
    try:
        return datetime.strptime(iso, '%Y-%m-%d').strftime('%m-%d-%y')
    except Exception:
        return iso

def explain_http_error(e: httpx.HTTPStatusError) -> str:
    try:
        data = e.response.json()
        if isinstance(data, dict) and 'detail' in data:
            return str(data['detail'])
        return str(data)
    except Exception:
        return e.response.text or str(e)

def rows_to_csv_bytes(rows: List[Dict[str, Any]], field_order: List[str]) -> bytes:
    buf = StringIO()
    writer = csv.DictWriter(buf, fieldnames=field_order, extrasaction='ignore')
    writer.writeheader()
    for r in rows:
        writer.writerow(r)
    return buf.getvalue().encode('utf-8-sig')

# ---------- API ----------
async def fetch_metals() -> List[Dict[str, Any]]:
    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.get(f'{API_URL}/metals')
        r.raise_for_status()
        return r.json()

async def fetch_transit_summary(date_from: str, date_to: str, metal: str | None):
    raw: Dict[str, Any] = {
        "date_from": date_from or None,
        "date_to":   date_to or None,
        "metal":     (None if not metal or metal == "All" else metal),
    }
    params = {k: v for k, v in raw.items() if v is not None}
    async with httpx.AsyncClient(timeout=15.0) as c:
        r = await c.get(f'{API_URL}/reports/transit', params=params)
        r.raise_for_status()
        return r.json()

async def fetch_transit_trees(date_from: str, date_to: str, metal: str):
    raw: Dict[str, Any] = {
        "date_from": date_from or None,
        "date_to":   date_to or None,
        "metal":     metal or None,
    }
    if raw["metal"] in (None, "", "All"):
        raw.pop("metal", None)
    params = {k: v for k, v in raw.items() if v is not None}
    async with httpx.AsyncClient(timeout=20.0) as c:
        r = await c.get(f'{API_URL}/reports/transit/trees', params=params)
        r.raise_for_status()
        return r.json()

async def fetch_scrap_loss(date_from: str, date_to: str, metal: Optional[str]):
    raw: Dict[str, Any] = {
        "date_from": date_from or None,
        "date_to":   date_to or None,
        "metal":     (None if not metal or metal == "All" else metal),
    }
    params = {k: v for k, v in raw.items() if v is not None}
    async with httpx.AsyncClient(timeout=20.0) as c:
        r = await c.get(f'{API_URL}/reports/scrap_loss', params=params)
        r.raise_for_status()
        return r.json()

async def fetch_scrap_reserves():
    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.get(f'{API_URL}/scrap/reserves')
        r.raise_for_status()
        return r.json()

# ---------- PAGE ----------
@ui.page('/reports')
async def reports_page(client: Client):
    def notify(msg: str, color='primary'):
        with client:
            ui.notify(msg, color=color)

    ui.page_title('Reports · Casting Tracker')
    ui.add_head_html('''
    <style>
      .fill-parent{width:100%!important;max-width:100%!important}
    </style>
    ''')

    with ui.header().classes('items-center justify-between bg-gray-900 text-white'):
        ui.label('Reports').classes('text-lg font-semibold')
        ui.button(icon='home', on_click=lambda: ui.navigate.to('/')).props('flat round').classes('text-white')

    # preload metals
    try:
        metals = await fetch_metals()
        metal_options = ['All'] + sorted([m['name'] for m in metals if 'name' in m])
    except Exception:
        metal_options = ['All']

    # ------------- Outer splitter: 50/50 left-right -------------
    with ui.splitter(value=50).classes('px-6').style('width:100%; height: calc(100vh - 140px);') as split:

        # -------- RIGHT PANEL (top/bottom via horizontal splitter): Scrap Loss + Scrap Reserve --------
        with split.after:
            with ui.splitter(value=45).props('horizontal').classes('w-full h-full') as right_split:
                # TOP: Scrap Loss
                with right_split.before:
                    with ui.card().classes('w-full h-full p-0'):
                        with ui.row().classes('items-end justify-between p-3 gap-2 w-full'):
                            with ui.row().classes('items-end gap-2'):
                                ui.label('Scrap Loss').classes('text-base font-semibold mr-2')
                                today_iso = date.today().isoformat()
                                loss_from = ui.input('From').props('type=date dense').classes('w-32')
                                loss_to   = ui.input('To').props('type=date dense').classes('w-32')
                                loss_metal = ui.select(options=metal_options, value='All', label='Metal').props('dense').classes('w-40')
                                loss_metal.props('options-dense behavior=menu popup-content-style="z-index:4000"')
                                async def reset_loss():
                                    loss_from.value = ''; loss_to.value = ''; loss_metal.value = 'All'
                                    await refresh_loss(); notify('Loss filters reset.', 'positive')
                                ui.button('RESET FILTERS', on_click=lambda: asyncio.create_task(reset_loss())) \
                                  .props('outline size=sm padding="xs md"')
                            export_loss_btn = ui.button('EXPORT (CSV)').props('unelevated color=primary size=sm padding="xs md"').classes('text-white')
                        with ui.element('div').classes('fill-parent').style(
                            'flex:1 1 auto; overflow:auto; padding:0 12px 12px 12px; width:100%; max-width:100%;'
                        ):
                            loss_columns = [
                                {'name': 'date', 'label': 'Date', 'field': 'date'},
                                {'name': 'flask_no', 'label': 'Flask No', 'field': 'flask_no'},
                                {'name': 'metal_name', 'label': 'Metal', 'field': 'metal_name'},
                                {'name': 'before_cut', 'label': 'Before Cut', 'field': 'before_cut_A'},
                                {'name': 'after_casting', 'label': 'After Casting', 'field': 'after_casting_C'},
                                {'name': 'after_scrap', 'label': 'After Scrap', 'field': 'after_scrap_B'},
                                {'name': 'loss', 'label': 'Scrap Loss', 'field': 'loss'},
                            ]
                            loss_table = ui.table(columns=loss_columns, rows=[]) \
                                          .props('dense flat bordered row-key="id" hide-bottom') \
                                          .classes('w-full text-sm')

                # BOTTOM: Scrap Reserve
                with right_split.after:
                    with ui.card().classes('w-full h-full p-0'):
                        with ui.row().classes('items-center justify-between p-3 gap-2 w-full'):
                            ui.label('Current Scrap Reserve').classes('text-base font-semibold')
                            with ui.row().classes('items-center gap-2'):
                                right_refresh_reserve_btn = ui.button('REFRESH').props('outline size=sm padding="xs md"')
                                export_reserve_btn = ui.button('EXPORT (CSV)').props('unelevated color=primary size=sm padding="xs md"').classes('text-white')
                        with ui.element('div').classes('fill-parent').style(
                            'flex:1 1 auto; overflow:auto; padding:0 12px 12px 12px; width:100%; max-width:100%;'
                        ):
                            reserve_columns = [
                                {'name': 'metal_name', 'label': 'Metal', 'field': 'metal_name'},
                                {'name': 'qty_on_hand', 'label': 'Qty on Hand', 'field': 'qty_on_hand'},
                            ]
                            reserve_table = ui.table(columns=reserve_columns, rows=[]) \
                                             .props('dense flat bordered row-key="metal_id" hide-bottom') \
                                             .classes('w-full text-sm')

        # -------- LEFT PANEL: Transit Summary + Drilldown (with TOTAL row) --------
        with split.before:
            with ui.card().classes('w-full h-full p-0'):
                with ui.column().classes('w-full h-full').style('display:flex; flex-direction:column;'):
                    today_iso = date.today().isoformat()
                    # filters + export (right-aligned; compact)
                    with ui.row().classes('items-end justify-between p-3 gap-2 w-full').style('flex:0 0 auto;'):
                        with ui.row().classes('items-end gap-2'):
                            ui.label('Transit Summary').classes('text-base font-semibold mr-2')
                            d_from = ui.input('From').props('type=date dense').classes('w-32')
                            d_to   = ui.input('To').props('type=date dense').classes('w-32')
                            metal_filter = ui.select(options=metal_options, value='All', label='Metal').props('dense').classes('w-40')
                            metal_filter.props('options-dense behavior=menu popup-content-style="z-index:4000"')
                            async def reset_summary():
                                d_from.value = ''; d_to.value = ''; metal_filter.value = 'All'
                                await refresh_summary(); notify('Filters reset.', 'positive')
                            ui.button('RESET FILTERS', on_click=lambda: asyncio.create_task(reset_summary())).props('outline size=sm padding="xs md"')
                        export_summary_btn = ui.button('EXPORT (CSV)').props('unelevated color=primary size=sm padding="xs md"').classes('text-white')

                    total_lbl = ui.label('Total in Transit: —').classes('px-3 pb-2 text-gray-700')

                    # summary table
                    with ui.element('div').classes('fill-parent').style(
                        'flex:1 1 auto; overflow:auto; padding:0 12px 0 12px; width:100%; max-width:100%;'
                    ):
                        sum_columns = [
                            {'name': 'metal_name', 'label': 'Metal', 'field': 'metal_name'},
                            {'name': 'count', 'label': '# Trees', 'field': 'count'},
                            {'name': 'total_est_metal_weight', 'label': 'Total Est. Metal', 'field': 'total_est_metal_weight'},
                        ]
                        summary_table = ui.table(columns=sum_columns, rows=[]) \
                                          .props('dense flat bordered row-key="metal_name" selection="single" hide-bottom') \
                                          .classes('w-full text-sm') 
                    

                    # drilldown title + export
                    with ui.row().classes('items-center justify-between px-3 pt-3 w-full'):
                        drill_title = ui.label('Details (select a metal to see trees)').classes('text-gray-700')
                        export_drill_btn = ui.button('EXPORT (CSV)').props('unelevated color=primary size=sm padding="xs md"').classes('text-white')

                    # drilldown table (TOTAL row inside)
                    with ui.element('div').classes('fill-parent').style(
                        'flex:1 1 auto; overflow:auto; padding:0 12px 12px 12px; width:100%; max-width:100%;'
                    ):
                        drill_columns = [
                            {'name': 'date', 'label': 'Date', 'field': 'date'},
                            {'name': 'tree_no', 'label': 'Tree No', 'field': 'tree_no'},
                            {'name': 'metal_name', 'label': 'Metal', 'field': 'metal_name'},
                            {'name': 'tree_weight', 'label': 'Tree Wt', 'field': 'tree_weight'},
                            {'name': 'est_metal_weight', 'label': 'Est. Metal', 'field': 'est_metal_weight'},
                        ]
                        drill_table = ui.table(columns=drill_columns, rows=[]) \
                                        .props('dense flat bordered row-key="tree_id" hide-bottom') \
                                        .classes('w-full text-sm')




                        # TOTAL row cells: bold + black
                        drill_table.add_slot('body-cell-date', '''
                        <q-td :props="props">
                        <span :class="props.row.is_total ? 'text-weight-bold' : ''"
                                :style="props.row.is_total ? 'font-weight:700;color:#000' : ''">
                            {{ props.row.date }}
                        </span>
                        </q-td>
                        ''')

                        drill_table.add_slot('body-cell-tree_no', '''
                        <q-td :props="props">
                        <span :class="props.row.is_total ? 'text-weight-bold' : ''"
                                :style="props.row.is_total ? 'font-weight:700;color:#000' : ''">
                            {{ props.row.tree_no }}
                        </span>
                        </q-td>
                        ''')

                        drill_table.add_slot('body-cell-metal_name', '''
                        <q-td :props="props">
                        <span :class="props.row.is_total ? 'text-weight-bold' : ''"
                                :style="props.row.is_total ? 'font-weight:700;color:#000' : ''">
                            {{ props.row.metal_name }}
                        </span>
                        </q-td>
                        ''')

                        drill_table.add_slot('body-cell-tree_weight', '''
                        <q-td :props="props">
                        <span :class="props.row.is_total ? 'text-weight-bold' : ''"
                                :style="props.row.is_total ? 'font-weight:700;color:#000' : ''">
                            {{ props.row.tree_weight }}
                        </span>
                        </q-td>
                        ''')

                        drill_table.add_slot('body-cell-est_metal_weight', '''
                        <q-td :props="props">
                        <span :class="props.row.is_total ? 'text-weight-bold' : ''"
                                :style="props.row.is_total ? 'font-weight:700;color:#000' : ''">
                            {{ props.row.est_metal_weight }}
                        </span>
                        </q-td>
                        ''')
                        
    # ---------- loaders & actions ----------
    async def refresh_summary():
        try:
            js = await fetch_transit_summary(d_from.value, d_to.value, metal_filter.value)
        except httpx.HTTPStatusError as e:
            notify(explain_http_error(e), 'negative'); return
        except Exception as ex:
            notify(str(ex), 'negative'); return

        rows = js.get('rows', [])
        for r in rows:
            r['total_est_metal_weight'] = round(float(r.get('total_est_metal_weight', 0.0)), 3)

        summary_table.rows = rows
        summary_table.selected = []
        summary_table.update()

        overall = js.get('overall_total', 0.0)
        f = to_ui_date(d_from.value); t = to_ui_date(d_to.value)
        total_lbl.text = f"Total in Transit ({f} → {t}, {metal_filter.value}): {overall:.1f}"

        # clear drilldown
        drill_title.text = 'Details (select a metal to see trees)'
        drill_table.rows = []
        drill_table.update()

    async def refresh_drilldown(metal_name: str):
        if not metal_name or metal_name == 'All':
            drill_title.text = 'Details (select a metal to see trees)'
            drill_table.rows = []; drill_table.update()
            return
        try:
            rows = await fetch_transit_trees(d_from.value, d_to.value, metal_name)
        except httpx.HTTPStatusError as e:
            notify(explain_http_error(e), 'negative'); return
        except Exception as ex:
            notify(str(ex), 'negative'); return

        # format & totals
        total_trees = len(rows)
        sum_tree_wt = 0.0
        sum_est = 0.0
        for r in rows:
            if 'date' in r:
                r['date'] = to_ui_date(r['date'])
            try:
                tw = float(r.get('tree_weight') or 0.0)
            except Exception:
                tw = 0.0
            try:
                em = float(r.get('est_metal_weight') or 0.0)
            except Exception:
                em = 0.0
            r['tree_weight'] = round(tw, 3)
            r['est_metal_weight'] = round(em, 3)
            sum_tree_wt += tw
            sum_est += em

        drill_title.text = f"Trees in Transit for {metal_name} ({to_ui_date(d_from.value)} → {to_ui_date(d_to.value)})"

        # TOTAL row inside table:
        totals_row = {
            'tree_id': '__TOTAL__',
            'date': 'TOTAL',                     # leftmost column
            'tree_no': str(total_trees),         # # trees (no parentheses)
            'metal_name': '',
            'tree_weight': round(sum_tree_wt, 3),
            'est_metal_weight': round(sum_est, 3),
            'is_total': True,
        }
        rows.append(totals_row)

        drill_table.rows = rows
        drill_table.update()

    async def refresh_loss():
        try:
            rows = await fetch_scrap_loss(loss_from.value, loss_to.value, loss_metal.value)
        except httpx.HTTPStatusError as e:
            notify(explain_http_error(e), 'negative'); return
        except Exception as ex:
            notify(str(ex), 'negative'); return

        for r in rows:
            if 'date' in r:
                r['date'] = to_ui_date(r['date'])
            r['before_cut_A'] = float(r.get('before_cut_A') or r.get('before_cut') or 0.0)
            r['after_casting_C'] = float(r.get('after_casting_C') or r.get('after_casting') or 0.0)
            r['after_scrap_B'] = float(r.get('after_scrap_B') or r.get('after_scrap') or 0.0)
            r['loss'] = round(float(r.get('loss', 0.0)), 3)

        loss_table.rows = rows
        loss_table.update()

    async def refresh_reserve():
        try:
            rows = await fetch_scrap_reserves()
        except httpx.HTTPStatusError as e:
            notify(explain_http_error(e), 'negative'); return
        except Exception as ex:
            notify(str(ex), 'negative'); return

        # sort A→Z and format qty
        try:
            rows.sort(key=lambda r: (r.get('metal_name') or '').lower())
        except Exception:
            pass
        for r in rows:
            try:
                r['qty_on_hand'] = round(float(r.get('qty_on_hand', 0.0)), 3)
            except Exception:
                pass

        reserve_table.rows = rows
        reserve_table.update()

    # selection & filter events
    def on_summary_select(_e):
        try:
            row_list = summary_table.selected or []
            metal_name = row_list[0]['metal_name'] if row_list else ''
        except Exception:
            metal_name = ''
        asyncio.create_task(refresh_drilldown(metal_name))
    summary_table.on('selection', on_summary_select)

    d_from.on('change', lambda _e: asyncio.create_task(refresh_summary()))
    d_to.on('change',   lambda _e: asyncio.create_task(refresh_summary()))
    metal_filter.on('update:model-value', lambda _v: asyncio.create_task(refresh_summary()))

    loss_from.on('change', lambda _e: asyncio.create_task(refresh_loss()))
    loss_to.on('change',   lambda _e: asyncio.create_task(refresh_loss()))
    loss_metal.on('update:model-value', lambda _v: asyncio.create_task(refresh_loss()))

    right_refresh_reserve_btn.on('click', lambda: asyncio.create_task(refresh_reserve()))

    # exports
    def export_summary():
        rows = summary_table.rows or []
        csv_bytes = rows_to_csv_bytes(rows, ['metal_name', 'count', 'total_est_metal_weight'])
        ui.download(csv_bytes, filename=f'transit_summary_{d_from.value}_{d_to.value}.csv')
    export_summary_btn.on('click', export_summary)

    def export_drill():
        rows = drill_table.rows or []
        csv_bytes = rows_to_csv_bytes(rows, ['date', 'tree_no', 'metal_name', 'tree_weight', 'est_metal_weight'])
        ui.download(csv_bytes, filename=f'transit_trees_{d_from.value}_{d_to.value}.csv')
    export_drill_btn.on('click', export_drill)

    def export_loss():
        rows = loss_table.rows or []
        csv_bytes = rows_to_csv_bytes(rows, ['date', 'flask_no', 'metal_name', 'before_cut_A', 'after_casting_C', 'after_scrap_B', 'loss'])
        ui.download(csv_bytes, filename=f'scrap_loss_{loss_from.value}_{loss_to.value}.csv')
    export_loss_btn.on('click', export_loss)

    def export_reserve():
        rows = reserve_table.rows or []
        csv_bytes = rows_to_csv_bytes(rows, ['metal_name', 'qty_on_hand'])
        ui.download(csv_bytes, filename='scrap_reserve.csv')
    export_reserve_btn.on('click', export_reserve)

    # initial loads
    await asyncio.create_task(refresh_summary())
    await asyncio.create_task(refresh_loss())
    await asyncio.create_task(refresh_reserve())
