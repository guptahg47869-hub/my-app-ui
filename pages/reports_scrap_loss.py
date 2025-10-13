import os, httpx
from nicegui import ui, Client

API_URL = os.getenv('API_URL', 'http://localhost:8000')

@ui.page('/reports/scrap-loss')
async def reports_scrap_loss(client: Client):
    ui.page_title('Scrap Loss')

    with ui.header().classes('items-center justify-between bg-gray-900 text-white'):
        ui.label('Scrap Loss').classes('text-lg font-semibold')
        with ui.row().classes('items-center gap-2'):
            ui.link('Reports', '/reports').classes('text-white')

    # --- Filters ---
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

    cols = [
        {'name':'date','label':'Date','field':'date'},
        {'name':'flask_no','label':'Flask No','field':'flask_no'},
        {'name':'metal_name','label':'Metal','field':'metal_name'},
        {'name':'before_cut_A','label':'Before','field':'before_cut_A','align':'right'},
        {'name':'after_casting_C','label':'After Casting','field':'after_casting_C','align':'right'},
        {'name':'after_scrap_B','label':'After Scrap','field':'after_scrap_B','align':'right'},
        {'name':'loss','label':'Scrap Loss','field':'loss','align':'right'},
    ]
    table = ui.table(columns=cols, rows=[]) \
        .props('dense flat bordered hide-bottom row-key="id"') \
        .classes('mx-6 mt-4')

    async def fetch():
        raw = {
            'date_from': d_from.value or None,
            'date_to':   d_to.value or None,
            'metal':     metal.value or None,
        }
        params = {k: v for k, v in raw.items() if v not in (None, '', 'All')}
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.get(f'{API_URL}/reports/scrap_loss', params=params)
            r.raise_for_status()
            return r.json()

    async def refresh():
        try:
            data = await fetch()
            for r in data:
                # normalize numeric fields to 3 decimals
                for k in ('before_cut_A','after_casting_C','after_scrap_B','loss'):
                    try:
                        r[k] = round(float(r.get(k) or 0.0), 3)
                    except Exception:
                        pass
            table.rows = data
            table.update()
        except Exception as ex:
            ui.notify(f'Failed to load scrap loss: {ex}', color='negative')

    with ui.row().classes('justify-end px-6 pt-2'):
        def export_csv():
            csv = 'Date,Flask,Metal,Before,AfterCasting,AfterScrap,Loss\n' + '\n'.join(
                f"{r.get('date','')},{r.get('flask_no','')},{r.get('metal_name','')},{r.get('before_cut_A','')},{r.get('after_casting_C','')},{r.get('after_scrap_B','')},{r.get('loss','')}"
                for r in table.rows
            )
            ui.download(bytes(csv, 'utf-8'), filename='scrap_loss.csv')
        ui.button('Export CSV', on_click=export_csv).props('color=primary')

    # hook up filter changes
    async def _on_filter_change(_e=None):
        await refresh()
    d_from.on('change', _on_filter_change)
    d_to.on('change', _on_filter_change)
    metal.on('change', _on_filter_change)

    # initial load in context
    await refresh()
