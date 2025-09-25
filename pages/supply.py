# jewelry-casting-ui/pages/supply.py
from nicegui import ui, Client # type: ignore
import httpx, os, asyncio # type: ignore
from datetime import datetime, date
from typing import Any, Dict, List, Optional

API_URL = os.getenv('API_URL', 'http://localhost:8000')
print('UI using API_URL =', API_URL)

# ---------------- helpers ----------------
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

async def fetch_supply_queue(flask_no: str = '') -> List[Dict[str, Any]]:
    params = {'flask_no': flask_no} if flask_no else None
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(f'{API_URL}/queue/supply', params=params)
        r.raise_for_status()
        return r.json()

async def fetch_metals() -> List[Dict[str, Any]]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(f'{API_URL}/metals')
        r.raise_for_status()
        return r.json()

async def fetch_reserves() -> List[Dict[str, Any]]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(f'{API_URL}/scrap/reserves')
        r.raise_for_status()
        return r.json()

async def post_supply(payload: Dict[str, Any]) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(f'{API_URL}/supply', json=payload)
        try:
            r.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise RuntimeError(explain_http_error(e)) from e
        return r.json()

# --- composition rules mirrored from backend ---
def rule_for_metal(metal_name: str) -> Dict[str, Any]:
    if not metal_name:
        return {"type": "none"}
    m = metal_name.strip().lower()
    if m in ("platinum", "silver"):
        return {"type": "pure_only"}  # alloy must be 0
    if m.startswith("10"):
        return {"type": "gold_ratio", "fine": 5, "alloy": 7}  # 5:7
    if m.startswith("14"):
        return {"type": "gold_ratio", "fine": 7, "alloy": 5}  # 7:5
    if m.startswith("18"):
        return {"type": "gold_ratio", "fine": 3, "alloy": 1}  # 3:1
    return {"type": "none"}

def split_with_ratio(total: float, fine_part: int, alloy_part: int):
    denom = fine_part + alloy_part
    if denom <= 0:
        return 0.0, 0.0
    fine = total * (fine_part / denom)
    alloy = total - fine
    return round(fine, 3), round(alloy, 3)

