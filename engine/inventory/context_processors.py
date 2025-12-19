from django.contrib.auth.models import Group
from worklog.models import StandardWorkHours
from .models import get_user_profile


def user_flags(request):
    """
    Adds commonly used user-related flags to template context.
    """
    user = getattr(request, "user", None)
    has_wl_master = False
    prefer_dark = None
    if user and user.is_authenticated:
        has_wl_master = user.groups.filter(name__iexact="work_log_master").exists()
        profile = get_user_profile(user)
        prefer_dark = profile.prefer_dark_theme if profile else None
    start_time = None
    end_time = None
    cfg = StandardWorkHours.objects.first()
    if cfg and cfg.end_time:
        end_time = cfg.end_time.isoformat(timespec="minutes")
    if cfg and cfg.start_time:
        start_time = cfg.start_time.isoformat(timespec="minutes")
    return {
        "has_work_log_master": has_wl_master,
        "standard_start_time": start_time,
        "standard_end_time": end_time,
        "sb_prefer_dark_theme": prefer_dark,
    }
