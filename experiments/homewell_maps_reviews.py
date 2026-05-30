"""Scrape Google Maps GBP data for HomeWell Care Services franchise locations.

Discovery runs once on the first URL (Claude Code SDK → static selector fan-out),
then every subsequent URL replays the cached selectors — zero extra LLM calls.

Run:
    uv run python experiments/homewell_maps_reviews.py

Options via env vars:
    WORKERS=8       concurrent browser workers (default 8)
    FETCHER=headless  fetcher type: headless|headful (default headless)
    FORCE=0         set to 1 to re-run discovery even if selectors cached
"""

from __future__ import annotations

import asyncio
import csv
import os
import re
import urllib.parse
from pathlib import Path
from typing import Any

import yosoi as ys
from yosoi import Pipeline
from yosoi.utils.files import init_yosoi, is_initialized

# ── Model / run config ────────────────────────────────────────────────────────

MODEL = ys.claude_sdk('claude-sonnet-4-6')
WORKERS = int(os.getenv('WORKERS', '8'))
FETCHER = os.getenv('FETCHER', 'headless')
FORCE = os.getenv('FORCE', '0') == '1'

OUTPUT_PATH = Path(__file__).parent / 'homewell_maps_results.csv'


# ── Contract ──────────────────────────────────────────────────────────────────


class MapsPlaceFacts(ys.Contract):
    """GBP signals from a Google Maps place/search page.

    All Maps place pages share the same DOM structure → Yosoi discovers
    selectors once (first HomeWell location URL) and replays on the other 150.
    Zero LLM after the first URL.
    """

    business_name: str = ys.Title(default='')
    rating: str = ys.Rating(default='')
    review_count: str = ys.js(
        description=(
            'Google Maps review count — the integer shown in parentheses next to the '
            "star rating, e.g. '47' from '4.7 (47)' or '1,234' from '4.8 (1,234)'. "
            'Return only the digits and commas, no parentheses or surrounding text.'
        ),
        default='',
    )
    category: str = ys.Field(
        default='',
        description="Google Maps business category, e.g. 'Home health care service'. Empty if not shown.",
    )
    address: str = ys.Field(default='', description='Street address shown on the Maps panel. Empty if not visible.')
    hours: str = ys.Field(
        default='',
        description="Opening hours status, e.g. 'Open 24 hours' or 'Closed'. Empty if not shown.",
    )
    phone: str = ys.Field(
        default='',
        description="Business phone number as shown on the Maps panel, e.g. '(972) 555-1234'. Empty if not displayed.",
    )


# ── Location data ─────────────────────────────────────────────────────────────
# (domain_regime, location_name, lat, lng, franchise_url)

