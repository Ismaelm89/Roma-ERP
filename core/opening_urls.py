"""URL routes for the manual opening-balance screens (الأرصدة الافتتاحية).

Mounted under ``/opening/`` (see config/urls.py) with namespace ``opening`` so the
views can ``redirect('opening:<name>')`` after each POST.
"""
from django.urls import path

from . import opening_views

app_name = 'opening'

urlpatterns = [
    path('',           opening_views.hub,       name='hub'),
    path('customers/', opening_views.customers, name='customers'),
    path('suppliers/', opening_views.suppliers, name='suppliers'),
    path('inventory/',   opening_views.inventory,   name='inventory'),
    path('accessories/', opening_views.accessories, name='accessories'),
    path('fabric/',      opening_views.fabric,      name='fabric'),
    path('assets/',    opening_views.assets,    name='assets'),
    path('cash/',      opening_views.cash,      name='cash'),
    path('finalize/',  opening_views.finalize,  name='finalize'),
]
