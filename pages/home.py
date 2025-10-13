from nicegui import ui # type: ignore

def stage_card(title: str, desc: str, route: str, icon: str = 'arrow_forward', color: str = 'teal'):
    with ui.card().classes('w-full hover:shadow-lg transition-shadow cursor-pointer') \
                 .style('min-height: 140px; display: flex; flex-direction: column; justify-content: space-between;') as c:
        with ui.row().classes('items-center justify-between w-full'):
            ui.label(title).classes('text-lg font-semibold')
            ui.icon(icon).classes(f'text-{color}-600 text-2xl')
        ui.label(desc).classes('text-gray-600 text-sm')
        ui.button('Open', on_click=lambda: ui.navigate.to(route)).classes(f'bg-{color}-600 text-white self-end')
    c.on('click', lambda _: ui.navigate.to(route))

@ui.page('/')
def landing():
    ui.page_title('Casting Tracker — Home')
    with ui.header().classes('items-center justify-between bg-gray-900 text-white'):
        ui.label('Casting Tracker').classes('text-lg font-semibold')

    ui.label('Select a stage').classes('text-xl font-semibold mt-6 mb-2 px-6')
    with ui.grid(columns=3).classes('gap-4 px-6 w-full'):
        ui.label('CREATE TREES AND FLASKS').classes('text-xl font-semibold mt-6 mb-2 px-6')
        stage_card('Tree Weight', 'Create tree entries, calculated expected metal weight', '/trees')
        stage_card('Create Flask', 'Create flask entries and push to Metal Supply.', '/post-flask')
    with ui.grid(columns=4).classes('gap-4 px-6 w-full'):
        ui.label('METAL DEPT').classes('text-xl font-semibold mt-6 mb-2 px-6')
        stage_card('Metal Prep', 'Review incoming flasks and prepare for casting.', '/metal-prep')
        stage_card('Metal Supply', 'Allocate scrap/fresh metal to flasks.', '/supply')
        stage_card('Reconciliation', 'Finalize scrap loss and complete flask.', '/reconciliation')
    with ui.grid(columns=4).classes('gap-4 px-6 w-full'):
        ui.label('CASTING DEPT').classes('text-xl font-semibold mt-6 mb-2 px-6')
        stage_card('Casting', 'Review temperature and push to Quenching.', '/casting')
        stage_card('Quenching', 'Track ready times & countdowns.', '/quenching')
        stage_card('Cutting', 'Record casting weights, scrap & loss.', '/cutting')
    with ui.grid(columns=4).classes('gap-4 px-6 w-full'):
        ui.label('OTHER').classes('text-xl font-semibold mt-6 mb-2 px-6')
        stage_card('Flask Search', 'See all flasks in rotation', '/flask-search')
        stage_card('Reports', 'Incoming metal supply & scrap loss', '/reports')
        stage_card('Scrap Adjust', 'Adjust scrap reserve quantities.', '/scrap-adjust')