_LOCATIONS_RAW: list[tuple[str, str, float, float, str]] = [
    ('TX132', 'Plano, TX', 33.021, -96.719, 'https://homewellcares.com/in-home-care-tx-plano-tx132'),
    ('UT176', 'Murray, UT', 40.653, -111.871, 'https://homewellcares.com/in-home-care-ut-murray-ut176'),
    ('FL129', 'Clermont, FL', 28.55, -81.752, 'https://homewellcares.com/in-home-care-fl-clermont-fl129'),
    ('AZ131', 'Mesa, AZ', 33.392, -111.751, 'https://homewellcares.com/in-home-care-az-mesa-az131'),
    ('FL180', 'Sarasota, FL', 27.339, -82.474, 'https://homewellcares.com/in-home-care-fl-sarasota-fl180'),
    ('TN152', 'Hendersonville, TN', 36.306, -86.609, 'https://homewellcares.com/in-home-care-tn-hendersonville-tn152'),
    ('FL149', 'Delray Beach, FL', 26.457, -80.067, 'https://homewellcares.com/in-home-care-fl-delray-beach-fl149'),
    ('MD163', 'Towson, MD', 39.401, -76.599, 'https://homewellcares.com/in-home-care-md-towson-md163'),
    ('TX200', 'Seabrook, TX', 29.561, -95.035, 'https://homewellcares.com/in-home-care-tx-seabrook-tx200'),
    ('MI130', 'Troy, MI', 42.558, -83.155, 'https://homewellcares.com/in-home-care-mi-troy-mi130'),
    ('MA154', 'Natick, MA', 42.308, -71.381, 'https://homewellcares.com/in-home-care-ma-natick-ma154'),
    (
        'TX133',
        'North Richland Hills, TX',
        32.849,
        -97.215,
        'https://homewellcares.com/in-home-care-tx-north-richland-hills-tx133',
    ),
    (
        'CO159',
        'Colorado Springs, CO',
        38.898,
        -104.744,
        'https://homewellcares.com/in-home-care-co-colorado-springs-co159',
    ),
    ('AZ165', 'Tucson, AZ', 32.335, -110.976, 'https://homewellcares.com/in-home-care-az-tucson-az165'),
    ('TN168', 'Shelbyville, TN', 35.483, -86.46, 'https://homewellcares.com/in-home-care-tn-shelbyville-tn168'),
    ('TX169', 'Cypress, TX', 29.997, -95.696, 'https://homewellcares.com/in-home-care-tx-cypress-tx169'),
    ('OH117', 'Worthington, OH', 40.1, -83.018, 'https://homewellcares.com/in-home-care-oh-worthington-oh117'),
    ('TX194', 'Mansfield, TX', 32.554, -97.122, 'https://homewellcares.com/in-home-care-tx-mansfield-tx194'),
    ('PA119', 'Trooper, PA', 40.14, -75.391, 'https://homewellcares.com/in-home-care-pa-trooper-pa119'),
    ('AR174', 'Conway, AR', 35.091, -92.435, 'https://homewellcares.com/in-home-care-ar-conway-ar174'),
    ('AK112', 'Anchorage, AK', 61.167, -149.848, 'https://homewellcares.com/in-home-care-ak-anchorage-ak112'),
    ('AZ179', 'Surprise, AZ', 33.639, -112.386, 'https://homewellcares.com/in-home-care-az-surprise-az179'),
    ('KS166', 'Overland Park, KS', 38.938, -94.665, 'https://homewellcares.com/in-home-care-ks-overland-park-ks166'),
    ('TX148', 'Stafford, TX', 29.642, -95.569, 'https://homewellcares.com/in-home-care-tx-stafford-tx148'),
    ('CA123', 'San Rafael, CA', 37.972, -122.533, 'https://homewellcares.com/in-home-care-ca-san-rafael-ca123'),
    ('VA184', 'Fairfax, VA', 38.866, -77.234, 'https://homewellcares.com/in-home-care-va-fairfax-va184'),
    ('DE160', 'Georgetown, DE', 38.692, -75.384, 'https://homewellcares.com/in-home-care-de-georgetown-de160'),
    ('OH114', 'Cincinnati, OH', 39.284, -84.45, 'https://homewellcares.com/in-home-care-oh-cincinnati-oh114'),
    ('KS182', 'Wichita, KS', 37.723, -97.363, 'https://homewellcares.com/in-home-care-ks-wichita-ks182'),
    ('WA118', 'Seattle, WA', 47.734, -122.356, 'https://homewellcares.com/in-home-care-wa-seattle-wa118'),
    ('TX140', 'Cedar Park, TX', 30.517, -97.777, 'https://homewellcares.com/in-home-care-tx-cedar-park-tx140'),
    ('FL162', 'Fort Myers, FL', 26.554, -81.755, 'https://homewellcares.com/in-home-care-fl-fort-myers-fl162'),
    ('NJ111', 'Hackensack, NJ', 40.898, -74.037, 'https://homewellcares.com/in-home-care-nj-hackensack-nj111'),
    ('FL177', 'Orlando, FL', 28.537, -81.379, 'https://homewellcares.com/in-home-care-fl-orlando-fl177'),
    ('CA151', 'Roseville, CA', 38.752, -121.268, 'https://homewellcares.com/in-home-care-ca-roseville-ca151'),
    ('MA155', 'North Andover, MA', 42.675, -71.146, 'https://homewellcares.com/in-home-care-ma-north-andover-ma155'),
    ('GA113', 'Sandy Springs, GA', 33.926, -84.381, 'https://homewellcares.com/in-home-care-ga-sandy-springs-ga113'),
    ('FL173', 'Tampa, FL', 28.036, -82.489, 'https://homewellcares.com/in-home-care-fl-tampa-fl173'),
    ('CO167', 'Loveland, CO', 40.422, -105.098, 'https://homewellcares.com/in-home-care-co-loveland-co167'),
    ('CA178', 'Torrance, CA', 33.846, -118.329, 'https://homewellcares.com/in-home-care-ca-torrance-ca178'),
    ('FL172', 'Sunrise, FL', 26.138, -80.338, 'https://homewellcares.com/in-home-care-fl-sunrise-fl172'),
    ('DE1602', 'Smyrna, DE', 39.257, -75.587, 'https://homewellcares.com/in-home-care-de-smyrna-de1602'),
    ('MA156', 'Beverly Farms, MA', 42.562, -70.813, 'https://homewellcares.com/in-home-care-ma-beverly-farms-ma156'),
    ('OR120', 'Clackamas, OR', 45.408, -122.552, 'https://homewellcares.com/in-home-care-or-clackamas-or120'),
    ('MD146', 'Gaithersburg, MD', 39.121, -77.177, 'https://homewellcares.com/in-home-care-md-gaithersburg-md146'),
    ('NC157', 'Huntersville, NC', 35.41, -80.85, 'https://homewellcares.com/in-home-care-nc-huntersville-nc157'),
    ('TX175', 'New Braunfels, TX', 29.711, -98.166, 'https://homewellcares.com/in-home-care-tx-new-braunfels-tx175'),
    ('FL1292', 'The Villages, FL', 28.914, -81.922, 'https://homewellcares.com/in-home-care-fl-the-villages-fl1292'),
    ('AZ1312', 'Scottsdale, AZ', 33.581, -111.879, 'https://homewellcares.com/in-home-care-az-scottsdale-az1312'),
    ('FL1802', 'Bradenton, FL', 27.392, -82.443, 'https://homewellcares.com/in-home-care-fl-bradenton-fl1802'),
    ('OH1142', 'Dayton, OH', 39.626, -84.197, 'https://homewellcares.com/in-home-care-oh-dayton-oh1142'),
    ('NJ1112', 'Union, NJ', 40.697, -74.25, 'https://homewellcares.com/in-home-care-nj-union-nj1112'),
    ('NJ1113', 'Brick, NJ', 40.064, -74.144, 'https://homewellcares.com/in-home-care-nj-brick-nj1113'),
    ('CO1673', 'Westminster, CO', 39.85, -105.049, 'https://homewellcares.com/in-home-care-co-westminster-co1673'),
    ('CO1674', 'Englewood, CO', 39.668, -104.99, 'https://homewellcares.com/in-home-care-co-englewood-co1674'),
    ('AZ183', 'Glendale, AZ', 33.568, -112.182, 'https://homewellcares.com/in-home-care-az-glendale-az183'),
    ('MO193', 'St Louis, MO', 38.673, -90.374, 'https://homewellcares.com/in-home-care-mo-st-louis-mo193'),
    ('IL207', 'Lake Forest, IL', 42.254, -87.842, 'https://homewellcares.com/in-home-care-il-lake-forest-il207'),
    ('FL196', 'Flagler Beach, FL', 29.477, -81.126, 'https://homewellcares.com/in-home-care-fl-flagler-beach-fl196'),
    ('MS221', 'Madison, MS', 32.517, -90.094, 'https://homewellcares.com/in-home-care-ms-madison-ms221'),
    ('NC197', 'Fayetteville, NC', 35.047, -78.918, 'https://homewellcares.com/in-home-care-nc-fayetteville-nc197'),
    ('PA199', 'Philadelphia, PA', 39.953, -75.166, 'https://homewellcares.com/in-home-care-pa-philadelphia-pa199'),
    ('TX205', 'Carrollton, TX', 33.014, -96.886, 'https://homewellcares.com/in-home-care-tx-carrollton-tx205'),
    ('IN219', 'Valparaiso, IN', 41.454, -87.036, 'https://homewellcares.com/in-home-care-in-valparaiso-in219'),
    ('MN203', 'Edina, MN', 44.87, -93.352, 'https://homewellcares.com/in-home-care-mn-edina-mn203'),
    ('TX206', 'Humble, TX', 30.052, -95.231, 'https://homewellcares.com/in-home-care-tx-humble-tx206'),
    ('TX212', 'Pearland, TX', 29.553, -95.396, 'https://homewellcares.com/in-home-care-tx-pearland-tx212'),
    ('VA217', 'Fredericksburg, VA', 38.303, -77.513, 'https://homewellcares.com/in-home-care-va-fredericksburg-va217'),
    ('NC222', 'Greenville, NC', 35.58, -77.359, 'https://homewellcares.com/in-home-care-nc-greenville-nc222'),
    ('NC218', 'Greensboro, NC', 36.088, -79.771, 'https://homewellcares.com/in-home-care-nc-greensboro-nc218'),
    ('TX225', 'Galveston, TX', 29.306, -94.792, 'https://homewellcares.com/in-home-care-tx-galveston-tx225'),
    ('FL189', 'Largo, FL', 27.924, -82.796, 'https://homewellcares.com/in-home-care-fl-largo-fl189'),
    ('PA1992', 'Aston, PA', 39.852, -75.428, 'https://homewellcares.com/in-home-care-pa-aston-pa1992'),
    ('NC1572', 'Charlotte, NC', 35.239, -80.915, 'https://homewellcares.com/in-home-care-nc-charlotte-nc1572'),
    ('TX223', 'The Woodlands, TX', 30.136, -95.443, 'https://homewellcares.com/in-home-care-tx-the-woodlands-tx223'),
    ('AZ236', 'Glendale AZ (N)', 33.644, -112.23, 'https://homewellcares.com/in-home-care-az-glendale-az236'),
    ('WI241', 'Mequon, WI', 43.227, -87.924, 'https://homewellcares.com/in-home-care-wi-mequon-wi241'),
    ('IL214', 'Chicago, IL', 41.973, -87.807, 'https://homewellcares.com/in-home-care-il-chicago-il214'),
    ('CO1675', 'Parker, CO', 39.526, -104.77, 'https://homewellcares.com/in-home-care-co-parker-co1675'),
    ('PA209', 'Philadelphia PA (N)', 39.977, -75.274, 'https://homewellcares.com/in-home-care-pa-philadelphia-pa209'),
    ('FL215', 'Miami, FL', 25.66, -80.326, 'https://homewellcares.com/in-home-care-fl-miami-fl215'),
    ('GA235', 'Atlanta, GA', 33.854, -84.25, 'https://homewellcares.com/in-home-care-ga-atlanta-ga235'),
    ('WI249', 'Brookfield, WI', 43.039, -88.122, 'https://homewellcares.com/in-home-care-wi-brookfield-wi249'),
    ('IL226', 'Edwardsville, IL', 38.785, -89.98, 'https://homewellcares.com/in-home-care-il-edwardsville-il226'),
    ('CT248', 'Danbury, CT', 41.389, -73.498, 'https://homewellcares.com/in-home-care-ct-danbury-ct248'),
    ('AZ244', 'Mesa AZ (W)', 33.416, -111.856, 'https://homewellcares.com/in-home-care-az-mesa-az244'),
    ('MI251', 'Auburn Hills, MI', 42.679, -83.247, 'https://homewellcares.com/in-home-care-mi-auburn-hills-mi251'),
    ('TX237', 'Garland, TX', 32.895, -96.666, 'https://homewellcares.com/in-home-care-tx-garland-tx237'),
    ('IN256', 'Carmel, IN', 39.93, -86.11, 'https://homewellcares.com/in-home-care-in-carmel-in256'),
    ('FL260', 'Jacksonville FL (SE)', 30.263, -81.625, 'https://homewellcares.com/in-home-care-fl-jacksonville-fl260'),
    (
        'IL250',
        'Glendale Heights, IL',
        41.931,
        -88.08,
        'https://homewellcares.com/in-home-care-il-glendale-heights-il250',
    ),
    ('NV239', 'Las Vegas, NV', 36.195, -115.25, 'https://homewellcares.com/in-home-care-nv-las-vegas-nv239'),
    ('NC258', 'Raleigh, NC', 35.834, -78.667, 'https://homewellcares.com/in-home-care-nc-raleigh-nc258'),
    ('CT264', 'Simsbury, CT', 41.873, -72.802, 'https://homewellcares.com/in-home-care-ct-simsbury-ct264'),
    ('MA267', 'Taunton, MA', 41.902, -71.09, 'https://homewellcares.com/in-home-care-ma-taunton-ma267'),
    ('FL262', 'Jacksonville FL (N)', 30.484, -81.603, 'https://homewellcares.com/in-home-care-fl-jacksonville-fl262'),
    ('AZ276', 'Goodyear, AZ', 33.468, -112.384, 'https://homewellcares.com/in-home-care-az-goodyear-az276'),
    ('SC259', 'Mount Pleasant, SC', 32.811, -79.868, 'https://homewellcares.com/in-home-care-sc-mount-pleasant-sc259'),
    ('SC272', 'Fort Mill, SC', 35.058, -80.992, 'https://homewellcares.com/in-home-care-sc-fort-mill-sc272'),
    ('TX270', 'Temple, TX', 31.079, -97.408, 'https://homewellcares.com/in-home-care-tx-temple-tx270'),
    ('GA268', 'Gainesville, GA', 34.302, -83.827, 'https://homewellcares.com/in-home-care-ga-gainesville-ga268'),
    ('MI265', 'Ann Arbor, MI', 42.225, -83.732, 'https://homewellcares.com/in-home-care-mi-ann-arbor-mi265'),
    ('MD247', 'Pikesville, MD', 39.37, -76.716, 'https://homewellcares.com/in-home-care-md-pikesville-md247'),
    ('PA277', 'Bensalem, PA', 40.086, -74.935, 'https://homewellcares.com/in-home-care-pa-bensalem-pa277'),
    ('FL263', 'Apollo Beach, FL', 27.769, -82.394, 'https://homewellcares.com/in-home-care-fl-apollo-beach-fl263'),
    ('MI252', 'Saginaw, MI', 43.485, -83.969, 'https://homewellcares.com/in-home-care-mi-saginaw-mi252'),
    ('MD242', 'Crofton, MD', 38.992, -76.7, 'https://homewellcares.com/in-home-care-md-crofton-md242'),
    ('NC284', 'Carolina Beach, NC', 34.046, -77.898, 'https://homewellcares.com/in-home-care-nc-carolina-beach-nc284'),
    ('AR1742', 'Springdale, AR', 36.155, -94.143, 'https://homewellcares.com/in-home-care-ar-springdale-ar1742'),
    ('NV253', 'Las Vegas NV (NW)', 36.141, -115.244, 'https://homewellcares.com/in-home-care-nv-las-vegas-nv253'),
    ('GA274', 'Atlanta GA (NE)', 33.847, -84.369, 'https://homewellcares.com/in-home-care-ga-atlanta-ga274'),
    ('CA273', 'Lake Forest, CA', 33.661, -117.672, 'https://homewellcares.com/in-home-care-ca-lake-forest-ca273'),
    ('OK287', 'Oklahoma City, OK', 35.449, -97.689, 'https://homewellcares.com/in-home-care-ok-oklahoma-city-ok287'),
    ('GA290', 'Evans, GA', 33.513, -82.143, 'https://homewellcares.com/in-home-care-ga-evans-ga290'),
    ('PA279', 'Pittsburgh, PA', 40.375, -80.07, 'https://homewellcares.com/in-home-care-pa-pittsburgh-pa279'),
    ('NV275', 'Henderson, NV', 36.022, -115.082, 'https://homewellcares.com/in-home-care-nv-henderson-nv275'),
    ('CA285', 'Chula Vista, CA', 32.651, -117.05, 'https://homewellcares.com/in-home-care-ca-chula-vista-ca285'),
    ('GA296', 'Marietta, GA', 33.993, -84.523, 'https://homewellcares.com/in-home-care-ga-marietta-ga296'),
    ('GA294', 'Hiram, GA', 33.886, -84.732, 'https://homewellcares.com/in-home-care-ga-hiram-ga294'),
    ('MA291', 'Braintree, MA', 42.211, -71.0, 'https://homewellcares.com/in-home-care-ma-braintree-ma291'),
    ('TX293', 'Port Arthur, TX', 29.954, -93.985, 'https://homewellcares.com/in-home-care-tx-port-arthur-tx293'),
    ('CO1676', 'Denver, CO', 39.765, -104.904, 'https://homewellcares.com/in-home-care-co-denver-co1676'),
    ('ME156', 'Biddeford, ME', 43.443, -70.352, 'https://homewellcares.com/in-home-care-me-biddeford-me156'),
    ('NH156', 'Portsmouth, NH', 43.089, -70.79, 'https://homewellcares.com/in-home-care-nh-portsmouth-nh156'),
    ('NJ289', 'Marlton, NJ', 39.909, -74.939, 'https://homewellcares.com/in-home-care-nj-marlton-nj289'),
    ('ID288', 'Boise, ID', 43.573, -116.222, 'https://homewellcares.com/in-home-care-id-boise-id288'),
    ('IL292', 'Rockford, IL', 42.269, -88.997, 'https://homewellcares.com/in-home-care-il-rockford-il292'),
    ('IL283', 'Crystal Lake, IL', 42.235, -88.337, 'https://homewellcares.com/in-home-care-il-crystal-lake-il283'),
    ('CA282', 'San Diego, CA', 32.945, -117.242, 'https://homewellcares.com/in-home-care-ca-san-diego-ca282'),
    ('IL278', 'Schaumburg, IL', 42.026, -88.034, 'https://homewellcares.com/in-home-care-il-schaumburg-il278'),
    ('SC301', 'Greenville, SC', 34.862, -82.342, 'https://homewellcares.com/in-home-care-sc-greenville-sc301'),
    (
        'PA295',
        'N Philadelphia, PA',
        40.012,
        -75.184,
        'https://homewellcares.com/in-home-care-pa-north-philadelphia-pa295',
    ),
    ('TX297', 'Houston, TX', 29.947, -95.421, 'https://homewellcares.com/in-home-care-tx-houston-tx297'),
    ('TX303', 'Magnolia, TX', 30.224, -95.584, 'https://homewellcares.com/in-home-care-tx-magnolia-tx303'),
    ('CT299', 'Hartford, CT', 41.766, -72.675, 'https://homewellcares.com/in-home-care-ct-hartford-ct299'),
    ('SC313', 'Myrtle Beach, SC', 33.808, -78.713, 'https://homewellcares.com/in-home-care-sc-myrtle-beach-sc313'),
    ('SC316', 'Lexington, SC', 33.978, -81.231, 'https://homewellcares.com/in-home-care-sc-lexington-sc316'),
    ('AL315', 'Birmingham, AL', 33.367, -86.762, 'https://homewellcares.com/in-home-care-al-birmingham-al315'),
    ('OK312', 'Tulsa, OK', 36.087, -95.923, 'https://homewellcares.com/in-home-care-ok-tulsa-ok312'),
    ('TN306', 'Oak Ridge, TN', 36.013, -84.24, 'https://homewellcares.com/in-home-care-tn-oak-ridge-tn306'),
    ('CA308', 'Sacramento, CA', 38.6, -121.431, 'https://homewellcares.com/in-home-care-ca-sacramento-ca308'),
    ('GA311', 'Alpharetta, GA', 34.068, -84.299, 'https://homewellcares.com/in-home-care-ga-alpharetta-ga311'),
    ('CA304', 'San Mateo, CA', 37.563, -122.326, 'https://homewellcares.com/in-home-care-ca-san-mateo-ca304'),
    ('CA305', 'Upland, CA', 34.105, -117.668, 'https://homewellcares.com/in-home-care-ca-upland-ca305'),
    ('TX1332', 'Denton, TX', 33.219, -97.136, 'https://homewellcares.com/in-home-care-tx-denton-tx1332'),
    ('AL319', 'Madison, AL', 34.682, -86.751, 'https://homewellcares.com/in-home-care-al-madison-al319'),
    ('CA310', 'Sunnyvale, CA', 37.396, -121.98, 'https://homewellcares.com/in-home-care-ca-sunnyvale-ca310'),
    ('IL281', 'Glenview, IL', 42.091, -87.801, 'https://homewellcares.com/in-home-care-il-glenview-il281'),
    ('MA320', 'Lynnfield, MA', 42.539, -71.048, 'https://homewellcares.com/in-home-care-ma-lynnfield-ma320'),
    ('MO331', 'Ballwin, MO', 38.61, -90.568, 'https://homewellcares.com/in-home-care-mo-ballwin-mo331'),
    ('UT321', 'Lehi, UT', 40.428, -111.892, 'https://homewellcares.com/in-home-care-ut-lehi-ut321'),
]

