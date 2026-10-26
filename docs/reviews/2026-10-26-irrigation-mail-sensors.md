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
builder. A consistent production database copy generated all six configured
attachments. All **25 original runtime tabs** retained their values, cell styles,
column widths, frozen panes and order. All **68 sensor rows** matched the page's
shared query, using typed liters and exact timestamp bounds. The sensor sheet
was rendered in three ranges covering every row; all fields are readable and
the formula-error scan found no matches. A subsequent two-line alignment fix
passed the five targeted tests again and was revalidated on the production copy.

The tested daily window is **2026-10-25 07:00:00 → 10-26 06:59:59 Shanghai**.
Site 3 Low/High/WP are respectively **2170 / 400 / 54200 L** for this window,
which differs from the prior 15:32 operator reconciliation.

Production advanced to **a8e0ed51** with a fresh code/SQLite rollback backup and
unchanged configuration hash. No migration or dependency installation was
needed. Django checks passed; `horticulture` restarted at **2026-10-26 23:10:38
CST**, active/running with zero automatic restarts. GitHub temporarily rejected
the first pushes, which later succeeded; a verified Git bundle transferred the
same revision to the office server after its GitHub read timed out.

Exactly one test message, subject prefixed `【测试】`, was sent using the existing
SMTP configuration at **2026-10-26 23:12:18 Shanghai** to the one user-authorized
test mailbox. The SMTP backend returned 1 (accepted); inbox delivery is for the
operator to confirm. All six attachment hashes were checked before sending. The
irrigation workbook is **46,938 bytes**, SHA-256
`b6d56ab1317fb34a71105b9ac96799d85fbcd71d6bfc792517e5c649882a55fb`.

No normal recipients were included in the test. The scheduled configuration's
full-row hash was identical before and after the send, preserving its recipient
list, frequency, windows, send hour, last-send time and status. The test did not
consume a normal dispatch slot. Its immutable start marker prevents an accidental
duplicate send, and the MIME message, attachment manifest and SMTP receipt are
retained privately with the release evidence.

Private working directory:
`/home/noname/irrigation/deployment_backups/irrigation-mail-sensors-20261026/`.
