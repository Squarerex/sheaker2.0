# core/context_processors.py
from orders.cart import Cart


def cart_context(request):
    """
    Make a Cart instance available in all templates as {{ cart }}.
    Cart is now robust to stray session keys, so we don't need to swallow errors.
    """
    return {"cart": Cart(request)}
