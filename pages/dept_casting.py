from nicegui import ui  # type: ignore
from .ui_components import stage_card

DEPT_COLOR = 'amber'

@ui.page('/dept/casting')
def casting_dept():
    ui.page_title('Casting Department · Casting Tracker')
    with ui.header().classes('items-center justify-between bg-gray-900 text-white'):
        ui.label('CASTING DEPARTMENT').classes('text-lg font-semibold')
        ui.button(icon='home', on_click=lambda: ui.navigate.to('/')).props('flat round').classes('text-white')

    ui.label('Select a stage').classes('text-xl font-semibold mt-6 mb-2 px-6')
    with ui.grid(columns=3).classes('gap-4 px-6 w-full'):
        stage_card('Create Flask', 'Create flask entries and push to Casting Metal In.', '/post-flask', color=DEPT_COLOR)
        stage_card('Casting Metal In', 'Allocate scrap/fresh metal to flasks.', '/casting-metal-in', color=DEPT_COLOR)
        stage_card('Casting', 'Review temperature and push to Quenching.', '/casting', color=DEPT_COLOR)
        stage_card('Quenching', 'Track ready times & countdowns.', '/quenching', color=DEPT_COLOR)
        stage_card('Casting Metal Out', 'Enter after-casting weight and move to Cutting.', '/casting-metal-out', color=DEPT_COLOR)