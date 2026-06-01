from django.urls import path
from . import views

app_name = 'manufacturing'

urlpatterns = [
    path('fabric/on-hand/', views.fabric_on_hand, name='fabric_on_hand'),
    path('fabric/movements/', views.fabric_movements, name='fabric_movements'),
    path('suppliers/balances/', views.suppliers_balances, name='suppliers_balances'),
    path('supplier/<int:pk>/ledger/', views.supplier_ledger, name='supplier_ledger'),
    path('dyer/<int:pk>/ledger/', views.dyer_ledger, name='dyer_ledger'),
    path('production/<int:order_pk>/print/', views.production_order_print,
         name='production_order_print'),
]
