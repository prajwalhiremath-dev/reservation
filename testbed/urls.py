from django.urls import path
from . import views

app_name = 'testbed'

urlpatterns = [
    path('', views.testbed_overview, name='testbed_overview'),
    path('api/family/<int:family_id>/details/', views.get_family_details, name='family_details'),
]