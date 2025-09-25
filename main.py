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
    ui.run(title='Casting Tracker', reload=False)  # reload=False for production
