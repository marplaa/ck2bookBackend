from django.urls import path

from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('get_recipe_data_json_get', views.get_recipe_data_json_get, name='get_json'),
    path('toPdf', views.create_tex_file, name='compile'),
]