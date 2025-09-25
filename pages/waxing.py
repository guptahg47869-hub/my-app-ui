# pages/waxing.py
from nicegui import ui, Client
from datetime import datetime, date
import asyncio
import httpx
import os
from typing import List, Dict, Any

# ---------- helpers ----------
def to_ui(d_iso: str) -> str:
    """YYYY-MM-DD -> MM-DD-YY"""
    try:
        return datetime.strptime(d_iso, '%Y-%m-%d').strftime('%m-%d-%y')
    except Exception:
        return d_iso

def parse_iso_date(s: str):
    try:
        return datetime.strptime(s, '%Y-%m-%d').date()
    except Exception:
        return None

def explain_http_error(exc: Exception) -> str:
    # Try to pull FastAPI's {"detail": "..."} from the response
    if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
        try:
            data = exc.response.json()
            if isinstance(data, dict) and "detail" in data:
                return str(data["detail"])
            return str(data)
        except Exception:
            return exc.response.text or str(exc)
    return str(exc)

API_URL = os.getenv("API_URL", "http://localhost:8000")

# ---------- API calls (no direct UI here) ----------
async def fetch_metals() -> List[Dict[str, Any]]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(f"{API_URL}/metals")
        r.raise_for_status()
        return r.json()

async def post_waxing(payload: Dict[str, Any]) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(f"{API_URL}/waxing", json=payload)
        try:
            r.raise_for_status()
        except httpx.HTTPStatusError as e:
            # surface FastAPI's detail message
            raise RuntimeError(explain_http_error(e)) from e
        return r.json()

async def fetch_supply_queue(flask_no_filter: str = "") -> List[Dict[str, Any]]:
    params = {"flask_no": flask_no_filter} if flask_no_filter else None
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(f"{API_URL}/queue/supply", params=params)
        r.raise_for_status()
        return r.json()

# ---------- preview helper ----------
def metal_weight_preview(gasket: float, tree: float, _metal_name: str) -> float:
    try:
        g = float(gasket or 0)
        t = float(tree or 0)
    except Exception:
        return 0.0
    return round(t - g, 1)

