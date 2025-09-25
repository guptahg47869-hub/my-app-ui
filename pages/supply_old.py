from nicegui import ui, Client
from datetime import datetime
import asyncio
import httpx
import os
from typing import List, Dict, Any, Tuple

API_URL = os.getenv('API_URL', 'http://localhost:8000')

# ---------- helpers ----------
def to_ui(d_iso: str) -> str:
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
    if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
        try:
            data = exc.response.json()
            if isinstance(data, dict) and "detail" in data:
                return str(data["detail"])
            return str(data)
        except Exception:
            return exc.response.text or str(exc)
    return str(exc)

def karat_from_name(metal_name: str) -> int:
    try:
        k = int(''.join(ch for ch in metal_name if ch.isdigit()))
        return k if k in (8, 9, 10, 12, 14, 18, 22, 24) else 0
    except Exception:
        return 0

def calc_fine_alloy_for_fresh(metal_name: str, fresh_weight: float) -> Tuple[float, float]:
    """For gold karats: split fresh → fine 24k + alloy. For Pt/Ag/24k: (0, fresh)."""
    k = karat_from_name(metal_name)
    if k <= 0 or k >= 24:
        return 0.0, round(fresh_weight, 3)
    fine_frac = k / 24.0
    fine = fresh_weight * fine_frac
    alloy = fresh_weight - fine
    return round(fine, 3), round(alloy, 3)

# ---------- network ----------
async def get_json(url, **kw):
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(url, **kw)
        r.raise_for_status()
        return r.json()

async def post_json(url, payload):
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(url, json=payload)
        try:
            r.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise RuntimeError(explain_http_error(e)) from e
        return r.json()

async def fetch_metals():          return await get_json(f'{API_URL}/metals')
async def fetch_supply_queue(q=''): 
    params = {'flask_no': q} if q else None
    return await get_json(f'{API_URL}/queue/supply', params=params)
async def fetch_casting_queue():   return await get_json(f'{API_URL}/queue/casting')
async def fetch_reserves():        return await get_json(f'{API_URL}/scrap/reserves')

