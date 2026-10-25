# Maxicom water-volume investigation — 2026-10-25

## Scope and evidence

This is a read-only investigation of the water table on `/irrigation/`, following
the runtime/timezone release. Production source HEAD was `4bf2a45`. No production
application code, business records, importer settings, or Maxicom settings were
changed during this investigation.

The full original `Maxicom2-20261024.mdb` was examined: 23 active Sites, 93 active
FLO WATCH zones, 3,496 active station configurations and **4,042,513 flow readings**.
The raw flow timestamp span is `20250830000000`…`20261023231700` UTC. The system
preference is `Liters`; all observed flow multipliers are 1. There are no negative
flow values, zero multipliers, undefined flow-zone references, or disagreements
between a reading's `SiteID` and its zone's `FlowZoneSiteNumber` in this snapshot.

**Unit qualification:** numerical quantities marked L below describe the existing
application's raw-as-liter convention so its arithmetic can be reproduced. They
are **not independently validated physical liters**. A subsequent unit check
found strong evidence of imperial internal storage despite the metric display
preference; see finding 7. This qualification applies equally to omitted totals,
the 2,803/5,606 example and historical estimate differences. Ratios, key mappings,
inclusion-flag errors and overlapping coverage do not depend on that unit choice.

For numerical comparisons, the MDB was paired with the already isolated
`db-candidate.sqlite3` built from that same source. The live server had subsequently
imported `MC2Backup10252026.zip`; its newer row totals are deliberately not compared
with the older MDB as evidence of loss or corruption. No additional reconciliation
of the operator's 20 runtime reference values was performed.

Detailed source-derived results and the read-only audit script are retained under
`/home/noname/irrigation/deployment_backups/maxicom-review-20261025-004202/`:

- `audit-flow.py`, `flow-audit-consistent.json`, `flow-factor-history.json`;
- the original MDB, the same-source candidate SQLite database, and prior backups.

Local evidence copies are in ignored `.tmp-pm-review/flow-audit-consistent.json`
and `.tmp-pm-review/flow-factor-history.json`. No credentials are included.

## Findings

### 1. Site internal keys are treated as geographic CCU numbers

`FLOZO_CF.FlowZoneSiteNumber` and `XA_FLOZO.SiteID` refer to
**`SITE_CF.IndexNumber`**, not `SITE_CF.SiteNumber`. Configuration rows have
history: `SITE_CF` contains 1,486 rows for 23 distinct internal keys. The active
version supplies the displayed Site number/name. A mapping must resolve this
relationship, rather than attach the numeric foreign key to `Patch.code`.

The flow importer currently builds a dictionary from `CCU<n>` patches and uses
`site_map.get(FlowZoneSiteNumber)` directly. Representative consequences:

| Source internal key | Active Site number / source name | Current water attribution |
| --- | --- | --- |
| 3 | 5 / Fantasyland Seven Dwaft | CCU3 / TL |
| 5 | 3 / Tomorrowland | CCU5 / FL |
| 4 | 7 / Adventure Isle & ME | Dropped |
| 8 | 9 / Garden (217) | CCU8 / 宝藏湾 |
| 12 | 14 / Parking lot | CCU12 / 小镇 |
| 13 | 35 / North Service Rd | CCU13 / 蓝天大道 |
| 15 | 37 / West Loop Rd | CCU15 / 酒店3 |
| 16 | 38 / South-West Loop Rd | CCU16 / Site 16 |
| 17 | 39 / South Loop Rd | CCU17 / Site 17 |
| 18 | 40 / North Branch RD | Dropped |
| 19 | 43 / Lake park East | Dropped |
| 20 | 44 / Lake park South | Dropped |
| 21 | 45 / Lake park West | Dropped |
| 22 | 13 / PTC | Dropped |
| 28 | 36 / Start from 18/6/22 | Dropped |

This explains why matching a meter total and a runtime estimate on their current
`site_id` can combine different physical areas.

The source Site number is stable across all stored versions for the listed
Sites except internal key 28, which has historical numbers 33 and 36. Historical
renaming/renumbering must therefore be retained, rather than overwrite raw keys.

### 2. Real flow zones are silently excluded

The importer saves 68 of the 93 zones. Of the 25 skipped zones, only one is the
zero-volume `MC Bench Test` zone. Twenty-four belong to real source Sites; 23 of
these have positive recorded volumes. They include Adventure Isle, PTC, the lake
parks, North Branch Road and Site 36.

Across the complete source snapshot, skipped zones with `FlowZoneJoinSite=Y`
contain **39,874,622 raw volume units**, currently labeled L by the app. This is not a claim about a user's
selected day or independently measured net consumption. It quantifies included
source readings omitted solely because the wrong numeric CCU lookup fails.

### 3. The Site-total inclusion flag is imported but ignored

