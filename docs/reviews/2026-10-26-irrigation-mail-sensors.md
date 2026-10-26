# Actual sensor water in the scheduled irrigation workbook

The operator requested physical Low/High/WP/WD/Toilet sensor liters in the
scheduled irrigation report, with a test sent to their explicitly designated
email address using the current production “每日推送” configuration.

## Configuration and report scope

Production configuration 2 is active, daily at 09:00 Shanghai time. Irrigation
uses yesterday 07:00:00 through today 06:59:59, all CCUs. The selected report
types are work reports, irrigation, projects, inventory catalog, inventory
transactions and purchase orders. Test preparation uses these same six report
builders/windows; only the test delivery recipient is overridden in memory.
Normal schedule, recipient lists and dispatch state remain intact.

The shared irrigation builder now adds `传感器水量` as the first sheet, retaining
the original CCU matrix tabs and their relative order, values and formatting.
Web downloads, scheduled mail, manual report generation and API exports all use
this builder. The application keeps its existing Python/openpyxl report stack;
Artifact Tool is used to inspect/render the actual generated XLSX for visual QA.

The sheet uses the same exact local query bounds and `sensor_window` service as
the web page. It includes typed query/sync timestamps, source backup, Site,
channel, sensor name, numeric liters, record status and associated CCUs. Source
labels remain literal Excel text. Zero, missing, disabled and incomplete data
retain their distinct meanings. Masters/submeters are never added together.

CCU subsets resolve through controller source Site keys, not a coincidental
match between internal Site ID and geographic CCU number. Shared Sites retain
the whole physical meter and list their associated CCUs; no allocation ratio
is invented. A missing association does not broaden a restricted report.

The new sheet uses the existing dark-green theme, readable typography, grouped
rows, filters, a frozen header and repeated print headings on landscape A4.
Unrelated reports and the existing SMTP/scheduling behavior are unchanged.

## Validation and release

Full isolated core suite: **281 tests, 280 passed, one existing CAD fixture skip**.
The five added report regressions cover real original sensor readings, exact
seconds and the production 07:00–06:59:59 window, source identity/shared meters,
missing coverage, disabled sensors, literal labels, and the scheduled email
attachment path. Existing runtime workbook regressions still verify all prior
operator values by the relevant CCU tab, since the water sheet is now first.

The existing production workbook was generated and rendered before changing the
builder. Candidate production-data comparison, final rendering, deployment and
the single authorized test-send result will be recorded when complete.

Private working directory:
`/home/noname/irrigation/deployment_backups/irrigation-mail-sensors-20261026/`.
