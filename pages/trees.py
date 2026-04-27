# pages/trees.py
from nicegui import ui, Client  # type: ignore
import httpx, os, asyncio  # type: ignore
from datetime import date, datetime
from typing import Any, Dict, List
import base64, json
from nicegui.elements.html import Html

# Backend se baat karne ke liye (server-side, httpx se)
API_URL = os.getenv('API_URL', 'http://localhost:8000')
print('UI using API_URL =', API_URL)

# Browser se direct call ke liye (JS fetch) – nginx /api → backend
BROWSER_API_BASE = os.getenv('BROWSER_API_BASE', '/api')


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

async def fetch_transit(
    date_from: str | None = None,
    date_to: str | None = None,
    tree_no: str | None = None,
    metal: str | None = None,
):
    params: Dict[str, Any] = {}
    if date_from:
        params['date_from'] = date_from
    if date_to:
        params['date_to'] = date_to
    if tree_no:
        params['tree_no'] = tree_no
    if metal and metal != 'All':
        params['metal'] = metal
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
    if '10' in name:
        factor = 11
    elif '14' in name:
        factor = 13.25
    elif '18' in name:
        factor = 16.5
    elif 'PLATINUM' in name:
        factor = 21
    elif 'SILVER' in name:
        factor = 11
    return round((tree_weight or 0.0) * factor, 3)

