from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0019_edgeconfig_mediamtx_rtsp_url'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='edgeconfig',
            name='gac_path',
        ),
        migrations.AddField(
            model_name='edgeconfig',
            name='gcs_key_path',
            field=models.CharField(blank=True, default='', help_text='Path to GCS service account JSON key file', max_length=500),
        ),
        migrations.AddField(
            model_name='edgeconfig',
            name='gcs_bucket',
            field=models.CharField(blank=True, default='', help_text='GCS bucket name', max_length=200),
        ),
        migrations.AddField(
            model_name='edgeconfig',
            name='gcs_path_prefix',
            field=models.CharField(blank=True, default='', help_text='GCS path prefix for this edge', max_length=200),
        ),
        migrations.AddField(
            model_name='edgeconfig',
            name='pubsub_key_path',
            field=models.CharField(blank=True, default='', help_text='Path to Pub/Sub service account JSON key file', max_length=500),
        ),
        migrations.AddField(
            model_name='edgeconfig',
            name='engine_api_key',
            field=models.CharField(blank=True, default='', help_text='ENGINE_API_KEY set on soca-engine — required to push config', max_length=64),
        ),
        migrations.AddField(
            model_name='edgeconfig',
            name='last_engine_push_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='edgeconfig',
            name='last_engine_push_ok',
            field=models.BooleanField(blank=True, null=True),
        ),
    ]
