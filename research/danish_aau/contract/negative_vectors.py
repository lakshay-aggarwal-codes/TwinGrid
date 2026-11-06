"""Declarative negative test vectors for the Task 8 contract (language-neutral: path edits on the shipped examples).

Each vector is (id, base_example_file_stem, [(dotted_path, new_value_or_DELETE), ...], expected_error_code).
Apply the edits to a copy of `examples/<base>.json`; a conforming validator MUST report the expected code.
Dotted paths index lists with integers (for example "records.1.ts_source_text").
"""

from __future__ import annotations

DELETE = "__delete__"
T = "record_observed_temperature"
P = "record_power_group"
M = "record_missing_conflict_tie"
S = "record_stale_live"
D = "record_derived_rack_proxy_shape"
V = "record_v5_shape_only_no_value"
H = "envelope_history"
RV = "envelope_rack_view"
LA = "envelope_latest_absent_group_channel"
LP = "envelope_latest_present"
SL = "envelope_sensor_list"
ER = "envelope_error_unknown_entity"
LE = "ledger_entry_exact_duplicate"
TS0 = "2000-01-01 00:00:00"
V5_POWER1 = [
    ("sensor_external_id", "danish-aau-v5.power.ch1"), ("asset_external_id", "danish-aau-v5.pdu.ch1"), ("measurand", "power"),
    ("unit", "W"), ("resolution_decimals", 1), ("source_rack_id", None), ("mapping.method", "source_workbook_port_group"),
]  # fmt: skip

