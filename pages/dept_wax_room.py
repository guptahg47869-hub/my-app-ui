from nicegui import ui  # type: ignore
from .ui_components import stage_card

DEPT_COLOR = 'teal'

@ui.page('/dept/wax-room')
def wax_room_dept():
    ui.page_title('Wax Room · Casting Tracker')
    with ui.header().classes('items-center justify-between bg-gray-900 text-white'):
        ui.label('WAX ROOM').classes('text-lg font-semibold')
        ui.button(icon='home', on_click=lambda: ui.navigate.to('/')).props('flat round').classes('text-white')

    ui.label('Select a stage').classes('text-xl font-semibold mt-6 mb-2 px-6')
    with ui.grid(columns=3).classes('gap-4 px-6 w-full'):
        stage_card('Tree Weight', 'Create tree entries, calculated expected metal weight', '/trees', color=DEPT_COLOR)
        stage_card('Create Flask', 'Create flask entries and push to Metal Supply.', '/post-flask', color=DEPT_COLOR)