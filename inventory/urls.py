from django.urls import path
from . import views

app_name = 'inventory'

urlpatterns = [
    path('valuation/', views.valuation_report, name='valuation'),
    path('products/', views.products_report, name='products'),
    path('product/<int:item_id>/history/', views.product_history, name='product_history'),
]
