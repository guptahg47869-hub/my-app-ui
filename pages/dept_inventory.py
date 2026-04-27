from nicegui import ui  # type: ignore
from .ui_components import quick_action, stage_card

DEPT_COLOR = 'green'

@ui.page('/dept/inventory')
def inventory_dept():
    ui.page_title('Inventory · Casting Tracker')
    with ui.header().classes('items-center justify-between bg-gray-900 text-white'):
        ui.label('INVENTORY').classes('text-lg font-semibold')
        ui.button(icon='home', on_click=lambda: ui.navigate.to('/')).props('flat round').classes('text-white')

    ui.label('Quick actions').classes('text-lg font-semibold mt-6 px-6')
    with ui.row().classes('gap-3 px-6 flex-wrap'):
        quick_action('Flask Search', '/flask-search', icon='search', color='gray')
        quick_action('Reports', '/dept/reports', icon='bar_chart', color='gray')

    ui.label('Select a stage').classes('text-xl font-semibold mt-6 mb-2 px-6')
    with ui.grid(columns=3).classes('gap-4 px-6 w-full'):
        stage_card('Metal Prep', 'Review incoming flasks and prepare for casting.', '/metal-prep', color=DEPT_COLOR)
        stage_card('Reconciliation', 'Finalize scrap loss and complete flask.', '/reconciliation', color=DEPT_COLOR)
        # stage_card('Scrap Adjust', 'Adjust scrap reserve quantities.', '/scrap-adjust', color=DEPT_COLOR)
        # stage_card('Flask Search', 'See all flasks in rotation', '/flask-search', color=DEPT_COLOR)
        # stage_card('Reports', 'Incoming metal supply & scrap loss', '/reports', color=DEPT_COLOR)