# ---------------- page ----------------
@ui.page('/supply')
async def supply_page(client: Client):
    # safe notifier in UI context
    def notify(msg: str, color='primary'):
        with client:
            ui.notify(msg, color=color)

    ui.page_title('Metal Supply · Casting Tracker')
    ui.add_head_html("""
    <style>
      .fill-parent { width:100% !important; max-width:100% !important; }
    </style>
    """)

    with ui.header().classes('items-center justify-between bg-gray-900 text-white'):
        ui.label('Metal Supply').classes('text-lg font-semibold')
        ui.button('Home', on_click=lambda: ui.navigate.to('/')).props('flat').classes('text-white')

    # preload metals for filter options (left panel)
    try:
        metals = await fetch_metals()
        metal_options = ['All'] + sorted([m['name'] for m in metals if 'name' in m])
    except Exception as e:
        notify(f'Failed to load metals: {e}', color='negative')
        metal_options = ['All']

    # page state
    selected: Dict[str, Any] | None = None
    # override flags (if user edits these manually, stop auto-calc)
    fine_overridden = False
    alloy_overridden = False
    pure_overridden = False

    # ---- layout ----
    with ui.splitter(value=60).classes('px-6').style('width: 100%; height: calc(100vh - 140px);') as main_split:

        # LEFT: queue (top ~2/3) + reserves (bottom ~1/3)
        with main_split.before:
            with ui.card().classes('w-full h-full p-0'):
                inner = ui.splitter(value=55).props('horizontal').style('width:100%; height:100%')

                # TOP: Queue (filters fixed, rows scroll)
                with inner.before:
                    with ui.column().classes('w-full h-full').style('display:flex; flex-direction:column;'):
                        today_iso = date.today().isoformat()
                        with ui.row().classes('items-end gap-3 p-4').style('flex:0 0 auto;'):
                            ui.label('Flasks in Metal Supply').classes('text-base font-semibold mr-4')
                            search = ui.input('Search by Flask No').props('clearable').classes('w-48')
                            date_from = ui.input('From', value=today_iso).props('type=date').classes('w-36')
                            date_to   = ui.input('To',   value=today_iso).props('type=date').classes('w-36')
                            metal_pick = ui.select(options=metal_options, value='All', label='Metal').classes('w-48')
                            metal_pick.props('options-dense behavior=menu popup-content-style="z-index:4000"')

                            async def reset_filters():
                                date_from.value = today_iso
                                date_to.value   = today_iso
                                metal_pick.value = 'All'
                                search.value = ''
                                await refresh_current()
                                notify('Filters reset to today / All metals', color='positive')

                            ui.button('RESET FILTERS', on_click=lambda: asyncio.create_task(reset_filters())).props('outline')

                        with ui.element('div').classes('fill-parent').style(
                            'flex:1 1 auto; overflow:auto; padding:0 16px 16px 16px; width:100%; max-width:100%;'
                        ):
                            columns = [
                                {'name': 'date',         'label': 'Date',        'field': 'date'},
                                {'name': 'flask_no',     'label': 'Flask No',    'field': 'flask_no'},
                                {'name': 'metal_name',   'label': 'Metal',       'field': 'metal_name'},
                                {'name': 'metal_weight', 'label': 'Required Wt', 'field': 'metal_weight'},
                            ]
                            table = ui.table(columns=columns, rows=[]) \
                                      .props('dense flat bordered row-key="flask_id" selection="single" hide-bottom') \
                                      .classes('w-full text-sm')

                # BOTTOM: Scrap Reserve (scroll)
                with inner.after:
                    with ui.column().classes('w-full h-full').style('display:flex; flex-direction:column;'):
                        with ui.row().classes('items-center justify-between p-4').style('flex:0 0 auto;'):
                            ui.label('Scrap Reserve').classes('text-base font-semibold')
                        with ui.element('div').classes('fill-parent').style(
                            'flex:1 1 auto; overflow:auto; padding:0 16px 16px 16px; width:100%; max-width:100%;'
                        ):
                            reserve_columns = [
                                {'name': 'metal', 'label': 'Metal', 'field': 'metal_name'},
                                {'name': 'qty',   'label': 'Scrap Available', 'field': 'qty_on_hand'},
                            ]
                            reserve_table = ui.table(columns=reserve_columns, rows=[]) \
                                              .props('dense flat bordered hide-bottom') \
                                              .classes('w-full text-sm')

        # RIGHT: editor
        with main_split.after:
            with ui.card().classes('w-full h-full p-4'):
                ui.label('Supply to Selected Flask').classes('text-base font-semibold mb-2')

                with ui.grid(columns=2).classes('gap-2 mb-2'):
                    ui.label('Flask No:');     flask_no_lbl = ui.label('—')
                    ui.label('Metal:');        metal_lbl    = ui.label('—')
                    ui.label('Required Wt:');  req_lbl      = ui.label('—')

                # common scrap input
                scrap_in = ui.number('Scrap', value=0.0).classes('w-full')

                # GOLD inputs group
                gold_box = ui.column().classes('w-full')
                with gold_box:
                    fine_in  = ui.number('24K',   value=0.0).classes('w-full')
                    alloy_in = ui.number('Alloy', value=0.0).classes('w-full')

                # PURE inputs group (Pt / Silver)
                pure_box = ui.column().classes('w-full')
                with pure_box:
                    pure_in = ui.number('Pure Metal', value=0.0).classes('w-full')
                # start hidden (we show/hide depending on selected row)
                pure_box.visible = False

                # ---- behaviors for editor ----
                def show_gold():
                    gold_box.visible = True
                    pure_box.visible = False
                    gold_box.update(); pure_box.update()

                def show_pure():
                    gold_box.visible = False
                    pure_box.visible = True
                    gold_box.update(); pure_box.update()

                def reset_overrides():
                    nonlocal fine_overridden, alloy_overridden, pure_overridden
                    fine_overridden = False
                    alloy_overridden = False
                    pure_overridden = False

                def current_required_and_rule():
                    if not selected:
                        return 0.0, {"type": "none"}
                    required_wt = float(selected.get('metal_weight') or 0.0)
                    rule = rule_for_metal(selected.get('metal_name') or '')
                    return required_wt, rule

                def auto_fill_from_required():
                    """When a row is selected OR scrap changes (and not overridden)."""
                    required_wt, rule = current_required_and_rule()
                    scrap_val = float(scrap_in.value or 0.0)
                    remain = max(required_wt - scrap_val, 0.0)
                    if rule["type"] == "pure_only":
                        if not pure_overridden:
                            pure_in.value = round(remain, 3)
                    elif rule["type"] == "gold_ratio":
                        if not (fine_overridden or alloy_overridden):
                            f, a = rule["fine"], rule["alloy"]
                            fval, aval = split_with_ratio(remain, f, a)
                            fine_in.value = fval
                            alloy_in.value = aval
                    else:
                        # no rule: clear unless overridden
                        if not pure_overridden and pure_box.visible:
                            pure_in.value = round(remain, 3)
                        if gold_box.visible and not (fine_overridden or alloy_overridden):
                            fine_in.value = 0.0
                            alloy_in.value = 0.0

                # select row -> fill labels + default numbers and show right group
                async def sync_selection_from_table():
                    nonlocal selected
                    row_list = table.selected or []
                    row = row_list[0] if row_list else None
                    selected = row
                    reset_overrides()
                    with client:
                        if not row:
                            flask_no_lbl.text = '—'
                            metal_lbl.text = '—'
                            req_lbl.text = '—'
                            scrap_in.value = 0.0
                            fine_in.value = 0.0
                            alloy_in.value = 0.0
                            pure_in.value = 0.0
                            show_gold()
                        else:
                            flask_no_lbl.text = f"{row.get('flask_no', '—')}"
                            metal_lbl.text    = f"{row.get('metal_name', '—')}"
                            req_lbl.text      = f"{row.get('metal_weight', '—')}"
                            scrap_in.value = 0.0
                            # choose group
                            rule = rule_for_metal(row.get('metal_name') or '')
                            if rule["type"] == "pure_only":
                                show_pure()
                                pure_in.value = 0.0
                            else:
                                show_gold()
                                fine_in.value  = 0.0
                                alloy_in.value = 0.0
                        # now auto-calc once on selection
                        auto_fill_from_required()

                # input events
                scrap_in.on('change', lambda _e: auto_fill_from_required())
                fine_in.on('change',  lambda _e: (globals().update(fine_overridden=True), None))
                alloy_in.on('change', lambda _e: (globals().update(alloy_overridden=True), None))
                pure_in.on('change',  lambda _e: (globals().update(pure_overridden=True), None))

                async def submit():
                    if not selected:
                        notify('Please select a flask from the table first.', color='warning'); return
                    fid = selected.get('flask_id') or selected.get('id')
                    if fid is None:
                        notify('Internal error: missing flask_id on selected row', color='negative'); return

                    rule = rule_for_metal(selected.get('metal_name') or '')
                    scrap = float(scrap_in.value or 0.0)
                    if rule["type"] == "pure_only":
                        payload = {
                            'flask_id': int(fid),
                            'scrap_supplied': scrap,
                            'fine_24k_supplied': float(pure_in.value or 0.0),
                            'alloy_supplied': 0.0,
                            'posted_by': 'supply_ui',
                        }
                    else:
                        payload = {
                            'flask_id': int(fid),
                            'scrap_supplied': scrap,
                            'fine_24k_supplied': float(fine_in.value or 0.0),
                            'alloy_supplied': float(alloy_in.value or 0.0),
                            'posted_by': 'supply_ui',
                        }

                    try:
                        await post_supply(payload)
                        notify(f"Supplied flask {selected.get('flask_no')}", color='positive')
                        # remove from table & clear editor
                        with client:
                            table.rows = [r for r in table.rows if (r.get('flask_id') or r.get('id')) != fid]
                            table.selected = []
                            table.update()
                            flask_no_lbl.text = '—'
                            metal_lbl.text = '—'
                            req_lbl.text = '—'
                            scrap_in.value = 0.0
                            fine_in.value  = 0.0
                            alloy_in.value = 0.0
                            pure_in.value  = 0.0
                            show_gold()
                        await refresh_reserve()
                    except Exception as ex:
                        notify(str(ex), color='negative')

                def recompute_defaults():
                    # drop any manual overrides and re-apply auto math
                    reset_overrides()
                    auto_fill_from_required()

                with ui.row().classes('gap-2 mt-2'):
                    ui.button('Recalculate', on_click=recompute_defaults).props('outline')
                    ui.button('Supply', on_click=lambda: asyncio.create_task(submit())) \
                    .classes('bg-emerald-600 text-white')

    # ---------- data & behaviors for left panel ----------
    async def _load_rows() -> List[Dict[str, Any]]:
        try:
            return await fetch_supply_queue(search.value.strip() if search.value else '')
        except Exception as e:
            notify(f'Failed to fetch supply queue: {e}', color='negative')
            return []

    def _apply_filters(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        f_date = parse_iso_date(date_from.value)
        t_date = parse_iso_date(date_to.value)
        pick   = metal_pick.value or 'All'

        out: List[Dict[str, Any]] = []
        for r in rows:
            rid = r.get('flask_id') or r.get('id')
            if rid is None:
                continue
            d_iso = r.get('date', '') or ''
            d = parse_iso_date(d_iso)
            if not d:
                continue
            if f_date and d < f_date:
                continue
            if t_date and d > t_date:
                continue
            if pick != 'All' and r.get('metal_name') != pick:
                continue
            rr = dict(r)
            rr['flask_id'] = rid
            rr['_sort_ord'] = -d.toordinal()                  # date DESC
            rr['_sort_metal'] = rr.get('metal_name') or ''     # metal ASC
            rr['_display_date'] = to_ui_date(d_iso)
            out.append(rr)

        out.sort(key=lambda x: (x['_sort_ord'], x['_sort_metal']))
        for rr in out:
            rr['date'] = rr['_display_date']
            for k in ('_sort_ord', '_sort_metal', '_display_date'):
                rr.pop(k, None)
        return out

    async def refresh_current():
        rows = await _load_rows()
        normalized = _apply_filters(rows)
        with client:
            table.rows = normalized
            table.update()
            if normalized:
                if not table.selected or table.selected[0] not in normalized:
                    table.selected = [normalized[0]]
            else:
                table.selected = []
            table.update()
            await sync_selection_from_table()

    async def refresh_reserve():
        try:
            rows = await fetch_reserves()
        except Exception as e:
            notify(f'Failed to fetch reserves: {e}', color='negative')
            rows = []
        normalized = []
        for r in rows:
            name = r.get('metal_name') or r.get('metal') or r.get('name')
            qty  = r.get('qty_on_hand') or r.get('qty') or 0
            if name is None:
                continue
            try: qty = float(qty)
            except Exception: qty = 0.0
            normalized.append({'metal_name': name, 'qty_on_hand': qty})
        normalized.sort(key=lambda x: x['metal_name'])
        with client:
            reserve_table.rows = normalized
            reserve_table.update()

    # filter events (instant)
    search.on('change',     lambda _e: asyncio.create_task(refresh_current()))
    metal_pick.on('update:model-value', lambda _v: asyncio.create_task(refresh_current()))
    date_from.on('change',  lambda _e: asyncio.create_task(refresh_current()))
    date_to.on('change',    lambda _e: asyncio.create_task(refresh_current()))
    table.on('selection',   lambda _e: asyncio.create_task(sync_selection_from_table()))

    # initial load
    await asyncio.create_task(refresh_current())
    await asyncio.create_task(refresh_reserve())
