# pages/flask_search.py
from __future__ import annotations

import os
import io
import csv
import base64
import asyncio
from typing import Any, Dict, List

import httpx
from nicegui import ui, context  # <-- use context.client (no ui.get_client)

API_URL = os.getenv('API_URL', 'http://127.0.0.1:8000')

# Label <-> code mapping
STAGE_LABEL_TO_CODE: Dict[str, str] = {
    'Active (not Done)': 'active',
    'Transit': 'transit',
    'Metal Prep': 'metal_prep',
    'Supply': 'supply',
    'Casting': 'casting',
    'Quenching': 'quenching',
    'Cutting': 'cutting',
    'Reconciliation': 'reconciliation',
    'Done': 'done',
    'All': 'all',
}
STAGE_CODE_TO_LABEL = {v: k for k, v in STAGE_LABEL_TO_CODE.items()}
STAGE_LABELS: List[str] = list(STAGE_LABEL_TO_CODE.keys())


async def api_get(path: str, params: Dict[str, Any] | None = None) -> Any:
    url = f'{API_URL}{path}'
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        return r.json()


@ui.page('/flask-search')
def flask_search() -> None:
    ui.page_title('Flask Search')
    client = context.client  # <-- capture the current client for later 'with client:' blocks

    with ui.column().classes('w-full gap-2'):
        ui.label('Flask Search').classes('text-2xl font-bold')

        # ---------------- Filters ----------------
        with ui.row().classes('items-end justify-between w-full'):
            with ui.row().classes('items-end gap-3'):
                q_ft   = ui.input('Flask / Tree').props('dense clearable').classes('w-48')
                q_bag  = ui.input('Bag No').props('dense clearable').classes('w-40')

                date_from = ui.input('From').props('dense clearable type=date').classes('w-36')
                date_to   = ui.input('To').props('dense clearable type=date').classes('w-36')

                stage_sel = ui.select(STAGE_LABELS, label='Stage') \
                              .props('dense clearable') \
                              .classes('w-56')
                stage_sel.value = 'Active (not Done)'

                metal_sel = ui.select([], label='Metal') \
                              .props('dense clearable use-input input-debounce="0"') \
                              .classes('w-40')

            with ui.row().classes('items-end gap-2'):
                reset_btn  = ui.button('RESET FILTERS', on_click=lambda: asyncio.create_task(reset_filters())) \
                              .props('outline').classes('q-px-md')
                export_btn = ui.button('EXPORT (CSV)', on_click=lambda: export_csv()).classes('q-px-md')

        # ---------------- Table ----------------
        columns = [
            {'name': 'date',         'label': 'Date',      'field': 'date',         'sortable': True},
            {'name': 'stage_label',  'label': 'Stage',     'field': 'stage_label',  'sortable': True},
            {'name': 'metal_name',   'label': 'Metal',     'field': 'metal_name',   'sortable': True},
            {'name': 'flask_no',     'label': 'Flask No',  'field': 'flask_no',     'sortable': True},
            {'name': 'tree_no',      'label': 'Tree No',   'field': 'tree_no',      'sortable': True},
            {'name': 'metal_weight', 'label': 'Metal Wt',  'field': 'metal_weight', 'align': 'right', 'sortable': True},
            {'name': 'bag_nos_text', 'label': 'Bags',      'field': 'bag_nos_text'},
        ]
        table = ui.table(columns=columns, rows=[]) \
                  .props('dense flat bordered hide-bottom row-key="id"') \
                  .classes('w-full')

        # ---------------- Behaviors ----------------
        async def refresh_metals() -> None:
            try:
                metals = await api_get('/metals')
                metal_names = [m['name'] for m in metals] if metals and isinstance(metals[0], dict) else (metals or [])
                with client:
                    metal_sel.options = metal_names
            except Exception as ex:
                with client:
                    ui.notify(f'Failed to load metals: {ex}', color='negative')

        async def refresh_table() -> None:
            params: Dict[str, Any] = {}
            stage_label = stage_sel.value or 'Active (not Done)'
            params['stage'] = STAGE_LABEL_TO_CODE.get(stage_label, 'active')
            if date_from.value:
                params['date_from'] = date_from.value
            if date_to.value:
                params['date_to'] = date_to.value
            if metal_sel.value:
                params['metal'] = metal_sel.value
            if q_ft.value:
                params['q'] = q_ft.value           # flask/tree
            if q_bag.value:
                params['bag'] = q_bag.value        # bag only

            try:
                data = await api_get('/search/flasks', params=params)
                for r in data:
                    r['stage_label'] = STAGE_CODE_TO_LABEL.get(r.get('stage'), r.get('stage') or '')
                    if not r.get('bag_nos_text'):
                        bags = r.get('bag_nos') or []
                        r['bag_nos_text'] = ', '.join(bags)
                    if r.get('metal_weight') is not None:
                        try:
                            r['metal_weight'] = f"{float(r['metal_weight']):.3f}"
                        except Exception:
                            pass
                with client:
                    table.rows = data
            except httpx.HTTPStatusError as he:
                with client:
                    ui.notify(f'Failed to load flasks: {he}', color='negative')
            except Exception as ex:
                with client:
                    ui.notify(f'Error: {ex}', color='negative')

        async def reset_filters() -> None:
            q_ft.value = ''
            q_bag.value = ''
            date_from.value = None
            date_to.value = None
            metal_sel.value = None
            stage_sel.value = 'Active (not Done)'
            await refresh_table()

        # live filtering
        q_ft.on('keyup',   lambda e: asyncio.create_task(refresh_table()))
        q_bag.on('keyup',  lambda e: asyncio.create_task(refresh_table()))
        date_from.on('change', lambda e: asyncio.create_task(refresh_table()))
        date_to.on('change',   lambda e: asyncio.create_task(refresh_table()))
        metal_sel.on('update:model-value', lambda e: asyncio.create_task(refresh_table()))
        stage_sel.on('update:model-value', lambda e: asyncio.create_task(refresh_table()))

        # ---------------- Export ----------------
        def export_csv() -> None:
            rows: List[Dict[str, Any]] = table.rows or []
            if not rows:
                with client:
                    ui.notify('Nothing to export', color='warning')
                return
            fields = ['date', 'stage_label', 'metal_name', 'flask_no', 'tree_no', 'metal_weight', 'bag_nos_text']
            buf = io.StringIO()
            w = csv.DictWriter(buf, fieldnames=fields)
            w.writeheader()
            for r in rows:
                w.writerow({k: r.get(k, '') for k in fields})
            b64 = base64.b64encode(buf.getvalue().encode('utf-8')).decode('ascii')
            with client:
                ui.run_javascript(f"""
                    (function(){{
                        const a=document.createElement('a');
                        a.href='data:text/csv;base64,{b64}';
                        a.download='flasks.csv';
                        document.body.appendChild(a);
                        a.click();
                        a.remove();
                    }})();
                """)

        # initial loads
        ui.timer(0.01, lambda: asyncio.create_task(refresh_metals()), once=True)
        ui.timer(0.02, lambda: asyncio.create_task(refresh_table()), once=True)
