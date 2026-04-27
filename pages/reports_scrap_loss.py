from nicegui import ui, Client  # type: ignore
import httpx, os, asyncio  # type: ignore
from datetime import datetime, date
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

def r3(v: Any) -> Any:
    try:
        if v is None:
            return None
        return round(float(v), 3)
    except Exception:
        return v

def f0(v: Any) -> float:
    # numeric sum helper: treat None as 0
    try:
        return 0.0 if v is None else float(v)
    except Exception:
        return 0.0

# ---------- API ----------
async def fetch_metals() -> List[Dict[str, Any]]:
    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.get(f'{API_URL}/metals')
        r.raise_for_status()
        return r.json()

async def fetch_scrap_loss_summary(date_from: str, date_to: str, metal: Optional[str]):
    raw: Dict[str, Any] = {
        "date_from": date_from or None,
        "date_to":   date_to or None,
        "metal":     (None if not metal or metal == "All" else metal),
    }
    params = {k: v for k, v in raw.items() if v is not None}
    async with httpx.AsyncClient(timeout=20.0) as c:
        r = await c.get(f'{API_URL}/reports/scrap_loss/summary', params=params)
        r.raise_for_status()
        return r.json()

async def fetch_scrap_loss_flasks(date_from: str, date_to: str, metal: Optional[str]):
    raw: Dict[str, Any] = {"date_from": date_from or None, "date_to": date_to or None}
    if metal and metal != "All":
        raw["metal"] = metal
    params = {k: v for k, v in raw.items() if v is not None}
    async with httpx.AsyncClient(timeout=20.0) as c:
        r = await c.get(f'{API_URL}/reports/scrap_loss/flasks', params=params)
        r.raise_for_status()
        return r.json()

async def fetch_scrap_offset_summary(date_from: str, date_to: str):
    raw: Dict[str, Any] = {"date_from": date_from or None, "date_to": date_to or None}
    params = {k: v for k, v in raw.items() if v is not None}
    async with httpx.AsyncClient(timeout=20.0) as c:
        r = await c.get(f'{API_URL}/reports/scrap_loss/offset_summary', params=params)
        r.raise_for_status()
        return r.json()

async def post_scrap_offset(offset_date: str, offset: float, created_by: str):
    payload = {"date": offset_date, "offset": offset, "created_by": created_by}
    async with httpx.AsyncClient(timeout=20.0) as c:
        r = await c.post(f'{API_URL}/reports/scrap_loss/offset', json=payload)
        r.raise_for_status()
        return r.json()


