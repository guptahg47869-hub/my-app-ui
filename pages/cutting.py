from nicegui import ui, Client  # type: ignore
import httpx, os, asyncio  # type: ignore
from datetime import date, datetime
from typing import Any, Dict, List, Optional

API_URL = os.getenv('API_URL', 'http://localhost:8000')
print('UI using API_URL =', API_URL)

# ---------- helpers ----------
def to_ui_date(iso: str) -> str:
    try:
        return datetime.strptime(iso, '%Y-%m-%d').strftime('%m-%d-%y')
    except Exception:
        return iso

def parse_iso_date(s: str) -> Optional[date]:
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

# ---------- API ----------
async def fetch_metals() -> List[Dict[str, Any]]:
    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.get(f'{API_URL}/metals')
        r.raise_for_status()
        return r.json()

async def fetch_cutting_queue(flask_no: str | None = None) -> List[Dict[str, Any]]:
    """/queue/cutting returns flasks in cutting stage; includes 'metal_weight' (supplied)."""
    # params = {'flask_no': flask_no} if flask_no else None
    async with httpx.AsyncClient(timeout=15.0) as c:
        # r = await c.get(f'{API_URL}/queue/cutting', params=params)
        r = await c.get(f'{API_URL}/queue/cutting')
        r.raise_for_status()
        return r.json()

async def post_cutting(payload: Dict[str, Any]) -> Dict[str, Any]:
    """POST /cutting expects flask_id, before_cut_A, after_scrap_B, after_casting_C, posted_by."""
    async with httpx.AsyncClient(timeout=20.0) as c:
        r = await c.post(f'{API_URL}/cutting', json=payload)
        try:
            r.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise RuntimeError(explain_http_error(e)) from e
        return r.json()

