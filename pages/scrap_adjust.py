# pages/scrap_adjust.py
from nicegui import ui, Client  # type: ignore
import httpx, os, asyncio  # type: ignore
from typing import Any, Dict, List

API_URL = os.getenv('API_URL', 'http://localhost:8000')
print('UI using API_URL =', API_URL)

# ---------- API helpers ----------
async def fetch_reserves() -> List[Dict[str, Any]]:
    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.get(f'{API_URL}/scrap/reserves')
        r.raise_for_status()
        return r.json()

async def post_adjust(metal_id: int, action: str, amount: float) -> Dict[str, Any]:
    payload = {'metal_id': metal_id, 'action': action, 'amount': amount}
    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.post(f'{API_URL}/scrap/adjust', json=payload)
        r.raise_for_status()
        return r.json()

# ---------- PAGE ----------
@ui.page('/scrap-adjust')
async def scrap_adjust_page(client: Client):
    ui.page_title('Scrap Reserve Adjust · Casting Tracker')

    def notify(msg: str, color='primary'):
        with client:
            ui.notify(msg, color=color)

    ui.add_head_html('''
    <style>
      .fill-parent{width:100%!important;max-width:100%!important}
    </style>
    ''')

    with ui.header().classes('items-center justify-between bg-gray-900 text-white'):
        ui.label('Adjust Scrap Reserve').classes('text-lg font-semibold')
        ui.button(icon='home', on_click=lambda: ui.navigate.to('/')).props('flat round').classes('text-white')

    # state
    selected_row: Dict[str, Any] | None = None

    # layout: 50/50 like Supply page
    with ui.splitter(value=50).classes('px-6').style('width:100%; height: calc(100vh - 140px);') as split:

        # LEFT: current reserves table (sorted by metal name)
        with split.before:
            with ui.card().classes('w-full h-full p-0'):
                with ui.row().classes('items-center justify-between p-4 w-full'):
                    ui.label('Current Scrap Reserve').classes('text-base font-semibold')
                    refresh_btn = ui.button('REFRESH').props('outline')
                with ui.element('div').classes('fill-parent').style(
                    'flex:1 1 auto; overflow:auto; padding:0 16px 16px 16px; width:100%; max-width:100%;'
                ):
                    columns = [
                        {'name': 'metal_name', 'label': 'Metal', 'field': 'metal_name'},
                        {'name': 'qty_on_hand', 'label': 'Qty on Hand', 'field': 'qty_on_hand'},
                    ]
                    reserve_table = ui.table(columns=columns, rows=[]) \
                                      .props('flat bordered row-key="metal_id" selection="single" hide-bottom') \
                                      .classes('w-full')

        # RIGHT: editor (spread out like Supply page: wide inputs, roomy spacing, normal buttons)
        with split.after:
            with ui.card().classes('w-full h-full p-0'):
                with ui.column().classes('w-full h-full p-6 gap-4').style('display:flex;'):
                    # Big title and meta
                    ui.label('Supply to Selected Metal').classes('text-lg font-semibold')
                    meta_metal   = ui.label('Metal: —').classes('text-base text-gray-700')
                    meta_current = ui.label('Current Reserve: —').classes('text-base text-gray-700')

                    ui.separator()

                    # Wide stacked fields (full width underlines like your Supply page)
                    action_sel = ui.select(['Add', 'Remove'], value='Add', label='Action') \
                                   .classes('w-full')
                    amount_in = ui.number(label='Metal Weight', value=0.0, format='%.1f') \
                                  .classes('w-full')

                    # Preview (grey by default, red if invalid, primary when valid)
                    preview_lbl = ui.label('New Reserve: —').classes('text-base text-gray-500')

                    # Buttons (regular size)
                    with ui.row().classes('gap-3'):
                        recalc_btn = ui.button('RECALCULATE').props('outline')
                        post_btn   = ui.button('POST').props('unelevated color=primary').classes('text-white')
                        post_btn.disable()

    # ---------- behaviors ----------
    async def load_reserves():
        """Fetch, normalize, and sort by metal name A→Z."""
        try:
            rows = await fetch_reserves()
            for r in rows:
                try:
                    r['qty_on_hand'] = round(float(r.get('qty_on_hand') or 0.0), 3)
                except Exception:
                    r['qty_on_hand'] = 0.0
            rows.sort(key=lambda r: (r.get('metal_name') or '').lower())
            reserve_table.rows = rows
            reserve_table.update()
        except httpx.HTTPStatusError as e:
            try:
                detail = e.response.json().get('detail', e.response.text)
            except Exception:
                detail = e.response.text
            notify(f'Failed to load reserves: {detail}', 'negative')
        except Exception as ex:
            notify(f'Failed to load reserves: {ex}', 'negative')

    async def refresh_preview():
        """Preview new total; red if < 0; enable/disable POST accordingly."""
        nonlocal selected_row
        if not selected_row:
            preview_lbl.text = 'New Reserve: —'
            preview_lbl.classes(replace='text-base text-gray-500')
            post_btn.disable()
            return

        current = float(selected_row.get('qty_on_hand') or 0.0)
        amt = float(amount_in.value or 0.0)
        act = (action_sel.value or 'Add').lower()
        new_total = current + (amt if act == 'add' else -amt)

        if new_total < 0:
            preview_lbl.text = f'New Reserve: {new_total:.1f}  (cannot go below 0)'
            preview_lbl.classes(replace='text-base text-negative')
            post_btn.disable()
        elif amt > 0:
            preview_lbl.text = f'New Reserve: {new_total:.1f}'
            preview_lbl.classes(replace='text-base text-primary')
            post_btn.enable()
        else:
            preview_lbl.text = f'New Reserve: {new_total:.1f}'
            preview_lbl.classes(replace='text-base text-gray-500')
            post_btn.disable()

    def on_select(_e):
        nonlocal selected_row
        try:
            selected_row = (reserve_table.selected or [None])[0]
        except Exception:
            selected_row = None

        if selected_row:
            name = selected_row.get('metal_name') or '—'
            qty  = float(selected_row.get('qty_on_hand') or 0.0)
            meta_metal.text   = f'Metal: {name}'
            meta_current.text = f'Current Reserve: {qty:.1f}'

            # reset inputs & preview
            action_sel.value = 'Add'
            amount_in.value = 0.0
            preview_lbl.text = 'New Reserve: —'
            preview_lbl.classes(replace='text-base text-gray-500')
            post_btn.disable()
        else:
            meta_metal.text = 'Metal: —'
            meta_current.text = 'Current Reserve: —'
            preview_lbl.text = 'New Reserve: —'
            preview_lbl.classes(replace='text-base text-gray-500')
            post_btn.disable()

    async def do_post():
        nonlocal selected_row
        if not selected_row:
            notify('Please select a metal from the table first.', 'warning')
            return

        metal_id = int(selected_row['metal_id'])
        action   = (action_sel.value or 'Add').lower()
        amount   = float(amount_in.value or 0.0)

        if amount <= 0:
            notify('Amount must be greater than 0', 'warning')
            return

        try:
            res = await post_adjust(metal_id, action, amount)
        except httpx.HTTPStatusError as e:
            try:
                detail = e.response.json().get('detail', e.response.text)
            except Exception:
                detail = e.response.text
            notify(detail or 'Adjustment failed', 'negative')
            return
        except Exception as ex:
            notify(str(ex), 'negative')
            return

        # success: update right panel + table
        new_qty = float(res.get('qty_on_hand') or 0.0)
        meta_current.text = f'Current Reserve: {new_qty:.1f}'
        preview_lbl.text = 'New Reserve: —'
        preview_lbl.classes(replace='text-base text-gray-500')
        amount_in.value = 0.0
        post_btn.disable()
        notify('Reserve updated', 'positive')

        # reload and keep selection on the same metal
        await load_reserves()
        for r in reserve_table.rows:
            if int(r['metal_id']) == metal_id:
                reserve_table.selected = [r]
                selected_row = r
                break
        reserve_table.update()

    # wiring
    reserve_table.on('selection', on_select)
    refresh_btn.on('click', lambda: asyncio.create_task(load_reserves()))
    recalc_btn.on('click', lambda: asyncio.create_task(refresh_preview()))
    action_sel.on('update:model-value', lambda _v: asyncio.create_task(refresh_preview()))
    amount_in.on('change', lambda _e: asyncio.create_task(refresh_preview()))
    post_btn.on('click', lambda: asyncio.create_task(do_post()))

    # initial load
    await load_reserves()