# ---------- PDF: 12" x 0.5" long strip tree label ----------
def _build_tree_label_pdf_bytes(
    *,
    tree_no: str,
    metal_name: str,
    when_iso: str,
    # est_metal: float,
    bag_nos: list[str] | None = None,
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
    c.rect(1, 1, W - 2, H - 2)

    info = f"  {date_disp}  | {tree_no}  |  Metal: {metal_name}"
    bags_line = None
    if bag_nos:
        bags_line = "  Bags: " + ", ".join(bag_nos)

    text_x = M
    text_w = W - (M + GAP + (W * BAR_W_FRACTION) + M)
    top_pad = 0.8 * mm
    bottom_pad = 0.7 * mm

    def _fit_size(text: str, max_w: float, base: float, minsz: float) -> float:
        size = base
        while size >= minsz:
            if pdfmetrics.stringWidth(text, "Helvetica-Bold", size) <= max_w:
                return size
            size -= 0.5
        return minsz
    
    def _max_font_for_two_lines(y1: float, y2: float, safety: float = 0.4 * mm) -> float:
        """
        Given two baselines y1 (top) and y2 (bottom), compute a max font size so
        the two lines don't overlap and don't clip.
        """
        # distance between baselines
        baseline_gap = abs(y1 - y2)

        # In ReportLab, a rough line height ≈ 1.15 * font_size
        # So we need baseline_gap >= 1.15 * font_size
        max_by_gap = (baseline_gap - safety) / 1.15

        return max_by_gap


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

    def _split_into_two_lines(prefix: str, items: list[str], max_w: float, font: str, size: float) -> tuple[str, str, bool]:
        """
        Returns (line1, line2, truncated)
        line1 starts with prefix, then as many items as fit.
        line2 continues with remaining items.
        If not all items fit by end of line2, truncated=True.
        """
        # Build tokens like ["AAA", "BBB", ...]
        remaining = list(items)

        def take_line(start_text: str) -> tuple[str, list[str]]:
            text = start_text
            # try to add ", " + item while it fits
            while remaining:
                candidate = (text + ("" if text.endswith(": ") else ", ") + remaining[0]) if text != start_text else (text + remaining[0])
                if pdfmetrics.stringWidth(candidate, font, size) <= max_w:
                    text = candidate
                    remaining.pop(0)
                else:
                    break
            return text, remaining

        # line1
        line1, _ = take_line(prefix)

        # line2 starts with two spaces for alignment (looks nice under "Bags:")
        line2_prefix = "  "  # indent
        line2, _ = take_line(line2_prefix)

        truncated = len(remaining) > 0
        return line1, line2, truncated


    def _draw_bags_two_lines(bag_nos: list[str], y1: float, y2: float, base: float, minsz: float):
        prefix = "  Bags: "
        font = "Helvetica-Bold"

        # NEW: clamp font size so two lines fit vertically
        max_by_height = _max_font_for_two_lines(y1, y2)
        sz = min(base, max_by_height)
        sz = max(sz, minsz)

        # try sizes from base down to minsz until both lines fit
        # sz = base
        best = None  # (line1, line2, truncated, final_line2)

        while sz >= minsz:
            line1, line2, truncated = _split_into_two_lines(prefix, bag_nos, text_w, font, sz)

            # if we need ellipsis, make sure line2+… fits
            final_line2 = line2
            if truncated:
                ell = "…"
                # hard-trim until it fits with ellipsis
                while final_line2 and pdfmetrics.stringWidth(final_line2 + ell, font, sz) > text_w:
                    final_line2 = final_line2[:-1]
                final_line2 = (final_line2 + ell) if final_line2 else ell

            # validate width fit
            w1_ok = pdfmetrics.stringWidth(line1, font, sz) <= text_w
            w2_ok = (final_line2.strip() == "") or (pdfmetrics.stringWidth(final_line2, font, sz) <= text_w)

            if w1_ok and w2_ok:
                best = (line1, line2, truncated, final_line2, sz)
                break

            sz -= 0.5  # shrink step; tweak to 0.25 if you want smoother

        # if nothing fit even at minsz, just force-ellipsis on line2 at minsz
        if best is None:
            sz = minsz
            line1, line2, truncated = _split_into_two_lines(prefix, bag_nos, text_w, font, sz)
            final_line2 = line2
            if truncated or pdfmetrics.stringWidth(final_line2, font, sz) > text_w:
                ell = "…"
                while final_line2 and pdfmetrics.stringWidth(final_line2 + ell, font, sz) > text_w:
                    final_line2 = final_line2[:-1]
                final_line2 = (final_line2 + ell) if final_line2 else ell
            best = (line1, line2, True, final_line2, sz)

        line1, _line2, _truncated, final_line2, sz = best

        c.setFont(font, sz)
        c.drawString(text_x, y1, line1)
        if final_line2.strip():
            c.drawString(text_x, y2, final_line2)

    top_base, top_min = 10.0, 5.0
    bot_base, bot_min = 9.0, 5.0

    top_y = H - M - top_pad - top_base * 0.9
    bot_y = M + bottom_pad

    line_gap = 2.6 * mm  # tweak if you want tighter/looser
    bot_y2 = M + bottom_pad
    bot_y1 = bot_y2 + line_gap



    _draw_line(info, top_y, top_base, top_min)
    if bag_nos:
        # _draw_line(bags_line, bot_y, bot_base, bot_min)
        _draw_bags_two_lines(bag_nos, bot_y1, bot_y2, bot_base, bot_min)


    bar_x = W - M - max(W * BAR_W_FRACTION, 1.5 * inch)
    avail_h = H - 2 * M
    avail_w = max(W * BAR_W_FRACTION, 1.5 * inch)

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
    # nice notify helper
    def notify(msg: str, color: str = 'primary') -> None:
        with client:
            ui.notify(msg, color=color)

    ui.page_title('Create Tree · Casting Tracker')

    # header
    with ui.header().classes('items-center justify-between bg-gray-900 text-white'):
        ui.label('Create Tree').classes('text-lg font-semibold')
        with ui.row().classes('items-center gap-2'):
            ui.button('← Wax Room', on_click=lambda: ui.navigate.to('/dept/wax-room')).props('flat').classes('text-white font-semibold')

    # preload metals
    try:
        metals = await fetch_metals()
        metal_options = sorted([m['name'] for m in metals if 'name' in m])
        name_to_id = {m['name']: m['id'] for m in metals}
    except Exception as e:
        notify(f'Failed to load metals: {e}', 'negative')
        metal_options, name_to_id = [], {}

    with ui.splitter(value=50).classes('px-6').style('width:100%; height: calc(100vh - 140px);') as split:

        # LEFT: form
        with split.before:
            with ui.element('div').classes('w-full h-full').style('width:100%; height:100%;'):
                with ui.card().props('flat').classes('w-full h-full m-0 p-4'):

                    # date + tree_no
                    with ui.row().classes('w-full justify-between items-end gap-4'):
                        d_in = ui.input('Date', value=date.today().isoformat()) \
                            .props('type=date dense filled') \
                            .classes('flex-1')
                        t_no = ui.input('Tree No') \
                            .props('dense filled') \
                            .classes('flex-1')
                        f_no = ui.input('Flask No') \
                            .props('autofocus clearable') \
                            .classes('w-full')
                    metal_pick = ui.select(options=metal_options, label='Metal').classes('w-full')

                    # Bags
                    bag_vals: List[str] = []
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
                    bag_in.on('change', lambda e: add_bag(bag_in.value))
                    render_bag_chips()

                    # weights
                    # with ui.row().classes('w-full justify-between items-end gap-4'):
                    #     g_in = ui.number('Gasket Weight', value=0.0).classes('flex-1')
                    #     tot_in = ui.number('Total Weight', value=0.0).classes('flex-1')

                    # tw_label = ui.label('Tree Weight: —').classes('text-gray-600 mt-1')
                    # est_label = ui.label('Estimated Metal Weight: —').classes('text-gray-600 mt-1')

                    # def refresh_est():
                    #     try:
                    #         g = float(g_in.value or 0.0)
                    #         t = float(tot_in.value or 0.0)
                    #         tw = max(0.0, t - g)
                    #         tw_label.text = f'Tree Weight: {tw:.2f}'
                    #         if not metal_pick.value:
                    #             est_label.text = 'Estimated Metal Weight: —'
                    #             return
                    #         est = est_metal_weight(tw, metal_pick.value)
                    #         est_label.text = f'Estimated Metal Weight: {est:.2f}'
                    #     except Exception:
                    #         tw_label.text = 'Tree Weight: —'
                    #         est_label.text = 'Estimated Metal Weight: —'

                    # metal_pick.on('update:model-value', lambda _v: refresh_est())
                    # g_in.on('change', lambda _e: refresh_est())
                    # tot_in.on('change', lambda _e: refresh_est())

                    # --- PHOTO: plain HTML input + JS upload ---
                    ui.separator().classes('my-2')
                    # ui.label('Photo (optional)').classes('text-gray-700')

                    # photo_html = ui.html(
                    #     '''
                    #     <div id="photo-wrapper" style="margin-top:10px; display:flex; align-items:center; gap:10px;">

                    #         <!-- Custom file label styled like button -->
                    #         <label for="tree-photo" id="file-btn"
                    #             style="
                    #                     background:#e0e0e0;
                    #                     padding:6px 14px;
                    #                     border-radius:6px;
                    #                     cursor:pointer;
                    #                     font-weight:bold;
                    #                     font-size:1rem;
                    #             ">
                    #             Choose File
                    #         </label>

                    #         <!-- Actual file input (hidden) -->
                    #         <input id="tree-photo" type="file" accept="image/*" style="display:none;">

                    #         <!-- Filename appears here -->
                    #         <span id="file-name" style="color:#333; font-size:0.95rem;">No file chosen</span>

                    #         <!-- Clear button -->
                    #         <button id="clear-photo" type="button"
                    #                 style="
                    #                     background:#e0e0e0;
                    #                     padding:6px 12px;
                    #                     border-radius:6px;
                    #                     cursor:pointer;
                    #                     font-weight:bold;
                    #                     font-size:1rem;
                    #                 ">
                    #             Clear Photo
                    #         </button>
                    #     </div>

                    #     <!-- preview -->
                    #     <img id="tree-photo-preview"
                    #         style="display:none; margin-top:10px; width:96px; height:96px;
                    #                 object-fit:cover; border:1px solid #ccc; border-radius:6px;">

                    #     <style>
                    #     /* Disable button style */
                    #     #clear-photo:disabled {
                    #         opacity: 0.5;
                    #         cursor: not-allowed;
                    #     }
                    #     </style>
                    #     ''', 
                    #     # sanitize=False # new version of NiceGUI
                    # )

                    # # JS logic (preview + filename + clear)./.venv/Scripts/
                    # with client:
                    #     ui.run_javascript(
                    #         """
                    #         (function () {
                    #             const input = document.getElementById('tree-photo');
                    #             const clearBtn = document.getElementById('clear-photo');
                    #             const img = document.getElementById('tree-photo-preview');
                    #             const fileName = document.getElementById('file-name');

                    #             function resetPreview() {
                    #                 img.style.display = 'none';
                    #                 img.src = '';
                    #                 clearBtn.disabled = true;
                    #                 fileName.textContent = 'No file chosen';
                    #             }

                    #             input.addEventListener('change', () => {
                    #                 if (!input.files || !input.files.length) {
                    #                     resetPreview();
                    #                     return;
                    #                 }
                    #                 const file = input.files[0];

                    #                 // filename display
                    #                 fileName.textContent = file.name;

                    #                 // preview
                    #                 const reader = new FileReader();
                    #                 reader.onload = e => {
                    #                     img.src = e.target.result;
                    #                     img.style.display = 'block';
                    #                     clearBtn.disabled = false;
                    #                 };
                    #                 reader.readAsDataURL(file);
                    #             });

                    #             clearBtn.addEventListener('click', () => {
                    #                 input.value = '';
                    #                 resetPreview();
                    #             });

                    #             resetPreview();
                    #         })();
                    #         """
                    #     )
                        
                    # auto next tree no
                    async def fill_next_no():
                        try:
                            t_no.value = await fetch_next_tree_no()
                        except Exception as ex:
                            notify(f'Failed to auto-assign Tree No: {ex}', 'warning')

                    async def _date_changed():
                        await fill_next_no()

                    d_in.on('change', lambda _e: asyncio.create_task(_date_changed()))

                    # main submit
                    async def submit(do_print: bool):
                        if not (d_in.value and t_no.value and f_no.value and metal_pick.value):
                            notify('Please fill Date, Tree No, Flask No, and Metal.', 'warning')
                            return
                        if metal_pick.value not in name_to_id:
                            notify('Unknown metal selected.', 'negative')
                            return
                        try:
                            payload = {
                                'date': d_in.value,
                                'tree_no': t_no.value.strip(),
                                'flask_no': f_no.value.strip(),
                                'metal_id': int(name_to_id[metal_pick.value]),
                                # 'gasket_weight': float(g_in.value or 0.0),
                                # 'total_weight': float(tot_in.value or 0.0),
                                'posted_by': 'tree_ui',
                                'bag_nos': bag_vals,
                            }
                        except Exception:
                            notify('Invalid numbers.', 'negative')
                            return

                        # g = float(payload['gasket_weight'])
                        # t = float(payload['total_weight'])
                        # tw = max(0.0, t - g)
                        # est = est_metal_weight(tw, metal_pick.value)

                        try:
                            # 1) create tree (server → API)
                            async with httpx.AsyncClient(timeout=10.0) as c:
                                r = await c.post(f'{API_URL}/trees', json=payload)
                                r.raise_for_status()
                                data = r.json()

                            # est_label.text = f"Estimated Metal Weight: {float(data['est_metal_weight']):.2f}"
                            notify(f'Tree created → Transit', 'positive')

                            # 2) client-side JS: upload photo directly to /api/trees/{id}/photo
                            tree_id = data['id']
                            js = f"""
                            (async () => {{
                              const input = document.getElementById('tree-photo');
                              if (!input || !input.files || !input.files.length) {{
                                console.log('[UPLOAD DEBUG] no file selected');
                                return;
                              }}
                              const file = input.files[0];
                              console.log('[UPLOAD DEBUG] browser file size=', file.size);
                              const form = new FormData();
                              form.append('file', file);
                              try {{
                                const res = await fetch('{BROWSER_API_BASE}/trees/{tree_id}/photo', {{
                                  method: 'POST',
                                  body: form
                                }});
                                if (!res.ok) {{
                                  const txt = await res.text();
                                  window.alert('Photo upload failed: ' + res.status + ' ' + txt);
                                }} else {{
                                  console.log('Photo upload OK');
                                  window.alert('Photo uploaded');
                                }}
                              }} catch (err) {{
                                console.error('Photo upload error', err);
                                window.alert('Photo upload error: ' + err);
                              }}
                            }})();
                            """
                            with client:
                                ui.run_javascript(js)

                            # 3) print label (optional)
                            if do_print:
                                try:
                                    pdf_bytes = _build_tree_label_pdf_bytes(
                                        tree_no=payload['tree_no'],
                                        metal_name=metal_pick.value or '',
                                        when_iso=payload['date'],
                                        # est_metal=est,
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

                            # 4) reset form
                            # g_in.value = 0.0
                            # tot_in.value = 0.0
                            bag_vals.clear()
                            render_bag_chips()
                            bag_in.value = ''
                            f_no.value = ''

                            # clear photo input + preview via JS
                            with client:
                                ui.run_javascript(
                                    """
                                    (function () {
                                      const input = document.getElementById('tree-photo');
                                      const img = document.getElementById('tree-photo-preview');
                                      if (input) input.value = '';
                                      if (img) { img.src = ''; img.style.display = 'none'; }
                                    })();
                                    """
                                )

                            # refresh_est()
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
                        # ui.button('RECALCULATE', on_click=refresh_est).props('outline')

                    await fill_next_no()

        # RIGHT: transit table
        with split.after:
            with ui.card().classes('w-full h-full p-0'):
                with ui.column().classes('w-full h-full').style('display:flex; flex-direction:column;'):
                    with ui.row().classes('items-end gap-3 p-4').style('flex:0 0 auto;'):
                        ui.label('Trees in Transit').classes('text-base font-semibold mr-4')
                        t_search = ui.input('Search by Tree No').props('clearable').classes('w-48')
                        d_from = ui.input('From').props('type=date').classes('w-36')
                        d_to = ui.input('To').props('type=date').classes('w-36')
                        metal_filter = ui.select(options=['All'] + metal_options, value='All', label='Metal').classes('w-48')
                        metal_filter.props('options-dense behavior=menu popup-content-style="z-index:4000"')

                        async def reset_filters():
                            d_from.value = ''
                            d_to.value = ''
                            t_search.value = ''
                            metal_filter.value = 'All'
                            await refresh_transit_table()
                            notify('Filters reset.', 'positive')

                        ui.button('RESET FILTERS', on_click=lambda: asyncio.create_task(reset_filters())).props('outline')

                    with ui.element('div').classes('fill-parent').style(
                        'flex:1 1 auto; overflow:auto; padding:0 16px 16px 16px; width:100%; max-width:100%;'
                    ):
                        columns = [
                            {'name': 'date', 'label': 'Date', 'field': 'date'},
                            {'name': 'tree_no', 'label': 'Tree No', 'field': 'tree_no'},
                            {'name': 'flask_no', 'label': 'Flask No', 'field': 'flask_no'},
                            {'name': 'metal_name', 'label': 'Metal', 'field': 'metal_name'},
                            # {'name': 'gasket_weight', 'label': 'Gasket', 'field': 'gasket_weight'},
                            # {'name': 'total_weight', 'label': 'Total', 'field': 'total_weight'},
                            # {'name': 'tree_weight', 'label': 'Tree Weight', 'field': 'tree_weight'},
                            # {'name': 'est_metal_weight', 'label': 'Req. Metal Weight', 'field': 'est_metal_weight'},
                        ]
                        transit_table = ui.table(columns=columns, rows=[]) \
                            .props('dense flat bordered row-key="tree_id" hide-bottom') \
                            .classes('w-full text-sm')

    # -------- filtering & refresh --------
    def _apply_filters_transit(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        f_date = parse_iso_date(d_from.value)
        t_date = parse_iso_date(d_to.value)
        pick = metal_filter.value or 'All'
        needle = (t_search.value or '').strip().lower()

        out: List[Dict[str, Any]] = []
        for r in rows:
            d_iso = r.get('date') or ''
            d = parse_iso_date(d_iso)
            if not d:
                continue
            if f_date and d < f_date:
                continue
            if t_date and d > t_date:
                continue
            if pick != 'All' and (r.get('metal_name') != pick):
                continue
            if needle and needle not in str(r.get('tree_no', '')).lower():
                continue

            rr = dict(r)
            rr['_sort_ord'] = -d.toordinal()
            rr['_sort_metal'] = rr.get('metal_name') or ''
            rr['_sort_tree'] = str(rr.get('tree_no', ''))
            rr['_display_date'] = to_ui_date(d_iso)
            out.append(rr)

        out.sort(key=lambda x: (x['_sort_ord'], x['_sort_metal'], x['_sort_tree']))
        for rr in out:
            rr['date'] = rr['_display_date']
            for k in ('_sort_ord', '_sort_metal', '_sort_tree', '_display_date'):
                rr.pop(k, None)
        return out

    async def refresh_transit_table():
        try:
            raw = await fetch_transit(
                date_from=d_from.value,
                date_to=d_to.value,
                tree_no=(t_search.value or '').strip(),
                metal=metal_filter.value,
            )
        except Exception as e:
            notify(f'Failed to fetch transit: {e}', 'negative')
            raw = []
        rows = _apply_filters_transit(raw)
        transit_table.rows = rows
        transit_table.update()

    metal_filter.on('update:model-value', lambda _v: asyncio.create_task(refresh_transit_table()))
    t_search.on('change', lambda _e: asyncio.create_task(refresh_transit_table()))
    d_from.on('change', lambda _e: asyncio.create_task(refresh_transit_table()))
    d_to.on('change', lambda _e: asyncio.create_task(refresh_transit_table()))

    await asyncio.create_task(refresh_transit_table())