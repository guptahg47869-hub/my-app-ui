from nicegui import ui  # type: ignore
from .ui_components import stage_card

DEPT_COLOR = 'gray'

@ui.page('/dept/reports')
def reports_dept():
    ui.page_title('Reports · Casting Tracker')
    with ui.header().classes('items-center justify-between bg-gray-900 text-white'):
        ui.label('REPORTS').classes('text-lg font-semibold')
        with ui.row().classes('items-center gap-2'):

            ui.button('← Inventory', on_click=lambda: ui.navigate.to('/dept/inventory')).props('flat').classes('text-white font-semibold')
            ui.button('← Job Bag Supply', on_click=lambda: ui.navigate.to('/dept/job-bag')).props('flat').classes('text-white font-semibold')
            ui.button(icon='home', on_click=lambda: ui.navigate.to('/')).props('flat round').classes('text-white')

    ui.label('Select a report').classes('text-xl font-semibold mt-6 mb-2 px-6')
    with ui.grid(columns=3).classes('gap-4 px-6 w-full'):
        stage_card('Transit Summary', 'Trees currently in transit, with drilldown.', '/reports/transit', color=DEPT_COLOR)
        stage_card('Scrap Loss', 'Scrap loss by flask (post-reconciliation).', '/reports/scrap-loss', color=DEPT_COLOR)
        stage_card('Scrap Adjust', 'Adjust scrap reserve quantities.', '/reports/scrap-adjust', color=DEPT_COLOR)