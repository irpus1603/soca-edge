from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0017_edgeconfig_pubsub'),
    ]

    operations = [
        migrations.AddField(
            model_name='edgeconfig',
            name='gac_path',
            field=models.CharField(
                blank=True,
                default='',
                help_text='Path to Google service account JSON key file (GOOGLE_APPLICATION_CREDENTIALS)',
                max_length=500,
            ),
        ),
    ]
