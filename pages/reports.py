from nicegui import ui, Client # type: ignore
import httpx, os, asyncio # type: ignore
from datetime import date, datetime
from typing import Any, Dict, List

API_URL = os.getenv('API_URL', 'http://localhost:8000')
print('UI using API_URL =', API_URL)

# --- helpers (same style as other pages) ---
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

async def fetch_metals() -> List[Dict[str, Any]]:
    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.get(f'{API_URL}/metals')
        r.raise_for_status()
        return r.json()

async def fetch_transit_summary(date_from: str, date_to: str, metal: str | None):
    params: Dict[str, Any] = {"date_from": date_from, "date_to": date_to}
    if metal and metal != "All":
        params["metal"] = metal
    async with httpx.AsyncClient(timeout=15.0) as c:
        r = await c.get(f'{API_URL}/reports/transit', params=params)
        r.raise_for_status()
        return r.json()

@ui.page('/reports')
async def reports_page(client: Client):
    def notify(msg: str, color='primary'):
        with client:
            ui.notify(msg, color=color)

    ui.page_title('Reports · Casting Tracker')
    ui.add_head_html('<style>.fill-parent{width:100%!important;max-width:100%!important}</style>')

    # Header
    with ui.header().classes('items-center justify-between bg-gray-900 text-white'):
        ui.label('Reports').classes('text-lg font-semibold')
        with ui.row().classes('items-center gap-2'):
            ui.button('Home', on_click=lambda: ui.navigate.to('/')).props('flat').classes('text-white')
            ui.button('Trees', on_click=lambda: ui.navigate.to('/trees')).props('flat').classes('text-white')
            ui.button('Post Flask', on_click=lambda: ui.navigate.to('/post-flask')).props('flat').classes('text-white')

    # preload metals for filter
    try:
        metals = await fetch_metals()
        metal_options = ['All'] + sorted([m['name'] for m in metals if 'name' in m])
    except Exception:
        metal_options = ['All']

    # Layout: left panel = transit summary; right panel placeholder
    with ui.splitter(value=60).classes('px-6').style('width:100%; height: calc(100vh - 140px);') as split:

        # LEFT: Transit Summary
        with split.before:
            with ui.card().classes('w-full h-full p-0'):
                with ui.column().classes('w-full h-full').style('display:flex; flex-direction:column;'):
                    today_iso = date.today().isoformat()

                    # Filters (fixed bar)
                    with ui.row().classes('items-end gap-3 p-4').style('flex:0 0 auto;'):
                        ui.label('Transit Summary').classes('text-base font-semibold mr-4')
                        d_from = ui.input('From', value=today_iso).props('type=date').classes('w-36')
                        d_to   = ui.input('To',   value=today_iso).props('type=date').classes('w-36')
                        metal_filter = ui.select(options=metal_options, value='All', label='Metal').classes('w-48')
                        metal_filter.props('options-dense behavior=menu popup-content-style="z-index:4000"')

                        async def reset_filters():
                            d_from.value = today_iso
                            d_to.value   = today_iso
                            metal_filter.value = 'All'
                            await refresh_summary()
                            notify('Filters reset.', 'positive')

                        ui.button('RESET FILTERS', on_click=lambda: asyncio.create_task(reset_filters())).props('outline')

                    # Total label
                    total_lbl = ui.label('Total in Transit: —').classes('px-4 pb-2 text-gray-700')

                    # Table (scrollable)
                    with ui.element('div').classes('fill-parent').style(
                        'flex:1 1 auto; overflow:auto; padding:0 16px 16px 16px; width:100%; max-width:100%;'
                    ):
                        columns = [
                            {'name': 'metal_name', 'label': 'Metal', 'field': 'metal_name'},
                            {'name': 'count', 'label': '# Trees', 'field': 'count'},
                            {'name': 'total_est_metal_weight', 'label': 'Total Est. Metal', 'field': 'total_est_metal_weight'},
                        ]
                        summary_table = ui.table(columns=columns, rows=[]) \
                                          .props('dense flat bordered hide-bottom row-key="metal_name"') \
                                          .classes('w-full text-sm')

        # RIGHT: placeholder for future reports
        with split.after:
            with ui.card().classes('w-full h-full p-6'):
                ui.label('More reports coming soon…').classes('text-gray-600')

    # ---- data loader ----
    async def refresh_summary():
        try:
            js = await fetch_transit_summary(d_from.value, d_to.value, metal_filter.value)
        except httpx.HTTPStatusError as e:
            notify(explain_http_error(e), 'negative'); return
        except Exception as ex:
            notify(str(ex), 'negative'); return

        rows = js.get('rows', [])
        # format totals and sort by metal (API returns asc already; this is just defensive)
        for r in rows:
            r['total_est_metal_weight'] = round(float(r.get('total_est_metal_weight', 0.0)), 3)

        # update table
        summary_table.rows = rows
        summary_table.update()

        # update total label
        overall = js.get('overall_total', 0.0)
        # show the filter range and total in MM-DD-YY for readability
        f = to_ui_date(d_from.value)
        t = to_ui_date(d_to.value)
        total_lbl.text = f"Total in Transit ({f} → {t}, {metal_filter.value}): {overall:.3f}"

    # events
    d_from.on('change', lambda _e: asyncio.create_task(refresh_summary()))
    d_to.on('change',   lambda _e: asyncio.create_task(refresh_summary()))
    metal_filter.on('update:model-value', lambda _v: asyncio.create_task(refresh_summary()))

    # initial load
    await asyncio.create_task(refresh_summary())
