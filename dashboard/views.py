from django.shortcuts import redirect, render

from accounts.decorators import role_required


def dashboard_home(request):
    # Simple router; adjust later for other roles
    if request.user.is_authenticated and getattr(request.user, "user_type", None) == "admin":
        return redirect("dashboard:admin_dashboard")
    return redirect("login")  # or render a neutral landing page


@role_required(["admin"])
def admin_dashboard(request):
    return render(
        request,
        "dashboard/admin_dashboard.html",
        {
            "user_type": getattr(request.user, "user_type", None),
        },
    )