`MaxicomFlowZone.join_site` already stores `FlowZoneJoinSite`, but neither the
water table's meter aggregation nor the AI `query_flow_daily` total filters it.
Both sum every stored flow zone.

Rain Bird explicitly allows a FLO WATCH zone to be excluded from whole-Site
calculations. The manual's Site FLO WATCH setup, sections 4.15–4.16, describes the
checkbox and its effect on whole-Site flow calculations:
[Rain Bird Maxicom2 manual](https://rainbirdservices.com/wp-content/uploads/2018/10/Maxicom2-Manual.pdf).

An original-data example for **2026-09-11 22:00:00 → 2026-09-12 21:59:59 Shanghai**:

| East Entrance source zone | Include in Site | Recorded value (raw units) |
| --- | --- | ---: |
| z3 — Flow Zone 1 IRR | Y | 2,803 |
| z42 — 2-inch FS | N | 0 |
| z43 — 4-inch FS | N | 2,803 |
| z99 — NOFLOWSENSOR | Y | 0 |

The existing arithmetic gives **5,606**, while honoring the source's
whole-Site inclusion settings gives **2,803** raw volume units for these recorded zones.
There are 98 readings each in z3 and z43 in this window. No exact duplicate rows
occur within any individual flow zone in the sample window; the duplication is
across overlapping zones, not repeated ingestion of the same row.

In the entire same-source candidate database, the current stored meter sum of
193,445,205 raw units consists of 126,630,304 from included zones and **66,814,901 from
zones explicitly excluded by the source configuration**. Removing excluded zones
alone is insufficient: the dropped Sites and wrong geographic assignments still
need correction. These whole-history figures must not be presented as a corrected
physical irrigation total.

### 4. Meter readings and all-station estimates are added without coverage rules

The estimate is `actual runtime minutes × current station flow factor`, for every
station in a CCU. The code does not check `STATN_CF.StationWatchZone` or whether
the station belongs to a zone already represented by recorded flow.

For the same September 12 window, source internal Site 8 (displayed Site 9 / Garden)
has included recorded values of 7,087 in z5 and 24,063 in z6. The active-factor
runtime estimate is approximately 9,736.93 for stations in z5 and 67,730.58 for
stations in z6. All of that estimate belongs to those same two monitored zones.
Adding the 31,150 recorded units to the 77,467.51 estimated units has no established
meaning as a distinct total; both describe the same coverage by different methods.
This example does not claim that either method independently measures true usage.

Conversely, Site 2 has stations assigned to z99 `NOFLOWSENSOR`, so a blanket rule
that estimates can never complement readings would also be unjustified. Sensor
coverage and explicit source/report rules are required. A zero reading alone does
not prove a sensor is absent and must not silently trigger estimated replacement.

The prior code comments claiming desktop agreement from one 98.8% example are
not a valid specification. The comparison mixed inconsistent Site/CCU identities
and does not establish a universal addition formula.

### 5. The same bad fallback also affects some runtime/estimate CCU labels

Controller names with an explicit prefix, such as `SAT 7-1`, resolve through that
prefix. Names such as `SAT1`, `SAT2` and `SAT5(North pump)` do not. The current
fallback attaches these stations/controllers by internal Site key again.

This puts internal Sites 13, 15, 16 and 17 under CCU13, CCU15, CCU16 and CCU17
instead of source display numbers 35, 37, 38 and 39. It is a distinct grouping
problem outside the already verified CCU2/7/44 operator examples. Any repair must
retain station IDs and original runtime timestamps rather than adjust minutes.

### 6. Historical estimates use today's factor rather than its effective version

The source retains dated station configurations, but `MaxicomStationFlowFactor`
stores only the latest active factor. The page applies that snapshot to every
historical runtime event.

Twenty-three source stations have different factor values across their history.
For 15 of them, 281 positive runtime events in the same-source candidate fall
inside a historical configuration interval with a different factor. Comparing
the current algorithm with the source's `DateOpen <= event < DateClose` factor
produces a signed difference of **+100,310.613 raw estimated-volume units** across those events.
This is an estimate-method difference over the full snapshot, not a measured loss,
a difference for one user-selected day, or proof of true physical consumption.

Example: station 1280 changes from 9.508716583 to 15.847859383 in raw flow-factor units at
`20251029031641`. Forty-five earlier events total 1,904 minutes; applying the later
factor to them adds approximately 12,069.728 raw estimated-volume units.

### 7. Strong evidence that raw flow units are mislabeled as liters

The importer copies `StationFlowFactor` directly into a field labeled L/min and
copies `FlowZoneValue × FlowZoneMultiplier` into `liters`, without a documented
unit conversion. A metric display preference does not establish MDB storage units.
The manual explicitly describes these preferences as display-unit choices:
[Maxicom2 manual, section 3.11](https://rainbirdservices.com/wp-content/uploads/2018/10/Maxicom2-Manual.pdf).

Independent numerical clues in the source configuration:

| Stored value / field | Numerical relationship |
| --- | --- |
| Station flow factor 31.695719 | × 3.786 ≈ 120, equivalent to 2 L/s if stored as GPM |
| Station flow factor 39.619648 | × 3.786 ≈ 150, equivalent to 2.5 L/s if stored as GPM |
| Station flow factor 63.391438 | × 3.786 ≈ 240, equivalent to 4 L/s if stored as GPM |
| Flow decoder pulse value 18.494055063 | × 3.785 ≈ 70 |
| Flow decoder pulse value 52.840157322 | × 3.785 ≈ 200 |
| System water price 0.01703250036 | ÷ 3.785 × 1000 ≈ 4.5 |

All 18 most frequent positive station factors convert to round multiples of 6
under the 3.786 relationship. This, the independent flow-decoder calibration and
water-price relationships strongly suggest gallons/GPM internally and metric
conversion at display time. Rain Bird's addendum also describes the flow sensor
configuration in gallons per pulse, but does not document these MDB fields or
their exact conversion constants:
[Maxicom2 addendum, page 63](https://rainbirdservices.com/wp-content/uploads/2018/10/Maxicom2-User-Manual-Addendum.pdf).

**This remains an inference, not a verified storage-unit specification.** An
independent source-screen flow setting with its unit, or an Actual Log volume
report with an exact window and selected zones, is needed to settle the scale.
The slight difference between 3.785 and 3.786 is observable and must not be
silently replaced with one universal constant. Logged-rate versus interval-volume
semantics should also be established before claiming physical liters. No numeric
conversion has been deployed on the strength of this inference alone.

## Source coverage that still requires a defined reporting policy

- **Shared meter:** source Site 12 is displayed as Site 14. Its z21 IRR zone
  contains stations from `SAT 14-1`…`SAT 14-6` and `LR37-4`. One measured total
  therefore spans geographic CCU14 and CCU37. The z22 WD zone's assigned stations
  belong to CCU14. These distinctions should be retained; z21 cannot be divided
  by an invented ratio or credited in full to both CCUs.
- **Non-irrigation coverage:** source Site 3 includes `4-inch WD Flow logs` and
  `4-inch Toilet Flow logs`, both with `JoinSite=Y`. They contribute 4,319 and
  23,192 raw recorded units respectively in the sample window. A whole-Site water report may
  legitimately include these; a table titled irrigation volume must explain or
  separate this coverage instead of silently equating the two.
- **Source configuration may itself overlap:** Site 40's source zones named
  `total`, `2-inch` and `4-inch` are all marked included. Similar totals suggest
  overlapping coverage, but names and totals alone are insufficient to delete a
  zone or alter Maxicom configuration. Honoring `JoinSite` reproduces source
  inclusion settings; it does not prove all source meters are hydraulically
  independent.
- **Custom time windows:** the application stores daily water aggregates only.
  The existing complete-irrigation-day restriction remains necessary until
  original timed readings or suitable finer aggregates are retained. Do not
  compare a full-day meter sum against an arbitrary hourly runtime window.

## Concrete repair design

1. Retain source Site internal key, displayed number/name, effective configuration
   dates and flow-zone identity independently of the geographic Patch foreign key.
   Import all original flow zones, including unmapped/shared ones; expose their
   attribution status rather than discard them.
   Establish raw storage units, displayed units and interval semantics separately;
   preserve raw values alongside an explicitly verified conversion.
2. Resolve the source Site foreign key through `SITE_CF`. Use the resulting display
   number as the validated fallback for controllers without a geographic prefix.
   Preserve explicit geographic sub-area prefixes and detect conflicts/shared
   ownership instead of flattening them into one CCU.
3. Apply `FlowZoneJoinSite` to a whole-Site recorded-water total. Keep excluded
   sub-zone readings visible as detail, clearly outside the total. Apply identical
   rules to the server-rendered page, AJAX/paging and AI water query.
4. Present **recorded water and runtime-based estimates separately**. Remove the
   unsupported arithmetic combined total. A future combined/fallback metric
   requires explicit non-overlapping coverage and source report rules first.
5. Calculate historical station estimates against effective-dated source factors;
   expose missing factors/coverage rather than count them as measured zero.
6. Show source Site 14 / shared CCU14+37 coverage explicitly; keep ambiguous
   non-irrigation/source-overlap settings visible without rewriting them.

Before production release, use an isolated same-source database to verify all-zone
retention, the z3/z43 inclusion regression, source-key/display-number swaps,
unprefixed-controller fallback, shared z21 ownership, dated factors, all-CCU versus
single-CCU/AJAX/AI consistency, and unchanged business records/station identities.
The runtime reference cases already supplied by the operator must remain unchanged.

**Status:** investigation complete; these water-volume corrections have not been
implemented or deployed by this investigation. Existing runtime/timezone fixes
remain in place.
