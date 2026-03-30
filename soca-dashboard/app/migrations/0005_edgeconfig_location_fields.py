from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0004_schedule_conf_threshold"),
    ]

    operations = [
        migrations.AddField(model_name="edgeconfig", name="latitude",  field=models.FloatField(blank=True, null=True)),
        migrations.AddField(model_name="edgeconfig", name="longitude", field=models.FloatField(blank=True, null=True)),
        migrations.AddField(model_name="edgeconfig", name="address",   field=models.CharField(blank=True, max_length=500)),
        migrations.AddField(model_name="edgeconfig", name="building",  field=models.CharField(blank=True, max_length=200)),
        migrations.AddField(model_name="edgeconfig", name="floor",     field=models.CharField(blank=True, max_length=50)),
        migrations.AddField(model_name="edgeconfig", name="site_notes",field=models.TextField(blank=True)),
    ]