# ---------- PAGE ----------
@ui.page('/reports/scrap-loss')
async def reports_scrap_loss_page(client: Client):
    def notify(msg: str, color='primary'):
        with client:
            ui.notify(msg, color=color)

    ui.page_title('Scrap Loss · Casting Tracker')
    ui.add_head_html('''
    <style>
      .fill-parent{width:100%!important;max-width:100%!important}
    </style>
    ''')

    with ui.header().classes('items-center justify-between bg-gray-900 text-white'):
        ui.label('Scrap Loss').classes('text-lg font-semibold')
        with ui.row().classes('items-center gap-2'):
            ui.button('← Reports', on_click=lambda: ui.navigate.to('/dept/reports')).props('flat').classes('text-white font-semibold')
            ui.button(icon='home', on_click=lambda: ui.navigate.to('/')).props('flat round').classes('text-white')

    # preload metals
    try:
        metals = await fetch_metals()
        metal_options = ['All'] + sorted([m['name'] for m in metals if 'name' in m])
    except Exception:
        metal_options = ['All']

    # ---------- LAYOUT (LEFT/RIGHT) ----------
    with ui.splitter(value=50).props('vertical').classes('px-6').style('width:100%; height: calc(100vh - 140px);') as split:

        # LEFT: metal-wise summary
        with split.before:
            with ui.card().classes('w-full h-full p-0'):
                with ui.row().classes('items-end justify-between p-3 gap-2 w-full'):
                    with ui.row().classes('items-end gap-2'):
                        ui.label('Scrap Loss Summary').classes('text-base font-semibold mr-2')
                        loss_from = ui.input('From').props('type=date dense').classes('w-32')
                        loss_to   = ui.input('To').props('type=date dense').classes('w-32')
                        loss_metal = ui.select(options=metal_options, value='All', label='Metal').props('dense').classes('w-40')
                        loss_metal.props('options-dense behavior=menu popup-content-style="z-index:4000"')

                        async def reset_filters():
                            loss_from.value = ''
                            loss_to.value = ''
                            loss_metal.value = 'All'
                            await refresh_summary(clear_drill=True)
                            notify('Filters reset.', 'positive')

                        ui.button('RESET FILTERS', on_click=lambda: asyncio.create_task(reset_filters())) \
                          .props('outline size=sm padding="xs md"')

                    export_summary_btn = ui.button('EXPORT (CSV)') \
                        .props('unelevated color=primary size=sm padding="xs md"') \
                        .classes('text-white')

                # with ui.element('div').classes('fill-parent').style(
                #     'flex:1 1 auto; overflow:auto; padding:0 12px 12px 12px; width:100%; max-width:100%;'
                # ):

                with ui.element('div').classes('fill-parent').style(
                    'flex:1 1 auto; overflow:auto; padding:0 12px 12px 12px; width:100%; max-width:100%;'
                ):
                    summary_columns = [
                        {'name': 'metal_name', 'label': 'Metal', 'field': 'metal_name'},
                        {'name': 'flask_count', 'label': '# Flasks', 'field': 'flask_count'},
                        {'name': 'total_scrap_loss', 'label': 'Total scrap loss', 'field': 'total_scrap_loss'},
                    ]
                    summary_table = ui.table(columns=summary_columns, rows=[]) \
                        .props('dense flat bordered row-key="metal_name" selection="single" hide-bottom') \
                        .classes('w-full text-sm')

                    # bold TOTAL row cells
                    summary_table.add_slot('body-cell-metal_name', '''
                    <q-td :props="props">
                      <span :style="props.row.is_total ? 'font-weight:700;color:#000' : ''">
                        {{ props.row.metal_name }}
                      </span>
                    </q-td>
                    ''')
                    summary_table.add_slot('body-cell-flask_count', '''
                    <q-td :props="props">
                      <span :style="props.row.is_total ? 'font-weight:700;color:#000' : ''">
                        {{ props.row.flask_count }}
                      </span>
                    </q-td>
                    ''')
                    summary_table.add_slot('body-cell-total_scrap_loss', '''
                    <q-td :props="props">
                      <span :style="props.row.is_total ? 'font-weight:700;color:#d32f2f' : ''">
                        {{ props.row.total_scrap_loss }}
                      </span>
                    </q-td>
                    ''')

                # --- NEW: totals + offset section (fixed under table) ---
                # with ui.element('div').style('padding: 10px 12px 12px 12px; border-top: 1px solid #eee;'):
                with ui.element('div').classes('w-full').style(
                    'padding: 12px; border-top: 1px solid #eee; width: 100%;'
                ):
                    ui.label('Scrap Offset').classes('text-base font-semibold mb-2')

                    # total_scrap_lbl = ui.label('Total scrap loss: -').classes('text-sm')
                    # offset_lbl = ui.label('Offset: -').classes('text-sm')
                    # actual_lbl = ui.label('Actual loss: -').classes('text-sm font-semibold')

                    offset_summary_rows = [
                        {"label": "Total scrap loss", "value": "-"},
                        {"label": "Offset", "value": "-"},
                        {"label": "Actual loss", "value": "-"},
                    ]

                    offset_summary_table = ui.table(
                        columns=[
                            {"name": "label", "label": "", "field": "label"},
                            {"name": "value", "label": "", "field": "value"},
                        ],
                        rows=offset_summary_rows,
                    ).props('dense flat bordered hide-header').classes('w-full text-sm')

                    offset_summary_table.add_slot('body-cell-value', '''
                    <q-td :props="props">
                    <span :style="
                        'font-weight:700;' +
                        (props.row.label === 'Actual loss' ? 'color:#d32f2f;' : '')
                    ">
                        {{ props.row.value }}
                    </span>
                    </q-td>
                    ''')


                    ui.separator().classes('my-2')

                    ui.label('Add offset').classes('text-xs text-gray-500')

                    with ui.row().classes('items-end gap-4 w-full'):

                        offset_date_in = ui.input('Date') \
                            .props('type=date dense') \
                            .classes('flex-1')
                        offset_date_in.value = date.today().isoformat()

                        offset_amt_in = ui.number('Scrap offset (g)', value=0) \
                            .props('dense') \
                            .classes('flex-1')


                        async def save_offset():
                            if not offset_date_in.value:
                                notify('Pick a date for the offset.', 'negative')
                                return
                            amt = float(offset_amt_in.value or 0)
                            if amt == 0:
                                notify('Offset cannot be 0.', 'negative')
                                return

                            try:
                                await post_scrap_offset(offset_date_in.value, amt, created_by='system')  # or your user
                            except httpx.HTTPStatusError as e:
                                notify(explain_http_error(e), 'negative')
                                return
                            except Exception as ex:
                                notify(str(ex), 'negative')
                                return

                            notify('Offset saved.', 'positive')
                            offset_amt_in.value = 0
                            await refresh_totals_box()   # ✅ refresh the numbers


                        ui.button('SAVE OFFSET',
                            on_click=lambda: asyncio.create_task(save_offset())
                        ).props('unelevated color=primary size=sm') \
                        .classes('text-white self-end')

        # RIGHT: drilldown for selected metal
        with split.after:
            with ui.card().classes('w-full h-full p-0'):
                with ui.row().classes('items-center justify-between p-3 gap-2 w-full'):
                    drill_title = ui.label('Details (select a metal)').classes('text-base font-semibold')
                    export_drill_btn = ui.button('EXPORT (CSV)') \
                        .props('unelevated color=primary size=sm padding="xs md"') \
                        .classes('text-white')

                with ui.element('div').classes('fill-parent').style(
                    'flex:1 1 auto; overflow:auto; padding:0 12px 12px 12px; width:100%; max-width:100%;'
                ):
                    drill_columns = [
                        {'name': 'date', 'label': 'Date', 'field': 'date'},
                        {'name': 'flask_no', 'label': 'Flask No', 'field': 'flask_no'},
                        {'name': 'metal_name', 'label': 'Metal', 'field': 'metal_name'},
                        {'name': 'supplied_weight', 'label': 'Supplied wt', 'field': 'supplied_weight'},
                        {'name': 'casting_loss', 'label': 'Casting loss', 'field': 'casting_loss'},
                        {'name': 'cutting_loss', 'label': 'Cutting loss', 'field': 'cutting_loss'},
                        {'name': 'total_transit_loss', 'label': 'Transit loss', 'field': 'total_transit_loss'},
                        {'name': 'total_loss', 'label': 'Total loss', 'field': 'total_loss'},
                    ]
                    drill_table = ui.table(columns=drill_columns, rows=[]) \
                        .props('dense flat bordered row-key="flask_id" hide-bottom') \
                        .classes('w-full text-sm')

                    # bold TOTAL row, and also bold Total loss column for normal rows
                    drill_table.add_slot('body-cell-total_loss', '''
                    <q-td :props="props">
                      <span :style="(props.row.is_total || true) ? (props.row.is_total ? 'font-weight:700;color:#d32f2f' : 'font-weight:700') : ''">
                        {{ props.row.total_loss }}
                      </span>
                    </q-td>
                    ''')
                    # bold total row for other columns
                    for col in ['date','flask_no','metal_name','supplied_weight','casting_loss','cutting_loss','total_transit_loss']:
                        drill_table.add_slot(f'body-cell-{col}', f'''
                        <q-td :props="props">
                          <span :style="props.row.is_total ? 'font-weight:700;color:#000' : ''">
                            {{{{ props.row.{col} }}}}
                          </span>
                        </q-td>
                        ''')

    # ---------- loaders ----------
    selected_metal: Optional[str] = None

    async def refresh_summary(clear_drill: bool = False):
        nonlocal selected_metal
        try:
            rows = await fetch_scrap_loss_summary(loss_from.value, loss_to.value, loss_metal.value)
        except httpx.HTTPStatusError as e:
            notify(explain_http_error(e), 'negative')
            return
        except Exception as ex:
            notify(str(ex), 'negative')
            return

        # normalize
        total_flasks = 0
        total_loss = 0.0
        for r in rows:
            r['flask_count'] = int(r.get('flask_count') or 0)
            r['total_scrap_loss'] = r3(r.get('total_scrap_loss'))
            total_flasks += r['flask_count']
            total_loss += f0(r.get('total_scrap_loss'))

        # sort
        try:
            rows.sort(key=lambda x: (x.get('metal_name') or '').lower())
        except Exception:
            pass

        # append TOTAL row
        rows.append({
            'metal_name': 'TOTAL',
            'flask_count': total_flasks,
            'total_scrap_loss': round(total_loss, 3),
            'is_total': True,
        })

        summary_table.rows = rows
        summary_table.update()
        await refresh_totals_box()


        if clear_drill:
            selected_metal = None
            drill_title.text = 'Details (select a metal)'
            drill_table.rows = []
            drill_table.update()

    async def refresh_totals_box():
        # total scrap loss = TOTAL row value from summary_table
        total_scrap = 0.0
        for r in (summary_table.rows or []):
            if r.get('metal_name') == 'TOTAL':
                total_scrap = float(r.get('total_scrap_loss') or 0.0)

        # offset = sum of offsets within date range
        try:
            off = await fetch_scrap_offset_summary(loss_from.value, loss_to.value)
            total_offset = float(off.get('total_offset') or 0.0)
        except Exception:
            total_offset = 0.0

        actual = total_scrap - total_offset

        # total_scrap_lbl.text = f'Total scrap loss: {round(total_scrap, 3)} g'
        # offset_lbl.text = f'Offset: {round(total_offset, 3)} g'
        # actual_lbl.text = f'Actual loss: {round(actual, 3)} g'

        offset_summary_table.rows = [
            {"label": "Total scrap loss", "value": f"{round(total_scrap, 3)}"},
            {"label": "Offset", "value": f"{round(total_offset, 3)}"},
            {"label": "Actual loss", "value": f"{round(actual, 3)}"},
        ]
        offset_summary_table.update()


    # async def refresh_drill(metal_name: Optional[str]):
    #     nonlocal selected_metal
    #     if not metal_name or metal_name == 'TOTAL':
    #         selected_metal = None
    #         drill_title.text = 'Details (select a metal)'
    #         drill_table.rows = []
    #         drill_table.update()
    #         return

    #     # selected_metal = metal_name
    #     # drill_title.text = f'Flasks · {metal_name}'


    #     # TOTAL row means "All metals"
    #     drill_metal = None if metal_name == 'TOTAL' else metal_name
    #     selected_metal = metal_name

    #     drill_title.text = 'Flasks · All metals' if metal_name == 'TOTAL' else f'Flasks · {metal_name}'
    #     rows = await fetch_scrap_loss_flasks(loss_from.value, loss_to.value, drill_metal)

    #     try:
    #         rows = await fetch_scrap_loss_flasks(loss_from.value, loss_to.value, metal_name)
    #     except httpx.HTTPStatusError as e:
    #         notify(explain_http_error(e), 'negative')
    #         return
    #     except Exception as ex:
    #         notify(str(ex), 'negative')
    #         return

    #     # normalize + totals
    #     total_flasks = len(rows)
    #     sum_supplied = 0.0
    #     sum_cast = 0.0
    #     sum_cut = 0.0
    #     sum_transit = 0.0
    #     sum_total = 0.0

    #     for r in rows:
    #         if 'date' in r and r['date']:
    #             r['date'] = to_ui_date(r['date'])

    #         r['supplied_weight'] = r3(r.get('supplied_weight'))
    #         r['casting_loss'] = r3(r.get('casting_loss'))
    #         r['cutting_loss'] = r3(r.get('cutting_loss'))
    #         r['total_transit_loss'] = r3(r.get('total_transit_loss'))
    #         r['total_loss'] = r3(r.get('total_loss'))

    #         sum_supplied += f0(r.get('supplied_weight'))
    #         sum_cast += f0(r.get('casting_loss'))
    #         sum_cut += f0(r.get('cutting_loss'))
    #         sum_transit += f0(r.get('total_transit_loss'))
    #         sum_total += f0(r.get('total_loss'))

    #     # append TOTAL row
    #     rows.append({
    #         'flask_id': '__TOTAL__',
    #         'date': 'TOTAL',
    #         'flask_no': str(total_flasks),
    #         'metal_name': '',
    #         'supplied_weight': round(sum_supplied, 3),
    #         'casting_loss': round(sum_cast, 3),
    #         'cutting_loss': round(sum_cut, 3),
    #         'total_transit_loss': round(sum_transit, 3),
    #         'total_loss': round(sum_total, 3),
    #         'is_total': True,
    #     })

    #     drill_table.rows = rows
    #     drill_table.update()

    async def refresh_drill(metal_name: Optional[str]):
        nonlocal selected_metal

        # clear if nothing selected
        if not metal_name:
            selected_metal = None
            drill_title.text = 'Details (select a metal)'
            drill_table.rows = []
            drill_table.update()
            return

        # ✅ TOTAL means "all metals"
        drill_metal = None if metal_name == 'TOTAL' else metal_name
        selected_metal = metal_name
        drill_title.text = 'Flasks · All metals' if metal_name == 'TOTAL' else f'Flasks · {metal_name}'

        try:
            rows = await fetch_scrap_loss_flasks(loss_from.value, loss_to.value, drill_metal)
        except httpx.HTTPStatusError as e:
            notify(explain_http_error(e), 'negative')
            return
        except Exception as ex:
            notify(str(ex), 'negative')
            return

        # normalize + totals
        total_flasks = len(rows)
        sum_supplied = 0.0
        sum_cast = 0.0
        sum_cut = 0.0
        sum_transit = 0.0
        sum_total = 0.0

        for r in rows:
            if 'date' in r and r['date']:
                r['date'] = to_ui_date(r['date'])

            r['supplied_weight'] = r3(r.get('supplied_weight'))
            r['casting_loss'] = r3(r.get('casting_loss'))
            r['cutting_loss'] = r3(r.get('cutting_loss'))
            r['total_transit_loss'] = r3(r.get('total_transit_loss'))
            r['total_loss'] = r3(r.get('total_loss'))

            sum_supplied += f0(r.get('supplied_weight'))
            sum_cast += f0(r.get('casting_loss'))
            sum_cut += f0(r.get('cutting_loss'))
            sum_transit += f0(r.get('total_transit_loss'))
            sum_total += f0(r.get('total_loss'))

        rows.append({
            'flask_id': '__TOTAL__',
            'date': 'TOTAL',
            'flask_no': str(total_flasks),
            'metal_name': '',
            'supplied_weight': round(sum_supplied, 3),
            'casting_loss': round(sum_cast, 3),
            'cutting_loss': round(sum_cut, 3),
            'total_transit_loss': round(sum_transit, 3),
            'total_loss': round(sum_total, 3),
            'is_total': True,
        })

        drill_table.rows = rows
        drill_table.update()

    # ---------- events ----------
    # def on_summary_select(e):
    #     sel = (e.args or {}).get('rows', []) or []
    #     metal_name = sel[0].get('metal_name') if sel else None
    #     asyncio.create_task(refresh_drill(metal_name))

    # # ✅ selection + deselection: this event fires either way
    # summary_table.on('selection', on_summary_select)

    def on_summary_selected(_e=None):
        row_list = summary_table.selected or []
        metal_name = row_list[0].get('metal_name') if row_list else None
        asyncio.create_task(refresh_drill(metal_name))

    # ✅ fires on select + deselect reliably
    summary_table.on('update:selected', on_summary_selected)


    # filters: refresh summary and keep drill in sync if still selected
    async def on_filters_changed():
        await refresh_summary(clear_drill=False)
        if selected_metal:
            await refresh_drill(selected_metal)
        else:
            await refresh_drill(None)

    loss_from.on('change', lambda _e: asyncio.create_task(on_filters_changed()))
    loss_to.on('change',   lambda _e: asyncio.create_task(on_filters_changed()))
    loss_metal.on('update:model-value', lambda _v: asyncio.create_task(on_filters_changed()))

    # ---------- exports ----------
    def export_summary():
        rows = [r for r in (summary_table.rows or []) if not r.get('is_total')]
        csv_bytes = rows_to_csv_bytes(rows, ['metal_name', 'flask_count', 'total_scrap_loss'])
        ui.download(csv_bytes, filename=f'scrap_loss_summary_{loss_from.value}_{loss_to.value}.csv')

    export_summary_btn.on('click', export_summary)

    def export_drill():
        rows = [r for r in (drill_table.rows or []) if not r.get('is_total')]
        csv_bytes = rows_to_csv_bytes(rows, [
            'date', 'flask_no', 'metal_name', 'supplied_weight',
            'casting_loss', 'cutting_loss', 'total_transit_loss', 'total_loss'
        ])
        # name = selected_metal or 'metal'
        name = 'all_metals' if selected_metal == 'TOTAL' else (selected_metal or 'metal')

        ui.download(csv_bytes, filename=f'scrap_loss_flasks_{name}_{loss_from.value}_{loss_to.value}.csv')

    export_drill_btn.on('click', export_drill)

    # initial load
    await asyncio.create_task(refresh_summary(clear_drill=True))
