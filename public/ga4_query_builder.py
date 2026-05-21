"""
GA4 BigQuery SQL Query Builder
Supports:
  1. Basic event queries  (web / app / ecom)
  2. App Firebase A/B test analysis

NOTE: This tool targets a *flattened / pre-transformed* GA4 schema, NOT the raw
BigQuery GA4 export (where event parameters live inside the nested `event_params`
array). All event parameters are expected to be top-level columns in your table.
See the README for the full list of schema assumptions.
"""

import re
from datetime import datetime
from typing import Any


# ── Table placeholders (edit before running) ──────────────────────────────────
PROJECT_ID = "your-project-id"   # e.g. "my-company-analytics"
DATASET    = "your_dataset"      # e.g. "analytics_ga4_prod"

TABLES = {
    "web":  f"`{PROJECT_ID}.{DATASET}.ga4_web_events`",
    "app":  f"`{PROJECT_ID}.{DATASET}.ga4_app_events`",
    "ecom": f"`{PROJECT_ID}.{DATASET}.ga4_ecom_events`",
}
# ──────────────────────────────────────────────────────────────────────────────

# Standard GA4 preset metrics for App Firebase A/B tests
PRESET_METRICS: list[dict[str, Any]] = [
    {"name": "purchase",         "event": "purchase",        "extra": "", "desc": "COUNT(events) / exposed user"},
    {"name": "add_to_cart",      "event": "add_to_cart",     "extra": "", "desc": "COUNT(events) / exposed user"},
    {"name": "begin_checkout",   "event": "begin_checkout",  "extra": "", "desc": "COUNT(events) / exposed user"},
    {"name": "view_item",        "event": "view_item",       "extra": "", "desc": "COUNT(events) / exposed user"},
    {"name": "view_item_list",   "event": "view_item_list",  "extra": "", "desc": "COUNT(events) / exposed user"},
    {"name": "search",           "event": "search",          "extra": "", "desc": "COUNT(events) / exposed user"},
    {"name": "session_start",    "event": "session_start",   "extra": "", "desc": "COUNT(events) / exposed user  [1 per session → avg sessions/user]"},
    {"name": "screen_view",      "event": "screen_view",     "extra": "", "desc": "COUNT(events) / exposed user, filtered by screen_name", "needs_screen": True},
    {"name": "pdp_views",        "event": "screen_view",     "extra": "firebase_screen = 'Productdetail'", "desc": "COUNT(events) / exposed user, screen_view on Productdetail"},
    {"name": "engaged_sessions", "event": None, "special": "engaged_sessions", "desc": "COUNT(DISTINCT session_id) / exposed user"},
    {"name": "active_user_base", "event": None, "special": "active_user_base", "desc": "COUNT(DISTINCT user) with ≥1 engaged session  [denominator only, no avg output]", "exclude_mode3": True, "exclude_mode4": True},
]


# ── Shared helpers ─────────────────────────────────────────────────────────────

