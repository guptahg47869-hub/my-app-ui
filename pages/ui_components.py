from nicegui import ui  # type: ignore


def quick_action(title: str, route: str, icon: str, color: str = 'blue'):
    with ui.card().classes(
        'cursor-pointer hover:shadow-md transition-shadow'
    ).style(
        'min-width: 160px;'
    ) as c:
        with ui.row().classes('items-center gap-2 px-4 py-3'):
            ui.icon(icon).classes(f'text-{color}-600 text-xl')
            ui.label(title).classes('font-semibold text-gray-800')

    c.on('click', lambda _: ui.navigate.to(route))


def department_card(title: str, stages: list[str], route: str, icon: str, color: str):
    """Department card used on home page (no 'Open' label/button)."""
    with ui.card().classes(
        f'w-full hover:shadow-lg transition-shadow cursor-pointer border-l-4 border-{color}-600'
    ).style(
        'min-height: 170px; display: flex; flex-direction: column; justify-content: space-between;'
    ) as c:
        with ui.row().classes('items-start justify-between w-full'):
            with ui.row().classes('items-center gap-2'):
                ui.icon(icon).classes(f'text-{color}-600 text-2xl')
                ui.label(title).classes('text-lg font-semibold')
            ui.icon('arrow_forward').classes('text-gray-400 text-xl')

        with ui.column().classes('mt-2 text-sm text-gray-600 gap-1'):
            for s in stages:
                ui.label(f'• {s}')

    c.on('click', lambda _: ui.navigate.to(route))


def stage_card(title: str, desc: str, route: str, icon: str = 'arrow_forward', color: str = 'teal'):
    """Stage card used on department pages, styled to match home cards (no 'Open' button)."""
    with ui.card().classes(
        f'w-full hover:shadow-lg transition-shadow cursor-pointer border-l-4 border-{color}-600'
    ).style(
        'min-height: 140px; display: flex; flex-direction: column; justify-content: space-between;'
    ) as c:
        with ui.row().classes('items-start justify-between w-full'):
            with ui.row().classes('items-center gap-2'):
                ui.icon(icon).classes(f'text-{color}-600 text-2xl')
                ui.label(title).classes('text-lg font-semibold')
            ui.icon('arrow_forward').classes('text-gray-400 text-xl')

        ui.label(desc).classes('text-gray-600 text-sm')

    c.on('click', lambda _: ui.navigate.to(route))
