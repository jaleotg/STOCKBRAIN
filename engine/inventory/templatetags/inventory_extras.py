from django import template

register = template.Library()


@register.filter
def has_group(user, group_name):
    """
    Return True if the user belongs to the given group (case-insensitive).
    Usage: {% if request.user|has_group:"work_log_master" %}...{% endif %}
    """
    if not user or not user.is_authenticated:
        return False
    return user.groups.filter(name__iexact=group_name).exists()
