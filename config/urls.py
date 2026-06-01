from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from core.views import dashboard
from core import admin_sidebar

admin.site.site_header = 'Roma ERP'
admin.site.site_title = 'Roma ERP'
admin.site.index_title = 'لوحة التحكم'
admin_sidebar.install()

urlpatterns = [
    path('', dashboard, name='home'),
    path('admin/', admin.site.urls),
    path('sales/', include('sales.urls', namespace='sales')),
    path('inventory/', include('inventory.urls', namespace='inventory')),
    path('manufacturing/', include('manufacturing.urls', namespace='manufacturing')),
    path('opening/', include('core.opening_urls', namespace='opening')),
    path('reports/', include('core.urls', namespace='core')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
