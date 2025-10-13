import os, httpx, asyncio
from nicegui import ui, Client

API_URL = os.getenv('API_URL', 'http://localhost:8000')

@ui.page('/reports/transit')
async def reports_transit(client: Client):
    ui.page_title('Transit Summary')

    with ui.header().classes('items-center justify-between bg-gray-900 text-white'):
        ui.label('Transit Summary').classes('text-lg font-semibold')
        with ui.row().classes('items-center gap-2'):
            ui.link('Reports', '/reports').classes('text-white')

    # --- Filters (no auto-date; send nothing when blank) ---
    with ui.row().classes('items-end gap-3 px-6 pt-4'):
        d_from = ui.input('From').props('type=date dense outlined').classes('w-44')
        d_to   = ui.input('To').props('type=date dense outlined').classes('w-44')
        metal  = ui.input('Metal (optional)').props('dense outlined clearable').classes('w-56')
        def reset():
            d_from.value = ''
            d_to.value = ''
            metal.value = ''
            ui.run(refresh)
        ui.button('RESET FILTERS', on_click=reset).props('outline')

    # --- Tables ---
    summary_cols = [
        {'name':'metal_name','label':'Metal','field':'metal_name'},
        {'name':'count','label':'# Trees','field':'count','align':'right'},
        {'name':'total_est_metal_weight','label':'Total Est. Metal','field':'total_est_metal_weight','align':'right'},
    ]
    drill_cols = [
        {'name':'date','label':'Date','field':'date'},
        {'name':'tree_no','label':'Tree No','field':'tree_no'},
        {'name':'metal_name','label':'Metal','field':'metal_name'},
        {'name':'tree_weight','label':'Tree Wt','field':'tree_weight','align':'right'},
        {'name':'est_metal_weight','label':'Est. Metal','field':'est_metal_weight','align':'right'},
    ]

    with ui.card().classes('w-full mx-6 mt-4'):
        ui.label('Summary by Metal').classes('text-lg font-medium')
        summary_table = ui.table(columns=summary_cols, rows=[]) \
            .props('dense flat bordered row-key="metal_name" hide-bottom selection="single"')
        with ui.row().classes('justify-end'):
            ui.button('Export CSV', on_click=lambda: export_summary(summary_table.rows)).props('color=primary')

    with ui.card().classes('w-full mx-6 mt-4'):
        drill_title = ui.label('Trees in Transit').classes('text-lg font-medium')
        drill_table = ui.table(columns=drill_cols, rows=[]) \
            .props('dense flat bordered row-key="tree_no" hide-bottom')
        # total-row styling (applied once; the prop expression is reactive)
        drill_table.props(
            ":row-style=\"row => row.is_total ? 'font-weight:700;border-top:2px solid #000;border-bottom:2px solid #000;' : ''\""
        )
        with ui.row().classes('justify-end'):
            ui.button('Export CSV', on_click=lambda: export_drill(drill_table.rows)).props('color=primary')

    # ---- Data helpers ----
    async def fetch_summary():
        raw = {
            'date_from': d_from.value or None,
            'date_to':   d_to.value or None,
            'metal':     metal.value or None,
        }
        params = {k: v for k, v in raw.items() if v not in (None, '', 'All')}
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.get(f'{API_URL}/reports/transit', params=params)
            r.raise_for_status()
            return r.json()

    async def fetch_trees(sel_metal: str):
        raw = {
            'date_from': d_from.value or None,
            'date_to':   d_to.value or None,
            'metal':     sel_metal or None,
        }
        params = {k: v for k, v in raw.items() if v not in (None, '', 'All')}
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.get(f'{API_URL}/reports/transit/trees', params=params)
            r.raise_for_status()
            return r.json()

    async def refresh():
        try:
            data = await fetch_summary()
            rows = data.get('rows', [])
            for r in rows:
                try:
                    r['total_est_metal_weight'] = round(float(r['total_est_metal_weight']), 3)
                except Exception:
                    pass
            summary_table.rows = rows
            summary_table.update()
            # clear drill
            drill_table.rows = []
            drill_title.text = 'Trees in Transit'
        except Exception as ex:
            ui.notify(f'Failed to load transit: {ex}', color='negative')

    # selection handler (no decorator; works on current NiceGUI)
    async def _on_pick(_e=None):
        sel = getattr(summary_table, 'selection', None) or getattr(summary_table, 'selected', None) or []
        if not sel:
            drill_table.rows = []
            drill_title.text = 'Trees in Transit'
            return
        metal_name = sel[0].get('metal_name')
        drill_title.text = f'Trees in Transit — {metal_name}'
        try:
            trees = await fetch_trees(metal_name)
            # add total row
            tot_wt  = sum(float(x.get('tree_weight') or 0) for x in trees)
            tot_est = sum(float(x.get('est_metal_weight') or 0) for x in trees)
            trees.append({
                'date':'', 'tree_no':'TOTAL', 'metal_name':'',
                'tree_weight': round(tot_wt, 3),
                'est_metal_weight': round(tot_est, 3),
                'is_total': True,
            })
            drill_table.rows = trees
            drill_table.update()
        except Exception as ex:
            ui.notify(f'Failed to load trees: {ex}', color='negative')

    summary_table.on('selection', _on_pick)

    # filter change handlers
    async def _on_filter_change(_e=None):
        await refresh()
    d_from.on('change', _on_filter_change)
    d_to.on('change', _on_filter_change)
    metal.on('change', _on_filter_change)

    # first load (inside page context)
    await refresh()

    # --- CSV exports ---
    def export_summary(rows):
        csv = 'Metal,# Trees,Total Est. Metal\n' + '\n'.join(
            f"{r.get('metal_name','')},{r.get('count','')},{r.get('total_est_metal_weight','')}" for r in rows
        )
        ui.download(bytes(csv, 'utf-8'), filename='transit_summary.csv')

    def export_drill(rows):
        csv = 'Date,Tree No,Metal,Tree Wt,Est. Metal\n' + '\n'.join(
            f"{r.get('date','')},{r.get('tree_no','')},{r.get('metal_name','')},{r.get('tree_weight','')},{r.get('est_metal_weight','')}"
            for r in rows if not r.get('is_total')
        )
        ui.download(bytes(csv, 'utf-8'), filename='transit_trees.csv')
