from django.contrib import admin
from django.urls import path
from inventory.views import (
    login_view,
    logout_view,
    home_view,
    work_log_view,
    work_log_detail,
    update_unit,
    update_group,
    update_field,
    update_favorite,
    update_note,
    create_item,
    delete_item,
)
from datatools.views import db_tools

urlpatterns = [
    path("admin/", admin.site.urls),

    # Authentication
    path("login/", login_view, name="login"),
    path("logout/", logout_view, name="logout"),

    # Home — oba adresy działają
    path("", home_view, name="home"),
    path("home/", home_view, name="home_alias"),
    path("work-log/", work_log_view, name="work_log"),
    path("api/work-log/<int:pk>/", work_log_detail, name="work_log_detail"),
    path("admin/db-tools/", db_tools, name="db_tools"),

    # AJAX API endpoints (InventoryItem)
    path("api/update-unit/", update_unit, name="update_unit"),
    path("api/update-group/", update_group, name="update_group"),
    path("api/update-field/", update_field, name="update_field"),
    path("api/create-item/", create_item, name="create_item"),
    path("api/delete-item/", delete_item, name="delete_item"),

    # AJAX API endpoints (per-user meta: favorites + notes)
    path("api/update-favorite/", update_favorite, name="update_favorite"),
    path("api/update-note/", update_note, name="update_note"),
]