# ── URL builder ────────────────────────────────────────────────────────────────


def _build_maps_url(location_name: str, lat: float, lng: float) -> str:
    """Google Maps text search scoped to coordinates for the exact franchise area."""
    clean = re.sub(r'\s*\([^)]+\)', '', location_name).strip().rstrip(',')
    query = urllib.parse.quote_plus(f'HomeWell Care Services {clean}')
    return f'https://www.google.com/maps/search/{query}/@{lat},{lng},15z'


def _build_locations() -> list[dict[str, Any]]:
    return [
        {
            'domain_regime': code,
            'location_name': name,
            'lat': lat,
            'lng': lng,
            'franchise_url': furl,
            'maps_url': _build_maps_url(name, lat, lng),
        }
        for code, name, lat, lng, furl in _LOCATIONS_RAW
    ]


# ── Main ──────────────────────────────────────────────────────────────────────

_CSV_FIELDS = [
    'domain_regime',
    'location_name',
    'lat',
    'lng',
    'franchise_url',
    'maps_url',
    'business_name',
    'rating',
    'review_count',
    'category',
    'address',
    'hours',
    'phone',
    'status',
]


async def main() -> None:
    if not is_initialized():
        init_yosoi()

    locations = _build_locations()
    maps_urls = [loc['maps_url'] for loc in locations]

    print(f'Scraping {len(maps_urls)} Google Maps locations with {WORKERS} workers...')
    print(f'Model: {MODEL.provider}:{MODEL.model_name}  Fetcher: {FETCHER}\n')

    pipeline = Pipeline(
        MODEL,
        contract=MapsPlaceFacts,
        output_format=['json'],
        selector_level=ys.SelectorLevel.CSS,
        experimental_a3node=False,  # DOMLoader must run per-URL to load the business panel
    )

    run_results = await pipeline.process_urls(
        maps_urls,
        workers=WORKERS,
        fetcher_type=FETCHER,
        force=FORCE,
        skip_verification=False,
    )

    successful_set = set(run_results.get('successful', []))
    failed_set = set(run_results.get('failed', []))
    print(f'\n✓ {len(successful_set)} succeeded  ✗ {len(failed_set)} failed')

    # Load extracted content for each location
    enriched: list[dict[str, Any]] = []
    for loc in locations:
        url = loc['maps_url']
        content: dict[str, Any] = {}

        raw = await pipeline.storage.load_content(url, contract_sig=pipeline._contract_sig)
        if isinstance(raw, dict):
            content = raw
        elif isinstance(raw, list) and raw:
            content = raw[0]

        # Split "4.6 (77)" into rating="4.6" and review_count="77"
        raw_rating = content.get('rating', '') or ''
        rc_from_js = content.get('review_count', '') or ''
        m = re.search(r'\((\d[\d,]*)\)', raw_rating)
        if m:
            clean_rating = raw_rating[: m.start()].strip().rstrip('(').strip()
            rc_from_css = m.group(1)
        else:
            clean_rating = raw_rating
            rc_from_css = ''
        # JS result takes priority; fall back to CSS-embedded count
        review_count = rc_from_js if (rc_from_js and rc_from_js != clean_rating) else rc_from_css

        enriched.append(
            {
                **loc,
                'business_name': content.get('business_name', ''),
                'rating': clean_rating,
                'review_count': review_count,
                'category': content.get('category', ''),
                'address': content.get('address', ''),
                'hours': content.get('hours', ''),
                'phone': content.get('phone', ''),
                'status': 'ok' if url in successful_set else 'failed',
            }
        )

    # Write output CSV
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open('w', newline='', encoding='utf-8') as fh:
        writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDS)
        writer.writeheader()
        writer.writerows(enriched)

    print(f'\nResults written to: {OUTPUT_PATH}')
    print(f'  {sum(1 for r in enriched if r["rating"])} locations with rating')
    print(f'  {sum(1 for r in enriched if r["review_count"])} locations with review count')

    # Quick preview
    print('\nSample results:')
    print(f'{"Domain":<10} {"Location":<25} {"Rating":<8} {"Reviews":<10} {"Phone"}')
    print('-' * 75)
    for row in enriched[:10]:
        print(
            f'{row["domain_regime"] or ""!s:<10} {row["location_name"] or ""!s:<25} '
            f'{row["rating"] or ""!s:<8} {row["review_count"] or ""!s:<10} {row["phone"] or ""!s}'
        )


if __name__ == '__main__':
    asyncio.run(main())
