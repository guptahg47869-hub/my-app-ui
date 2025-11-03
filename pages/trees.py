# pages/trees.py
from nicegui import ui, Client  # type: ignore
import httpx, os, asyncio  # type: ignore
from datetime import date, datetime
from typing import Any, Dict, List
import base64, json

API_URL = os.getenv('API_URL', 'http://localhost:8000')
print('UI using API_URL =', API_URL)

# ---------- helpers ----------
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

async def fetch_metals() -> List[Dict[str, Any]]:
    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.get(f'{API_URL}/metals')
        r.raise_for_status()
        return r.json()

async def fetch_transit(date_from: str | None = None, date_to: str | None = None,
                        tree_no: str | None = None, metal: str | None = None):
    params: Dict[str, Any] = {}
    if date_from: params['date_from'] = date_from
    if date_to:   params['date_to']   = date_to
    if tree_no:   params['tree_no']   = tree_no
    if metal and metal != 'All': params['metal'] = metal
    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.get(f'{API_URL}/queue/transit', params=params or None)
        r.raise_for_status()
        return r.json()

async def fetch_next_tree_no() -> str:
    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.get(f'{API_URL}/trees/next_number')
        r.raise_for_status()
        return r.json()['tree_no']

# client-side preview for est. metal
def est_metal_weight(tree_weight: float, metal_name: str) -> float:
    name = (metal_name or '').upper()
    factor = 1.0
    if '10' in name: factor = 11
    elif '14' in name: factor = 13.25
    elif '18' in name: factor = 16.5
    elif 'PLATINUM' in name: factor = 21
    elif 'SILVER' in name: factor = 11
    return round((tree_weight or 0.0) * factor, 3)

# ---------- PDF: 12" x 0.5" long strip tree label ----------
def _build_tree_label_pdf_bytes(
    *,
    tree_no: str,
    metal_name: str,
    when_iso: str,
    est_metal: float,
    bag_nos: list[str] | None = None,    # <-- includes Bags line
) -> bytes:
    try:
        from reportlab.pdfgen import canvas
        from reportlab.lib.units import inch, mm
        from reportlab.graphics.barcode import code128
        from reportlab.pdfbase import pdfmetrics
        from io import BytesIO
        from datetime import datetime
    except ImportError:
        raise RuntimeError("Missing dependency: reportlab. Install with: pip install reportlab")

    try:
        date_disp = datetime.strptime(when_iso, "%Y-%m-%d").strftime("%m-%d")
    except Exception:
        date_disp = when_iso

    W, H = (4 * inch, 0.5 * inch)
    M = 0.5 * mm
    GAP = 1 * mm
    BAR_W_FRACTION = 0.33

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=(W, H))
    c.setLineWidth(0.6)
    c.rect(1, 1, W-2, H-2)

    info = f"  {date_disp}  | {tree_no}  |  Metal: {metal_name}  |  Est: {est_metal:.1f}g"
    bags_line = None
    if bag_nos:
        bags_line = "  Bags: " + ", ".join(bag_nos)

    bar_w = max(W * BAR_W_FRACTION, 1.5 * inch)
    text_x = M
    text_w = W - (M + GAP + bar_w + M)
    top_pad = 0.8 * mm
    bottom_pad = 0.7 * mm

    def _fit_size(text: str, max_w: float, base: float, minsz: float) -> float:
        size = base
        while size >= minsz:
            if pdfmetrics.stringWidth(text, "Helvetica-Bold", size) <= max_w:
                return size
            size -= 0.5
        return minsz

    def _draw_line(text: str, y: float, base: float, minsz: float):
        sz = _fit_size(text, text_w, base, minsz)
        if pdfmetrics.stringWidth(text, "Helvetica-Bold", sz) <= text_w:
            c.setFont("Helvetica-Bold", sz)
            c.drawString(text_x, y, text)
            return
        ell = "…"
        while text and pdfmetrics.stringWidth(text + ell, "Helvetica-Bold", sz) > text_w:
            text = text[:-1]
        c.setFont("Helvetica-Bold", sz)
        c.drawString(text_x, y, (text + ell) if text else ell)

    top_base, top_min = 10.0, 5.0
    bot_base, bot_min = 9.0, 5.0

    top_y = H - M - top_pad - top_base * 0.9
    bot_y = M + bottom_pad

    _draw_line(info, top_y, top_base, top_min)
    if bags_line:
        _draw_line(bags_line, bot_y, bot_base, bot_min)

    bar_x = W - M - bar_w
    avail_h = H - 2 * M
    avail_w = bar_w

    b = code128.Code128(tree_no, barHeight=avail_h, barWidth=1)
    scale_x = avail_w / float(b.width)
    scale_y = avail_h / float(b.height)
    scale = min(scale_x, scale_y, 1.0)

    bx = bar_x + (avail_w - b.width * scale) / 2.0
    by = M + (avail_h - b.height * scale) / 2.0

    c.saveState()
    c.translate(bx, by)
    c.scale(scale, scale)
    b.drawOn(c, 0, 0)
    c.restoreState()

    c.showPage()
    c.save()
    pdf = buf.getvalue()
    buf.close()
    return pdf

