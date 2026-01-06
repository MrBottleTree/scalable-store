from django.urls import path
from . import views#, public_views

urlpatterns = [
    path('api/items/', views.api_items, name = "API Items"),
    path('api/authreceiver/', views.api_authreceiver, name = "API Auth Receiver"),
    path('api/items/<int:id>', views.api_specificitem, name = "Get item details or update item"),
    path('api/mylistings/', views.api_mylisting, name = "API my listings"),
    path('api/categories/', views.api_categories, name = "GET only API categories"),
    path('api/hostels', views.api_hostels, name = "API hostels"),
    path('api/misc', views.api_misc, name = "all small shit"),
    path('api/feedback', views.api_feedback, name = "API feedback"),
    # path("public/api/items", public_views.public_api_items, name="public_api_items"),
    # path("public/api/items/<int:item_id>", public_views.public_api_item_detail, name="public_api_item_detail"),
    # path("public/api/categories", public_views.public_api_categories, name="public_api_categories"),
    # path("public/api/hostels", public_views.public_api_hostels, name="public_api_hostels"),
    # path("public/api/campuses", public_views.public_api_campuses, name="public_api_campuses"),
]
