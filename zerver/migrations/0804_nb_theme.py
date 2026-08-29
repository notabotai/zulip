from django.db import migrations, models


def set_all_animals(apps, schema_editor):
    apps.get_model("zerver", "UserProfile").objects.update(nb_theme="animals")
    apps.get_model("zerver", "RealmUserDefault").objects.update(nb_theme="animals")


class Migration(migrations.Migration):
    dependencies = [
        ("zerver", "0803_nb_modern_theme_default_off"),
    ]

    operations = [
        migrations.AddField(
            model_name="realmuserdefault",
            name="nb_theme",
            field=models.TextField(default="animals"),
        ),
        migrations.AddField(
            model_name="userprofile",
            name="nb_theme",
            field=models.TextField(default="animals"),
        ),
        # Ship Animals as the default for everyone (this rollout).
        migrations.RunPython(set_all_animals, migrations.RunPython.noop),
        migrations.RemoveField(model_name="realmuserdefault", name="nb_modern_theme"),
        migrations.RemoveField(model_name="userprofile", name="nb_modern_theme"),
    ]