# ---------- Waxing Page ----------
@ui.page('/waxing')
async def waxing_page(client: Client):
    # Safe notifier — ALWAYS wrap UI ops in the client context:
    def notify(msg: str, color: str = 'primary'):
        with client:
            ui.notify(msg, color=color)

    ui.page_title("Waxing · Casting Tracker")

    ui.add_head_html("""
    <style>
      .nicegui-content { max-width: 100% !important; padding-left: 16px; padding-right: 16px; }
      body { overflow-x: hidden; }
      .q-menu { z-index: 4000 !important; }
    </style>
    """)

    # Header
    with ui.header().classes('items-center justify-between bg-gray-900 text-white'):
        ui.label('Waxing').classes('text-lg font-semibold')
        with ui.row().classes('items-center gap-2'):
            ui.button('Home', on_click=lambda: ui.navigate.to('/')).props('flat').classes('text-white')

    # Load metals for the form
    try:
        metals = await fetch_metals()
    except Exception as e:
        notify(f"Failed to fetch metals: {e}", color='negative')
        metals = []

    metal_names = sorted([m.get('name') for m in metals if 'name' in m])
    metal_name_to_id = {m['name']: m['id'] for m in metals if 'name' in m and 'id' in m}

    # Layout: form left, queue right
    with ui.splitter(value=50).classes('px-6').style('width: 100%; height: calc(100vh - 160px);') as splitter:

        # LEFT FORM
        with splitter.before:
            with ui.card().classes('w-full h-full p-4'):
                ui.label('Create New').classes('text-base font-semibold mb-2')

                today_iso = date.today().isoformat()
                date_input = ui.input('Date', value=today_iso).props('type=date').classes('w-full')
                flask_no = ui.input('Flask No').props('clearable').classes('w-full')
                metal_select = ui.select(options=metal_names, label='Metal').classes('w-full')
                metal_select.props('options-dense behavior=menu popup-content-style="z-index:4000"')

                gasket_weight = ui.number('Gasket Weight').classes('w-full')
                tree_weight = ui.number('Total Tree Weight').classes('w-full')
                preview = ui.label('Tree Weight Preview: 0.0').classes('text-gray-600')

                def on_change():
                    name = metal_select.value or ''
                    gasket = gasket_weight.value or 0
                    tree = tree_weight.value or 0
                    # pure UI update; already in slot context
                    preview.text = f"Tree Weight Preview: {metal_weight_preview(gasket, tree, name):.1f}"
                for c in (metal_select, gasket_weight, tree_weight):
                    c.on('change', lambda _e: on_change())

                async def submit():
                    if not flask_no.value:
                        notify('Please enter a flask number', color='negative'); return
                    if not metal_select.value:
                        notify('Please select a metal', color='negative'); return
                    m_id = metal_name_to_id.get(metal_select.value)
                    if not m_id:
                        notify('Unknown metal. Reload metals?', color='negative'); return

                    payload = {
                        "date": (date_input.value or today_iso),
                        "flask_no": (flask_no.value or '').strip(),
                        "metal_id": m_id,
                        "gasket_weight": float(gasket_weight.value or 0),
                        "tree_weight": float(tree_weight.value or 0),
                        "posted_by": "waxing_ui",
                    }
                    try:
                        resp = await post_waxing(payload)
                        notify(f"Posted flask {resp.get('flask_id')} (Metal Weight = {resp.get('metal_weight')})", color='positive')
                        # reset fields
                        date_input.value = today_iso
                        flask_no.value = ''
                        metal_select.value = None
                        gasket_weight.value = None
                        tree_weight.value = None
                        preview.text = 'Tree Weight Preview: 0.0'
                        # refresh right panel
                        await refresh_supply()
                    except Exception as e:
                        notify(str(e), color='negative')

                # Use asyncio.create_task to preserve UI context during the async call
                ui.button('Post to Metal Supply', on_click=lambda: asyncio.create_task(submit())) \
                  .classes('bg-emerald-600 text-white mt-1')

        # RIGHT QUEUE + DATE FILTERS
        with splitter.after:
            with ui.card().classes('w-full h-full p-4'):
                ui.label('Metal Supply Queue').classes('text-base font-semibold mb-2')

                today_iso_right = date.today().isoformat()

                with ui.row().classes('items-end gap-3 w-full mb-2'):
                    search_in = ui.input('Search by Flask No').props('clearable').classes('w-48')
                    date_from = ui.input('From', value=today_iso_right).props('type=date').classes('w-36')
                    date_to   = ui.input('To',   value=today_iso_right).props('type=date').classes('w-36')

                    async def reset_filters():
                        search_in.value = ''
                        date_from.value = today_iso_right
                        date_to.value   = today_iso_right
                        await refresh_supply()
                        notify('Filters reset', color='positive')

                    ui.button('Reset Filters', on_click=lambda: asyncio.create_task(reset_filters())).props('outline')

                columns = [
                    {'name': 'date', 'label': 'Date', 'field': 'date'},
                    {'name': 'flask_no', 'label': 'Flask No', 'field': 'flask_no'},
                    {'name': 'metal_name', 'label': 'Metal', 'field': 'metal_name'},
                    {'name': 'metal_weight', 'label': 'Metal Weight', 'field': 'metal_weight'},
                    {'name': 'status', 'label': 'Stage', 'field': 'status'},
                ]
                table = ui.table(columns=columns, rows=[]).props('dense flat bordered').classes('w-full text-sm')

                async def refresh_supply():
                    try:
                        rows = await fetch_supply_queue(flask_no_filter=search_in.value.strip())
                    except Exception as e:
                        notify(f'Failed to fetch supply queue: {e}', color='warning')
                        rows = []

                    f_date = parse_iso_date(date_from.value)
                    t_date = parse_iso_date(date_to.value)

                    pruned = []
                    for r in rows:
                        d = parse_iso_date(r.get('date', '') or '')
                        if not d:
                            continue
                        if f_date and d < f_date:
                            continue
                        if t_date and d > t_date:
                            continue
                        pruned.append(r)

                    STATUS_DISPLAY = {
                        'waxing': 'Waxing',
                        'supply': 'Metal Supply',
                        'casting': 'Casting',
                        'quenching': 'Quenching',
                        'cutting': 'Cutting',
                        'done': 'Done',
                    }
                    for r in pruned:
                        r['date'] = to_ui(r.get('date', ''))
                        if r.get('status'):
                            r['status'] = STATUS_DISPLAY.get(r['status'], r['status'])
                        if r.get('metal_weight') is not None:
                            try:
                                r['metal_weight'] = float(r['metal_weight'])
                            except Exception:
                                pass

                    # ENTER UI CONTEXT to update components
                    with client:
                        table.rows = pruned
                        table.update()

                # trigger refresh on filter changes (keep UI context)
                search_in.on('change', lambda _e: asyncio.create_task(refresh_supply()))
                date_from.on('change', lambda _e: asyncio.create_task(refresh_supply()))
                date_to.on('change',   lambda _e: asyncio.create_task(refresh_supply()))

                # auto-refresh + initial load (keep UI context)
                ui.timer(4.0, lambda: asyncio.create_task(refresh_supply()))
                await refresh_supply()
