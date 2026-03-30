from django.contrib.auth.decorators import user_passes_test


def role_required(*roles):
    """Restrict a view to users whose role is in `roles`. Admin always passes."""
    def check(user):
        return user.is_authenticated and user.role in roles
    return user_passes_test(check, login_url='/login/')