def validate_date(date_str: str) -> str:
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(date_str.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValueError(f"Invalid date '{date_str}'. Use YYYY-MM-DD or YYYYMMDD.")


def get_input(prompt: str, allow_empty: bool = False) -> str:
    while True:
        value = input(prompt).strip()
        if value or allow_empty:
            return value
        print("  [!] This field is required.")


def ask_dates() -> tuple[str, str]:
    while True:
        raw_start = get_input("Start date  (YYYY-MM-DD): ")
        raw_end   = get_input("End date    (YYYY-MM-DD): ")
        try:
            start = validate_date(raw_start)
            end   = validate_date(raw_end)
            if start > end:
                print("  [!] Start date must be on or before end date.")
                continue
            return start, end
        except ValueError as e:
            print(f"  [!] {e}")


def safe_name(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def save_sql(sql: str, filename: str) -> None:
    answer = input("Save to file? (y/N): ").strip().lower()
    if answer == "y":
        with open(filename, "w", encoding="utf-8") as f:
            f.write(sql)
        print(f"  Saved → {filename}")


# ── Mode 1-3: Basic event query ────────────────────────────────────────────────

def build_event_sql(platform: str, event_name: str, start_date: str,
                    end_date: str, country: str | None) -> str:
    table = TABLES[platform]
    country_filter = f"\n  AND geo.country = '{country}'" if country else ""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    shared = f"""\
-- ============================================================
-- GA4 Event Query  [{platform.upper()}]
-- Event     : {event_name}
-- Date range: {start_date} to {end_date}
-- Country   : {country if country else 'All'}
-- Generated : {now}
-- ============================================================

SELECT
  user_pseudo_id,
  user_id,
  ga_session_id,
  user_session_id,
  event_name,
  event_date,
  time.event_timestamp_utc                  AS event_timestamp,
  platform,
  stream_id,
  is_active_user,
  session_source,
  session_medium,
  session_campaign,
  session_content,
  geo.country                               AS country,
  geo.city                                  AS city,
  geo.region                                AS region,
  geo.continent                             AS continent,
  device.category                           AS device_category,
  device.operating_system                   AS os,
  device.operating_system_version           AS os_version,
  device.language                           AS device_language,"""

    if platform == "app":
        specific = """
  app_info.id                               AS app_id,
  app_info.version                          AS app_version,
  app_info.install_store                    AS install_store,
  firebase_screen,
  firebase_screen_class,
  firebase_screen_id,
  utm_source,
  utm_medium,
  utm_campaign,
  url_referrer"""
    elif platform == "ecom":
        specific = """
  device.web_info.browser                   AS browser,
  device.web_info.browser_version           AS browser_version,
  device.web_info.hostname                  AS hostname,
  page_location,
  page_title,
  page_referrer,
  page_language,
  page_country,
  ecommerce.transaction_id                  AS transaction_id,
  ecommerce.purchase_revenue                AS purchase_revenue,
  ecommerce.purchase_revenue_in_usd         AS purchase_revenue_usd,
  ecommerce.total_item_quantity             AS total_item_quantity,
  ecommerce.shipping_value                  AS shipping_value,
  ecommerce.tax_value                       AS tax_value,
  ecommerce.unique_items                    AS unique_items,
  currency,
  value                                     AS event_value,
  item.item_id,
  item.item_name,
  item.item_brand,
  item.item_category,
  item.item_category2,
  item.item_variant,
  item.price,
  item.quantity,
  item.item_revenue,
  item.coupon"""
    else:  # web
        specific = """
  device.web_info.browser                   AS browser,
  device.web_info.browser_version           AS browser_version,
  device.web_info.hostname                  AS hostname,
  page_location,
  page_title,
  page_referrer,
  page_language,
  page_country"""

    from_clause = (
        f"\n\nFROM\n  {table},\n  UNNEST(items) AS item"
        if platform == "ecom"
        else f"\n\nFROM\n  {table}"
    )

    return (
        shared + specific + from_clause
        + f"\n\nWHERE\n  event_date BETWEEN DATE('{start_date}') AND DATE('{end_date}')"
        + f"\n  AND event_name = '{event_name}'{country_filter}"
        + "\n\nORDER BY\n  time.event_timestamp_utc DESC;\n"
    )


def run_event_query() -> None:
    print("\nPlatform:")
    print("  [1] web")
    print("  [2] app")
    print("  [3] ecom  (includes items UNNEST)")
    while True:
        c = input("Select [1/2/3]: ").strip()
        m = {"1":"web","2":"app","3":"ecom","web":"web","app":"app","ecom":"ecom"}
        if c in m:
            platform = m[c]; break
        print("  [!] Enter 1, 2, or 3.")

    event_name  = get_input("\nEvent name  (e.g. page_view, purchase): ")
    start, end  = ask_dates()
    country_raw = get_input("Country     (leave blank for all): ", allow_empty=True)
    country     = country_raw or None

    sql = build_event_sql(platform, event_name, start, end, country)
    print("\n" + "="*60 + "\n  Generated SQL\n" + "="*60 + "\n")
    print(sql)

    country_tag = f"_{country.replace(' ','_')}" if country else ""
    save_sql(sql, f"ga4_{platform}_{event_name}_{start}_{end}{country_tag}.sql")


# ── Mode 2: App Firebase A/B test ─────────────────────────────────────────────

def _metric_cte(m: dict[str, Any]) -> str:
    """Build one metric CTE block (without trailing comma)."""
    cte_id = f"metric_{safe_name(m['name'])}"
    special = m.get("special", "")

    if special == "engaged_sessions":
        return f"""\
{cte_id} AS (
  SELECT
    platform, raw_experiment_id, variant,
    'engaged_sessions' AS metric_name,
    COUNT(DISTINCT user_session_id) AS events,
    COUNT(DISTINCT user_pseudo_id)  AS users_with_event
  FROM prep
  WHERE engaged_session_event = 1
  GROUP BY platform, raw_experiment_id, variant
)"""

    if special == "active_user_base":
        return f"""\
{cte_id} AS (
  SELECT
    ep.platform, ep.raw_experiment_id, ep.variant,
    'active_user_base' AS metric_name,
    CAST(NULL AS INT64)              AS events,
    COUNT(DISTINCT p.user_pseudo_id) AS users_with_event
  FROM experiment_population ep
  JOIN prep p
    ON  p.platform              = ep.platform
   AND  IFNULL(p.raw_experiment_id, '') = IFNULL(ep.raw_experiment_id, '')
   AND  p.variant               = ep.variant
  WHERE p.engaged_session_event = 1
  GROUP BY ep.platform, ep.raw_experiment_id, ep.variant
)"""

    extra = m.get("extra", "")
    extra_clause = f"\n    AND {extra}" if extra else ""
    return f"""\
{cte_id} AS (
  SELECT
    platform, raw_experiment_id, variant,
    '{m["name"]}' AS metric_name,
    COUNT(1)                        AS events,
    COUNT(DISTINCT user_pseudo_id)  AS users_with_event
  FROM prep
  WHERE event_name = '{m["event"]}'{extra_clause}
  GROUP BY platform, raw_experiment_id, variant
)"""


def _ttest_metric_ctes(m: dict[str, Any]) -> str:
    """Build two CTEs per metric for t-test: raw per-user counts + winsorized at p99."""
    cte_id = f"metric_{safe_name(m['name'])}"
    raw_id = f"{cte_id}_raw"
    special = m.get("special", "")
    extra = m.get("extra", "")
    extra_clause = f"\n    AND {extra}" if extra else ""

    if special == "engaged_sessions":
        count_expr = "COUNT(DISTINCT user_session_id)"
        where_clause = "WHERE engaged_session_event = 1"
    else:
        count_expr = "COUNT(1)"
        where_clause = f"WHERE event_name = '{m['event']}'{extra_clause}"

    return f"""\
{raw_id} AS (
  SELECT
    platform, raw_experiment_id, variant, user_pseudo_id,
    {count_expr} AS raw_count
  FROM prep
  {where_clause}
  GROUP BY platform, raw_experiment_id, variant, user_pseudo_id
),

{cte_id} AS (
  SELECT
    platform, raw_experiment_id, variant,
    '{m["name"]}' AS metric_name,
    LEAST(
      CAST(raw_count AS FLOAT64),
      PERCENTILE_CONT(raw_count, 0.99) OVER (
        PARTITION BY platform, raw_experiment_id, variant
      )
    ) AS winsorized_count
  FROM {raw_id}
)"""


def collect_metrics(mode3: bool = False, mode4: bool = False) -> list[dict[str, Any]]:
    """Interactive metric selection: presets + custom."""
    print()
    print("  Add metrics (presets or custom):")
    available = [
        p for p in PRESET_METRICS
        if not (mode3 and p.get("exclude_mode3"))
        and not (mode4 and p.get("exclude_mode4"))
    ]
    for i, p in enumerate(available, 1):
        desc = p.get("desc", "")
        tag = f"  — {desc}" if desc else ""
        print(f"    [{i:>2}] {p['name']}{tag}")
    print("    [ c] custom event name")
    print("    [ d] done — finish adding metrics")
    print()

    selected: list[dict[str, Any]] = []
    added_names: set[str] = set()

    while True:
        raw = input("  Add metric > ").strip().lower()

        if raw in ("d", "done", ""):
            if not selected:
                print("  [!] Add at least one metric.")
                continue
            break

        if raw in ("c", "custom"):
            event = get_input("    Event name: ")
            extra = get_input("    Extra WHERE condition (leave blank for none): ", allow_empty=True)
            name  = get_input(f"    Metric label [{event}]: ", allow_empty=True) or event
            if name in added_names:
                print(f"  [!] '{name}' already added.")
                continue
            selected.append({"name": name, "event": event, "extra": extra})
            added_names.add(name)
            print(f"  + added: {name}")
            continue

        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(available):
                preset = dict(available[idx])
                if preset["name"] in added_names:
                    print(f"  [!] '{preset['name']}' already added.")
                    continue
                if preset.get("needs_screen"):
                    screen = get_input(f"    firebase_screen filter for '{preset['name']}': ")
                    preset["extra"] = f"firebase_screen = '{screen}'"
                selected.append(preset)
                added_names.add(preset["name"])
                print(f"  + added: {preset['name']}")
                continue

        print("  [!] Enter a number, 'c' for custom, or 'd' when done.")

    return selected


def build_ab_test_app_sql(start_date: str, end_date: str,
                           android_key: str, ios_key: str,
                           metrics: list[dict[str, Any]]) -> str:
    table = TABLES["app"]
    now   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    has_active_base = any(m.get("special") == "active_user_base" for m in metrics)
    active_base_case = "\n    WHEN m.metric_name = 'active_user_base' THEN NULL" if has_active_base else ""

    cte_blocks = [_metric_cte(m) for m in metrics]
    metric_ctes_sql = ",\n\n".join(cte_blocks) + ","

    union_lines = "\n  UNION ALL SELECT * FROM ".join(
        f"metric_{safe_name(m['name'])}" for m in metrics
    )

    return f"""\
-- ============================================================
-- App Firebase A/B Test Query
-- Date range  : {start_date} to {end_date}
-- Android key : {android_key}
-- iOS key     : {ios_key}
-- Metrics     : {", ".join(m["name"] for m in metrics)}
-- Generated   : {now}
-- ============================================================

DECLARE start_date DATE DEFAULT DATE('{start_date}');
DECLARE end_date   DATE DEFAULT DATE('{end_date}');

WITH prep_platform AS (
  SELECT
    event_date,
    platform,
    user_pseudo_id,
    user_session_id,
    event_name,
    firebase_screen,
    engaged_session_event,
    time.event_timestamp_utc       AS event_ts,
    ufe.key                        AS raw_experiment_id,
    ufe.string_value               AS variant
  FROM {table}
  CROSS JOIN UNNEST(user_firebase_experiments) AS ufe
  WHERE event_date BETWEEN start_date AND end_date
    AND platform IN ('ANDROID', 'IOS')
    AND user_pseudo_id IS NOT NULL
    AND user_session_id IS NOT NULL
    AND ufe.key IN ('{android_key}', '{ios_key}')
    AND (
          (platform = 'ANDROID' AND ufe.key = '{android_key}')
       OR (platform = 'IOS'     AND ufe.key = '{ios_key}')
    )
),

prep_all AS (
  SELECT
    event_date,
    'ALL'                          AS platform,
    user_pseudo_id,
    user_session_id,
    event_name,
    firebase_screen,
    engaged_session_event,
    time.event_timestamp_utc       AS event_ts,
    CAST(NULL AS STRING)           AS raw_experiment_id,
    ufe.string_value               AS variant
  FROM {table}
  CROSS JOIN UNNEST(user_firebase_experiments) AS ufe
  WHERE event_date BETWEEN start_date AND end_date
    AND platform IN ('ANDROID', 'IOS')
    AND user_pseudo_id IS NOT NULL
    AND user_session_id IS NOT NULL
    AND ufe.key IN ('{android_key}', '{ios_key}')
    AND (
          (platform = 'ANDROID' AND ufe.key = '{android_key}')
       OR (platform = 'IOS'     AND ufe.key = '{ios_key}')
    )
),

prep AS (
  SELECT * FROM prep_platform
  UNION ALL
  SELECT * FROM prep_all
),

experiment_population AS (
  SELECT
    platform,
    raw_experiment_id,
    variant,
    COUNT(DISTINCT user_pseudo_id) AS experiment_population_users
  FROM prep
  GROUP BY platform, raw_experiment_id, variant
),

{metric_ctes_sql}

metrics_union AS (
  SELECT * FROM {union_lines}
)

SELECT
  m.platform,
  m.raw_experiment_id,
  m.variant,
  m.metric_name,
  ep.experiment_population_users,
  m.users_with_event,
  CASE{active_base_case}
    WHEN ep.experiment_population_users = 0 THEN NULL
    ELSE ROUND(SAFE_DIVIDE(CAST(m.events AS FLOAT64),
                           CAST(ep.experiment_population_users AS FLOAT64)), 4)
  END AS avg_per_exposed_user,
  CASE{active_base_case}
    WHEN m.users_with_event = 0 THEN NULL
    ELSE ROUND(SAFE_DIVIDE(CAST(m.events AS FLOAT64),
                           CAST(m.users_with_event AS FLOAT64)), 4)
  END AS avg_per_user_with_event
FROM metrics_union m
JOIN experiment_population ep
  ON  ep.platform                          = m.platform
 AND  IFNULL(ep.raw_experiment_id, '')     = IFNULL(m.raw_experiment_id, '')
 AND  ep.variant                           = m.variant
ORDER BY platform, variant, metric_name;
"""


def build_significance_sql(start_date: str, end_date: str,
                            android_key: str, ios_key: str,
                            metrics: list[dict[str, Any]],
                            control_variant: str) -> str:
    """Welch's t-test on avg_per_exposed_user with 99th-percentile winsorization."""
    table = TABLES["app"]
    now   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cte_blocks = [_ttest_metric_ctes(m) for m in metrics]
    metric_ctes_sql = ",\n\n".join(cte_blocks) + ","

    union_lines = "\n  UNION ALL SELECT * FROM ".join(
        f"metric_{safe_name(m['name'])}" for m in metrics
    )

    return f"""\
-- ============================================================
-- App Firebase A/B Test — Significance Test (Welch's t-test)
-- avg_per_exposed_user, winsorized at p99
-- Date range  : {start_date} to {end_date}
-- Android key : {android_key}
-- iOS key     : {ios_key}
-- Control     : {control_variant}
-- Metrics     : {", ".join(m["name"] for m in metrics)}
-- Generated   : {now}
-- ============================================================

DECLARE start_date DATE DEFAULT DATE('{start_date}');
DECLARE end_date   DATE DEFAULT DATE('{end_date}');

WITH prep_platform AS (
  SELECT
    event_date,
    platform,
    user_pseudo_id,
    user_session_id,
    event_name,
    firebase_screen,
    engaged_session_event,
    time.event_timestamp_utc       AS event_ts,
    ufe.key                        AS raw_experiment_id,
    ufe.string_value               AS variant
  FROM {table}
  CROSS JOIN UNNEST(user_firebase_experiments) AS ufe
  WHERE event_date BETWEEN start_date AND end_date
    AND platform IN ('ANDROID', 'IOS')
    AND user_pseudo_id IS NOT NULL
    AND user_session_id IS NOT NULL
    AND ufe.key IN ('{android_key}', '{ios_key}')
    AND (
          (platform = 'ANDROID' AND ufe.key = '{android_key}')
       OR (platform = 'IOS'     AND ufe.key = '{ios_key}')
    )
),

prep_all AS (
  SELECT
    event_date,
    'ALL'                          AS platform,
    user_pseudo_id,
    user_session_id,
    event_name,
    firebase_screen,
    engaged_session_event,
    time.event_timestamp_utc       AS event_ts,
    CAST(NULL AS STRING)           AS raw_experiment_id,
    ufe.string_value               AS variant
  FROM {table}
  CROSS JOIN UNNEST(user_firebase_experiments) AS ufe
  WHERE event_date BETWEEN start_date AND end_date
    AND platform IN ('ANDROID', 'IOS')
    AND user_pseudo_id IS NOT NULL
    AND user_session_id IS NOT NULL
    AND ufe.key IN ('{android_key}', '{ios_key}')
    AND (
          (platform = 'ANDROID' AND ufe.key = '{android_key}')
       OR (platform = 'IOS'     AND ufe.key = '{ios_key}')
    )
),

prep AS (
  SELECT * FROM prep_platform
  UNION ALL
  SELECT * FROM prep_all
),

experiment_population AS (
  SELECT
    platform,
    raw_experiment_id,
    variant,
    COUNT(DISTINCT user_pseudo_id) AS n
  FROM prep
  GROUP BY platform, raw_experiment_id, variant
),

{metric_ctes_sql}

metrics_agg AS (
  SELECT
    platform, raw_experiment_id, variant, metric_name,
    SUM(winsorized_count)                        AS sum_x,
    SUM(winsorized_count * winsorized_count)     AS sum_x2
  FROM (
    SELECT * FROM {union_lines}
  )
  GROUP BY platform, raw_experiment_id, variant, metric_name
),

stats AS (
  SELECT
    ep.platform,
    ep.raw_experiment_id,
    ep.variant,
    ma.metric_name,
    ep.n,
    SAFE_DIVIDE(ma.sum_x,  ep.n)                                              AS mean,
    SAFE_DIVIDE(ma.sum_x2, ep.n)
      - POW(SAFE_DIVIDE(ma.sum_x, ep.n), 2)                                  AS var
  FROM experiment_population ep
  JOIN metrics_agg ma
    ON  ma.platform                      = ep.platform
   AND  IFNULL(ma.raw_experiment_id, '') = IFNULL(ep.raw_experiment_id, '')
   AND  ma.variant                       = ep.variant
),

sig_base AS (
  SELECT
    s_t.platform,
    s_t.raw_experiment_id,
    s_t.metric_name,
    '{control_variant}'                                      AS control_variant,
    s_t.variant                                              AS treatment_variant,
    s_c.n                                                    AS control_n,
    s_t.n                                                    AS treatment_n,
    ROUND(s_c.mean, 4)                                       AS control_mean,
    ROUND(s_t.mean, 4)                                       AS treatment_mean,
    SAFE_DIVIDE(
      s_t.mean - s_c.mean,
      SQRT(SAFE_DIVIDE(s_c.var, s_c.n) + SAFE_DIVIDE(s_t.var, s_t.n))
    )                                                        AS t_stat
  FROM stats s_t
  JOIN stats s_c
    ON  s_c.platform                      = s_t.platform
   AND  IFNULL(s_c.raw_experiment_id, '') = IFNULL(s_t.raw_experiment_id, '')
   AND  s_c.metric_name                   = s_t.metric_name
   AND  s_c.variant                       = '{control_variant}'
  WHERE s_t.variant != '{control_variant}'
),

sig_pvalue AS (
  SELECT
    *,
    ABS(t_stat) / SQRT(2)                               AS _x,
    1.0 / (1.0 + 0.3275911 * ABS(t_stat) / SQRT(2))    AS _tp
  FROM sig_base
)

SELECT
  platform,
  raw_experiment_id,
  metric_name,
  control_variant,
  treatment_variant,
  control_n,
  treatment_n,
  control_mean,
  treatment_mean,
  ROUND(SAFE_DIVIDE(treatment_mean - control_mean,
                    control_mean), 4)                        AS relative_lift,
  ROUND(t_stat, 4)                                           AS t_stat,
  ROUND(
    (  0.254829592  * _tp
     - 0.284496736  * POW(_tp, 2)
     + 1.421413741  * POW(_tp, 3)
     - 1.453152027  * POW(_tp, 4)
     + 1.061405429  * POW(_tp, 5))
    * EXP(-_x * _x)
  , 4)                                                       AS p_value,
  ABS(t_stat) >= 1.96                                        AS is_significant_95
FROM sig_pvalue
ORDER BY platform, metric_name, treatment_variant;
"""


def _raw_user_metric_cte(m: dict[str, Any]) -> str:
    """Per-user event count CTE for Mode 4 raw data export."""
    cte_id  = f"metric_{safe_name(m['name'])}"
    special = m.get("special", "")

    if special == "engaged_sessions":
        count_expr   = "COUNT(DISTINCT user_session_id)"
        where_clause = "WHERE engaged_session_event = 1"
    else:
        extra = m.get("extra", "")
        extra_clause  = f"\n    AND {extra}" if extra else ""
        count_expr    = "COUNT(1)"
        where_clause  = f"WHERE event_name = '{m['event']}'{extra_clause}"

    return f"""\
{cte_id} AS (
  SELECT
    user_pseudo_id, variant,
    {count_expr} AS cnt
  FROM prep
  {where_clause}
  GROUP BY user_pseudo_id, variant
)"""


def build_raw_data_sql(start_date: str, end_date: str,
                        android_key: str, ios_key: str,
                        metrics: list[dict[str, Any]]) -> str:
    """One row per user_pseudo_id with per-metric event counts — for custom significance tests."""
    table = TABLES["app"]
    now   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cte_blocks      = [_raw_user_metric_cte(m) for m in metrics]
    metric_ctes_sql = ",\n\n".join(cte_blocks)

    join_lines = "\n".join(
        f"LEFT JOIN metric_{safe_name(m['name'])} AS m_{safe_name(m['name'])}"
        f"\n  USING (user_pseudo_id, variant)"
        for m in metrics
    )

    select_metric_cols = ",\n".join(
        f"  COALESCE(m_{safe_name(m['name'])}.cnt, 0)  AS metric_{safe_name(m['name'])}"
        for m in metrics
    )

    return f"""\
-- ============================================================
-- App Firebase A/B Test — User-Level Raw Data  (Mode 4)
-- One row per user_pseudo_id; use for your own significance test
-- Date range  : {start_date} to {end_date}
-- Android key : {android_key}
-- iOS key     : {ios_key}
-- Metrics     : {", ".join(m["name"] for m in metrics)}
-- Generated   : {now}
-- ============================================================

DECLARE start_date DATE DEFAULT DATE('{start_date}');
DECLARE end_date   DATE DEFAULT DATE('{end_date}');

WITH prep AS (
  SELECT
    user_pseudo_id,
    user_session_id,
    event_name,
    firebase_screen,
    engaged_session_event,
    ufe.string_value               AS variant
  FROM {table}
  CROSS JOIN UNNEST(user_firebase_experiments) AS ufe
  WHERE event_date BETWEEN start_date AND end_date
    AND platform IN ('ANDROID', 'IOS')
    AND user_pseudo_id IS NOT NULL
    AND user_session_id IS NOT NULL
    AND ufe.key IN ('{android_key}', '{ios_key}')
    AND (
          (platform = 'ANDROID' AND ufe.key = '{android_key}')
       OR (platform = 'IOS'     AND ufe.key = '{ios_key}')
    )
),

experiment_population AS (
  SELECT DISTINCT
    user_pseudo_id,
    variant
  FROM prep
),

{metric_ctes_sql}

SELECT
  ep.user_pseudo_id,
  ep.variant,
{select_metric_cols}
FROM experiment_population ep
{join_lines}
ORDER BY ep.variant, ep.user_pseudo_id;
"""


def run_raw_data_export() -> None:
    print()
    start, end = ask_dates()

    print()
    android_key = get_input("Android firebase_exp key (e.g. firebase_exp_android): ")
    ios_key     = get_input("iOS     firebase_exp key (e.g. firebase_exp_ios): ")

    metrics = collect_metrics(mode4=True)

    sql = build_raw_data_sql(start, end, android_key, ios_key, metrics)

    print("\n" + "="*60 + "\n  Generated SQL\n" + "="*60 + "\n")
    print(sql)

    metric_tag = "_".join(safe_name(m["name"]) for m in metrics[:3])
    save_sql(sql, f"raw_{android_key}_{start}_{end}_{metric_tag}.sql")


def run_ab_test_app() -> None:
    print()
    start, end = ask_dates()

    print()
    android_key = get_input("Android firebase_exp key (e.g. firebase_exp_android): ")
    ios_key     = get_input("iOS     firebase_exp key (e.g. firebase_exp_ios): ")

    metrics = collect_metrics()

    sql = build_ab_test_app_sql(start, end, android_key, ios_key, metrics)

    print("\n" + "="*60 + "\n  Generated SQL\n" + "="*60 + "\n")
    print(sql)

    metric_tag = "_".join(safe_name(m["name"]) for m in metrics[:3])
    save_sql(sql, f"ab_app_{android_key}_{start}_{end}_{metric_tag}.sql")


def run_significance_test() -> None:
    print()
    start, end = ask_dates()

    print()
    android_key = get_input("Android firebase_exp key (e.g. firebase_exp_android): ")
    ios_key     = get_input("iOS     firebase_exp key (e.g. firebase_exp_ios): ")

    metrics = collect_metrics(mode3=True)

    print()
    control_variant = get_input("Control variant name (e.g. 0, control, baseline): ")

    sql = build_significance_sql(start, end, android_key, ios_key, metrics, control_variant)

    print("\n" + "="*60 + "\n  Generated SQL\n" + "="*60 + "\n")
    print(sql)

    metric_tag = "_".join(safe_name(m["name"]) for m in metrics[:3])
    save_sql(sql, f"sig_{android_key}_{start}_{end}_{metric_tag}.sql")


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 60)
    print("  GA4 BigQuery SQL Query Builder")
    print("=" * 60)
    print()
    print("  [1] Basic event query   (web / app / ecom)")
    print("  [2] App Firebase A/B test")
    print("  [3] App Firebase A/B test — significance test")
    print("  [4] App Firebase A/B test — user-level raw data export")
    print()

    while True:
        mode = input("Select mode [1/2/3/4]: ").strip()
        if mode == "1":
            run_event_query()
            break
        if mode == "2":
            run_ab_test_app()
            break
        if mode == "3":
            run_significance_test()
            break
        if mode == "4":
            run_raw_data_export()
            break
        print("  [!] Enter 1, 2, 3, or 4.")


if __name__ == "__main__":
    main()
