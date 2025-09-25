import os
from nicegui import ui

# import your pages
import pages.trees
import pages.post_flask
import pages.home
import pages.waxing
import pages.supply
import pages.casting
import pages.quenching
import pages.reports

if __name__ in {"__main__", "__mp_main__"}:
    port = int(os.getenv("PORT", 8080))  # Use Render-assigned PORT or default 8080
    ui.run(title='Casting Tracker', port=port, reload=False)
