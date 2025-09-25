from nicegui import ui # type: ignore

# import all pages so they register with @ui.page
import pages.trees
import pages.post_flask
import pages.home
import pages.waxing
import pages.supply
import pages.casting
import pages.quenching
# import pages.cutting
import pages.reports

if __name__ in {"__main__", "__mp_main__"}:
    ui.run(title='Casting Tracker', reload=True)
