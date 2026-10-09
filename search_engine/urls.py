from django.urls import path
from . import views

app_name = 'search_engine'

urlpatterns = [
    # Unified Smart Search (/search/)
    path('', views.search_view, name='search'),
    # Backward-compatible Person Search route (/search/person/) -> uses unified engine in 'person' mode
    path('person/', views.person_search_view, name='person-search'),
    path('person/', views.person_search_view, name='person_search'),
]
