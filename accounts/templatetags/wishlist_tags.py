# Create this file: accounts/templatetags/wishlist_tags.py

from django import template
from django.contrib.auth.models import AnonymousUser

register = template.Library()


@register.simple_tag
def is_in_wishlist(user, product):
    """Check if a product is in user's wishlist."""

    if not user.is_authenticated or isinstance(user, AnonymousUser):
        return False

    try:
        from accounts.models import Wishlist, WishlistItem

        wishlist = Wishlist.objects.get(user=user)
        return WishlistItem.objects.filter(wishlist=wishlist, product=product).exists()
    except Wishlist.DoesNotExist:
        return False


@register.simple_tag
def wishlist_count(user):
    """Get wishlist count for a user."""

    if not user.is_authenticated or isinstance(user, AnonymousUser):
        return 0

    try:
        from accounts.models import Wishlist, WishlistItem

        wishlist = Wishlist.objects.get(user=user)
        return WishlistItem.objects.filter(wishlist=wishlist).count()
    except Wishlist.DoesNotExist:
        return 0


@register.inclusion_tag("accounts/_wishlist_button.html", takes_context=True)
def wishlist_button(context, product, classes="", show_text=False):
    """Render a wishlist toggle button."""
    user = context["request"].user
    return {
        "user": user,
        "product": product,
        "is_in_wishlist": is_in_wishlist(user, product),
        "classes": classes,
        "show_text": show_text,
        "request": context["request"],
    }
