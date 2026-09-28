from .permissions import user_can_write_trasmittal_interno


def user_permissions(request):
    if request.user.is_authenticated:
        return {
            "user_can_write": request.user.can_write,
            "user_is_admin": request.user.is_app_admin,
            "trasmittal_interno_can_write": user_can_write_trasmittal_interno(request.user),
        }
    return {
        "user_can_write": False,
        "user_is_admin": False,
        "trasmittal_interno_can_write": False,
    }
