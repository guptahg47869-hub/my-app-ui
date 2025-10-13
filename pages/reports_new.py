from nicegui import ui

@ui.page('/reports')
def reports_home():
    ui.page_title('Reports')

    with ui.header().classes('items-center justify-between bg-gray-900 text-white'):
        ui.label('Reports').classes('text-lg font-semibold')
        ui.link('Home', '/').classes('text-white')

    ui.label('Choose a report').classes('text-xl font-semibold mt-4 mb-2 px-6')

    with ui.row().classes('gap-4 px-6 w-full'):
        def tile(title: str, desc: str, to: str):
            with ui.card().classes('cursor-pointer hover:shadow-lg transition w-96') \
                          .on('click', lambda e, dest=to: ui.navigate.to(dest)):
                ui.label(title).classes('text-lg font-medium')
                ui.separator()
                ui.label(desc).classes('text-gray-500 text-sm')
                with ui.row().classes('justify-end pt-2'):
                    ui.button('Open', on_click=lambda to=to: ui.navigate.to(to)).props('color=primary')

        tile('Transit Summary', 'By metal with drill-down to trees.', '/reports/transit')
        tile('Scrap Loss', 'Confirmed loss (after Reconciliation).', '/reports/scrap-loss')
