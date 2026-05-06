from django.db import migrations


def seed_levels(apps, schema_editor):
    Level = apps.get_model("qualifications", "Level")

    for value in [
        "level-1",
        "level-2",
        "level-3",
        "level-4",
        "level-5",
        "level-6",
        "level-7",
    ]:
        Level.objects.get_or_create(name=value)


class Migration(migrations.Migration):
    dependencies = [
        ("qualifications", "0002_initial"),
    ]

    operations = [
        migrations.RunPython(seed_levels, migrations.RunPython.noop),
    ]
