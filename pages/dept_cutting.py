from nicegui import ui  # type: ignore
from .ui_components import stage_card

DEPT_COLOR = 'red'

@ui.page('/dept/cutting')
def cutting_dept():
    ui.page_title('Cutting Department · Casting Tracker')
    with ui.header().classes('items-center justify-between bg-gray-900 text-white'):
        ui.label('CUTTING DEPARTMENT').classes('text-lg font-semibold')
        ui.button(icon='home', on_click=lambda: ui.navigate.to('/')).props('flat round').classes('text-white')

    ui.label('Select a stage').classes('text-xl font-semibold mt-6 mb-2 px-6')
    with ui.grid(columns=3).classes('gap-4 px-6 w-full'):
        stage_card('Cutting', 'Record cutting weights, scrap & loss.', '/cutting', color=DEPT_COLOR)
