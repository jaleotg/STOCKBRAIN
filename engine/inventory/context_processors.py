from django.contrib.auth.models import Group
from worklog.models import StandardWorkHours


def user_flags(request):
    """
    Adds commonly used user-related flags to template context.
    """
    user = getattr(request, "user", None)
    has_wl_master = False
    if user and user.is_authenticated:
        has_wl_master = user.groups.filter(name__iexact="work_log_master").exists()
    end_time = None
    cfg = StandardWorkHours.objects.first()
    if cfg and cfg.end_time:
        end_time = cfg.end_time.isoformat(timespec="minutes")
    return {
        "has_work_log_master": has_wl_master,
        "standard_end_time": end_time,
    }
