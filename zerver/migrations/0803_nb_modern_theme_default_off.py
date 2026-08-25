from django.db import migrations, models


def reset_to_classic(apps, schema_editor):
    apps.get_model("zerver", "UserProfile").objects.update(nb_modern_theme=False)
    apps.get_model("zerver", "RealmUserDefault").objects.update(nb_modern_theme=False)


class Migration(migrations.Migration):
    dependencies = [
        ("zerver", "0802_nb_modern_theme"),
    ]

    operations = [
        migrations.AlterField(
            model_name="realmuserdefault",
            name="nb_modern_theme",
            field=models.BooleanField(default=False),
        ),
        migrations.AlterField(
            model_name="userprofile",
            name="nb_modern_theme",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(reset_to_classic, migrations.RunPython.noop),
    ]