VECTORS = [
    # --- value / state / quality -------------------------------------------------------------------------------------
    ("state_missing_but_value", T, [("state", "missing")], "E_STATE_VALUE"),
    ("value_is_string", T, [("value", "20.12")], "E_VALUE"),
    ("observed_without_value", T, [("value", None), ("value_text", None), ("observed", False)], "E_STATE_VALUE"),
    ("observed_flag_disagrees", T, [("observed", False)], "E_OBSERVED"),
    ("observed_without_quality", T, [("quality", None)], "E_STATE_QUALITY"),
    ("flagged_without_reason", T, [("quality", "flagged")], "E_STATE_REASON"),
    ("reason_on_ok_record", T, [("reason_code", "some_reason")], "E_STATE_REASON"),
    ("value_text_mismatch", T, [("value_text", "20.13")], "E_VALUE_TEXT"),
    ("value_text_wrong_decimals", T, [("value_text", "20.1")], "E_VALUE_TEXT"),
    ("age_on_observed", T, [("age_seconds", 5)], "E_AGE"),
    ("missing_with_value", M, [("value", 20.0), ("value_text", "20.00"), ("observed", True)], "E_STATE_VALUE"),
    ("missing_without_reason", M, [("reason_code", None)], "E_STATE_REASON"),
    ("missing_with_quality", M, [("quality", "ok")], "E_STATE_QUALITY"),
    ("tie_not_marked_conflict_cell_missing", M, [("ledger.row_disposition", "retained")], "E_LEDGER"),
    ("tie_in_group_of_one", M, [("ledger.group_size", 1)], "E_LEDGER"),
    ("stale_on_import_stream", S, [("dataset_id", "synthetic-example"), ("stream_id", "import:synthetic-example")], "E_STALE_SCOPE"),
    ("stale_without_utc_instant", S, [("time_basis", "source_text_undeclared_tz"), ("ts_source_text", "2000-01-01 00:10:00"), ("ts_utc", None)], "E_STALE_SCOPE"),
    ("stale_zero_age", S, [("age_seconds", 0)], "E_AGE"),
    # --- time --------------------------------------------------------------------------------------------------------
    ("utc_while_timezone_undeclared", T, [("ts_utc", "2000-01-01T00:00:01Z")], "E_TIME_UTC_FORBIDDEN"),
    ("impossible_calendar_date", T, [("ts_source_text", "2000-02-30 00:00:01")], "E_TIME_TEXT"),
    ("iso_text_instead_of_source_text", T, [("ts_source_text", "2000-01-01T00:00:01")], "E_TIME_TEXT"),
    ("utc_basis_without_utc", T, [("time_basis", "utc_instant")], "E_TIME_UTC"),
    # --- provenance / storage / fixture ------------------------------------------------------------------------------
    ("measured_in_fixture_storage", T, [("provenance", "measured")], "E_STORAGE"),
    ("derived_without_derivation", T, [("provenance", "derived"), ("storage_class", "derived_series")], "E_DERIVATION"),
    ("derived_in_telemetry_sample", D, [("storage_class", "telemetry_sample")], "E_STORAGE"),
    ("synthetic_in_telemetry_sample", T, [("storage_class", "telemetry_sample")], "E_STORAGE"),
    ("origin_enum_extended", T, [("origin_db", "synthetic")], "E_ENUM"),
    ("synthetic_with_db_origin", T, [("origin_db", "measured")], "E_STORAGE"),
    ("synthetic_without_fixture_id", T, [("sensor_external_id", "fac1.temperature")], "E_FIXTURE_ID"),
    ("synthetic_not_fixture", T, [("fixture", False)], "E_FIXTURE"),
    ("shape_only_measured_with_value", V, [("value", 20.0), ("value_text", "20.00"), ("state", "observed"), ("observed", True), ("quality", "ok"), ("reason_code", None)], "E_FIXTURE_VALUE"),
    ("derived_from_group_becomes_per_rack", D, [("derivation.input_scopes", ["rack_group"])], "E_GROUP_SPLIT"),
    # --- ids / stream / keys -----------------------------------------------------------------------------------------
    ("import_stream_without_dataset", T, [("dataset_id", None)], "E_DATASET_STREAM"),
    ("dataset_on_live_stream", T, [("stream_id", "live")], "E_DATASET_STREAM"),
    ("stream_names_other_dataset", T, [("stream_id", "import:other")], "E_DATASET_STREAM"),
    ("unknown_key", T, [("foo", 1)], "E_KEYS_UNKNOWN"),
    ("missing_key", T, [("unit", DELETE)], "E_KEYS_MISSING"),
    ("unsupported_major_version", T, [("contract_version", "2.0.0")], "E_VERSION"),
    ("empty_unit", T, [("unit", "")], "E_UNIT"),
    ("server_id_without_status", T, [("source_server_id", "srv1")], "E_SERVER"),
    # --- attribution / group power -----------------------------------------------------------------------------------
    ("split_allowed_true", T, [("attribution.split_allowed", True)], "E_GROUP_SPLIT"),
    ("rack_scope_two_members", T, [("attribution.member_source_rack_ids", ["1", "2"])], "E_ATTRIBUTION"),
    ("group_power_as_rack_scope", P, [("attribution.scope", "rack")], "E_ATTRIBUTION"),
    ("group_power_with_rack_id", P, [("source_rack_id", "2")], "E_GROUP_SPLIT"),
    ("group_power_single_member", P, [("attribution.member_source_rack_ids", ["1"])], "E_GROUP_SPLIT"),
    # --- lineage -----------------------------------------------------------------------------------------------------
    ("source_ref_key_wrong", T, [("source_ref.key", "x")], "E_SOURCE_REF"),
    ("row_ordinal_zero", T, [("source_ref.row_ordinal", 0)], "E_SOURCE_REF"),
    ("source_ref_time_differs", T, [("source_ref.ts_text", "2000-01-01 00:00:09")], "E_SOURCE_REF"),
    ("record_with_exact_duplicate_disposition", T, [("ledger.row_disposition", "exact_duplicate")], "E_LEDGER"),
    ("unknown_mapping_method", T, [("mapping.method", "guess")], "E_MAPPING"),
    ("derived_without_derivation_block", D, [("derivation", None)], "E_DERIVATION"),
    ("ledger_entry_flagged_without_reason", LE, [("disposition", "flagged")], "E_STATE_REASON"),
    ("ledger_entry_unknown_disposition", LE, [("disposition", "kept_dup")], "E_ENUM"),
    ("ledger_entry_duplicate_group_of_one", LE, [("group_size", 1)], "E_LEDGER"),
    ("measured_import_without_source_ref", V, [("source_ref", None)], "E_LINEAGE"),
    ("measured_in_telemetry_sample_without_origin", T, [("provenance", "measured"), ("storage_class", "telemetry_sample")], "E_ORIGIN"),
    ("protocol_hash_malformed", T, [("protocol_ref.protocol_sha256", "xyz")], "E_PROTOCOL_REF"),
    ("stream_id_unknown_form", T, [("stream_id", "streamX")], "E_STREAM"),
    ("embedded_record_invalid", LP, [("record.value", "20")], "E_RECORD"),
    # --- v5 profile --------------------------------------------------------------------------------------------------
    ("v5_sensor_id_malformed", V, [("sensor_external_id", "danish-aau-v5.temperature.mod1")], "E_V5_SENSOR_ID"),
    ("v5_rack_out_of_range", V, [("asset_external_id", "danish-aau-v5.rack.7")], "E_V5_ASSET_ID"),
    ("v5_server_id_present", V, [("source_server_id", "s1"), ("source_server_status", "present")], "E_V5_SERVER"),
    ("v5_utc_asserted", V, [("time_basis", "utc_instant"), ("ts_utc", "2000-01-01T00:00:01Z")], "E_V5_TIME"),
    ("v5_wrong_unit", V, [("unit", "K")], "E_V5_UNIT"),
    ("v5_wrong_resolution", V, [("resolution_decimals", 3)], "E_V5_RESOLUTION"),
    ("v5_wrong_protocol_hash", V, [("protocol_ref.protocol_sha256", "0" * 64)], "E_V5_PROTOCOL"),
    ("v5_temperature_method_not_image_label", V, [("mapping.method", "csv_header_key")], "E_V5_MAPPING"),
    ("v5_mapping_not_uniform", V, [("mapping.applied_uniformly_over_window", False)], "E_V5_MAPPING"),
    ("v5_site_asserted", V, [("site_status", "location_established")], "E_V5_SITE"),
    ("v5_unknown_measurand", V, [("measurand", "humidity")], "E_V5_MEASURAND"),
    ("v5_power_ch1_wrong_members", V, V5_POWER1 + [("attribution.scope", "rack_group"), ("attribution.member_source_rack_ids", ["1", "2"])], "E_V5_POWER_GROUP"),
    ("v5_power_ch1_split_per_rack", V, V5_POWER1 + [("source_rack_id", "1"), ("attribution.scope", "rack"), ("attribution.member_source_rack_ids", ["1"])], "E_V5_POWER_GROUP"),
    ("v5_temperature_group_attributed", V, [("source_rack_id", None), ("attribution.scope", "rack_group"), ("attribution.member_source_rack_ids", ["2", "3"])], "E_V5_ATTRIBUTION"),
    # --- envelopes ---------------------------------------------------------------------------------------------------
    ("latest_absent_without_reason", LA, [("record_absent_reason", None)], "E_ABSENT"),
    ("latest_present_but_group_channel", LP, [("measurand_status", "group_channel_only")], "E_ABSENT"),
    ("latest_facility_mismatch", LP, [("facility_id", "other-facility")], "E_ENVELOPE_MISMATCH"),
    ("envelope_without_stream", H, [("stream_id", DELETE)], "E_KEYS_MISSING"),
    ("envelope_stream_dataset_disagree", H, [("stream_id", "live")], "E_DATASET_STREAM"),
    ("history_count_wrong", H, [("count", 5)], "E_COUNT"),
    ("history_limit_too_large", H, [("page.limit", 5000)], "E_HISTORY"),
    ("history_state_not_included", H, [("include_states", ["missing"])], "E_HISTORY"),
    ("history_utc_bound", H, [("from_source_text", "2000-01-01T00:00:00Z")], "E_TIME_TEXT"),
    ("history_not_ascending", H, [("records.1.ts_source_text", TS0), ("records.1.source_ref.ts_text", TS0), ("records.1.source_ref.key", f"synthetic_example_file.csv|Synthetic temperature 1|{TS0}")], "E_ORDER"),
    ("sensor_list_count_wrong", SL, [("count", 3)], "E_COUNT"),
    ("rack_view_group_power_has_value", RV, [("power.value", 300.0)], "E_GROUP_SPLIT"),
    ("rack_view_group_power_splittable", RV, [("power.split_allowed", True)], "E_GROUP_SPLIT"),
    ("rack_view_rack_not_a_member", RV, [("power.member_source_rack_ids", ["2", "3"])], "E_GROUP_SPLIT"),
    ("error_unknown_code", ER, [("code", "oops")], "E_ERROR"),
    ("error_success_status", ER, [("status", 200)], "E_ERROR"),
]  # fmt: skip
