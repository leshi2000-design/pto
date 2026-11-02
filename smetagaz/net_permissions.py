"""Server-owned SQL and settings policy, shared with the client for UI preferences."""

PERSONAL_SETTINGS = frozenset({
    'is_dark', 'accent_color', 'font_family', 'font_size', 'tabs_config', 'today_calendar',
    'estimates_hidden_cols', 'gsvp_tree_visible', 'gsvp_order_desc',
    'export_font', 'export_font_size', 'estimate_prepared_by',
    'calc_nds_pct', 'calc_tax_pct', 'calc_soc_pct', 'invoice_markup',
    'last_name_selector', 'last_price_selector',
})


def personal_setting(key):
    return key in PERSONAL_SETTINGS or str(key).startswith(('cols_', 'filters_'))


# The second argument of these pragmas is an object name, never a new value.
OBJECT_PRAGMAS = frozenset({
    'table_info', 'table_xinfo', 'foreign_key_list', 'foreign_key_check',
    'index_list', 'index_info', 'index_xinfo', 'integrity_check', 'quick_check',
})
VALUE_PRAGMAS = frozenset({
    'database_list', 'data_version', 'schema_version', 'user_version', 'foreign_keys',
    'journal_mode', 'synchronous', 'compile_options', 'page_count', 'freelist_count',
    'encoding', 'table_list',
})


def read_pragma(name, argument):
    name = str(name or '').lower()
    return name in OBJECT_PRAGMAS or (name in VALUE_PRAGMAS and argument is None)
