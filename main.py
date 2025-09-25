# main.py
import os
from nicegui import ui  # type: ignore

# import all pages so they register with @ui.page
import pages.trees
import pages.post_flask
import pages.home
import pages.waxing
import pages.supply
import pages.casting
import pages.quenching
import pages.reports

if __name__ in {"__main__", "__mp_main__"}:
    PORT = int(os.environ.get("PORT", 8080))
    ui.run(
        title='Casting Tracker',
        host='0.0.0.0',
        port=PORT,
        reload=False,   # prod on Render
        show=False      # browser auto-open off
    )
