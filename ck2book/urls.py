from django.urls import path

from . import views

urlpatterns = [
    path('scrape_recipe', views.scrape_recipe, name='get_json'),
]
