from django.urls import path
from . import views

app_name = 'sales'

urlpatterns = [
    path('invoice/<int:pk>/print/', views.print_invoice, name='print_invoice'),
    path('invoices/bulk-print-copies/', views.bulk_print_copies, name='bulk_print_copies'),
    path('receipt/<int:pk>/print/', views.print_receipt, name='print_receipt'),
    path('return/<int:pk>/print/', views.print_return, name='print_return'),
    path('invoice/<int:pk>/return/new/', views.create_return_from_invoice, name='create_return_from_invoice'),
    path('customer/<int:pk>/ledger/', views.customer_ledger, name='customer_ledger'),
    path('aging/', views.aging_report, name='aging_report'),
    path('report-visual/', views.visual_sales_report, name='visual_sales_report'),
    path('customers-report/', views.customers_report, name='customers_report'),
    path('performance/', views.performance_report, name='performance_report'),
    path('item/<int:pk>/price/', views.item_default_price, name='item_price'),
    path('item/<int:pk>/variants/', views.variants_for_item, name='item_variants'),
    path('customer/<int:pk>/invoices/', views.invoices_for_customer, name='customer_invoices'),
]
