# main.py
import os
from nicegui import ui  # type: ignore

# remove later

# import os
# from pathlib import Path
# from dotenv import load_dotenv, find_dotenv

# load_dotenv(find_dotenv())   # or: load_dotenv() if .env sits next to main.py

# # Now read your vars
# API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
# PORT = int(os.getenv("PORT", "8080"))

# import all pages so they register with @ui.page
import pages.trees
import pages.post_flask
import pages.home
import pages.waxing
import pages.supply
import pages.casting
import pages.quenching
import pages.cutting
import pages.reports
import pages.reports_transit
import pages.reports_scrap_loss
import pages.scrap_adjust
import pages.metal_prep
import pages.reconciliation
import pages.flask_search


if __name__ in {"__main__", "__mp_main__"}:
    PORT = int(os.environ.get("PORT", 8080))
    ui.run(
        title='Casting Tracker',
        host='0.0.0.0',
        port=PORT,
        reload=True,   # prod on Render
        show=False      # browser auto-open off
    )

    # print("API_BASE_URL =", API_BASE_URL)