# ---------- page ----------
@ui.page('/supply')
async def page(client: Client):
    # notify that always works (even inside async)
    def notify(msg: str, color='primary'):
        try:
            with client:
                ui.notify(msg, color=color)
        except Exception:
            print(f'NOTIFY[{color}]: {msg}')

    ui.page_title('Metal Supply · Casting Tracker')

    with ui.header().classes('items-center justify-between bg-gray-900 text-white'):
        ui.label('Metal Supply').classes('text-lg font-semibold')
        ui.button('Home', on_click=lambda: ui.navigate.to('/')).props('flat').classes('text-white')

    metals = await fetch_metals()
    metal_names = sorted([m['name'] for m in metals])

    # caches/state
    scrap_by_metal: Dict[str, float] = {}     # e.g. {'10W': 160.0}
    row_state: Dict[Any, Dict[str, Any]] = {} # per flask id: scrap/fine/alloy + overrides
    editing = {'value': False}                # blocks auto-refresh while user is typing

    def row_id(row: Dict[str, Any]):
        return row.get('id') or row.get('flask_id')

    def ensure_state(row: Dict[str, Any]):
        rid = row_id(row)
        if rid not in row_state:
            total = float(row.get('metal_weight') or 0.0)
            fine, alloy = calc_fine_alloy_for_fresh(row.get('metal_name', ''), total)
            row_state[rid] = {
                'scrap': 0.0,
                'fine': fine,
                'alloy': alloy,
                'override_fine': False,
                'override_alloy': False,
            }
        return row_state[rid]

    def inject_display_fields(rows: List[Dict[str, Any]]):
        for r in rows:
            st = ensure_state(r)
            r['_scrap'] = st['scrap']
            r['_fine']  = st['fine']
            r['_alloy'] = st['alloy']

    # ----------- TOP CARD: Supply table -----------
    with ui.card().classes('m-4 p-4').style('width:100%; height:50vh; overflow:auto;'):
        ui.label('Metal Supply Queue').classes('text-base font-semibold mb-2')

        today_iso = datetime.today().strftime('%Y-%m-%d')
        with ui.row().classes('items-end gap-3 w-full mb-2'):
            search_in = ui.input('Search by Flask No').props('clearable').classes('w-48')
            date_from = ui.input('From', value=today_iso).props('type=date').classes('w-36')
            date_to   = ui.input('To',   value=today_iso).props('type=date').classes('w-36')
            metal_pick = ui.select(options=['All'] + metal_names, value='All', label='Metal').classes('w-48')
            metal_pick.props('options-dense behavior=menu popup-content-style="z-index:4000"')

            async def reset_filters():
                search_in.value = ''
                date_from.value = today_iso
                date_to.value = today_iso
                metal_pick.value = 'All'
                await safe_refresh_supply(force=True)
            ui.button('Reset Filters', on_click=reset_filters).props('outline')

        columns = [
            {'name': 'date',         'label': 'Date',     'field': 'date'},
            {'name': 'flask_no',     'label': 'Flask No', 'field': 'flask_no'},
            {'name': 'metal_name',   'label': 'Metal',    'field': 'metal_name'},
            {'name': 'metal_weight', 'label': 'Metal Wt', 'field': 'metal_weight'},
            {'name': 'scrap',        'label': 'Scrap',    'field': 'scrap'},
            {'name': 'fine',         'label': '24K',      'field': 'fine'},
            {'name': 'alloy',        'label': 'Alloy',    'field': 'alloy'},
            {'name': 'actions',      'label': '',         'field': 'actions', 'align': 'right'},
        ]
        table = ui.table(columns=columns, rows=[]).props('dense flat bordered row-key="id"').classes('w-full text-sm')

        # custom cell slots with focus/blur events to pause refresh during editing
        table.add_slot('body-cell-scrap', '''
          <q-td key="scrap" :props="props" class="number-td">
            <q-input type="number" dense outlined :min="0" :step="0.001"
                     v-model.number="props.row._scrap"
                     @focus="() => emit('cell-focus')"
                     @blur="() => emit('scrap-blur', { row: props.row, value: Number(props.row._scrap) })" />
          </q-td>
        ''')
        table.add_slot('body-cell-fine', '''
          <q-td key="fine" :props="props" class="number-td">
            <q-input type="number" dense outlined :min="0" :step="0.001"
                     v-model.number="props.row._fine"
                     @focus="() => emit('cell-focus')"
                     @blur="() => emit('fine-blur',  { row: props.row, value: Number(props.row._fine) })" />
          </q-td>
        ''')
        table.add_slot('body-cell-alloy', '''
          <q-td key="alloy" :props="props" class="number-td">
            <q-input type="number" dense outlined :min="0" :step="0.001"
                     v-model.number="props.row._alloy"
                     @focus="() => emit('cell-focus')"
                     @blur="() => emit('alloy-blur', { row: props.row, value: Number(props.row._alloy) })" />
          </q-td>
        ''')
        table.add_slot('body-cell-actions', '''
          <q-td key="actions" :props="props" class="action-td">
            <q-btn size="sm" color="primary" label="SUPPLY"
                   @click="() => emit('supply-row', props.row)" />
          </q-td>
        ''')

        # event handlers
        async def on_focus(_e): editing['value'] = True

        async def on_scrap_blur(e):
            data = getattr(e, 'args', {}) or {}
            row  = data.get('row') or {}
            val  = float(data.get('value') or 0.0)
            rid  = row_id(row)
            st   = ensure_state(row)

            metal = row.get('metal_name', '')
            avail = scrap_by_metal.get(metal, None)

            # only enforce if we already know the reserve
            if avail is not None and val > float(avail) + 1e-9:
                notify(f"Scrap exceeds reserve for {metal}: {val:.3f} > {float(avail):.3f}", color='negative')
                val = st['scrap']  # keep previous value

            if val < 0:
                val = st['scrap']

            st['scrap'] = float(val)

            # autocalc fresh = total - scrap → split into 24K / alloy
            total = float(row.get('metal_weight') or 0.0)
            fresh = max(total - st['scrap'], 0.0)
            fine, alloy = calc_fine_alloy_for_fresh(metal, fresh)
            if not st['override_fine']:
                st['fine'] = fine
            if not st['override_alloy']:
                st['alloy'] = alloy

            # reflect to the displayed row
            for r in table.rows:
                if row_id(r) == rid:
                    r['_scrap'] = st['scrap']
                    r['_fine']  = st['fine']
                    r['_alloy'] = st['alloy']
                    break
            table.update()
            editing['value'] = False

        async def on_fine_blur(e):
            data = getattr(e, 'args', {}) or {}
            row  = data.get('row') or {}
            val  = float(data.get('value') or 0.0)
            st   = ensure_state(row)
            st['fine'] = float(val); st['override_fine'] = True
            editing['value'] = False

        async def on_alloy_blur(e):
            data = getattr(e, 'args', {}) or {}
            row  = data.get('row') or {}
            val  = float(data.get('value') or 0.0)
            st   = ensure_state(row)
            st['alloy'] = float(val); st['override_alloy'] = True
            editing['value'] = False

        async def on_supply_row(e):
            row = getattr(e, 'args', None)
            if not isinstance(row, dict):
                return
            rid = row_id(row)
            if rid is None:
                notify("Cannot post: missing flask id", color='negative')
                return
            st = ensure_state(row)
            metal = row.get('metal_name', '')
            scrap_supplied = float(st['scrap'] or 0.0)
            avail = scrap_by_metal.get(metal, None)
            if avail is not None and scrap_supplied > float(avail) + 1e-9:
                notify(f"Scrap exceeds reserve for {metal}: {scrap_supplied:.3f} > {float(avail):.3f}", color='negative')
                return

            # Build payload EXACTLY as backend expects
            try:
                payload = {
                    'flask_id': int(rid),
                    'scrap_supplied': scrap_supplied,
                    'fine_24k_supplied': float(st['fine'] or 0.0),
                    'alloy_supplied': float(st['alloy'] or 0.0),
                    'posted_by': 'supply_ui',
                }
            except Exception:
                notify("Invalid flask id; expected integer", color='negative')
                return

            try:
                await post_json(f'{API_URL}/supply', payload)
                notify(f"Supplied flask {row.get('flask_no')}", color='positive')
                # clear local state for this row and refresh panes
                row_state.pop(rid, None)
                await safe_refresh_supply(force=True)
                await refresh_casting()
                await refresh_reserve()
            except Exception as ex:
                notify(str(ex), color='negative')

        table.on('cell-focus', on_focus)
        table.on('scrap-blur', on_scrap_blur)
        table.on('fine-blur', on_fine_blur)
        table.on('alloy-blur', on_alloy_blur)
        table.on('supply-row', on_supply_row)

        async def refresh_supply():
            rows = await fetch_supply_queue(q=search_in.value.strip())
            # filter by dates & metal
            f_date = parse_iso_date(date_from.value)
            t_date = parse_iso_date(date_to.value)
            pick   = metal_pick.value or 'All'

            pruned = []
            for r in rows:
                d = parse_iso_date(r.get('date', ''))
                if not d:
                    continue
                if f_date and d < f_date: continue
                if t_date and d > t_date: continue
                if pick != 'All' and r.get('metal_name') != pick: continue

                rid = r.get('id') or r.get('flask_id')
                if rid is None:     # must have a stable id for row-key & posting
                    continue
                r['id'] = rid

                r['date'] = to_ui(r.get('date', ''))
                if r.get('metal_weight') is not None:
                    try: r['metal_weight'] = float(r['metal_weight'])
                    except Exception: pass

                pruned.append(r)

            inject_display_fields(pruned)
            table.rows = pruned
            table.update()

        async def safe_refresh_supply(force=False):
            if editing['value'] and not force:
                return
            await refresh_supply()

        # re-query when filters change
        search_in.on('change', lambda _e: asyncio.create_task(safe_refresh_supply()))
        date_from.on('change', lambda _e: asyncio.create_task(safe_refresh_supply()))
        date_to.on('change',   lambda _e: asyncio.create_task(safe_refresh_supply()))
        metal_pick.on('change', lambda _e: asyncio.create_task(safe_refresh_supply()))

    # ----------- BOTTOM: Reserve + Casting -----------
    with ui.row().classes('w-full gap-4 px-4 pb-4'):
        with ui.card().classes('flex-1 p-4').style('height:50vh; overflow:auto;'):
            ui.label('Scrap Reserve').classes('text-base font-semibold mb-2')
            reserve_table = ui.table(
                columns=[{'name':'metal','label':'Metal','field':'metal_name'},
                         {'name':'qty','label':'Scrap Available','field':'qty_on_hand'}],
                rows=[],
            ).props('dense flat bordered').classes('w-full text-sm')

            async def refresh_reserve():
                rows = await fetch_reserves()
                scrap_by_metal.clear()
                normalized = []
                for r in rows:
                    name = r.get('metal_name') or r.get('metal') or r.get('name')
                    qty  = r.get('qty_on_hand') or r.get('qty') or r.get('amount') or 0
                    try: qty = float(qty)
                    except Exception: qty = 0.0
                    if name:
                        scrap_by_metal[name] = qty
                        normalized.append({'metal_name': name, 'qty_on_hand': qty})
                reserve_table.rows = normalized
                reserve_table.update()

        with ui.card().classes('flex-1 p-4').style('height:50vh; overflow:auto;'):
            ui.label('Casting Queue').classes('text-base font-semibold mb-2')
            casting_table = ui.table(
                columns=[{'name':'date','label':'Date','field':'date'},
                         {'name':'flask_no','label':'Flask No','field':'flask_no'},
                         {'name':'metal','label':'Metal','field':'metal_name'},
                         {'name':'mw','label':'Metal Wt','field':'metal_weight'},
                         {'name':'stage','label':'Stage','field':'status'}],
                rows=[],
            ).props('dense flat bordered').classes('w-full text-sm')

            async def refresh_casting():
                rows = await fetch_casting_queue()
                for r in rows:
                    r['date'] = to_ui(r.get('date', ''))
                    if r.get('metal_weight') is not None:
                        try: r['metal_weight'] = float(r['metal_weight'])
                        except Exception: pass
                casting_table.rows = rows
                casting_table.update()

    # ----------- timers + initial load -----------
    ui.timer(5.0,  lambda: asyncio.create_task(safe_refresh_supply()))
    ui.timer(10.0, lambda: asyncio.create_task(refresh_reserve()))
    ui.timer(7.0,  lambda: asyncio.create_task(refresh_casting()))

    asyncio.create_task(safe_refresh_supply(force=True))
    asyncio.create_task(refresh_reserve())
    asyncio.create_task(refresh_casting())
