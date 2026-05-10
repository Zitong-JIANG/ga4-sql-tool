# GA4 SQL Query Builder

A command-line tool that generates ready-to-run BigQuery SQL for GA4 event data — no manual template editing required.

Supports two modes:

| Mode | What it generates |
|---|---|
| Basic event query | A `SELECT` query filtered by event name, date range, and country — for web, app, or ecom tables |
| App Firebase A/B test | A full CTE-based analysis query with experiment population, per-metric CTEs, and `avg_per_exposed_user` / `avg_per_active_user` output |

## Prerequisites

- Python 3.10+
- A GA4 dataset exported to BigQuery (flattened / transformed schema with top-level event parameter columns)

## Configuration

Open `public/ga4_query_builder.py` and set your project details at the top of the file:

```python
PROJECT_ID = "your-project-id"   # GCP project ID
DATASET    = "your_dataset"      # BigQuery dataset name

TABLES = {
    "web":  f"`{PROJECT_ID}.{DATASET}.ga4_web_events`",
    "app":  f"`{PROJECT_ID}.{DATASET}.ga4_app_events`",
    "ecom": f"`{PROJECT_ID}.{DATASET}.ga4_ecom_events`",
}
```

## Usage

```bash
python3 public/ga4_query_builder.py
```

### Mode 1 — Basic event query

Prompts for platform, event name, date range, and optional country filter. Outputs a `SELECT` with session identifiers, traffic source, geo, device, and platform-specific fields (page info for web, screen info for app, item-level fields for ecom).

```
Select mode [1/2]: 1
Platform [1/2/3]: 2          # app
Event name: screen_view
Start date: 2024-01-01
End date:   2024-01-31
Country:                     # leave blank for all
```

### Mode 2 — App Firebase A/B test

Prompts for date range, Android and iOS Firebase experiment keys, then lets you pick metrics from a preset list or enter custom event names.

```
Select mode [1/2]: 2
Start date: 2024-01-01
End date:   2024-01-31
Android firebase_exp key: firebase_exp_android
iOS     firebase_exp key: firebase_exp_ios

  Add metrics (presets or custom):
  [ 1] purchase         — COUNT(events) / exposed user
  [ 2] add_to_cart      — COUNT(events) / exposed user
  [ 3] begin_checkout   — COUNT(events) / exposed user
  [ 4] view_item        — COUNT(events) / exposed user
  [ 5] view_item_list   — COUNT(events) / exposed user
  [ 6] search           — COUNT(events) / exposed user
  [ 7] session_start    — COUNT(events) / exposed user  [1 per session → avg sessions/user]
  [ 8] screen_view      — COUNT(events) / exposed user, filtered by screen_name
  [ 9] engaged_sessions — COUNT(DISTINCT session_id) / exposed user
  [10] active_user_base — COUNT(DISTINCT user) with ≥1 engaged session  [denominator only, no avg output]
  [ c] custom event name
  [ d] done — finish adding metrics

  Add metric > 1
  + added: purchase
  Add metric > 9
  + added: engaged_sessions
  Add metric > d
```

The generated SQL follows a standard 4-stage structure:

1. `prep_platform` + `prep_all` → `prep` — loads and filters experiment-exposed events, plus an ALL-platform rollup
2. `experiment_population` — distinct exposed users per platform × variant
3. One CTE per metric — `events` + `users_with_event` aggregated by platform × variant
4. Final `SELECT` — joins metrics with population, computes `avg_per_exposed_user` and `avg_per_active_user` via `SAFE_DIVIDE`

Output is split by `ANDROID`, `IOS`, and `ALL` rows automatically.

### Saving output

After the SQL is printed, the tool asks whether to save it to a `.sql` file. The filename encodes the key parameters (platform, event, date range).

## Project structure

```
public/
  ga4_query_builder.py   # main script (standard GA4 preset events)
```

## Schema assumptions

> **Important:** This tool is built for a **flattened / pre-transformed GA4 schema**, not the raw BigQuery GA4 export.
> In the raw export, event parameters live inside a nested `event_params` REPEATED RECORD and require `UNNEST` to access.
> This tool assumes your pipeline has already flattened those parameters into top-level columns.

Key assumptions:

- Timestamps: `time.event_timestamp_utc` (TIMESTAMP)
- Session traffic source: flat columns — `session_source`, `session_medium`, `session_campaign`
- Date filtering: `event_date` (DATE column), not `_TABLE_SUFFIX`
- App experiments: `user_firebase_experiments` (REPEATED RECORD with `key` / `string_value`)
- Ecommerce: `ecommerce` RECORD + `items` REPEATED RECORD
