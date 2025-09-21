# currency_system/views.py
from django.shortcuts import redirect


def set_currency(request):
    code = (request.GET.get("currency") or "").upper()
    nxt = request.GET.get("next") or "/"
    if code:
        request.session["manual_currency"] = code
        request.session["user_currency"] = code
    return redirect(nxt)