@ui.page('/trees')
async def create_tree_page(client: Client):
    def notify(msg: str, color='primary'):
        with client:
            ui.notify(msg, color=color)

    ui.page_title('Create Tree · Casting Tracker')
    ui.add_head_html('<style>.fill-parent{width:100%!important;max-width:100%!important}</style>')

    ui.add_head_html("""
    <style>
    /* --- Minimal uploader style --- */
    .q-uploader {
    background: #f2f2f2;              /* light gray */
    border: none !important;
    border-radius: 10px !important;   /* smooth rounded corners */
    color: #111 !important;           /* make all text black */
    }

    /* force rounded corners on inner content so gray background matches */
    .q-uploader__content,
    .q-uploader__list {
    border-radius: 10px !important;
    color: #111 !important;
    }

    /* tweak header + plus button */
    .q-uploader__header {
    background: transparent !important;
    color: #111 !important;
    border-bottom: none !important;
    padding: 6px !important;
    }

    .q-uploader__header .q-btn,
    .q-uploader__header .q-btn__content {
    color: #111 !important;
    }

    /* make percentage text and file names black */
    .q-uploader__file,
    .q-uploader__file--header,
    .q-uploader__title,
    .q-uploader__subtitle,
    .q-uploader__progress {
    color: #111 !important;
    }
    </style>
    """)

    ui.add_head_html("""
    <style>
    /* Remove the built-in checkmarks */
    .q-uploader__file-status,
    .q-uploader__header-icon,
    .q-icon.q-uploader__file-status,
    .q-uploader__file-header .q-icon {
    display: none !important;
    }
    </style>
    """)

    ui.add_head_html("""
    <style>
    /* Hide all selection/checkbox UI in QUploader */
    .q-uploader__header .q-checkbox,
    .q-uploader__header .q-checkbox * { display:none !important; }

    /* Per-file side section (the checkmark/circle lives here) */
    .q-uploader__file .q-item__section--side { 
    display:none !important; 
    width:0 !important; 
    padding:0 !important; 
    margin:0 !important; 
    }

    /* Any leftover status icons */
    .q-uploader__file-status,
    .q-uploader__header-icon,
    .q-uploader__file-header .q-icon,
    .q-icon.q-uploader__file-status {
    display:none !important;
    }

    /* Remove ripple/focus visuals that could look like a circle */
    .q-focus-helper, .q-ripple, .q-ripple__inner { display:none !important; }
    </style>
    """)

    ui.add_head_html("""
    <style>
    /* Hide ONLY the top-left checkmark icon in QUploader header, keep the + intact */

    /* target the icon element with a checkmark (usually has .q-icon--success or check SVG path) */
    .q-uploader__header .q-icon.q-icon--success,
    .q-uploader__header .q-icon.text-positive,
    .q-uploader__header .q-uploader__header-icon.q-icon--success {
    display: none !important;
    }

    /* reset any unintended hiding from previous rule */
    .q-uploader__header .q-btn,
    .q-uploader__header .q-btn__content,
    .q-uploader__header .q-icon:not(.q-icon--success) {
    display: inline-flex !important;
    pointer-events: auto !important;
    opacity: 1 !important;
    }
    </style>
    """)

    ui.add_head_html("""
    <style>
    /* Disable all pointer interactions inside the uploaded file list */
    .q-uploader__list,
    .q-uploader__file .q-item,
    .q-uploader__file .q-item__section {
    pointer-events: none !important;
    user-select: none !important;
    }

    /* Ensure header (+) stays clickable */
    .q-uploader__header, .q-uploader__header * {
    pointer-events: auto !important;
    }

    /* If selection somehow happens via keyboard, keep text visible */
    .q-uploader__file--selected .q-uploader__title,
    .q-uploader__file--selected .q-uploader__subtitle {
    opacity: 1 !important;
    }
    </style>
    """)

    ui.add_head_html("""
    <style>
    /* --- FINAL fix: disable click and hide the top-left checkmark in QUploader header --- */

    /* 1️⃣ Hide the icon element itself */
    .q-uploader__header .q-icon.q-icon--success,
    .q-uploader__header .q-icon.text-positive {
    opacity: 0 !important;          /* invisible */
    pointer-events: none !important;/* not clickable */
    width: 0 !important;
    height: 0 !important;
    margin: 0 !important;
    padding: 0 !important;
    }

    /* 2️⃣ Remove any hover or click on that header section */
    .q-uploader__header .q-item__section--side,
    .q-uploader__header .q-item__section--avatar {
    pointer-events: none !important;
    }

    /* 3️⃣ Keep the + add button visible and active */
    .q-uploader__header .q-btn,
    .q-uploader__header .q-btn__content,
    .q-uploader__header .q-icon:not(.q-icon--success):not(.text-positive) {
    opacity: 1 !important;
    pointer-events: auto !important;
    display: inline-flex !important;
    }
    </style>
    """)

    ui.add_head_html("""
    <style>
    /* Remove the whole left cluster in the QUploader header (icon + text) */
    .q-uploader__header .q-item__section--main,
    .q-uploader__header .q-item__section--avatar,
    .q-uploader__header .q-item__section--side:first-child {
    display: none !important;
    width: 0 !important;
    padding: 0 !important;
    margin: 0 !important;
    }

    /* Keep the right-side buttons (the +) visible and clickable */
    .q-uploader__header .q-item__section--side:last-child,
    .q-uploader__header .q-item__section--side:last-child * {
    display: inline-flex !important;
    pointer-events: auto !important;
    opacity: 1 !important;
    }

    /* Optional: tighten header height a bit */
    .q-uploader__header {
    padding: 6px !important;
    }
    </style>
    """)

    ui.add_head_html("""
    <style>
    /* Force filename + size text to stay visible even when file is selected */
    .q-uploader__file--selected .q-uploader__title,
    .q-uploader__file--selected .q-uploader__subtitle {
    opacity: 1 !important;
    color: #111 !important;
    visibility: visible !important;
    }
    </style>
    """)

    # header
    with ui.header().classes('items-center justify-between bg-gray-900 text-white'):
        ui.label('Create Tree').classes('text-lg font-semibold')
        with ui.row().classes('items-center gap-2'):
            ui.button(icon='home', on_click=lambda: ui.navigate.to('/')).props('flat round').classes('text-white')

    # preload metals
    try:
        metals = await fetch_metals()
        metal_options = sorted([m['name'] for m in metals if 'name' in m])
        name_to_id = {m['name']: m['id'] for m in metals}
    except Exception as e:
        notify(f'Failed to load metals: {e}', 'negative')
        metal_options, name_to_id = [], {}

    # layout: left form (full), right transit table
    with ui.splitter(value=50).classes('px-6').style('width:100%; height: calc(100vh - 140px);') as split:

        # LEFT: full-width form
        with split.before:
            with ui.element('div').classes('w-full h-full').style('width:100%; height:100%;'):
                with ui.card().props('flat').classes('w-full h-full m-0 p-4'):
                    with ui.row().classes('w-full justify-between items-end gap-4'):
                        d_in = ui.input('Date', value=date.today().isoformat()) \
                                .props('type=date dense filled') \
                                .classes('flex-1')
                        t_no = ui.input('Tree No') \
                                .props('dense filled') \
                                .classes('flex-1')                        
                    metal_pick = ui.select(options=metal_options, label='Metal').classes('w-full')

                    # --- Bags (unchanged) ---
                    bag_vals: List[str] = []  # local UI state
                    ui.label('Scan Bags').classes('mt-2')
                    bag_in = ui.input().props('autofocus clearable').classes('w-full')
                    chips_row = ui.row().classes('gap-2 flex-wrap mt-2')

                    def render_bag_chips():
                        chips_row.clear()
                        for b in bag_vals:
                            with chips_row:
                                ui.chip(b).props('removable').on('remove', lambda _=None, bb=b: remove_bag(bb))
                        chips_row.update()

                    def add_bag(raw: str):
                        s = (raw or '').strip().upper()
                        if not s:
                            return
                        if s not in bag_vals:
                            bag_vals.append(s)
                            render_bag_chips()
                        bag_in.value = ''

                    def remove_bag(b: str):
                        try:
                            bag_vals.remove(b)
                            render_bag_chips()
                        except ValueError:
                            pass

                    bag_in.on('keydown.enter', lambda e: add_bag(bag_in.value))
                    bag_in.on('change',        lambda e: add_bag(bag_in.value))
                    render_bag_chips()

                    # --- Weights (unchanged) ---
                    # --- Gasket + Total Weight side by side ---
                    with ui.row().classes('w-full justify-between items-end gap-4'):
                        g_in = ui.number('Gasket Weight', value=0.0) \
                                .classes('flex-1')
                        tot_in = ui.number('Total Weight', value=0.0) \
                                .classes('flex-1')

                    # derived preview
                    tw_label = ui.label('Tree Wt: —').classes('text-gray-600 mt-1')
                    est_label = ui.label('Estimated Metal: —').classes('text-gray-600 mt-1')

                    def refresh_est():
                        try:
                            g = float(g_in.value or 0.0)
                            t = float(tot_in.value or 0.0)
                            tw = max(0.0, t - g)
                            tw_label.text = f'Tree Wt: {tw:.1f}'
                            if not metal_pick.value:
                                est_label.text = 'Estimated Metal: —'; return
                            est = est_metal_weight(tw, metal_pick.value)
                            est_label.text = f'Estimated Metal: {est:.1f}'
                        except Exception:
                            tw_label.text = 'Tree Wt: —'
                            est_label.text = 'Estimated Metal: —'

                    metal_pick.on('update:model-value', lambda _v: refresh_est())
                    g_in.on('change', lambda _e: refresh_est())
                    tot_in.on('change', lambda _e: refresh_est())

                    # --- NEW: optional photo upload (after weights) ---
                    ui.separator().classes('my-2')
                    ui.label('Photo (optional)').classes('text-gray-700')

                    photo_bytes: bytes | None = None
                    photo_name: str | None = None
                    photo_preview = ui.image().classes('w-24 h-24 object-cover rounded border').style('display:none;')
                    # photo_wrapper = ui.element('div').classes('relative inline-block')
                    photo_preview = ui.image().classes('w-24 h-24 object-cover rounded border').style('display:none;')

                    # with photo_wrapper:
                    #     photo_preview
                    #     remove_btn = ui.button('×', on_click=lambda: clear_photo()) \
                    #         .classes('absolute top-0 right-0 text-xs bg-white text-black rounded-full shadow hover:bg-gray-200') \
                    #         .style('display:none;')

                    # wrap uploader so we can position the “×” over the file row
                    with ui.element('div').classes('relative inline-block'):
                        uploader = ui.upload(
                            label='Upload Photo',
                            multiple=False,
                            auto_upload=True,
                            on_upload=None,   # keep your existing handler
                            # hide-upload-btn=True,
                        ).props('accept="image/*" capture="environment" no-thumbnails max-files="1" flat square bordered hide-upload-btn=True') \
                        .classes('w-56')

                        # the “×” over the file row (hidden until a file is present)
                        file_remove = ui.button(icon='close', on_click=lambda: clear_photo()) \
                            .props('round dense flat') \
                            .classes('absolute') \
                            .style('display:none; right:20px; top:77px; background:none; color:#111; z-index:50; pointer-events:auto;')
                        
                        # place this RIGHT AFTER your existing visible `uploader = ui.upload(...)` block

                        # a hidden uploader that is camera-focused; it uses the same _on_file handler
                        camera_uploader = ui.upload(
                            label='',
                            multiple=False,
                            auto_upload=True,
                            on_upload=None,  # reuse your existing handler so preview + bytes just work
                        ).props('accept="image/*" capture="environment" no-thumbnails max-files="1" hide-upload-btn') \
                        .style('display:none;')

                        # a small button to open the device camera (on mobile it goes straight to camera)
                        ui.button('Take Photo (Camera)', on_click=lambda: camera_uploader.run_method('pickFiles')) \
                        .props('flat dense') \
                        .classes('text-gray-700')



                    def clear_photo():
                        nonlocal photo_bytes, photo_name
                        photo_bytes = None
                        photo_name = None
                        photo_preview.style('display:none;')
                        # remove_btn.style('display:none;')
                        file_remove.style('display:none;')
                        uploader.reset()
                        notify('Photo removed', 'info')

                    def _on_file(e):
                        nonlocal photo_bytes, photo_name
                        try:
                            # Newer NiceGUI (files list with inline content)
                            files = getattr(e, 'files', None)
                            if files:
                                f = files[0]
                                photo_name = f.get('name', 'upload.jpg')
                                photo_bytes = f.get('content', b'') or b''
                            else:
                                # Older NiceGUI (stream-like content + name)
                                file_obj = getattr(e, 'content', None)
                                photo_name = getattr(e, 'name', 'upload.jpg')
                                photo_bytes = file_obj.read() if file_obj else b''

                            # Preview (only if we actually have bytes)
                            if photo_bytes:
                                b64 = base64.b64encode(photo_bytes).decode('ascii')
                                photo_preview.source = f'data:image/*;base64,{b64}'
                                photo_preview.style('display:block;')
                                # clear_photo_btn.style('display:inline-flex;'); clear_photo_btn.update()
                                # remove_btn.style('display:block;')
                                file_remove.style('display:block;'); file_remove.update()
                                photo_preview.update()
                                # remove_btn.update()

                            else:
                                photo_preview.style('display:none;')
                                # clear_photo_btn.style('display:none;'); clear_photo_btn.update()
                                # remove_btn.style('display:none;')
                                file_remove.style('display:none;'); file_remove.update()

                            photo_preview.update()

                        except Exception as ex:
                            print('Upload handler error:', ex)
                            photo_name = None
                            photo_bytes = b''

                    uploader.on_upload(_on_file)
                    # uploader.on_upload(_on_file)
                    camera_uploader.on_upload(_on_file)
                    
                    # uploader = ui.upload(
                    #     label='Upload Photo',
                    #     multiple=False,
                    #     auto_upload=True,
                    #     on_upload=_on_file
                    # ).props('accept="image/*" capture="environment" no-thumbnails max-files="1" flat square bordered') \
                    # .classes('w-56')

                    # # tiny clear button; hidden until a file is present
                    # clear_photo_btn = ui.button('Remove photo', icon='close', on_click=lambda: asyncio.create_task(_clear_photo())) \
                    # .props('flat dense') \
                    # .classes('text-gray-700')
                    # clear_photo_btn.style('display:none;')

                    # async def _clear_photo():
                    #     nonlocal photo_bytes, photo_name
                    #     photo_bytes = None
                    #     photo_name = None
                    #     # hide preview
                    #     photo_preview.style('display:none;'); photo_preview.update()
                    #     # reset uploader selection
                    #     try:
                    #         uploader.reset()
                    #     except Exception:
                    #         try:
                    #             uploader.run_method('reset')   # Quasar method bridged by NiceGUI
                    #         except Exception:
                    #             uploader.value = None
                    #     # hide clear button
                    #     # clear_photo_btn.style('display:none;'); clear_photo_btn.update()
                    #     file_remove.style('display:none;'); file_remove.update()  

                    async def fill_next_no():
                        """Fetch and fill the next tree number."""
                        try:
                            t_no.value = await fetch_next_tree_no()
                        except Exception as ex:
                            notify(f'Failed to auto-assign Tree No: {ex}', 'warning')

                    async def _date_changed():
                        await fill_next_no()
                    d_in.on('change', lambda _e: asyncio.create_task(_date_changed()))

                    async def submit(do_print: bool):
                        if not (d_in.value and t_no.value and metal_pick.value):
                            notify('Please fill Date, Tree No, and Metal.', 'warning'); return
                        if metal_pick.value not in name_to_id:
                            notify('Unknown metal selected.', 'negative'); return
                        try:
                            payload = {
                                'date': d_in.value,
                                'tree_no': t_no.value.strip(),
                                'metal_id': int(name_to_id[metal_pick.value]),
                                'gasket_weight': float(g_in.value or 0.0),
                                'total_weight': float(tot_in.value or 0.0),
                                'posted_by': 'tree_ui',
                                'bag_nos': bag_vals,
                            }
                        except Exception:
                            notify('Invalid numbers.', 'negative'); return

                        # estimate for label preview
                        g = float(payload['gasket_weight'])
                        t = float(payload['total_weight'])
                        tw = max(0.0, t - g)
                        est = est_metal_weight(tw, metal_pick.value)

                        try:
                            async with httpx.AsyncClient(timeout=10.0) as c:
                                r = await c.post(f'{API_URL}/trees', json=payload)
                                r.raise_for_status()
                                data = r.json()

                            nonlocal photo_bytes, photo_name
                            est_label.text = f"Estimated Metal: {float(data['est_metal_weight']):.1f}"
                            notify('Tree created → Transit', 'positive')
                            print(f'Tree created: ID={data["id"]} No={data["tree_no"]}')

                            # --- NEW: upload photo if provided ---
                            try:
                                print(f"{photo_name} upload: {len(photo_bytes or b'')} bytes")

                                # if photo_bytes and photo_name:
                                if photo_bytes and isinstance(photo_bytes, (bytes, bytearray)) and len(photo_bytes) > 0:
                                    files = {'file': (photo_name or 'upload.jpg', photo_bytes, 'application/octet-stream')}
                                    # files = {'file': (photo_name, photo_bytes, 'image/jpeg')}
                                    async with httpx.AsyncClient(timeout=20.0) as c2:
                                        r2 = await c2.post(f'{API_URL}/trees/{data["id"]}/photo', files=files)
                                        r2.raise_for_status()
                                    notify('Photo uploaded', 'positive')
                                else:
                                    print('No photo to upload.')
                            except Exception as ex_up:
                                notify(f'Photo upload failed: {ex_up}', 'warning')

                            # print label if requested
                            if do_print:
                                try:
                                    pdf_bytes = _build_tree_label_pdf_bytes(
                                        tree_no=payload['tree_no'],
                                        metal_name=metal_pick.value or '',
                                        when_iso=payload['date'],
                                        est_metal=est,
                                        bag_nos=bag_vals,
                                    )
                                    b64 = base64.b64encode(pdf_bytes).decode('ascii')
                                    b64_json = json.dumps(b64)
                                    with client:
                                        ui.run_javascript(f"""
                                        (()=>{{
                                          if (window.__labelOpening) return;
                                          window.__labelOpening = true;
                                          const b64 = {b64_json};
                                          const bytes = atob(b64);
                                          const arr = new Uint8Array(bytes.length);
                                          for (let i=0;i<bytes.length;i++) arr[i] = bytes.charCodeAt(i);
                                          const blob = new Blob([arr], {{type:'application/pdf'}});
                                          const url = URL.createObjectURL(blob);
                                          const a = document.createElement('a');
                                          a.href = url; a.target = '_blank'; a.rel = 'noopener';
                                          document.body.appendChild(a); a.click(); a.remove();
                                          setTimeout(()=>{{ URL.revokeObjectURL(url); window.__labelOpening=false; }}, 30000);
                                        }})();
                                        """)
                                except Exception as ex:
                                    notify(f'Label error: {ex}', 'warning')

                            # reset inputs & prefill next number
                            g_in.value = 0.0
                            tot_in.value = 0.0

                            bag_vals.clear()
                            render_bag_chips()
                            bag_in.value = ''

                            # clear photo state & preview
                            photo_bytes = None
                            photo_name = None
                            photo_preview.style('display:none;'); photo_preview.update()
                            try:
                                # uploader.value = None  # clear selection if supported
                                uploader.reset()
                            except Exception:
                                # pass
                                uploader.value = None  # fallback
                            # clear_photo_btn.style('display:none;'); clear_photo_btn.update()
                            file_remove.style('display:none;'); file_remove.update()


                            refresh_est()
                            await fill_next_no()
                            await refresh_transit_table()
                        except httpx.HTTPStatusError as e:
                            notify(explain_http_error(e), 'negative')
                        except Exception as ex:
                            notify(str(ex), 'negative')

                    with ui.row().classes('gap-2 mt-2'):
                        ui.button('CREATE TREE', on_click=lambda: asyncio.create_task(submit(False))) \
                          .classes('bg-emerald-600 text-white')
                        ui.button('CREATE & PRINT BARCODE', on_click=lambda: asyncio.create_task(submit(True))) \
                          .classes('bg-indigo-600 text-white')
                        ui.button('RECALCULATE', on_click=refresh_est).props('outline')

                    # initial auto-assign
                    await fill_next_no()

        # RIGHT: transit queue (unchanged)
        with split.after:
            with ui.card().classes('w-full h-full p-0'):
                with ui.column().classes('w-full h-full').style('display:flex; flex-direction:column;'):
                    today_iso = date.today().isoformat()
                    with ui.row().classes('items-end gap-3 p-4').style('flex:0 0 auto;'):
                        ui.label('Trees in Transit').classes('text-base font-semibold mr-4')
                        t_search = ui.input('Search by Tree No').props('clearable').classes('w-48')
                        d_from = ui.input('From').props('type=date').classes('w-36')
                        d_to   = ui.input('To').props('type=date').classes('w-36')
                        metal_filter = ui.select(options=['All'] + metal_options, value='All', label='Metal').classes('w-48')
                        metal_filter.props('options-dense behavior=menu popup-content-style="z-index:4000"')

                        async def reset_filters():
                            d_from.value = ''; d_to.value = ''
                            t_search.value = ''; metal_filter.value = 'All'
                            await refresh_transit_table()
                            notify('Filters reset.', 'positive')

                        ui.button('RESET FILTERS', on_click=lambda: asyncio.create_task(reset_filters())).props('outline')

                    with ui.element('div').classes('fill-parent').style(
                        'flex:1 1 auto; overflow:auto; padding:0 16px 16px 16px; width:100%; max-width:100%;'
                    ):
                        columns = [
                            {'name': 'date', 'label': 'Date', 'field': 'date'},
                            {'name': 'tree_no', 'label': 'Tree No', 'field': 'tree_no'},
                            {'name': 'metal_name', 'label': 'Metal', 'field': 'metal_name'},
                            {'name': 'gasket_weight', 'label': 'Gasket', 'field': 'gasket_weight'},
                            {'name': 'total_weight', 'label': 'Total', 'field': 'total_weight'},
                            {'name': 'tree_weight', 'label': 'Tree Wt', 'field': 'tree_weight'},
                            {'name': 'est_metal_weight', 'label': 'Est. Metal', 'field': 'est_metal_weight'},
                        ]
                        transit_table = ui.table(columns=columns, rows=[]) \
                                          .props('dense flat bordered row-key="tree_id" hide-bottom') \
                                          .classes('w-full text-sm')

    # -------- filtering & refresh --------
    def _apply_filters_transit(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        f_date = parse_iso_date(d_from.value)
        t_date = parse_iso_date(d_to.value)
        pick   = metal_filter.value or 'All'
        needle = (t_search.value or '').strip().lower()

        out: List[Dict[str, Any]] = []
        for r in rows:
            d_iso = r.get('date') or ''
            d = parse_iso_date(d_iso)
            if not d: continue
            if f_date and d < f_date: continue
            if t_date and d > t_date: continue
            if pick != 'All' and (r.get('metal_name') != pick): continue
            if needle and needle not in str(r.get('tree_no','')).lower(): continue

            rr = dict(r)
            rr['_sort_ord'] = -d.toordinal()
            rr['_sort_metal'] = rr.get('metal_name') or ''
            rr['_sort_tree'] = str(rr.get('tree_no',''))
            rr['_display_date'] = to_ui_date(d_iso)
            out.append(rr)

        out.sort(key=lambda x: (x['_sort_ord'], x['_sort_metal'], x['_sort_tree']))
        for rr in out:
            rr['date'] = rr['_display_date']
            for k in ('_sort_ord','_sort_metal','_sort_tree','_display_date'):
                rr.pop(k, None)
        return out

    async def refresh_transit_table():
        try:
            raw = await fetch_transit(
                date_from=d_from.value, date_to=d_to.value,
                tree_no=(t_search.value or '').strip(),
                metal=metal_filter.value,
            )
        except Exception as e:
            notify(f'Failed to fetch transit: {e}', 'negative')
            raw = []
        rows = _apply_filters_transit(raw)
        transit_table.rows = rows
        transit_table.update()

    # events
    metal_filter.on('update:model-value', lambda _v: asyncio.create_task(refresh_transit_table()))
    t_search.on('change', lambda _e: asyncio.create_task(refresh_transit_table()))
    d_from.on('change',  lambda _e: asyncio.create_task(refresh_transit_table()))
    d_to.on('change',    lambda _e: asyncio.create_task(refresh_transit_table()))

    # initial
    await asyncio.create_task(refresh_transit_table())
