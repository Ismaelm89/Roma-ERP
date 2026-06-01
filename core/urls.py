from django.urls import path
from . import views

app_name = 'core'

urlpatterns = [
    path('dashboard/', views.dashboard, name='dashboard'),
    path('trial-balance/', views.trial_balance, name='trial_balance'),
    path('pnl/', views.pnl, name='pnl'),
    path('balance-sheet/', views.balance_sheet, name='balance_sheet'),
    path('cash-balances/', views.cash_balances, name='cash_balances'),
]
