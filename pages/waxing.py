# pages/waxing.py
from nicegui import ui, Client
from datetime import datetime, date
import asyncio
import httpx
import os
from typing import List, Dict, Any

# print(">>> WAXING PAGE VERSION: with gasket/total columns <<<")

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

# ---------- API calls ----------
async def fetch_transit() -> List[Dict[str, Any]]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(f"{API_URL}/queue/transit")
        r.raise_for_status()
        rows = r.json()
        # normalize numeric types for UI
        for row in rows:
            for k in ('gasket_weight', 'total_weight', 'tree_weight', 'est_metal_weight'):
                if row.get(k) is not None:
                    try:
                        row[k] = float(row[k])
                    except Exception:
                        pass
        return rows

async def post_to_supply(payload: Dict[str, Any]) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(f"{API_URL}/waxing/post_to_supply", json=payload)
        try:
            r.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise RuntimeError(explain_http_error(e)) from e
        return r.json()

async def fetch_supply_queue(flask_no_filter: str = "") -> List[Dict[str, Any]]:
    params = {"flask_no": flask_no_filter} if flask_no_filter else None
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(f"{API_URL}/queue/supply", params=params)
        r.raise_for_status()
        return r.json()

# ---------- preview helper ----------
def tree_weight_preview(gasket: float, total: float) -> float:
    try:
        g = float(gasket or 0)
        t = float(total or 0)
    except Exception:
        return 0.0
    return round(max(0.0, t - g), 3)

# ---------- Waxing Page ----------
@ui.page('/waxing')
async def waxing_page(client: Client):
    # notifier
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
        ui.label('Post Flask to Supply').classes('text-lg font-semibold')
        with ui.row().classes('items-center gap-2'):
            ui.button('CREATE TREE', on_click=lambda: ui.navigate.to('/trees')).props('flat').classes('text-white')
            ui.button(icon='home', on_click=lambda: ui.navigate.to('/')).props('flat round').classes('text-white')

    # Preload transit for selection
    try:
        transit_rows = await fetch_transit()
    except Exception as e:
        notify(f"Failed to fetch transit: {e}", color='negative')
        transit_rows = []

    # Layout
    with ui.splitter(value=50).classes('px-6').style('width: 100%; height: calc(100vh - 160px);') as splitter:

        # LEFT: Transit table
        with splitter.before:
            ui.label('Transit Queue').classes('text-base font-semibold mb-2')
            columns = [
                {'name': 'date', 'label': 'Date', 'field': 'date'},
                {'name': 'tree_no', 'label': 'Tree No', 'field': 'tree_no'},
                {'name': 'metal_name', 'label': 'Metal', 'field': 'metal_name'},
                # IMPORTANT: include these so they're present in the selected row dict
                {'name': 'gasket_weight', 'label': 'Gasket', 'field': 'gasket_weight'},
                {'name': 'total_weight', 'label': 'Total', 'field': 'total_weight'},
                {'name': 'tree_weight', 'label': 'Tree Wt', 'field': 'tree_weight'},
                {'name': 'est_metal_weight', 'label': 'Est. Metal', 'field': 'est_metal_weight'},
            ]
            tree_table = ui.table(columns=columns, rows=transit_rows, row_key='tree_id', selection='single') \
                          .props('dense flat bordered hide-bottom') \
                          .classes('w-full text-sm h-[420px]')

            async def refresh_transit():
                try:
                    rows = await fetch_transit()
                except Exception as e:
                    notify(f'Failed to fetch transit: {e}', 'negative'); rows = []
                tree_table.rows = rows
                tree_table.update()

            ui.button('REFRESH', on_click=lambda: asyncio.create_task(refresh_transit())).props('outline').classes('mt-2')

        # RIGHT: Flask form
        with splitter.after:
            ui.label('Post Flask to Supply').classes('text-base font-semibold mb-2')

            # selected tree state
            selected = {'tree_id': None, 'metal_name': None}

            today_iso = date.today().isoformat()
            flask_date = ui.input('Flask Date', value=today_iso).props('type=date').classes('w-full')
            flask_no = ui.input('Flask No').props('clearable').classes('w-full')

            gasket_weight = ui.number('Gasket Weight', value=0.0).classes('w-full')
            total_weight  = ui.number('Total Weight',  value=0.0).classes('w-full')

            tw_preview    = ui.label('Tree Weight (Total – Gasket): 0.000').classes('text-gray-600')
            metal_preview = ui.label('Final Metal (preview): 0.000').classes('text-gray-600')

            def recalc_preview():
                tw = tree_weight_preview(gasket_weight.value or 0, total_weight.value or 0)
                tw_preview.text = f'Tree Weight (Total – Gasket): {tw:.1f}'
                # Keep preview simple; server computes exact final on POST.
                metal_preview.text = f'Final Metal (preview): {0.0:.3f}'

            gasket_weight.on('change', lambda _: recalc_preview())
            total_weight.on('change',  lambda _: recalc_preview())

            # --- On row selection: autofill gasket/total (now present in row because of table columns) ---
            def on_select(_e):
                rows = tree_table.selected
                if not rows:
                    selected['tree_id'] = None
                    selected['metal_name'] = None
                    gasket_weight.value = 0.0
                    total_weight.value = 0.0
                    recalc_preview()
                    return

                row = rows[0]
                selected['tree_id'] = row.get('tree_id')
                selected['metal_name'] = row.get('metal_name')

                ui.notify(f"row keys: {list(row.keys())}", color='secondary')

                g = row.get('gasket_weight')
                t = row.get('total_weight')
                tw = float(row.get('tree_weight') or 0.0)

                # Fallback only if both missing (older trees)
                if g is None and t is None:
                    g = 0.0
                    t = tw

                gasket_weight.value = float(g or 0.0)
                total_weight.value  = float(t or 0.0)
                recalc_preview()

            tree_table.on('selection', on_select)

            async def submit():
                if not selected['tree_id']:
                    notify('Select a tree from Transit first', color='negative'); return
                if not flask_no.value:
                    notify('Enter a Flask No', color='negative'); return

                payload = {
                    "date": (flask_date.value or today_iso),
                    "flask_no": (flask_no.value or '').strip(),
                    "tree_id": int(selected['tree_id']),
                    "gasket_weight": float(gasket_weight.value or 0),
                    "total_weight": float(total_weight.value or 0),
                    "posted_by": "waxing_ui",
                }
                try:
                    resp = await post_to_supply(payload)
                    notify(f"Flask {resp.get('flask_id')} → Supply (Metal {resp.get('metal_weight')})", color='positive')
                    # reset flask no; keep selection
                    flask_no.value = ''
                    await refresh_transit()   # selected tree should leave transit
                except Exception as e:
                    notify(str(e), color='negative')

            with ui.row().classes('gap-2 mt-2'):
                ui.button('RECALCULATE', on_click=recalc_preview).props('outline')
                ui.button('POST TO SUPPLY', on_click=lambda: asyncio.create_task(submit())) \
                  .classes('bg-primary text-white')
