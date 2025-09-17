from __future__ import annotations

from django.conf import settings
from django.contrib.auth.models import Group
from django.db.models.signals import post_save
from django.dispatch import receiver

ROLE_GROUPS = {"admin", "editor", "marketer", "vendor", "customer"}


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def sync_role_group(sender, instance, **kwargs):
    role = (getattr(instance, "user_type", "") or "").lower()
    if not role:
        return
    # ensure role group exists
    role_group, _ = Group.objects.get_or_create(name=role)
    # remove user from other role groups, keep non-role groups intact
    other_role_groups = Group.objects.filter(name__in=ROLE_GROUPS - {role})
    instance.groups.remove(*other_role_groups)
    # add user to current role group
    instance.groups.add(role_group)
