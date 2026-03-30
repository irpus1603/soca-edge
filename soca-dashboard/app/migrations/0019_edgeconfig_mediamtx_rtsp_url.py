from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0018_edgeconfig_gac_path'),
    ]

    operations = [
        migrations.AddField(
            model_name='edgeconfig',
            name='mediamtx_rtsp_url',
            field=models.CharField(
                blank=True,
                default='rtsp://localhost:8554',
                help_text='MediaMTX RTSP relay base URL used by soca-engine, e.g. rtsp://localhost:8554',
                max_length=200,
            ),
        ),
    ]
