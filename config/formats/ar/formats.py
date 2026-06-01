"""Override Django's built-in 'ar' locale number formats.

The bundled 'ar' locale formats numbers European-style (',' decimal, '.'
thousands). The business wants the opposite — '.' decimal, ',' thousands
(e.g. 5,500.00) — so we pin the separators here. Django picks this up via
FORMAT_MODULE_PATH in settings and it overrides the locale defaults while
keeping the Arabic UI language.
"""
DECIMAL_SEPARATOR = '.'
THOUSAND_SEPARATOR = ','
USE_THOUSAND_SEPARATOR = True
NUMBER_GROUPING = 3
