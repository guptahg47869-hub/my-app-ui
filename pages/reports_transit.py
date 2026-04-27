from nicegui import ui, Client  # type: ignore
import httpx, os, asyncio  # type: ignore
from datetime import date, datetime
from typing import Any, Dict, List
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

async def fetch_transit_trees(date_from: str, date_to: str, metal: str | None):
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

# ---------- PAGE ----------
@ui.page('/reports/transit')
async def reports_transit_page(client: Client):
    def notify(msg: str, color='primary'):
        with client:
            ui.notify(msg, color=color)

    ui.page_title('Transit Summary · Casting Tracker')
    ui.add_head_html('''
    <style>
      .fill-parent{width:100%!important;max-width:100%!important}
    </style>
    ''')

    with ui.header().classes('items-center justify-between bg-gray-900 text-white'):
        ui.label('Transit Summary').classes('text-lg font-semibold')
        with ui.row().classes('items-center gap-2'):
            ui.button('← Reports', on_click=lambda: ui.navigate.to('/dept/reports')).props('flat').classes('text-white font-semibold')
            ui.button(icon='home', on_click=lambda: ui.navigate.to('/')).props('flat round').classes('text-white')

    # preload metals
    try:
        metals = await fetch_metals()
        metal_options = ['All'] + sorted([m['name'] for m in metals if 'name' in m])
    except Exception:
        metal_options = ['All']

    with ui.card().classes('w-full h-full p-0').style('height: calc(100vh - 140px);').props('flat'):
        with ui.column().classes('w-full h-full').style('display:flex; flex-direction:column;'):

            # --- LEFT/RIGHT layout: summary on left, drilldown on right ---
            with ui.splitter(value=50).props('vertical').classes('w-full').style('flex:1 1 auto; min-height:0;') as split:
                # LEFT: metal-wise summary
                with split.before:
                    with ui.column().classes('w-full h-full').style('min-height:0;'):

                        with ui.row().classes('items-end justify-between p-3 gap-2 w-full').style('flex:0 0 auto;'):
                            with ui.row().classes('items-end gap-2'):
                                ui.label('Transit Summary').classes('text-base font-semibold mr-2')
                                d_from = ui.input('From').props('type=date dense').classes('w-32')
                                d_to   = ui.input('To').props('type=date dense').classes('w-32')
                                metal_filter = ui.select(options=metal_options, value='All', label='Metal').props('dense').classes('w-40')
                                metal_filter.props('options-dense behavior=menu popup-content-style="z-index:4000"')

                                async def reset_summary():
                                    d_from.value = ''; d_to.value = ''; metal_filter.value = 'All'
                                    await refresh_summary()
                                    notify('Filters reset.', 'positive')

                                ui.button('RESET FILTERS', on_click=lambda: asyncio.create_task(reset_summary())).props('outline size=sm padding="xs md"')
                            export_summary_btn = ui.button('EXPORT (CSV)').props('unelevated color=primary size=sm padding="xs md"').classes('text-white')

                        total_lbl = ui.label('Total in Transit: —').classes('px-3 pb-2 text-gray-700')


                        with ui.element('div').classes('fill-parent').style(
                            'flex:1 1 auto; overflow:auto; padding:0 12px 12px 12px; width:100%; max-width:100%;'
                        ):
                            sum_columns = [
                                {'name': 'metal_name', 'label': 'Metal', 'field': 'metal_name'},
                                {'name': 'count', 'label': '# Trees', 'field': 'count'},
                                {'name': 'total_est_metal_weight', 'label': 'Total Est. Metal', 'field': 'total_est_metal_weight'},
                            ]
                            summary_table = ui.table(columns=sum_columns, rows=[]) \
                                            .props('dense flat bordered row-key="metal_name" selection="single" hide-bottom') \
                                            .classes('w-full text-sm')

                            # bold TOTAL row cells (same pattern as scrap loss)
                            summary_table.add_slot('body-cell-metal_name', '''
                            <q-td :props="props">
                            <span :style="props.row.is_total ? 'font-weight:700;color:#000' : ''">
                                {{ props.row.metal_name }}
                            </span>
                            </q-td>
                            ''')
                            summary_table.add_slot('body-cell-count', '''
                            <q-td :props="props">
                            <span :style="props.row.is_total ? 'font-weight:700;color:#000' : ''">
                                {{ props.row.count }}
                            </span>
                            </q-td>
                            ''')
                            summary_table.add_slot('body-cell-total_est_metal_weight', '''
                            <q-td :props="props">
                            <span :style="props.row.is_total ? 'font-weight:700;color:#000' : ''">
                                {{ props.row.total_est_metal_weight }}
                            </span>
                            </q-td>
                            ''')


                # RIGHT: drilldown for selected metal
                with split.after:
                    with ui.column().classes('w-full h-full').style('min-height:0;'):
                        with ui.row().classes('items-center justify-between px-3 pt-2 w-full'):
                            drill_title = ui.label('Details (select a metal to see trees)').classes('text-gray-700')
                            export_drill_btn = ui.button('EXPORT (CSV)').props('unelevated color=primary size=sm padding="xs md"').classes('text-white')

                        with ui.element('div').classes('fill-parent').style(
                            'flex:1 1 auto; overflow:auto; padding:0 12px 12px 12px; width:100%; max-width:100%;'
                        ):
                            drill_columns = [
                                {'name': 'date', 'label': 'Date', 'field': 'date'},
                                {'name': 'tree_no', 'label': 'Tree No', 'field': 'tree_no'},
                                {'name': 'metal_name', 'label': 'Metal', 'field': 'metal_name'},
                                {'name': 'tree_weight', 'label': 'Tree Weight', 'field': 'tree_weight'},
                                {'name': 'est_metal_weight', 'label': 'Req. Metal Weight', 'field': 'est_metal_weight'},
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




            # # summary table
            # with ui.element('div').classes('fill-parent').style(
            #     'flex:1 1 auto; overflow:auto; padding:0 12px 0 12px; width:100%; max-width:100%;'
            # ):
            #     sum_columns = [
            #         {'name': 'metal_name', 'label': 'Metal', 'field': 'metal_name'},
            #         {'name': 'count', 'label': '# Trees', 'field': 'count'},
            #         {'name': 'total_est_metal_weight', 'label': 'Total Est. Metal', 'field': 'total_est_metal_weight'},
            #     ]
            #     summary_table = ui.table(columns=sum_columns, rows=[]) \
            #                       .props('dense flat bordered row-key="metal_name" selection="single" hide-bottom') \
            #                       .classes('w-full text-sm')

            # # drilldown title + export
            # with ui.row().classes('items-center justify-between px-3 pt-3 w-full'):
            #     drill_title = ui.label('Details (select a metal to see trees)').classes('text-gray-700')
            #     export_drill_btn = ui.button('EXPORT (CSV)').props('unelevated color=primary size=sm padding="xs md"').classes('text-white')

            # # drilldown table (TOTAL row inside)
            # with ui.element('div').classes('fill-parent').style(
            #     'flex:1 1 auto; overflow:auto; padding:0 12px 12px 12px; width:100%; max-width:100%;'
            # ):
            #     drill_columns = [
            #         {'name': 'date', 'label': 'Date', 'field': 'date'},
            #         {'name': 'tree_no', 'label': 'Tree No', 'field': 'tree_no'},
            #         {'name': 'metal_name', 'label': 'Metal', 'field': 'metal_name'},
            #         {'name': 'tree_weight', 'label': 'Tree Weight', 'field': 'tree_weight'},
            #         {'name': 'est_metal_weight', 'label': 'Req. Metal Weight', 'field': 'est_metal_weight'},
            #     ]
            #     drill_table = ui.table(columns=drill_columns, rows=[]) \
            #                     .props('dense flat bordered row-key="tree_id" hide-bottom') \
            #                     .classes('w-full text-sm')

            #     # TOTAL row cells: bold + black
            #     drill_table.add_slot('body-cell-date', '''
            #     <q-td :props="props">
            #     <span :class="props.row.is_total ? 'text-weight-bold' : ''"
            #           :style="props.row.is_total ? 'font-weight:700;color:#000' : ''">
            #       {{ props.row.date }}
            #     </span>
            #     </q-td>
            #     ''')

            #     drill_table.add_slot('body-cell-tree_no', '''
            #     <q-td :props="props">
            #     <span :class="props.row.is_total ? 'text-weight-bold' : ''"
            #           :style="props.row.is_total ? 'font-weight:700;color:#000' : ''">
            #       {{ props.row.tree_no }}
            #     </span>
            #     </q-td>
            #     ''')

            #     drill_table.add_slot('body-cell-metal_name', '''
            #     <q-td :props="props">
            #     <span :class="props.row.is_total ? 'text-weight-bold' : ''"
            #           :style="props.row.is_total ? 'font-weight:700;color:#000' : ''">
            #       {{ props.row.metal_name }}
            #     </span>
            #     </q-td>
            #     ''')

            #     drill_table.add_slot('body-cell-tree_weight', '''
            #     <q-td :props="props">
            #     <span :class="props.row.is_total ? 'text-weight-bold' : ''"
            #           :style="props.row.is_total ? 'font-weight:700;color:#000' : ''">
            #       {{ props.row.tree_weight }}
            #     </span>
            #     </q-td>
            #     ''')

            #     drill_table.add_slot('body-cell-est_metal_weight', '''
            #     <q-td :props="props">
            #     <span :class="props.row.is_total ? 'text-weight-bold' : ''"
            #           :style="props.row.is_total ? 'font-weight:700;color:#000' : ''">
            #       {{ props.row.est_metal_weight }}
            #     </span>
            #     </q-td>
            #     ''')

    # ---------- loaders & actions ----------
    async def refresh_summary():
        try:
            js = await fetch_transit_summary(d_from.value, d_to.value, metal_filter.value)
        except httpx.HTTPStatusError as e:
            notify(explain_http_error(e), 'negative'); return
        except Exception as ex:
            notify(str(ex), 'negative'); return

        rows = js.get('rows', [])

        total_trees = 0
        total_est = 0.0

        for r in rows:
            r['count'] = int(r.get('count') or 0)
            r['total_est_metal_weight'] = round(float(r.get('total_est_metal_weight') or 0.0), 3)

            total_trees += r['count']
            total_est += float(r.get('total_est_metal_weight') or 0.0)

        # sort by metal (optional but nice)
        try:
            rows.sort(key=lambda x: (x.get('metal_name') or '').lower())
        except Exception:
            pass

        # append TOTAL row
        rows.append({
            'metal_name': 'TOTAL',
            'count': total_trees,
            'total_est_metal_weight': round(total_est, 3),
            'is_total': True,
        })
        summary_table.rows = rows
        summary_table.selected = []
        summary_table.update()

        overall = js.get('overall_total', 0.0)
        f = to_ui_date(d_from.value); t = to_ui_date(d_to.value)
        total_lbl.text = f"Total in Transit ({f} → {t}, {metal_filter.value}): {overall:.2f}"

        # clear drilldown
        drill_title.text = 'Details (select a metal to see trees)'
        drill_table.rows = []
        drill_table.update()

    async def refresh_drilldown(metal_name: str):
        if not metal_name or metal_name == 'All':
            drill_title.text = 'Details (select a metal to see trees)'
            drill_table.rows = []
            drill_table.update()
            return

        # TOTAL = show all metals
        drill_metal = None if metal_name == 'TOTAL' else metal_name
        try:
            rows = await fetch_transit_trees(d_from.value, d_to.value, drill_metal or 'All')
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

        # drill_title.text = f"Trees in Transit for {metal_name} ({to_ui_date(d_from.value)} → {to_ui_date(d_to.value)})"
        drill_title.text = (
            f"Trees in Transit · All metals ({to_ui_date(d_from.value)} → {to_ui_date(d_to.value)})"
            if metal_name == 'TOTAL'
            else f"Trees in Transit for {metal_name} ({to_ui_date(d_from.value)} → {to_ui_date(d_to.value)})"
        )


        totals_row = {
            'tree_id': '__TOTAL__',
            'date': 'TOTAL',
            'tree_no': str(total_trees),
            'metal_name': '',
            'tree_weight': round(sum_tree_wt, 3),
            'est_metal_weight': round(sum_est, 3),
            'is_total': True,
        }
        rows.append(totals_row)

        drill_table.rows = rows
        drill_table.update()

    # selection & filter events
    # def on_summary_select(_e):
    #     try:
    #         row_list = summary_table.selected or []
    #         metal_name = row_list[0]['metal_name'] if row_list else ''
    #     except Exception:
    #         metal_name = ''
    #     asyncio.create_task(refresh_drilldown(metal_name))
    # summary_table.on('selection', on_summary_select)

    def on_summary_selected(_e=None):
        row_list = summary_table.selected or []
        metal_name = row_list[0].get('metal_name') if row_list else None
        asyncio.create_task(refresh_drilldown(metal_name or ''))
    summary_table.on('update:selected', on_summary_selected)


    d_from.on('change', lambda _e: asyncio.create_task(refresh_summary()))
    d_to.on('change',   lambda _e: asyncio.create_task(refresh_summary()))
    metal_filter.on('update:model-value', lambda _v: asyncio.create_task(refresh_summary()))

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

    # initial load
    await asyncio.create_task(refresh_summary())