# ---------- PAGE ----------
@ui.page('/cutting')
async def cutting_page(client: Client):
    def notify(msg: str, color='primary'):
        with client:
            ui.notify(msg, color=color)

    ui.page_title('Cutting · Casting Tracker')
    ui.add_head_html('''
    <style>
      .fill-parent{width:100%!important;max-width:100%!important}
      .num-shadow{text-shadow:0 2px 8px rgba(0,0,0,.15)}
    </style>
    ''')

    with ui.header().classes('items-center justify-between bg-gray-900 text-white'):
        ui.label('Cutting Queue').classes('text-lg font-semibold')
        with ui.row().classes('items-center gap-2'):
            ui.button(icon='home', on_click=lambda: ui.navigate.to('/')).props('flat round').classes('text-white')

    # preload metals for filter
    try:
        metals = await fetch_metals()
        metal_options = ['All'] + sorted([m['name'] for m in metals if 'name' in m])
    except Exception:
        metal_options = ['All']

    selected: Dict[str, Any] | None = None
    current_supplied: float = 0.0  # <- used in preview

    # per-session drafts: remember last values per flask id
    drafts: Dict[int, Dict[str, float]] = {}

    with ui.splitter(value=60).classes('px-6').style('width:100%; height: calc(100vh - 140px);') as main_split:

        # LEFT: queue + filters
        with main_split.before:
            with ui.card().classes('w-full h-full p-0'):
                with ui.column().classes('w-full h-full').style('display:flex; flex-direction:column;'):

                    today_iso = date.today().isoformat()

                    with ui.row().classes('items-end gap-3 p-4').style('flex:0 0 auto;'):
                        ui.label('Flasks in Cutting').classes('text-base font-semibold mr-4')
                        f_search = ui.input('Search by Flask or Tree').props('clearable').classes('w-48')
                        d_from = ui.input('From').props('type=date').classes('w-36')
                        d_to   = ui.input('To').props('type=date').classes('w-36')
                        metal_filter = ui.select(options=metal_options, value='All', label='Metal').classes('w-48')
                        metal_filter.props('options-dense behavior=menu popup-content-style="z-index:4000"')

                        async def reset_filters():
                            d_from.value = ''; d_to.value = ''
                            f_search.value = ''; metal_filter.value = 'All'
                            await refresh_table()
                            notify('Filters reset.', 'positive')

                        ui.button('RESET FILTERS', on_click=lambda: asyncio.create_task(reset_filters())).props('outline')

                    # table
                    with ui.element('div').classes('fill-parent').style(
                        'flex:1 1 auto; overflow:auto; padding:0 16px 16px 16px; width:100%; max-width:100%;'
                    ):
                        columns = [
                            {'name': 'date', 'label': 'Date', 'field': 'date'},
                            {'name': 'flask_no', 'label': 'Flask No', 'field': 'flask_no'},
                            {'name': 'tree_no',  'label': 'Tree No',  'field': 'tree_no'},
                            {'name': 'metal_name', 'label': 'Metal', 'field': 'metal_name'},
                            # rename header only; field stays 'metal_weight' (supplied)
                            {'name': 'metal_weight', 'label': 'Supplied Wt', 'field': 'metal_weight'},
                        ]
                        cut_table = ui.table(columns=columns, rows=[]) \
                                      .props('dense flat bordered row-key="id" selection="single" hide-bottom') \
                                      .classes('w-full text-sm')

        # RIGHT: details + form + post (matches "Post Flask" style)
        with main_split.after:
            with ui.card().classes('w-full h-full p-6'):
                ui.label('Cutting Details').classes('text-base font-semibold mb-2')

                with ui.grid(columns=2).classes('gap-2 mb-2'):
                    ui.label('Flask No:'); flask_lbl = ui.label('—')
                    ui.label('Metal:');    metal_lbl = ui.label('—')
                    ui.label('Supplied Wt:'); metal_wt_lbl = ui.label('—')  # renamed

                # Form inputs
                before_cut = ui.number('Before Cutting Weight', value=0.0).props('step=0.001').classes('w-full')
                after_cast = ui.number('After Cut: Casting Weight', value=0.0).props('step=0.001').classes('w-full')
                after_scrap = ui.number('After Cut: Scrap Weight', value=0.0).props('step=0.001').classes('w-full')

                # Preview: show (i), (ii), and TOTAL
                preview_i    = ui.label('(i) Metal Loss in Casting: —').classes('text-gray-600')
                preview_ii   = ui.label('(ii) Metal Loss in Cutting : —').classes('text-gray-600')
                preview_total= ui.label('Total Scrap Loss: —').classes('text-gray-800 font-semibold')

                def update_preview_and_draft():
                    try:
                        A = float(before_cut.value or 0.0)
                        C = float(after_cast.value or 0.0)
                        B = float(after_scrap.value or 0.0)
                        supplied = float(current_supplied or 0.0)

                        part_i  = supplied - A
                        part_ii = A - (B + C)
                        total   = supplied - (B + C)

                        preview_i.text     = f'(i) Metal Loss in Casting: {part_i:.1f}'
                        preview_ii.text    = f'(ii) Metal Loss in Cutting: {part_ii:.1f}'
                        preview_total.text = f'Total Scrap Loss: {total:.1f}'

                        # color total if negative
                        preview_total.classes(remove='text-negative')
                        if total < 0:
                            preview_total.classes(add='text-negative')

                        # store draft for this flask
                        if selected and isinstance(selected.get('id'), int):
                            drafts[int(selected['id'])] = {'before': A, 'casting': C, 'scrap': B}
                    except Exception:
                        preview_i.text = '(i) Metal Loss in Casting: —'
                        preview_ii.text = '(ii) Metal Loss in Cutting: —'
                        preview_total.text = 'Total Scrap Loss: —'

                before_cut.on('change', lambda _: update_preview_and_draft())
                after_cast.on('change', lambda _: update_preview_and_draft())
                after_scrap.on('change', lambda _: update_preview_and_draft())

                async def sync_selection():
                    """Refresh right panel to match current selection (after table updates too)."""
                    nonlocal selected, current_supplied
                    row_list = cut_table.selected or []
                    if row_list:
                        sel_id = row_list[0].get('id')
                        current = next((r for r in cut_table.rows if r.get('id') == sel_id), row_list[0])
                        selected = current
                    else:
                        selected = None

                    with client:
                        if not selected:
                            flask_lbl.text = '—'
                            metal_lbl.text = '—'
                            metal_wt_lbl.text = '—'
                            current_supplied = 0.0
                            # hard reset inputs when nothing is selected
                            before_cut.value = 0.0
                            after_cast.value = 0.0
                            after_scrap.value = 0.0
                            update_preview_and_draft()
                            return

                        # ---- selected row summary ----
                        flask_lbl.text = f"{selected.get('flask_no','—')}"
                        metal_lbl.text = f"{selected.get('metal_name','—')}"

                        # show supplied weight (and use it to prefill "Before Cutting")
                        mw_raw = selected.get('metal_weight')
                        try:
                            mw = float(mw_raw or 0.0)
                        except Exception:
                            mw = 0.0
                        current_supplied = mw
                        metal_wt_lbl.text = f"{mw:.1f}" if mw_raw is not None else '—'

                        # ---- inputs: use per-flask draft if present; otherwise prefill A = supplied ----
                        sel_id = int(selected.get('id'))
                        if sel_id in drafts:
                            d = drafts[sel_id]
                            before_cut.value = float(d.get('before', mw))
                            after_cast.value  = float(d.get('casting', 0.0))
                            after_scrap.value = float(d.get('scrap', 0.0))
                        else:
                            before_cut.value = mw            # prefill A with supplied
                            after_cast.value  = 0.0
                            after_scrap.value = 0.0

                        update_preview_and_draft()

                cut_table.on('selection', lambda _e: asyncio.create_task(sync_selection()))

                async def submit_cutting():
                    if not selected:
                        notify('Select a flask first.', 'warning'); return
                    try:
                        # --- client-side 5% checks to match the backend ---
                        A = float(before_cut.value or 0.0)
                        B = float(after_scrap.value or 0.0)
                        C = float(after_cast.value or 0.0)
                        supplied = float(current_supplied or 0.0)

                        # A within 5% of supplied
                        if supplied > 0.0 and abs(A - supplied) > 0.05 * supplied:
                            notify(f'Before-cut must be within 5% of supplied ({supplied:.1f}).', 'negative')
                            return

                        # (B + C) within 5% of A
                        if A > 0.0 and abs((B + C) - A) > 0.05 * A:
                            notify('Casting + Scrap must be within 5% of Before-cut weight.', 'negative')
                            return

                        payload = {
                            'flask_id': int(selected['id']),
                            'before_cut_A': float(before_cut.value or 0.0),
                            'after_scrap_B': float(after_scrap.value or 0.0),
                            'after_casting_C': float(after_cast.value or 0.0),
                            'posted_by': 'cutting_ui',
                        }
                    except Exception:
                        notify('Invalid inputs.', 'negative'); return

                    try:
                        await post_cutting(payload)
                        notify('Sent to Reconciliation', 'positive')
                        # remove from table and clear
                        with client:
                            cut_table.rows = [r for r in cut_table.rows if r['id'] != selected['id']]
                            cut_table.selected = []
                            cut_table.update()
                        await sync_selection()
                    except Exception as ex:
                        notify(str(ex), 'negative')

                with ui.row().classes('gap-2 mt-2'):
                    ui.button('RECALCULATE', on_click=update_preview_and_draft).props('outline')
                    ui.button('POST CUTTING', on_click=lambda: asyncio.create_task(submit_cutting())) \
                      .classes('bg-emerald-600 text-white')

    # -------- filtering & refresh --------
    def _apply_filters(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        fdate = parse_iso_date(d_from.value)
        tdate = parse_iso_date(d_to.value)
        pick  = metal_filter.value or 'All'
        needle = (f_search.value or '').strip().lower()

        out: List[Dict[str, Any]] = []

        for r in rows:
            d_iso = r.get('date') or ''
            d = parse_iso_date(d_iso)
            if not d:
                continue
            if fdate and d < fdate: continue
            if tdate and d > tdate: continue
            if pick != 'All' and (r.get('metal_name') != pick): continue
            # if needle and needle not in str(r.get('flask_no','')).lower(): continue
            hay = f"{r.get('flask_no','')} {r.get('tree_no','')}".lower()
            if needle and needle not in hay:
                continue


            rr = dict(r)
            rr['_sort_ord'] = -d.toordinal()
            rr['_sort_metal'] = rr.get('metal_name') or ''
            rr['_sort_flask'] = str(rr.get('flask_no',''))
            rr['date'] = to_ui_date(d_iso)
            # normalize number
            if 'metal_weight' in rr and rr['metal_weight'] is not None:
                try: rr['metal_weight'] = float(rr['metal_weight'])
                except Exception: pass
            out.append(rr)

        out.sort(key=lambda x: (x['_sort_ord'], x['_sort_metal'], x['_sort_flask']))
        for rr in out:
            for k in ('_sort_ord','_sort_metal','_sort_flask'):
                rr.pop(k, None)
        return out

    async def refresh_table():
        """Refresh table; keep selection by id; update right panel."""
        try:
            # raw = await fetch_cutting_queue(flask_no=(f_search.value or '').strip() or None)
            raw = await fetch_cutting_queue()
        except Exception as e:
            notify(f'Failed to fetch cutting queue: {e}', 'negative')
            raw = []

        rows = _apply_filters(raw)

        # preserve selection
        selected_id = None
        try:
            if cut_table.selected:
                selected_id = cut_table.selected[0].get('id')
        except Exception:
            selected_id = None

        cut_table.rows = rows
        if selected_id is not None:
            re_row = next((r for r in rows if r.get('id') == selected_id), None)
            cut_table.selected = [re_row] if re_row else []
        cut_table.update()

        await sync_selection()

    # events
    metal_filter.on('update:model-value', lambda _v: asyncio.create_task(refresh_table()))
    f_search.on('change', lambda _e: asyncio.create_task(refresh_table()))
    d_from.on('change',  lambda _e: asyncio.create_task(refresh_table()))
    d_to.on('change',    lambda _e: asyncio.create_task(refresh_table()))

    # auto-refresh (like other pages)
    ui.timer(30.0, lambda: asyncio.create_task(refresh_table()))

    # initial
    await asyncio.create_task(refresh_table())
