from django.db import migrations


def create_groups(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")

    Product = apps.get_model("catalog", "Product")
    Variant = apps.get_model("catalog", "Variant")
    Media = apps.get_model("catalog", "Media")
    Inventory = apps.get_model("catalog", "Inventory")

    def perms_for(model, actions):
        ct = ContentType.objects.get_for_model(model)
        return list(
            Permission.objects.filter(
                content_type=ct, codename__in=[f"{a}_{ct.model}" for a in actions]
            )
        )

    groups = {
        name: Group.objects.get_or_create(name=name)[0]
        for name in ["admin", "editor", "marketer", "vendor", "customer"]
    }

    all_actions = ["view", "add", "change", "delete"]
    admin = set(
        perms_for(Product, all_actions)
        + perms_for(Variant, all_actions)
        + perms_for(Media, all_actions)
        + perms_for(Inventory, all_actions)
    )
    groups["admin"].permissions.add(*admin)

    editor = set(
        perms_for(Product, ["view", "add", "change"])
        + perms_for(Variant, ["view", "add", "change"])
        + perms_for(Media, ["view", "add", "change"])
        + perms_for(Inventory, ["view", "change"])
    )
    groups["editor"].permissions.add(*editor)

    marketer = set(
        perms_for(Product, ["view", "change"])
        + perms_for(Media, ["view", "change"])
        + perms_for(Variant, ["view"])
        + perms_for(Inventory, ["view"])
    )
    groups["marketer"].permissions.add(*marketer)

    vendor = set(
        perms_for(Product, ["view"])
        + perms_for(Variant, ["view"])
        + perms_for(Media, ["view"])
        + perms_for(Inventory, ["view"])
    )
    groups["vendor"].permissions.add(*vendor)

    # customer: catalog read-only (optional)
    customer = set(
        perms_for(Product, ["view"]) + perms_for(Variant, ["view"]) + perms_for(Media, ["view"])
    )
    groups["customer"].permissions.add(*customer)


def drop_groups(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name__in=["admin", "editor", "marketer", "vendor", "customer"]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_initial"),
        ("catalog", "0001_initial"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]
    operations = [migrations.RunPython(create_groups, reverse_code=drop_groups)]
