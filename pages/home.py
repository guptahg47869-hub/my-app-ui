from nicegui import ui  # type: ignore
from nicegui import ui  # type: ignore
from .ui_components import quick_action, department_card


# --- Small UI helpers ---------------------------------------------------------

# def quick_action(title: str, route: str, icon: str, color: str = 'gray'):
#     ui.button(
#         title,
#         icon=icon,
#         on_click=lambda: ui.navigate.to(route),
#     ).classes(
#         f'bg-{color}-800 hover:bg-{color}-900 text-white px-4 py-2 rounded-lg shadow-sm'
#     )


# def department_card(title: str, stages: list[str], route: str, icon: str, color: str):
#     """Clean, scannable department card: icon + title + bullet list of stages."""
#     with ui.card().classes(
#         f'w-full hover:shadow-lg transition-shadow cursor-pointer border-l-4 border-{color}-600'
#     ).style(
#         'min-height: 170px; display: flex; flex-direction: column; justify-content: space-between;'
#     ) as c:
#         # header row
#         with ui.row().classes('items-start justify-between w-full'):
#             with ui.row().classes('items-center gap-2'):
#                 ui.icon(icon).classes(f'text-{color}-600 text-2xl')
#                 ui.label(title).classes('text-lg font-semibold')
#             ui.icon('arrow_forward').classes('text-gray-400 text-xl')

#         # stages as bullets (easier to scan than a paragraph)
#         with ui.column().classes('mt-2 text-sm text-gray-600 gap-1'):
#             for s in stages:
#                 ui.label(f'• {s}')

#         # subtle affordance
#         ui.label('Open').classes(f'self-end text-sm font-medium text-{color}-700')

#     c.on('click', lambda _: ui.navigate.to(route))


# --- Home --------------------------------------------------------------------

@ui.page('/')
def landing():
    ui.page_title('Casting Tracker — Home')

    # Header
    with ui.header().classes('items-center justify-between bg-gray-900 text-white'):
        ui.label('Casting Tracker').classes('text-lg font-semibold')

    with ui.column().classes('w-full'):
        # Quick Actions
        ui.label('Quick actions').classes('text-lg font-semibold mt-6 px-6')
        with ui.row().classes('gap-3 px-6 flex-wrap'):
            quick_action('Flask Search', '/flask-search', icon='search', color='gray')
            quick_action('Reports', '/dept/reports', icon='bar_chart', color='gray')

        # Departments
        ui.label('Departments').classes('text-lg font-semibold mt-8 px-6')

        with ui.grid(columns=3).classes('gap-4 px-6 pb-10 w-full'):
            department_card(
                'WAX ROOM',
                stages=['Tree Weight', 'Create Flask'],
                route='/dept/wax-room',
                icon='science',
                color='teal',
            )

            department_card(
                'CASTING',
                stages=['Create Flask', 'Casting Metal In', 'Casting', 'Quenching', 'Casting Metal Out'],
                route='/dept/casting',
                icon='local_fire_department',
                color='amber',
            )

            department_card(
                'INVENTORY',
                stages=['Metal Prep', 'Reconciliation'],
                route='/dept/inventory',
                icon='inventory_2',
                color='green',
            )

            department_card(
                'CUTTING',
                stages=['Cutting'],
                route='/dept/cutting',
                icon='content_cut',
                color='red',
            )

            department_card(
                'JOB BAG SUPPLY',
                stages=['Job Bag Supply'],
                route='/dept/job-bag',
                icon='work',
                color='purple',
            )
